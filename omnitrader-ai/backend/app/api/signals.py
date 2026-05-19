"""
api/signals.py
==============
Signal, dashboard, and market analysis endpoints.

GET  /agents/signals            — paginated alert/signal feed
GET  /agents/dashboard          — executive dashboard summary
GET  /agents/market-analysis    — macro regime + sector rotation + cross-assets
GET  /agents/compounders        — long-term quality stock screen
POST /agents/alerts/mark-read   — mark alerts as read (all or by ids)
"""
import logging
from datetime import datetime, timedelta, timezone
from typing import List, Optional

from fastapi import APIRouter, Body, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func, text, update

from app.db.session import get_db
from app.models.market_data import Alert, AIAnalysis, Stock
from app.engines.regime import MacroRegimeClassifier
from app.engines.sector_rotation import SectorRotationEngine
from app.engines.compounder import CompoundersEngine
from app.ingestion.infra.universe import UniverseManager

router = APIRouter()
logger = logging.getLogger(__name__)


# ── Signals feed ──────────────────────────────────────────────────────────────

@router.get("/signals")
async def get_signals(
    page:    int            = Query(1, ge=1),
    limit:   int            = Query(50, ge=1, le=200),
    signal:  Optional[str]  = Query(None, description="Filter by signal type"),
    country: Optional[str]  = Query(None, description="US or IN"),
    db:      AsyncSession   = Depends(get_db),
):
    """
    Paginated feed of signal-change alerts, newest first.
    Filter by signal type (STRONG_BUY, ACCUMULATE, AVOID, DISTRIBUTION) and country.
    """
    stmt = (
        select(Alert, Stock.name, Stock.sector, Stock.country)
        .join(Stock, Alert.ticker == Stock.ticker, isouter=True)
        .order_by(Alert.generated_at.desc())
    )

    if signal:
        stmt = stmt.where(Alert.signal == signal.upper())
    if country:
        stmt = stmt.where(Stock.country == country.upper())

    # Total count
    count_stmt = select(func.count()).select_from(stmt.subquery())
    total_result = await db.execute(count_stmt)
    total = total_result.scalar() or 0

    # Paginate
    offset = (page - 1) * limit
    stmt = stmt.offset(offset).limit(limit)
    result = await db.execute(stmt)
    rows = result.fetchall()

    # Batch-fetch latest prices for all tickers in this page
    tickers_in_page = list({row[0].ticker for row in rows})
    current_prices: dict = {}
    if tickers_in_page:
        price_q = text("""
            SELECT DISTINCT ON (ticker) ticker, close
            FROM stock_prices
            WHERE ticker = ANY(:tickers)
            ORDER BY ticker, time DESC
        """)
        price_r = await db.execute(price_q, {"tickers": tickers_in_page})
        current_prices = {r.ticker: round(r.close, 2) for r in price_r.fetchall()}

    items = []
    for row in rows:
        alert, name, sector, country_code = row
        items.append({
            "id":              alert.id,
            "ticker":          alert.ticker,
            "name":            name,
            "sector":          sector,
            "country":         country_code,
            "signal":          alert.signal,
            "previous_signal": alert.previous_signal,
            "final_score":     alert.final_score,
            "headline":        alert.headline,
            "thesis":          alert.thesis,
            "image_url":       alert.image_url,
            "generated_at":    alert.generated_at,
            "is_read":         alert.is_read,
            "current_price":   current_prices.get(alert.ticker),
        })

    return {
        "total": total,
        "page": page,
        "limit": limit,
        "pages": max(1, -(-total // limit)),
        "items": items,
    }


# ── Executive dashboard ────────────────────────────────────────────────────────

@router.get("/dashboard")
async def get_dashboard(db: AsyncSession = Depends(get_db)):
    """
    Summary for the executive dashboard:
      • Today's signal counts by type
      • Current macro regime
      • Average final score across all tickers analysed today
      • Top 6 STRONG_BUY / ACCUMULATE signals from latest analysis
      • Recent 20 alerts
    """
    today = datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)

    # ── Today's signal counts ─────────────────────────────────────────────────
    counts_q = text("""
        SELECT signal, COUNT(*) AS n
        FROM ai_analysis
        WHERE analysis_date >= :today
        GROUP BY signal
    """)
    counts_r = await db.execute(counts_q, {"today": today})
    signal_counts = {r.signal: r.n for r in counts_r.fetchall()}

    # ── Average score ─────────────────────────────────────────────────────────
    avg_q = text("""
        SELECT AVG(final_score) AS avg_score
        FROM ai_analysis
        WHERE analysis_date >= :today AND final_score IS NOT NULL
    """)
    avg_r = await db.execute(avg_q, {"today": today})
    avg_score_row = avg_r.fetchone()
    avg_score = round(avg_score_row.avg_score, 1) if avg_score_row and avg_score_row.avg_score else None

    # ── Macro regime ──────────────────────────────────────────────────────────
    try:
        classifier = MacroRegimeClassifier(db)
        regime_data = await classifier.classify()
    except Exception as e:
        logger.warning("Dashboard regime classification failed: %s", e)
        regime_data = {"regime": "Unknown", "confidence": 0.0, "indicators": {}}

    # ── Top signals ───────────────────────────────────────────────────────────
    top_q = (
        select(AIAnalysis, Stock.name, Stock.sector, Stock.country)
        .join(Stock, AIAnalysis.ticker == Stock.ticker, isouter=True)
        .where(
            AIAnalysis.analysis_date >= today,
            AIAnalysis.signal.in_(["STRONG_BUY", "ACCUMULATE"]),
            AIAnalysis.final_score.isnot(None),
        )
        .order_by(AIAnalysis.final_score.desc())
        .limit(6)
    )
    top_r = await db.execute(top_q)
    top_signals = []
    for row in top_r.fetchall():
        a, name, sector, country = row
        top_signals.append({
            "ticker":       a.ticker,
            "name":         name,
            "sector":       sector,
            "country":      country,
            "signal":       a.signal,
            "final_score":  a.final_score,
            "signal_thesis": a.signal_thesis,
            "fundamental_score":   a.fundamental_score,
            "technical_score":     a.technical_score,
            "macro_score":         a.macro_score,
            "institutional_score": a.institutional_score,
            "sentiment_score":     a.sentiment_score,
        })

    # ── Recent alerts ─────────────────────────────────────────────────────────
    recent_q = (
        select(Alert, Stock.name, Stock.country)
        .join(Stock, Alert.ticker == Stock.ticker, isouter=True)
        .order_by(Alert.generated_at.desc())
        .limit(20)
    )
    recent_r = await db.execute(recent_q)
    recent_alerts = []
    for row in recent_r.fetchall():
        alert, name, country = row
        recent_alerts.append({
            "ticker":         alert.ticker,
            "name":           name,
            "country":        country,
            "signal":         alert.signal,
            "previous_signal":alert.previous_signal,
            "final_score":    alert.final_score,
            "headline":       alert.headline,
            "thesis":         alert.thesis,
            "image_url":      alert.image_url,
            "generated_at":   alert.generated_at,
        })

    # ── Unread alerts count ───────────────────────────────────────────────────
    unread_q = text("SELECT COUNT(*) FROM alerts WHERE is_read = false")
    unread_r = await db.execute(unread_q)
    unread_count = unread_r.scalar() or 0

    return {
        "signal_counts":  signal_counts,
        "avg_score":      avg_score,
        "regime":         regime_data["regime"],
        "regime_confidence": regime_data["confidence"],
        "unread_alerts":  unread_count,
        "top_signals":    top_signals,
        "recent_alerts":  recent_alerts,
    }


# ── Market analysis ────────────────────────────────────────────────────────────

@router.get("/market-analysis")
async def get_market_analysis(db: AsyncSession = Depends(get_db)):
    """
    Macro regime details + sector rotation rankings + cross-asset snapshot.
    """
    # ── Regime ────────────────────────────────────────────────────────────────
    try:
        classifier = MacroRegimeClassifier(db)
        regime_data = await classifier.classify()
    except Exception as e:
        logger.warning("Market analysis regime failed: %s", e)
        regime_data = {"regime": "Unknown", "confidence": 0.0, "indicators": {}}

    # ── Sector rotation ───────────────────────────────────────────────────────
    try:
        sector_engine = SectorRotationEngine(db)
        sectors = await sector_engine.calculate()
    except Exception as e:
        logger.warning("Sector rotation failed: %s", e)
        sectors = []

    # ── FII/DII 30-day trend ──────────────────────────────────────────────────
    since = datetime.now(timezone.utc) - timedelta(days=35)
    fii_q = text("""
        SELECT date, net_value, entity_type
        FROM institutional_flows
        WHERE entity_type IN ('FII', 'DII')
          AND market = 'INDIA'
          AND date >= :since
        ORDER BY date ASC
    """)
    fii_r = await db.execute(fii_q, {"since": since})
    fii_rows = fii_r.fetchall()

    fii_chart = {}
    for row in fii_rows:
        date_str = row.date.strftime("%Y-%m-%d") if hasattr(row.date, "strftime") else str(row.date)[:10]
        if date_str not in fii_chart:
            fii_chart[date_str] = {"date": date_str, "fii_net": 0, "dii_net": 0}
        if row.entity_type == "FII":
            fii_chart[date_str]["fii_net"] += row.net_value or 0
        else:
            fii_chart[date_str]["dii_net"] += row.net_value or 0

    fii_series = sorted(fii_chart.values(), key=lambda x: x["date"])

    # ── Cross-assets ──────────────────────────────────────────────────────────
    cross_asset_tickers = {
        "Gold":    "GC=F",
        "Oil WTI": "CL=F",
        "DXY":     "DX-Y.NYB",
        "US 10Y":  "US10Y",
        "VIX":     "VIX",
        "INR/USD": "INR=X",
    }

    cross_assets = []
    for label, indicator in cross_asset_tickers.items():
        try:
            # Try macro_data first
            macro_q = text("""
                SELECT value, time FROM macro_data
                WHERE indicator = :ind
                ORDER BY time DESC
                LIMIT 8
            """)
            macro_r = await db.execute(macro_q, {"ind": indicator})
            rows = macro_r.fetchall()
            if rows:
                current = rows[0].value
                week_ago = rows[-1].value if len(rows) > 1 else current
                change_1w = round(((current - week_ago) / week_ago) * 100, 2) if week_ago else 0
                cross_assets.append({
                    "label": label,
                    "ticker": indicator,
                    "value": round(current, 2),
                    "change_1w_pct": change_1w,
                })
        except Exception:
            pass

    return {
        "regime":       regime_data,
        "sectors":      sectors,
        "fii_dii":      fii_series,
        "cross_assets": cross_assets,
    }


# ── Compounder screen ─────────────────────────────────────────────────────────

@router.get("/compounders")
async def get_compounders(
    country: Optional[str] = Query(None, description="US or IN"),
    db: AsyncSession = Depends(get_db),
):
    """
    Long-term quality screen. Returns stocks classified as
    COMPOUNDER / ACCUMULATION_ZONE / OVERVALUED_WAIT.
    """
    mgr = UniverseManager(use_cache=True, cache_ttl_hours=24)
    tickers = mgr.get_all_tickers("MEDIUM")

    # Optionally filter by country
    if country:
        if country.upper() == "IN":
            tickers = [t for t in tickers if ".NS" in t or ".BO" in t]
        elif country.upper() == "US":
            tickers = [t for t in tickers
                       if not any(t.endswith(x) for x in (".NS", ".BO", "-USD", "=F"))
                       and "^" not in t]

    try:
        engine = CompoundersEngine(db)
        results = await engine.screen(tickers)
        return {"total": len(results), "items": results}
    except Exception as e:
        logger.error("Compounder screen failed: %s", e)
        return {"total": 0, "items": [], "error": str(e)}


# ── Alert mark-as-read ─────────────────────────────────────────────────────────

@router.post("/alerts/mark-read")
async def mark_alerts_read(
    ids: List[int]    = Body(default=[], description="Alert IDs to mark read. Empty list = mark all."),
    db:  AsyncSession = Depends(get_db),
):
    """
    Mark alerts as read.
    - Pass a list of IDs to mark specific alerts.
    - Pass an empty list (or omit body) to mark ALL unread alerts as read.
    """
    if ids:
        stmt = (
            update(Alert)
            .where(Alert.id.in_(ids))
            .values(is_read=True)
        )
    else:
        stmt = (
            update(Alert)
            .where(Alert.is_read == False)  # noqa: E712
            .values(is_read=True)
        )

    result = await db.execute(stmt)
    await db.commit()
    updated = result.rowcount
    logger.info("Marked %d alert(s) as read.", updated)
    return {"updated": updated}
