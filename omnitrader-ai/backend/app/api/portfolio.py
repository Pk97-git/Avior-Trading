"""
api/portfolio.py
================
Portfolio position management and P&L tracking endpoints.

GET    /portfolio              — list open positions with live unrealized P&L
POST   /portfolio/{ticker}     — open a new position
PATCH  /portfolio/{id}         — update stop/target/notes on open position
POST   /portfolio/{id}/close   — close a position and record realized P&L
GET    /portfolio/summary      — aggregate P&L statistics
GET    /portfolio/history      — closed positions (paginated, newest first)
"""
import logging
from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, Body, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, text, func

from app.db.session import get_db
from app.models.market_data import PortfolioPosition, Stock

router = APIRouter()
logger = logging.getLogger(__name__)


# ─── Helpers ──────────────────────────────────────────────────────────────────

async def _get_latest_prices(db: AsyncSession, tickers: list[str]) -> dict[str, float]:
    """Return {ticker: latest_close} for the given tickers using a single query."""
    if not tickers:
        return {}
    price_q = text("""
        SELECT DISTINCT ON (ticker) ticker, close
        FROM stock_prices
        WHERE ticker = ANY(:tickers)
        ORDER BY ticker, time DESC
    """)
    result = await db.execute(price_q, {"tickers": tickers})
    return {row.ticker: row.close for row in result.fetchall()}


async def _enrich_position(pos: PortfolioPosition, current_price: Optional[float],
                            name: Optional[str], sector: Optional[str],
                            country: Optional[str]) -> dict:
    """Build the full position dict with live P&L calculations."""
    cp = current_price
    unrealized_pnl = None
    unrealized_pnl_pct = None
    risk_pct = None
    reward_pct = None

    if cp is not None:
        unrealized_pnl = round((cp - pos.entry_price) * pos.shares, 2)
        unrealized_pnl_pct = round((cp / pos.entry_price - 1) * 100, 2) if pos.entry_price else None

    if pos.stop_loss and pos.entry_price:
        risk_pct = round((pos.entry_price - pos.stop_loss) / pos.entry_price * 100, 2)

    if pos.take_profit and pos.entry_price:
        reward_pct = round((pos.take_profit - pos.entry_price) / pos.entry_price * 100, 2)

    return {
        "id":                  pos.id,
        "ticker":              pos.ticker,
        "name":                name,
        "sector":              sector,
        "country":             country,
        "entry_date":          pos.entry_date,
        "entry_price":         pos.entry_price,
        "shares":              pos.shares,
        "position_value":      pos.position_value,
        "stop_loss":           pos.stop_loss,
        "take_profit":         pos.take_profit,
        "signal":              pos.signal,
        "regime":              pos.regime,
        "notes":               pos.notes,
        "is_open":             pos.is_open,
        # Closing fields
        "exit_date":           pos.exit_date,
        "exit_price":          pos.exit_price,
        "exit_reason":         pos.exit_reason,
        "realized_pnl":        pos.realized_pnl,
        "realized_pnl_pct":    pos.realized_pnl_pct,
        # Live enrichment
        "current_price":       round(cp, 4) if cp is not None else None,
        "unrealized_pnl":      unrealized_pnl,
        "unrealized_pnl_pct":  unrealized_pnl_pct,
        "risk_pct":            risk_pct,
        "reward_pct":          reward_pct,
    }


# ─── Endpoints ────────────────────────────────────────────────────────────────

@router.get("")
async def list_open_positions(db: AsyncSession = Depends(get_db)):
    """Return all open positions enriched with live unrealized P&L."""
    stmt = (
        select(PortfolioPosition, Stock.name, Stock.sector, Stock.country)
        .join(Stock, PortfolioPosition.ticker == Stock.ticker, isouter=True)
        .where(PortfolioPosition.is_open == True)  # noqa: E712
        .order_by(PortfolioPosition.entry_date.desc())
    )
    result = await db.execute(stmt)
    rows = result.fetchall()

    tickers = [row[0].ticker for row in rows]
    prices = await _get_latest_prices(db, tickers)

    items = []
    for pos, name, sector, country in rows:
        enriched = await _enrich_position(pos, prices.get(pos.ticker), name, sector, country)
        items.append(enriched)

    return {"total": len(items), "items": items}


@router.get("/summary")
async def get_portfolio_summary(db: AsyncSession = Depends(get_db)):
    """Aggregate P&L statistics across open and closed positions."""
    # Open positions
    open_stmt = (
        select(PortfolioPosition, Stock.name, Stock.sector, Stock.country)
        .join(Stock, PortfolioPosition.ticker == Stock.ticker, isouter=True)
        .where(PortfolioPosition.is_open == True)  # noqa: E712
    )
    open_result = await db.execute(open_stmt)
    open_rows = open_result.fetchall()

    tickers = [row[0].ticker for row in open_rows]
    prices = await _get_latest_prices(db, tickers)

    total_invested = 0.0
    total_current_value = 0.0
    best_pos = None
    worst_pos = None

    signal_breakdown: dict[str, dict] = {}

    for pos, name, sector, country in open_rows:
        invested = (pos.entry_price or 0) * (pos.shares or 0)
        total_invested += invested

        cp = prices.get(pos.ticker)
        current_val = (cp * pos.shares) if cp is not None else invested
        total_current_value += current_val

        pnl_pct = ((cp / pos.entry_price) - 1) * 100 if (cp and pos.entry_price) else 0.0

        enriched = {"ticker": pos.ticker, "unrealized_pnl_pct": pnl_pct}

        if best_pos is None or pnl_pct > best_pos["unrealized_pnl_pct"]:
            best_pos = enriched
        if worst_pos is None or pnl_pct < worst_pos["unrealized_pnl_pct"]:
            worst_pos = enriched

        sig = pos.signal or "UNKNOWN"
        if sig not in signal_breakdown:
            signal_breakdown[sig] = {"count": 0, "value": 0.0}
        signal_breakdown[sig]["count"] += 1
        signal_breakdown[sig]["value"] = round(signal_breakdown[sig]["value"] + invested, 2)

    total_unrealized_pnl = round(total_current_value - total_invested, 2)
    total_unrealized_pnl_pct = (
        round((total_current_value / total_invested - 1) * 100, 2)
        if total_invested > 0 else 0.0
    )

    # Realized P&L from closed positions
    realized_q = select(func.sum(PortfolioPosition.realized_pnl)).where(
        PortfolioPosition.is_open == False  # noqa: E712
    )
    realized_result = await db.execute(realized_q)
    total_realized_pnl = round(realized_result.scalar() or 0.0, 2)

    return {
        "total_invested":         round(total_invested, 2),
        "total_current_value":    round(total_current_value, 2),
        "total_unrealized_pnl":   total_unrealized_pnl,
        "total_unrealized_pnl_pct": total_unrealized_pnl_pct,
        "total_realized_pnl":     total_realized_pnl,
        "position_count":         len(open_rows),
        "best_position":          best_pos,
        "worst_position":         worst_pos,
        "by_signal":              signal_breakdown,
    }


@router.get("/history")
async def get_position_history(
    page:  int = Query(1, ge=1),
    limit: int = Query(20, ge=1, le=100),
    db:    AsyncSession = Depends(get_db),
):
    """Return closed positions, paginated, newest exit first."""
    offset = (page - 1) * limit

    count_q = select(func.count()).where(PortfolioPosition.is_open == False)  # noqa: E712
    total_result = await db.execute(count_q)
    total = total_result.scalar() or 0

    stmt = (
        select(PortfolioPosition, Stock.name, Stock.sector, Stock.country)
        .join(Stock, PortfolioPosition.ticker == Stock.ticker, isouter=True)
        .where(PortfolioPosition.is_open == False)  # noqa: E712
        .order_by(PortfolioPosition.exit_date.desc())
        .offset(offset)
        .limit(limit)
    )
    result = await db.execute(stmt)
    rows = result.fetchall()

    items = []
    for pos, name, sector, country in rows:
        enriched = await _enrich_position(pos, None, name, sector, country)
        items.append(enriched)

    return {"total": total, "page": page, "limit": limit, "items": items}


@router.post("/{ticker}")
async def open_position(
    ticker:      str,
    entry_price: float           = Body(...),
    shares:      float           = Body(...),
    stop_loss:   Optional[float] = Body(None),
    take_profit: Optional[float] = Body(None),
    signal:      Optional[str]   = Body(None),
    notes:       Optional[str]   = Body(None),
    db:          AsyncSession    = Depends(get_db),
):
    """Open a new portfolio position."""
    ticker = ticker.upper()

    stock_r = await db.execute(select(Stock).where(Stock.ticker == ticker))
    if not stock_r.scalars().first():
        raise HTTPException(status_code=404, detail=f"Ticker {ticker} not found in universe.")

    if entry_price <= 0:
        raise HTTPException(status_code=422, detail="entry_price must be positive.")
    if shares <= 0:
        raise HTTPException(status_code=422, detail="shares must be positive.")

    pos = PortfolioPosition(
        ticker         = ticker,
        entry_date     = datetime.now(timezone.utc),
        entry_price    = entry_price,
        shares         = shares,
        position_value = round(entry_price * shares, 2),
        stop_loss      = stop_loss,
        take_profit    = take_profit,
        signal         = signal.upper() if signal else None,
        notes          = notes,
        is_open        = True,
    )
    db.add(pos)
    await db.commit()
    await db.refresh(pos)

    logger.info("Opened position %s: %.4f shares @ %.4f (id=%d)", ticker, shares, entry_price, pos.id)
    return {"status": "opened", "id": pos.id, "ticker": ticker, "position_value": pos.position_value}


@router.patch("/{position_id}")
async def update_position(
    position_id: int,
    stop_loss:   Optional[float] = Body(None),
    take_profit: Optional[float] = Body(None),
    notes:       Optional[str]   = Body(None),
    db:          AsyncSession    = Depends(get_db),
):
    """Update stop loss, take profit, or notes on an open position."""
    result = await db.execute(
        select(PortfolioPosition).where(
            PortfolioPosition.id == position_id,
            PortfolioPosition.is_open == True,  # noqa: E712
        )
    )
    pos = result.scalars().first()
    if not pos:
        raise HTTPException(status_code=404, detail=f"Open position {position_id} not found.")

    if stop_loss is not None:
        pos.stop_loss = stop_loss
    if take_profit is not None:
        pos.take_profit = take_profit
    if notes is not None:
        pos.notes = notes

    await db.commit()
    return {"status": "updated", "id": position_id}


@router.post("/{position_id}/close")
async def close_position(
    position_id: int,
    exit_price:  float = Body(...),
    exit_reason: str   = Body("MANUAL"),
    db:          AsyncSession = Depends(get_db),
):
    """Close an open position and record realized P&L."""
    result = await db.execute(
        select(PortfolioPosition).where(
            PortfolioPosition.id == position_id,
            PortfolioPosition.is_open == True,  # noqa: E712
        )
    )
    pos = result.scalars().first()
    if not pos:
        raise HTTPException(status_code=404, detail=f"Open position {position_id} not found.")

    if exit_price <= 0:
        raise HTTPException(status_code=422, detail="exit_price must be positive.")

    entry_value = pos.entry_price * pos.shares
    exit_value  = exit_price * pos.shares
    realized_pnl = round(exit_value - entry_value, 2)
    realized_pnl_pct = round((exit_price / pos.entry_price - 1) * 100, 2) if pos.entry_price else 0.0

    pos.is_open          = False
    pos.exit_date        = datetime.now(timezone.utc)
    pos.exit_price       = exit_price
    pos.exit_reason      = exit_reason.upper()
    pos.realized_pnl     = realized_pnl
    pos.realized_pnl_pct = realized_pnl_pct

    await db.commit()

    logger.info(
        "Closed position %d (%s): exit=%.4f realized_pnl=%.2f (%.2f%%)",
        position_id, pos.ticker, exit_price, realized_pnl, realized_pnl_pct,
    )
    return {
        "status":            "closed",
        "id":                position_id,
        "ticker":            pos.ticker,
        "realized_pnl":      realized_pnl,
        "realized_pnl_pct":  realized_pnl_pct,
    }
