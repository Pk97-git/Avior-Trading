"""
api/briefing.py
===============
Daily Intelligence Briefing — synthesises every data stream into a single
actionable report: top buys, top sells, earnings catalysts, options alerts,
sector positioning, and macro context.

GET  /briefing/daily   — full report (cached 30 min)
POST /briefing/refresh — force a fresh generation
"""
import logging
from datetime import datetime, timedelta, timezone
from typing import Optional

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, text

from app.db.session import get_db
from app.models.market_data import (
    AIAnalysis, Stock, NewsSentiment, MacroEconomicData,
    Alert, StockPrice,
)
from app.engines.circuit_breaker import CircuitBreakerEngine
from app.engines.sector_rotation import SectorRotationEngine
from app.ingestion.core.economic_calendar import EconomicCalendarService

router = APIRouter()
logger = logging.getLogger("omnitrader.briefing")

# ── 30-minute in-memory cache ─────────────────────────────────────────────────
_cache: dict = {"report": None, "generated_at": None}
CACHE_TTL_MINUTES = 30

SIGNAL_RANK = {
    "BUY":             1,
    "HOLD":            2,
    "PROACTIVE_SWING": 3,
    "REDUCE":          4,
    "SELL":            5,
}

SIGNAL_LABEL = {
    "BUY":             "Buy",
    "HOLD":            "Hold",
    "PROACTIVE_SWING": "Swing Setup",
    "REDUCE":          "Reduce",
    "SELL":            "Sell",
}

SIGNAL_COLOR = {
    "BUY":             "green",
    "HOLD":            "blue",
    "PROACTIVE_SWING": "purple",
    "REDUCE":          "yellow",
    "SELL":            "red",
}


# ─── Helpers ──────────────────────────────────────────────────────────────────

def _rr(entry, stop, target):
    """Risk/reward ratio."""
    if not entry or not stop or not target:
        return None
    risk   = abs(entry - stop)
    reward = abs(target - entry)
    if risk == 0:
        return None
    return round(reward / risk, 2)


def _pct_from(a, b):
    if not a or not b or a == 0:
        return None
    return round((b - a) / a * 100, 2)


async def _latest_analysis_per_ticker(db: AsyncSession) -> list[AIAnalysis]:
    """
    Return the single most-recent AIAnalysis row per ticker
    (analysis_date within the last 7 days to exclude stale data).
    """
    cutoff = datetime.now(timezone.utc) - timedelta(days=7)
    stmt = text("""
        SELECT DISTINCT ON (ticker) *
        FROM ai_analysis
        WHERE analysis_date >= :cutoff
        ORDER BY ticker, analysis_date DESC
    """)
    result = await db.execute(stmt, {"cutoff": cutoff})
    rows = result.mappings().all()

    # Reconstruct as AIAnalysis-like dicts (avoids ORM overhead for bulk)
    return [dict(r) for r in rows]


async def _recent_news(db: AsyncSession, tickers: list[str], limit_per: int = 3) -> dict:
    """Return last `limit_per` news items per ticker."""
    if not tickers:
        return {}
    cutoff = datetime.now(timezone.utc) - timedelta(days=3)
    stmt = text("""
        SELECT DISTINCT ON (ticker, headline) ticker, headline, source,
               sentiment_score, time
        FROM news_sentiment
        WHERE ticker = ANY(:tickers) AND time >= :cutoff
        ORDER BY ticker, time DESC
    """)
    result = await db.execute(stmt, {"tickers": tickers, "cutoff": cutoff})
    rows = result.mappings().all()

    news: dict = {}
    for row in rows:
        t = row["ticker"]
        news.setdefault(t, [])
        if len(news[t]) < limit_per:
            news[t].append({
                "headline":       row["headline"],
                "source":         row["source"],
                "sentiment_score": row["sentiment_score"],
                "time":           row["time"].isoformat() if row["time"] else None,
            })
    return news


async def _macro_context(db: AsyncSession) -> dict:
    """Fetch latest values for key macro indicators."""
    indicators = ["VIX", "US10Y", "US2Y", "DXY", "OIL", "GOLD", "SP500"]
    stmt = text("""
        SELECT DISTINCT ON (indicator) indicator, value, time
        FROM macro_data
        WHERE indicator = ANY(:ind)
        ORDER BY indicator, time DESC
    """)
    result = await db.execute(stmt, {"ind": indicators})
    rows = result.mappings().all()

    ctx = {r["indicator"]: {"value": r["value"], "time": r["time"]} for r in rows}

    # Derived signals
    us10y = ctx.get("US10Y", {}).get("value")
    us2y  = ctx.get("US2Y",  {}).get("value")
    vix   = ctx.get("VIX",   {}).get("value")

    yield_spread   = round(us10y - us2y, 3) if us10y and us2y else None
    inverted       = yield_spread is not None and yield_spread < 0
    vix_regime     = ("PANIC" if vix and vix > 35
                      else "ELEVATED" if vix and vix > 25
                      else "CALM" if vix else "UNKNOWN")

    return {
        "indicators":    {k: v["value"] for k, v in ctx.items()},
        "yield_spread":  yield_spread,
        "yield_inverted": inverted,
        "vix_regime":    vix_regime,
        "vix":           vix,
    }


async def _sector_ranks(db: AsyncSession) -> dict[str, int]:
    """Map sector name → rotation rank."""
    try:
        engine = SectorRotationEngine(db)
        rankings = await engine.calculate()
        # Map each sector to rank_4w
        return {r["sector"]: r.get("rank_4w", 99) for r in rankings}
    except Exception:
        return {}


async def _stock_info(db: AsyncSession, tickers: list[str]) -> dict:
    """name + sector + country per ticker."""
    if not tickers:
        return {}
    result = await db.execute(
        select(Stock.ticker, Stock.name, Stock.sector, Stock.country)
        .where(Stock.ticker.in_(tickers))
    )
    return {
        r.ticker: {"name": r.name, "sector": r.sector, "country": r.country}
        for r in result.all()
    }


async def _recent_alerts(db: AsyncSession, tickers: list[str]) -> dict:
    """Most recent alert per ticker with signal context."""
    if not tickers:
        return {}
    cutoff = datetime.now(timezone.utc) - timedelta(days=3)
    stmt = text("""
        SELECT DISTINCT ON (ticker) ticker, signal, previous_signal,
               headline, thesis, generated_at
        FROM alerts
        WHERE ticker = ANY(:tickers) AND generated_at >= :cutoff
        ORDER BY ticker, generated_at DESC
    """)
    result = await db.execute(stmt, {"tickers": tickers, "cutoff": cutoff})
    return {
        r["ticker"]: {
            "signal":          r["signal"],
            "previous_signal": r["previous_signal"],
            "headline":        r["headline"],
            "thesis":          r["thesis"],
            "generated_at":    r["generated_at"].isoformat() if r["generated_at"] else None,
        }
        for r in result.mappings().all()
    }


def _build_stock_card(a: dict, info: dict, news: list, alert: Optional[dict],
                      sector_rank: Optional[int],
                      insider_signal: Optional[str] = None,
                      analyst_signal: Optional[dict] = None) -> dict:
    """Assemble one stock's briefing card from all available data."""
    ticker = a["ticker"]
    si     = info.get(ticker, {})

    entry  = a.get("entry_price")
    stop   = a.get("stop_loss")
    target = a.get("take_profit")

    # Compose the full reasoning — all agent theses + executive summary
    reasoning = {
        "executive":     a.get("signal_thesis")     or [],
        "technical":     a.get("technical_thesis")  or [],
        "fundamental":   a.get("fundamental_thesis") or [],
        "macro":         a.get("macro_thesis")      or [],
        "sentiment":     a.get("sentiment_thesis")  or [],
        "institutional": a.get("institutional_thesis") or [],
        "memory":        a.get("memory_thesis")     or [],
    }

    # Headline for the card — use alert headline if fresh, else build from signal_thesis
    headline = None
    if alert:
        headline = alert.get("headline")
    if not headline and reasoning["executive"]:
        headline = reasoning["executive"][0]

    # Risk metrics
    upside_pct   = _pct_from(entry, target)
    downside_pct = _pct_from(entry, stop)
    rr_ratio     = _rr(entry, stop, target)

    return {
        "ticker":         ticker,
        "name":           si.get("name"),
        "sector":         si.get("sector"),
        "country":        si.get("country"),
        "signal":         a.get("signal"),
        "signal_label":   SIGNAL_LABEL.get(a.get("signal"), a.get("signal")),
        "signal_color":   SIGNAL_COLOR.get(a.get("signal"), "grey"),
        "final_score":    a.get("final_score"),
        "regime":         a.get("regime"),
        "analysis_date":  a.get("analysis_date").isoformat() if a.get("analysis_date") else None,

        # Trade levels
        "entry_price":    entry,
        "stop_loss":      stop,
        "take_profit":    target,
        "atr_14":         a.get("atr_14"),
        "upside_pct":     upside_pct,
        "downside_pct":   downside_pct,
        "risk_reward":    rr_ratio,

        # Agent scores
        "scores": {
            "technical":     a.get("technical_score"),
            "fundamental":   a.get("fundamental_score"),
            "macro":         a.get("macro_score"),
            "institutional": a.get("institutional_score"),
            "sentiment":     a.get("sentiment_score"),
            "vision":        a.get("vision_score"),
        },

        # Risk sizing
        "calibrated_prob":  a.get("calibrated_prob"),
        "kelly_fraction":   a.get("kelly_fraction"),
        "max_position_pct": a.get("max_position_pct"),

        # Reasoning — all agent theses
        "reasoning":  reasoning,
        "headline":   headline,

        # Context enrichment
        "recent_news":   news,
        "sector_rank":   sector_rank,
        "recent_alert":  alert,

        # Factor & cross-asset context
        "factor_scores":           a.get("factor_scores"),
        "cross_asset_sensitivity": a.get("cross_asset_sensitivity"),
        "analogs":                 a.get("analogs"),

        # New enrichment signals
        "insider_signal":  insider_signal,   # "CLUSTER_BUY" / "INSIDER_BUY" / None
        "analyst_signal":  analyst_signal,   # {signal, upgrades, downgrades, avg_pt} / None
    }


# ─── Report Builder ───────────────────────────────────────────────────────────

async def _insider_signals(db: AsyncSession, tickers: list[str]) -> dict:
    """Recent insider purchase signals per ticker (last 30 days)."""
    try:
        cutoff = datetime.now(timezone.utc) - timedelta(days=30)
        stmt = text("""
            SELECT ticker, transaction_type, COUNT(*) as cnt,
                   SUM(total_value) as total_val,
                   COUNT(DISTINCT insider_name) as insider_count
            FROM insider_transactions
            WHERE ticker = ANY(:tickers) AND filed_date >= :cutoff
              AND transaction_type = 'P'
            GROUP BY ticker, transaction_type
        """)
        result = await db.execute(stmt, {"tickers": tickers, "cutoff": cutoff})
        signals = {}
        for row in result.mappings().all():
            t = row["ticker"]
            cnt = row["cnt"] or 0
            insider_count = row["insider_count"] or 0
            total_val = row["total_val"] or 0
            if insider_count >= 3 or total_val >= 1_000_000:
                signals[t] = "CLUSTER_BUY"
            elif cnt >= 1:
                signals[t] = "INSIDER_BUY"
        return signals
    except Exception:
        return {}


async def _analyst_signals(db: AsyncSession, tickers: list[str]) -> dict:
    """Recent analyst upgrades/downgrades per ticker (last 30 days)."""
    try:
        cutoff = datetime.now(timezone.utc) - timedelta(days=30)
        stmt = text("""
            SELECT ticker,
                   SUM(CASE WHEN action = 'upgrade' THEN 1 ELSE 0 END) as upgrades,
                   SUM(CASE WHEN action = 'downgrade' THEN 1 ELSE 0 END) as downgrades,
                   MAX(price_target) as max_pt,
                   MIN(price_target) FILTER (WHERE price_target > 0) as min_pt
            FROM analyst_ratings
            WHERE ticker = ANY(:tickers) AND date >= :cutoff
            GROUP BY ticker
        """)
        result = await db.execute(stmt, {"tickers": tickers, "cutoff": cutoff})
        signals = {}
        for row in result.mappings().all():
            t = row["ticker"]
            upgrades   = row["upgrades"] or 0
            downgrades = row["downgrades"] or 0
            if upgrades > downgrades:
                signals[t] = {"signal": "BULLISH", "upgrades": upgrades, "downgrades": downgrades,
                               "avg_pt": row["max_pt"]}
            elif downgrades > upgrades:
                signals[t] = {"signal": "BEARISH", "upgrades": upgrades, "downgrades": downgrades,
                               "avg_pt": row["min_pt"]}
        return signals
    except Exception:
        return {}


async def _build_report(db: AsyncSession) -> dict:
    now = datetime.now(timezone.utc)

    # 1. Latest analysis rows
    analyses = await _latest_analysis_per_ticker(db)
    if not analyses:
        return {
            "generated_at":     now.isoformat(),
            "has_data":         False,
            "message":          "No AI analysis data yet. Run the agent batch to generate signals.",
            "top_buys":         [],
            "top_sells":        [],
            "watchlist_holds":  [],
            "macro_context":    {},
            "circuit_breaker":  {},
            "sector_advice":    [],
        }

    tickers = [a["ticker"] for a in analyses]

    # 2. Enrichment — run concurrently where possible
    import asyncio
    stock_info, news_map, alerts_map, macro, sector_ranks_map, insider_sigs, analyst_sigs = await asyncio.gather(
        _stock_info(db, tickers),
        _recent_news(db, tickers),
        _recent_alerts(db, tickers),
        _macro_context(db),
        _sector_ranks(db),
        _insider_signals(db, tickers),
        _analyst_signals(db, tickers),
        return_exceptions=True,
    )
    if isinstance(insider_sigs,  Exception): insider_sigs  = {}
    if isinstance(analyst_sigs,  Exception): analyst_sigs  = {}
    # Fallback on errors
    if isinstance(stock_info,     Exception): stock_info     = {}
    if isinstance(news_map,       Exception): news_map       = {}
    if isinstance(alerts_map,     Exception): alerts_map     = {}
    if isinstance(macro,          Exception): macro          = {}
    if isinstance(sector_ranks_map, Exception): sector_ranks_map = {}

    # 3. Circuit breaker
    cb_state = {"status": "UNKNOWN"}
    try:
        cb_engine = CircuitBreakerEngine(db)
        cb_state  = await cb_engine.check()
    except Exception:
        pass

    # 4. Sector rotation advice
    sector_advice = []
    try:
        engine = SectorRotationEngine(db)
        rankings = await engine.calculate()
        # Top 3 BUY, bottom 3 AVOID
        ranked = [r for r in rankings if r.get("change_4w") is not None]
        for r in ranked[:3]:
            r["advice"] = "BUY"
        for r in ranked[-3:]:
            r["advice"] = "AVOID"
        sector_advice = rankings
    except Exception:
        pass

    # 5. Build cards
    buys   = []
    sells  = []
    holds  = []

    for a in analyses:
        signal = a.get("signal") or "AVOID"
        t      = a["ticker"]
        si     = stock_info.get(t, {})
        news   = news_map.get(t, [])
        alert  = alerts_map.get(t)
        s_rank = sector_ranks_map.get(si.get("sector")) if isinstance(sector_ranks_map, dict) else None

        card = _build_stock_card(
            a, stock_info, news, alert, s_rank,
            insider_signal=insider_sigs.get(t) if isinstance(insider_sigs, dict) else None,
            analyst_signal=analyst_sigs.get(t) if isinstance(analyst_sigs, dict) else None,
        )

        if signal in ("BUY", "PROACTIVE_SWING"):
            buys.append(card)
        elif signal in ("SELL", "REDUCE"):
            sells.append(card)
        else:
            holds.append(card)

    # Sort: buys by final_score desc, sells by final_score asc (weakest first)
    buys.sort(key=lambda x: (x.get("final_score") or 0), reverse=True)
    sells.sort(key=lambda x: (x.get("final_score") or 100))

    # Economic calendar
    try:
        cal_svc = EconomicCalendarService()
        upcoming_events = cal_svc.get_upcoming_events(days_ahead=14)
        next_event = cal_svc.get_next_event()
        is_blackout = cal_svc.is_blackout_period(hours_ahead=24)
    except Exception:
        upcoming_events = []
        next_event = None
        is_blackout = False

    return {
        "generated_at":    now.isoformat(),
        "has_data":        True,
        "total_analyzed":  len(analyses),
        "macro_context":   macro,
        "circuit_breaker": cb_state,
        "sector_advice":   sector_advice,
        "top_buys":        buys[:15],
        "top_sells":       sells[:10],
        "watchlist_holds": holds[:5],
        "upcoming_events": upcoming_events,
        "next_event":      next_event,
        "is_blackout":     is_blackout,
        "summary": {
            "buy_count":   len(buys),
            "sell_count":  len(sells),
            "hold_count":  len(holds),
            "regime":      buys[0].get("regime") if buys else (sells[0].get("regime") if sells else None),
        },
    }


# ─── Endpoints ────────────────────────────────────────────────────────────────

@router.get("/daily")
async def get_daily_briefing(
    force: bool = Query(False, description="Bypass cache and rebuild now"),
    db: AsyncSession = Depends(get_db),
):
    """
    Return the full daily intelligence briefing.

    The report is cached for 30 minutes. Pass `?force=true` to regenerate
    immediately (takes 2–5 seconds for large universes).
    """
    global _cache

    # Serve from cache if fresh
    if (
        not force
        and _cache["report"] is not None
        and _cache["generated_at"] is not None
        and (datetime.now(timezone.utc) - _cache["generated_at"]).seconds < CACHE_TTL_MINUTES * 60
    ):
        return {**_cache["report"], "cached": True}

    report = await _build_report(db)

    _cache["report"]       = report
    _cache["generated_at"] = datetime.now(timezone.utc)

    return {**report, "cached": False}


@router.post("/refresh")
async def refresh_briefing(db: AsyncSession = Depends(get_db)):
    """Force-regenerate the briefing and update the cache."""
    global _cache
    report = await _build_report(db)
    _cache["report"]       = report
    _cache["generated_at"] = datetime.now(timezone.utc)
    return {**report, "cached": False}
