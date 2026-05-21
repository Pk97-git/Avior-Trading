"""
api/agents.py
=============
Agent endpoints — trigger analysis and retrieve per-ticker results.

GET  /agents/analysis/{ticker}   — latest stored analysis for a ticker
POST /agents/analyze/{ticker}    — run fresh analysis right now
GET  /agents/performance         — signal accuracy report (hit rates, avg returns)
GET  /agents/system-status       — API key indicators, scheduler info, row counts
"""
import logging
import os
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, text

from app.db.session import get_db
from app.models.market_data import AIAnalysis, Stock
from app.agents.runner import run_all_agents

router = APIRouter()
logger = logging.getLogger(__name__)


def _serialise(a: AIAnalysis) -> dict:
    return {
        "ticker":               a.ticker,
        "analysis_date":        a.analysis_date,
        # Individual agent scores
        "fundamental_score":    a.fundamental_score,
        "technical_score":      a.technical_score,
        "macro_score":          a.macro_score,
        "institutional_score":  a.institutional_score,
        "sentiment_score":      a.sentiment_score,
        "memory_confidence":    a.memory_confidence,
        # Executive Trader output
        "final_score":          a.final_score,
        "signal":               a.signal,
        "regime":               a.regime,
        # Per-agent theses
        "fundamental_thesis":   a.fundamental_thesis,
        "technical_thesis":     a.technical_thesis,
        "macro_thesis":         a.macro_thesis,
        "institutional_thesis": a.institutional_thesis,
        "sentiment_thesis":     a.sentiment_thesis,
        "memory_thesis":        a.memory_thesis,
        "vision_score":         a.vision_score,
        "vision_thesis":        a.vision_thesis,
        "signal_thesis":        a.signal_thesis,
        # Phase 2: strategist outputs
        "factor_scores":           a.factor_scores,
        "cross_asset_sensitivity": a.cross_asset_sensitivity,
        # Phase 3: risk outputs
        "calibrated_prob":  a.calibrated_prob,
        "kelly_fraction":   a.kelly_fraction,
        "max_position_pct": a.max_position_pct,
        # Memory analogs
        "analogs": a.analogs,
        # Trade levels
        "entry_price":  a.entry_price,
        "stop_loss":    a.stop_loss,
        "take_profit":  a.take_profit,
        "atr_14":       a.atr_14,
    }


@router.get("/analysis/{ticker}")
async def get_analysis(ticker: str, db: AsyncSession = Depends(get_db)):
    """Fetch the latest stored AI analysis for a ticker. Triggers a fresh run if none exists."""
    ticker = ticker.upper()

    stmt = (
        select(AIAnalysis)
        .where(AIAnalysis.ticker == ticker)
        .order_by(AIAnalysis.analysis_date.desc())
        .limit(1)
    )
    result = await db.execute(stmt)
    analysis = result.scalars().first()

    if not analysis:
        logger.info("No stored analysis for %s — running agents now.", ticker)
        return await trigger_analysis(ticker, db)

    return _serialise(analysis)


@router.post("/analyze/{ticker}")
async def trigger_analysis(ticker: str, db: AsyncSession = Depends(get_db)):
    """Force a fresh analysis for the given ticker. Stores result and fires alerts."""
    ticker = ticker.upper()
    logger.info("Triggering full agent run for %s", ticker)

    try:
        result = await run_all_agents(db, ticker)
        return {"status": "success", **result}
    except Exception as e:
        logger.error("Agent run failed for %s: %s", ticker, e)
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/performance")
async def get_signal_performance(
    days: int = Query(90, ge=7, le=365, description="Lookback window in days"),
    db: AsyncSession = Depends(get_db),
):
    """
    Signal accuracy report: for each signal type, compute the hit rate and
    average forward return over 30-day windows using stored analysis history
    vs subsequent stock prices.
    """
    since = datetime.now(timezone.utc) - timedelta(days=days)

    # For each historical analysis, find the price at analysis date and 30 days later
    perf_q = text("""
        WITH analysis_with_prices AS (
            SELECT
                a.ticker,
                a.signal,
                a.final_score,
                a.analysis_date,
                p0.close  AS price_at_signal,
                p30.close AS price_30d_later
            FROM ai_analysis a
            -- Price on or after analysis date
            JOIN LATERAL (
                SELECT close FROM stock_prices
                WHERE ticker = a.ticker
                  AND time >= a.analysis_date
                ORDER BY time ASC LIMIT 1
            ) p0 ON true
            -- Price ~30 days later
            LEFT JOIN LATERAL (
                SELECT close FROM stock_prices
                WHERE ticker = a.ticker
                  AND time >= a.analysis_date + INTERVAL '28 days'
                  AND time <= a.analysis_date + INTERVAL '35 days'
                ORDER BY time ASC LIMIT 1
            ) p30 ON true
            WHERE a.analysis_date >= :since
              AND a.signal IN ('BUY', 'HOLD', 'REDUCE', 'SELL')
        )
        SELECT
            signal,
            COUNT(*)                                                    AS total,
            COUNT(price_30d_later)                                      AS with_outcome,
            ROUND(AVG(
                CASE
                  WHEN price_30d_later IS NOT NULL AND price_at_signal > 0
                  THEN (price_30d_later - price_at_signal) / price_at_signal * 100
                END
            )::numeric, 2)                                              AS avg_return_30d,
            ROUND(AVG(final_score)::numeric, 1)                        AS avg_score,
            COUNT(CASE WHEN signal = 'BUY'
                       AND price_30d_later > price_at_signal THEN 1 END) AS buy_wins,
            COUNT(CASE WHEN signal IN ('SELL', 'REDUCE')
                       AND price_30d_later < price_at_signal THEN 1 END) AS dist_wins
        FROM analysis_with_prices
        GROUP BY signal
        ORDER BY signal
    """)

    try:
        r = await db.execute(perf_q, {"since": since})
        rows = r.fetchall()
    except Exception as e:
        logger.error("Performance query failed: %s", e)
        rows = []

    results = []
    for row in rows:
        total = row.total or 0
        with_outcome = row.with_outcome or 0
        buy_wins = row.buy_wins or 0
        dist_wins = row.dist_wins or 0

        # Hit rate = wins / outcomes (directional correctness)
        if row.signal == "BUY":
            hit_rate = round(buy_wins / with_outcome * 100, 1) if with_outcome > 0 else None
        elif row.signal in ("SELL", "REDUCE"):
            hit_rate = round(dist_wins / with_outcome * 100, 1) if with_outcome > 0 else None
        else:
            hit_rate = None

        results.append({
            "signal":          row.signal,
            "total_signals":   total,
            "with_outcome":    with_outcome,
            "pending":         total - with_outcome,
            "avg_score":       float(row.avg_score) if row.avg_score else None,
            "avg_return_30d":  float(row.avg_return_30d) if row.avg_return_30d else None,
            "hit_rate_pct":    hit_rate,
        })

    # Total signal count
    total_q = text("SELECT COUNT(*) FROM ai_analysis WHERE analysis_date >= :since")
    total_r = await db.execute(total_q, {"since": since})
    total_analyses = total_r.scalar() or 0

    return {
        "lookback_days": days,
        "total_analyses": total_analyses,
        "by_signal": results,
    }


@router.get("/system-status")
async def get_system_status(db: AsyncSession = Depends(get_db)):
    """
    Returns system health: API key status, table row counts, and last run times.
    """
    # API key presence (don't expose the keys themselves)
    api_keys = {
        "groq":      bool(os.getenv("GROQ_API_KEY")),
        "anthropic": bool(os.getenv("ANTHROPIC_API_KEY")),
        "openai":    bool(os.getenv("OPENAI_API_KEY")),
        "gemini":    bool(os.getenv("GEMINI_API_KEY")),
        "fred":      bool(os.getenv("FRED_API_KEY")),
    }

    # Row counts per table
    table_counts = {}
    tables = [
        "stocks", "stock_prices", "company_financials", "macro_data",
        "news_sentiment", "institutional_flows", "promoter_holdings",
        "ai_analysis", "alerts", "watchlist",
    ]
    for tbl in tables:
        try:
            r = await db.execute(text(f"SELECT COUNT(*) FROM {tbl}"))
            table_counts[tbl] = r.scalar() or 0
        except Exception:
            table_counts[tbl] = None

    # Last run times (most recent analysis, alert, price)
    last_runs = {}
    try:
        r = await db.execute(text("SELECT MAX(analysis_date) FROM ai_analysis"))
        last_runs["last_analysis"] = r.scalar()
    except Exception:
        last_runs["last_analysis"] = None

    try:
        r = await db.execute(text("SELECT MAX(generated_at) FROM alerts"))
        last_runs["last_alert"] = r.scalar()
    except Exception:
        last_runs["last_alert"] = None

    try:
        r = await db.execute(text("SELECT MAX(time) FROM stock_prices"))
        last_runs["last_price_update"] = r.scalar()
    except Exception:
        last_runs["last_price_update"] = None

    try:
        r = await db.execute(text("SELECT MAX(time) FROM macro_data"))
        last_runs["last_macro_update"] = r.scalar()
    except Exception:
        last_runs["last_macro_update"] = None

    # Universe breakdown
    try:
        r = await db.execute(text("""
            SELECT country, COUNT(*) as n FROM stocks GROUP BY country ORDER BY n DESC
        """))
        universe_breakdown = {row.country or "unknown": row.n for row in r.fetchall()}
    except Exception:
        universe_breakdown = {}

    notification_channels = {
        "slack": bool(os.getenv("SLACK_WEBHOOK_URL")),
        "email": bool(os.getenv("ALERT_EMAIL_TO") and os.getenv("SMTP_USER")),
    }

    return {
        "api_keys":             api_keys,
        "table_counts":         table_counts,
        "last_runs":            last_runs,
        "universe_breakdown":   universe_breakdown,
        "notification_channels": notification_channels,
    }
