"""
api/watchlist.py
================
Watchlist management endpoints.

GET    /watchlist              — list all active watchlist entries with latest signal
POST   /watchlist/{ticker}     — add ticker to watchlist
DELETE /watchlist/{ticker}     — remove ticker from watchlist
PATCH  /watchlist/{ticker}     — update notes / priority
"""
import logging
from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, Body, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, text, delete

from app.db.session import get_db
from app.models.market_data import Watchlist, Stock, AIAnalysis

router = APIRouter()
logger = logging.getLogger(__name__)


@router.get("")
async def list_watchlist(db: AsyncSession = Depends(get_db)):
    """
    Return all active watchlist entries enriched with latest AI signal,
    current price, and basic stock metadata.
    """
    stmt = (
        select(Watchlist, Stock.name, Stock.sector, Stock.country)
        .join(Stock, Watchlist.ticker == Stock.ticker, isouter=True)
        .where(Watchlist.is_active == True)  # noqa: E712
        .order_by(Watchlist.priority.desc(), Watchlist.added_at.desc())
    )
    result = await db.execute(stmt)
    rows = result.fetchall()

    items = []
    for row in rows:
        wl, name, sector, country = row

        # Latest AI signal for this ticker
        signal_q = (
            select(AIAnalysis.signal, AIAnalysis.final_score, AIAnalysis.analysis_date, AIAnalysis.signal_thesis)
            .where(AIAnalysis.ticker == wl.ticker)
            .order_by(AIAnalysis.analysis_date.desc())
            .limit(1)
        )
        sig_r = await db.execute(signal_q)
        sig_row = sig_r.fetchone()

        # Latest price
        price_q = text("""
            SELECT close, time FROM stock_prices
            WHERE ticker = :t ORDER BY time DESC LIMIT 1
        """)
        price_r = await db.execute(price_q, {"t": wl.ticker})
        price_row = price_r.fetchone()

        items.append({
            "id":           wl.id,
            "ticker":       wl.ticker,
            "name":         name,
            "sector":       sector,
            "country":      country,
            "priority":     wl.priority,
            "notes":        wl.notes,
            "added_at":     wl.added_at,
            # Latest signal
            "signal":       sig_row.signal       if sig_row else None,
            "final_score":  sig_row.final_score  if sig_row else None,
            "signal_date":  sig_row.analysis_date if sig_row else None,
            "signal_thesis": sig_row.signal_thesis if sig_row else None,
            # Latest price
            "current_price": round(price_row.close, 2) if price_row else None,
            "price_date":    price_row.time if price_row else None,
        })

    return {"total": len(items), "items": items}


@router.post("/{ticker}")
async def add_to_watchlist(
    ticker:   str,
    notes:    Optional[str] = Body(None),
    priority: str           = Body("MEDIUM"),
    db:       AsyncSession  = Depends(get_db),
):
    """Add a ticker to the watchlist. Idempotent — re-activates if already present."""
    ticker = ticker.upper()

    # Verify ticker exists in stocks table
    stock_r = await db.execute(select(Stock).where(Stock.ticker == ticker))
    if not stock_r.scalars().first():
        raise HTTPException(status_code=404, detail=f"Ticker {ticker} not found in universe.")

    # Check if already in watchlist
    existing_q = select(Watchlist).where(Watchlist.ticker == ticker)
    existing_r = await db.execute(existing_q)
    existing = existing_r.scalars().first()

    if existing:
        existing.is_active = True
        existing.priority  = priority.upper()
        if notes is not None:
            existing.notes = notes
        await db.commit()
        return {"status": "reactivated", "ticker": ticker}

    entry = Watchlist(
        ticker    = ticker,
        added_at  = datetime.now(timezone.utc),
        notes     = notes,
        priority  = priority.upper(),
        is_active = True,
    )
    db.add(entry)
    await db.commit()
    logger.info("Added %s to watchlist (priority=%s)", ticker, priority)
    return {"status": "added", "ticker": ticker}


@router.delete("/{ticker}")
async def remove_from_watchlist(
    ticker: str,
    db:     AsyncSession = Depends(get_db),
):
    """Remove a ticker from the watchlist (soft-delete: sets is_active=False)."""
    ticker = ticker.upper()

    result = await db.execute(
        select(Watchlist).where(Watchlist.ticker == ticker, Watchlist.is_active == True)  # noqa: E712
    )
    entry = result.scalars().first()

    if not entry:
        raise HTTPException(status_code=404, detail=f"{ticker} not found in active watchlist.")

    entry.is_active = False
    await db.commit()
    return {"status": "removed", "ticker": ticker}


@router.patch("/{ticker}")
async def update_watchlist_entry(
    ticker:   str,
    notes:    Optional[str] = Body(None),
    priority: Optional[str] = Body(None),
    db:       AsyncSession  = Depends(get_db),
):
    """Update notes or priority for a watchlist entry."""
    ticker = ticker.upper()

    result = await db.execute(
        select(Watchlist).where(Watchlist.ticker == ticker, Watchlist.is_active == True)  # noqa: E712
    )
    entry = result.scalars().first()

    if not entry:
        raise HTTPException(status_code=404, detail=f"{ticker} not found in active watchlist.")

    if notes is not None:
        entry.notes = notes
    if priority is not None:
        entry.priority = priority.upper()

    await db.commit()
    return {"status": "updated", "ticker": ticker}
