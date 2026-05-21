"""
api/analysts.py
===============
Analyst rating change endpoints.

GET /analysts/recent          — recent upgrades/downgrades across the universe
GET /analysts/consensus/{ticker} — consensus ratings + price target distribution
GET /analysts/{ticker}        — full rating history for one ticker
"""
import asyncio
import logging
from datetime import datetime, timedelta, timezone
from typing import Optional

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from app.db.session import get_db
from app.models.market_data import AnalystRating, Stock
from app.ingestion.core.analyst_ratings import AnalystRatingService

router = APIRouter()
logger = logging.getLogger(__name__)

# ── Grade helpers ──────────────────────────────────────────────────────────────

_BULLISH_GRADES = frozenset({
    "buy", "strong buy", "overweight", "outperform", "accumulate",
    "positive", "top pick", "add",
})
_BEARISH_GRADES = frozenset({
    "sell", "strong sell", "underweight", "underperform", "negative", "reduce",
})
_BUY_ACTIONS    = frozenset({"upgrade", "init"})
_SELL_ACTIONS   = frozenset({"downgrade"})


def _grade_signal(action: Optional[str], to_grade: Optional[str]) -> str:
    """Return BULLISH, BEARISH, or NEUTRAL based on action and grade."""
    grade_lower = (to_grade or "").lower()
    action_lower = (action or "").lower()

    if action_lower in _BUY_ACTIONS and grade_lower in _BULLISH_GRADES:
        return "BULLISH"
    if action_lower in _SELL_ACTIONS and grade_lower in _BEARISH_GRADES:
        return "BEARISH"
    if grade_lower in _BULLISH_GRADES:
        return "BULLISH"
    if grade_lower in _BEARISH_GRADES:
        return "BEARISH"
    return "NEUTRAL"


def _rating_to_dict(r: AnalystRating, signal: Optional[str] = None) -> dict:
    return {
        "id":           r.id,
        "ticker":       r.ticker,
        "date":         r.date.isoformat() if r.date else None,
        "firm":         r.firm,
        "action":       r.action,
        "from_grade":   r.from_grade,
        "to_grade":     r.to_grade,
        "price_target": r.price_target,
        "signal":       signal or _grade_signal(r.action, r.to_grade),
    }


# ── GET /recent ────────────────────────────────────────────────────────────────

@router.get("/recent")
async def get_recent_ratings(
    days:    int           = Query(14,       ge=1, le=90),
    action:  str           = Query("all",    description="upgrade/downgrade/init/reit/all"),
    country: str           = Query("US",     description="Country filter: US, IN, or ALL"),
    db:      AsyncSession  = Depends(get_db),
):
    """
    Return recent analyst rating changes with stock info and a signal field.
    """
    since = datetime.now(timezone.utc) - timedelta(days=days)

    stmt = (
        select(AnalystRating, Stock.sector, Stock.country, Stock.name)
        .join(Stock, Stock.ticker == AnalystRating.ticker)
        .where(AnalystRating.date >= since)
    )

    if action.lower() != "all":
        stmt = stmt.where(AnalystRating.action == action.lower())

    if country.upper() != "ALL":
        stmt = stmt.where(Stock.country == country.upper())

    stmt = stmt.order_by(AnalystRating.date.desc()).limit(200)

    result = await db.execute(stmt)
    rows = result.fetchall()

    output = []
    for rating_obj, sector, stk_country, stk_name in rows:
        d = _rating_to_dict(rating_obj)
        d["sector"]  = sector
        d["country"] = stk_country
        d["name"]    = stk_name
        output.append(d)

    return output


# ── GET /consensus/{ticker} — must be before /{ticker} ────────────────────────

@router.get("/consensus/{ticker}")
async def get_consensus(
    ticker: str,
    db:     AsyncSession = Depends(get_db),
):
    """
    Return analyst consensus and price target distribution for one ticker.
    Tries DB data first; falls back to yfinance recommendations if stale.
    """
    ticker = ticker.upper()
    since  = datetime.now(timezone.utc) - timedelta(days=90)

    stmt = (
        select(AnalystRating)
        .where(AnalystRating.ticker == ticker)
        .where(AnalystRating.date >= since)
        .order_by(AnalystRating.date.desc())
    )
    result = await db.execute(stmt)
    db_ratings = result.scalars().all()

    # Compute counts from DB
    buy_count  = sum(1 for r in db_ratings if _grade_signal(r.action, r.to_grade) == "BULLISH")
    hold_count = sum(1 for r in db_ratings if _grade_signal(r.action, r.to_grade) == "NEUTRAL")
    sell_count = sum(1 for r in db_ratings if _grade_signal(r.action, r.to_grade) == "BEARISH")
    targets    = [r.price_target for r in db_ratings if r.price_target is not None]
    avg_target = round(sum(targets) / len(targets), 2) if targets else None

    # Try yfinance recommendations summary as supplemental data
    yf_summary = None
    try:
        import yfinance as yf

        def _fetch_yf():
            t = yf.Ticker(ticker)
            recs = t.recommendations
            if recs is None or (hasattr(recs, "empty") and recs.empty):
                return None
            # recommendations returns a DataFrame with period, strongBuy, buy, hold, sell, strongSell
            if hasattr(recs, "to_dict"):
                latest = recs.iloc[-1].to_dict() if len(recs) > 0 else {}
                return {k: v for k, v in latest.items() if k != "period"}
            return None

        yf_summary = await asyncio.to_thread(_fetch_yf)
    except Exception as e:
        logger.debug("[Analysts] yfinance consensus fallback failed for %s: %s", ticker, e)

    # Price target distribution
    target_distribution: dict = {}
    if targets:
        sorted_targets = sorted(targets)
        n = len(sorted_targets)
        target_distribution = {
            "min":    round(sorted_targets[0], 2),
            "max":    round(sorted_targets[-1], 2),
            "mean":   round(sum(sorted_targets) / n, 2),
            "median": round(sorted_targets[n // 2], 2),
            "count":  n,
        }

    return {
        "ticker":               ticker,
        "consensus": {
            "buy_count":        buy_count,
            "hold_count":       hold_count,
            "sell_count":       sell_count,
            "avg_price_target": avg_target,
        },
        "price_target_distribution": target_distribution,
        "yf_recommendations_summary": yf_summary,
    }


# ── GET /{ticker} ──────────────────────────────────────────────────────────────

@router.get("/{ticker}")
async def get_ticker_ratings(
    ticker: str,
    db:     AsyncSession = Depends(get_db),
):
    """
    Full analyst rating history for one ticker (last 90 days).
    Includes a consensus summary.
    """
    ticker = ticker.upper()
    since  = datetime.now(timezone.utc) - timedelta(days=90)

    stmt = (
        select(AnalystRating)
        .where(AnalystRating.ticker == ticker)
        .where(AnalystRating.date >= since)
        .order_by(AnalystRating.date.desc())
    )
    result = await db.execute(stmt)
    ratings = result.scalars().all()

    buy_count  = sum(1 for r in ratings if _grade_signal(r.action, r.to_grade) == "BULLISH")
    hold_count = sum(1 for r in ratings if _grade_signal(r.action, r.to_grade) == "NEUTRAL")
    sell_count = sum(1 for r in ratings if _grade_signal(r.action, r.to_grade) == "BEARISH")
    targets    = [r.price_target for r in ratings if r.price_target is not None]
    avg_target = round(sum(targets) / len(targets), 2) if targets else None

    return {
        "ticker":       ticker,
        "ratings":      [_rating_to_dict(r) for r in ratings],
        "summary": {
            "buy_count":        buy_count,
            "hold_count":       hold_count,
            "sell_count":       sell_count,
            "avg_price_target": avg_target,
        },
    }
