"""
api/earnings.py
===============
Earnings calendar and pre-earnings setup scoring endpoints.

GET /earnings/calendar              — upcoming earnings for HIGH-tier stocks
GET /earnings/calendar/{ticker}     — full earnings history + setup score for one ticker
GET /earnings/calendar/setups/best  — top pre-earnings setups filtered by score
"""
import asyncio
import logging
from typing import Optional

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from app.db.session import get_db
from app.models.market_data import Stock, AIAnalysis
from app.ingestion.core.earnings import EarningsCalendarService

router = APIRouter()
logger = logging.getLogger(__name__)

_svc = EarningsCalendarService()


# ── /calendar ─────────────────────────────────────────────────────────────────

@router.get("/calendar")
async def get_earnings_calendar(
    days_ahead: int = Query(30, ge=1, le=90, description="Number of days ahead to look"),
    country: Optional[str] = Query("ALL", description="Filter by country: US, IN, or ALL"),
    tickers: Optional[str] = Query(None, description="Comma-separated tickers override"),
    db: AsyncSession = Depends(get_db),
):
    """
    Return upcoming earnings events for HIGH-tier stocks within days_ahead days.
    Pass ?tickers=AAPL,MSFT to override the default universe.
    Pass ?country=US or ?country=IN to filter by country.
    """
    if tickers:
        ticker_list = [t.strip().upper() for t in tickers.split(",") if t.strip()]
    else:
        # Pull HIGH-tier tickers from the stocks table.
        # We use all stocks that have an AIAnalysis entry as a proxy for
        # "active" HIGH-tier names when the UniverseManager cache is cold.
        stmt = select(Stock.ticker)
        if country and country.upper() != "ALL":
            stmt = stmt.where(Stock.country == country.upper())
        result = await db.execute(stmt)
        ticker_list = [row[0] for row in result.fetchall()]

    if not ticker_list:
        return []

    upcoming = await _svc.get_upcoming_earnings(ticker_list, days_ahead=days_ahead)

    # Apply country filter when tickers were provided explicitly
    if tickers and country and country.upper() != "ALL":
        # Enrich with country from DB to allow filtering
        stmt = select(Stock.ticker, Stock.country).where(Stock.ticker.in_(ticker_list))
        res = await db.execute(stmt)
        country_map = {row[0]: row[1] for row in res.fetchall()}
        upcoming = [
            e for e in upcoming
            if country_map.get(e["ticker"], "").upper() == country.upper()
        ]

    return upcoming


# ── /calendar/setups/best — must be registered BEFORE /calendar/{ticker} ──────

@router.get("/calendar/setups/best")
async def get_best_earnings_setups(
    days_ahead: int = Query(7, ge=1, le=30),
    min_score: int = Query(60, ge=0, le=100),
    db: AsyncSession = Depends(get_db),
):
    """
    Scan upcoming earnings (within days_ahead) and return setups with
    setup_score >= min_score, sorted by score descending. Max 20 results.
    """
    # Get all tickers with earnings in the window
    stmt = select(Stock.ticker)
    result = await db.execute(stmt)
    all_tickers = [row[0] for row in result.fetchall()]

    if not all_tickers:
        return []

    upcoming = await _svc.get_upcoming_earnings(all_tickers, days_ahead=days_ahead)

    if not upcoming:
        return []

    # Score each upcoming ticker concurrently
    async def _score(entry: dict) -> Optional[dict]:
        try:
            scored = await _svc.score_pre_earnings_setup(entry["ticker"], db)
            scored["earnings_date"] = entry.get("earnings_date")
            scored["days_until"] = entry.get("days_until")
            scored["company_name"] = entry.get("company_name")
            return scored
        except Exception as exc:
            logger.debug("Setup score failed for %s: %s", entry["ticker"], exc)
            return None

    results = await asyncio.gather(*[_score(e) for e in upcoming])
    setups = [r for r in results if r is not None and r["setup_score"] >= min_score]
    setups.sort(key=lambda x: x["setup_score"], reverse=True)
    return setups[:20]


# ── /calendar/{ticker} ────────────────────────────────────────────────────────

@router.get("/calendar/{ticker}")
async def get_ticker_earnings(
    ticker: str,
    db: AsyncSession = Depends(get_db),
):
    """
    Full earnings history and pre-earnings setup score for a single ticker.
    """
    ticker = ticker.upper()
    history_task = _svc.get_ticker_earnings_history(ticker)
    score_task = _svc.score_pre_earnings_setup(ticker, db)

    history_result, score_result = await asyncio.gather(history_task, score_task)

    return {
        "ticker": ticker,
        "history": history_result.get("history", []),
        "setup_score": score_result,
    }
