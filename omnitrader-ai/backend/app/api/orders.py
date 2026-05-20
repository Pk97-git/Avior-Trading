"""
api/orders.py
=============
Order Management System endpoints.

POST /orders/submit/{ticker}   — submit a BUY from the latest AI analysis
     Body (optional): { manual_qty?: float, notes?: str }
POST /orders/manual            — place a manual order
     Body: { ticker, side, qty, order_type?, limit_price?, notes? }
GET  /orders                   — list orders (filters: status, ticker, page, limit)
GET  /orders/{order_id}        — single order + live status sync from broker
POST /orders/{order_id}/cancel — cancel a PENDING order
GET  /orders/broker/balance    — live account balance from broker
GET  /orders/broker/positions  — live positions from broker
POST /orders/broker/sync       — sync broker positions → portfolio_positions table
"""
import logging
from datetime import datetime, timezone
from typing import List, Optional

from fastapi import APIRouter, Body, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func

from app.db.session import get_db
from app.models.market_data import Order, Stock
from app.services.order_manager import OrderManager
from app.brokers.factory import get_broker

router = APIRouter()
logger = logging.getLogger(__name__)


# ─── Helpers ──────────────────────────────────────────────────────────────────

def _order_to_dict(order: Order) -> dict:
    """Serialize an Order ORM object to a plain dict."""
    return {
        "id":                    order.id,
        "ticker":                order.ticker,
        "created_at":            order.created_at,
        "side":                  order.side,
        "order_type":            order.order_type,
        "qty":                   order.qty,
        "limit_price":           order.limit_price,
        "broker":                order.broker,
        "broker_order_id":       order.broker_order_id,
        "status":                order.status,
        "filled_qty":            order.filled_qty,
        "filled_price":          order.filled_price,
        "filled_at":             order.filled_at,
        "signal":                order.signal,
        "final_score":           order.final_score,
        "notes":                 order.notes,
        "portfolio_position_id": order.portfolio_position_id,
        "stop_price":            order.stop_price if hasattr(order, 'stop_price') else None,
        "target_price":          order.target_price if hasattr(order, 'target_price') else None,
        "trail_amount":          order.trail_amount if hasattr(order, 'trail_amount') else None,
        "trail_type":            order.trail_type if hasattr(order, 'trail_type') else None,
        "execution_algo":        order.execution_algo if hasattr(order, 'execution_algo') else None,
        "bracket_group_id":      order.bracket_group_id if hasattr(order, 'bracket_group_id') else None,
    }


async def _get_country_for_ticker(db: AsyncSession, ticker: str) -> str:
    """Look up country for a ticker; default 'US'."""
    result = await db.execute(select(Stock.country).where(Stock.ticker == ticker))
    row = result.fetchone()
    return (row.country or "US") if row else "US"


# ─── Submit from AI analysis ──────────────────────────────────────────────────

@router.post("/submit/{ticker}")
async def submit_from_analysis(
    ticker:     str,
    manual_qty: Optional[float] = Body(None, description="Override computed qty"),
    notes:      Optional[str]   = Body(None),
    db:         AsyncSession    = Depends(get_db),
):
    """
    Submit a BUY order for *ticker* based on its latest AI analysis.

    The order is sized automatically using the kelly_fraction / max_position_pct
    from the analysis and the current broker account balance.

    Supply ``manual_qty`` to override the computed share count.
    Returns immediately — order status may be PENDING or FILLED.
    """
    ticker = ticker.upper()

    manager = OrderManager(db)

    # If caller overrides qty, inject it into the analysis dict so submit_from_analysis
    # respects it by recalculating with a synthetic 100 % pct (we'll override qty directly
    # after the call using submit_manual instead).
    if manual_qty is not None and manual_qty > 0:
        result = await manager.submit_manual(
            ticker=ticker,
            side="BUY",
            qty=manual_qty,
            order_type="MARKET",
            notes=notes,
        )
    else:
        result = await manager.submit_from_analysis(ticker=ticker, notes=notes)

    if result["status"] == "halted":
        raise HTTPException(status_code=503, detail=result["reason"])

    return result


# ─── Manual order ─────────────────────────────────────────────────────────────

@router.post("/manual")
async def place_manual_order(
    ticker:      str            = Body(...),
    side:        str            = Body(..., description="BUY or SELL"),
    qty:         float          = Body(..., gt=0),
    order_type:  str            = Body("MARKET", description="MARKET or LIMIT"),
    limit_price: Optional[float]= Body(None),
    notes:       Optional[str]  = Body(None),
    db:          AsyncSession   = Depends(get_db),
):
    """
    Place a manual order with full control over side, quantity, and order type.

    The circuit breaker is checked but does NOT block manual orders — it logs
    a warning only.  Market-hours detection still converts MARKET → LIMIT when
    the exchange is closed.
    """
    ticker = ticker.upper()
    manager = OrderManager(db)
    result = await manager.submit_manual(
        ticker=ticker,
        side=side,
        qty=qty,
        order_type=order_type,
        limit_price=limit_price,
        notes=notes,
    )
    if result["status"] == "rejected":
        raise HTTPException(status_code=422, detail=result["reason"])
    return result


# ─── List orders ──────────────────────────────────────────────────────────────

@router.get("")
async def list_orders(
    status: Optional[str] = Query(None, description="PENDING, FILLED, CANCELLED, REJECTED"),
    ticker: Optional[str] = Query(None),
    page:   int           = Query(1, ge=1),
    limit:  int           = Query(50, ge=1, le=200),
    db:     AsyncSession  = Depends(get_db),
):
    """
    Paginated list of orders, newest first.

    Filter by ``status`` (PENDING / FILLED / CANCELLED / REJECTED) and/or
    ``ticker``.
    """
    stmt = select(Order).order_by(Order.created_at.desc())

    if status:
        stmt = stmt.where(Order.status == status.upper())
    if ticker:
        stmt = stmt.where(Order.ticker == ticker.upper())

    # Total count
    count_stmt = select(func.count()).select_from(stmt.subquery())
    total_result = await db.execute(count_stmt)
    total = total_result.scalar() or 0

    # Paginate
    offset = (page - 1) * limit
    stmt = stmt.offset(offset).limit(limit)
    result = await db.execute(stmt)
    orders = result.scalars().all()

    return {
        "total": total,
        "page":  page,
        "limit": limit,
        "items": [_order_to_dict(o) for o in orders],
    }


# ─── Single order + live sync ─────────────────────────────────────────────────

@router.get("/{order_id}")
async def get_order(
    order_id: int,
    db:       AsyncSession = Depends(get_db),
):
    """
    Fetch a single order by id.

    If the order is still PENDING, also calls the broker for a live status
    update and persists any change before returning.
    """
    result = await db.execute(select(Order).where(Order.id == order_id))
    order = result.scalars().first()
    if not order:
        raise HTTPException(status_code=404, detail=f"Order {order_id} not found.")

    # Live status sync for pending orders
    if order.status == "PENDING" and order.broker_order_id:
        country = await _get_country_for_ticker(db, order.ticker)
        broker = get_broker(country)
        try:
            fresh = await broker.get_order_status(order.broker_order_id)
            if fresh.status != order.status:
                order.status = fresh.status
                if fresh.filled_qty:
                    order.filled_qty = fresh.filled_qty
                if fresh.filled_price:
                    order.filled_price = fresh.filled_price
                if fresh.status == "FILLED" and not order.filled_at:
                    order.filled_at = datetime.now(timezone.utc)
                await db.commit()
                await db.refresh(order)
        except Exception as exc:
            logger.warning("[orders] Live sync failed for order %d: %s", order_id, exc)

    return _order_to_dict(order)


# ─── Cancel order ─────────────────────────────────────────────────────────────

@router.post("/{order_id}/cancel")
async def cancel_order(
    order_id: int,
    db:       AsyncSession = Depends(get_db),
):
    """
    Cancel a PENDING order both at the broker and in the database.

    Returns 422 if the order is not in PENDING status.
    """
    result = await db.execute(select(Order).where(Order.id == order_id))
    order = result.scalars().first()
    if not order:
        raise HTTPException(status_code=404, detail=f"Order {order_id} not found.")

    if order.status != "PENDING":
        raise HTTPException(
            status_code=422,
            detail=f"Order {order_id} is '{order.status}' — only PENDING orders can be cancelled.",
        )

    country = await _get_country_for_ticker(db, order.ticker)
    broker = get_broker(country)

    cancelled = False
    if order.broker_order_id:
        try:
            cancelled = await broker.cancel_order(order.broker_order_id)
        except Exception as exc:
            logger.warning("[orders] Broker cancel failed for order %d: %s", order_id, exc)

    order.status = "CANCELLED"
    await db.commit()

    return {
        "status":          "cancelled",
        "order_id":        order_id,
        "broker_cancel":   cancelled,
    }


# ─── Broker balance ───────────────────────────────────────────────────────────

@router.get("/broker/balance")
async def get_broker_balance(
    country: str = Query("US", description="'US' for Alpaca, 'IN' for Zerodha"),
):
    """
    Return the live account balance from the configured broker.

    Uses PaperBroker when no real credentials are set.
    """
    broker = get_broker(country.upper())
    balance = await broker.get_account_balance()
    return {
        "broker":          broker.name,
        "country":         country.upper(),
        "cash":            balance.cash,
        "portfolio_value": balance.portfolio_value,
        "buying_power":    balance.buying_power,
        "currency":        balance.currency,
    }


# ─── Broker positions ─────────────────────────────────────────────────────────

@router.get("/broker/positions")
async def get_broker_positions(
    country: str = Query("US", description="'US' for Alpaca, 'IN' for Zerodha"),
):
    """
    Return live open positions directly from the broker.

    Returns an empty list when the PaperBroker is active (no real credentials).
    """
    broker = get_broker(country.upper())
    positions = await broker.get_positions()
    return {
        "broker":  broker.name,
        "country": country.upper(),
        "total":   len(positions),
        "items": [
            {
                "ticker":         p.ticker,
                "qty":            p.qty,
                "avg_price":      p.avg_price,
                "current_price":  p.current_price,
                "unrealized_pnl": p.unrealized_pnl,
            }
            for p in positions
        ],
    }


# ─── Broker sync ──────────────────────────────────────────────────────────────

@router.post("/broker/sync")
async def sync_broker_positions(
    db: AsyncSession = Depends(get_db),
):
    """
    Reconcile live broker holdings against the portfolio_positions table.

    Any position held at the broker but absent from the DB is added
    automatically (signal='BROKER_SYNC').

    Also polls all PENDING orders for status updates.

    Returns counts of positions reconciled and orders updated.
    """
    manager = OrderManager(db)

    orders_updated = await manager.sync_order_statuses()
    positions_result = await manager.sync_broker_positions()

    return {
        "orders_synced": orders_updated,
        **positions_result,
    }


# ─── Bracket order ────────────────────────────────────────────────────────────

@router.post("/bracket/{ticker}")
async def submit_bracket_order(
    ticker: str,
    entry_type: str = Body("MARKET", description="MARKET or LIMIT"),
    entry_price: Optional[float] = Body(None, description="Required for LIMIT entry"),
    stop_price: Optional[float] = Body(None, description="Stop loss price (derived from analysis if not set)"),
    target_price: Optional[float] = Body(None, description="Take profit price (derived from analysis if not set)"),
    qty: Optional[float] = Body(None, description="Override computed qty"),
    notes: Optional[str] = Body(None),
    db: AsyncSession = Depends(get_db),
):
    """
    Submit a bracket order: entry + stop loss + take profit as one atomic order.

    If stop_price/target_price not provided, they are derived from the latest
    AI analysis for the ticker (analysis.stop_loss, analysis.take_profit).

    Bracket orders are supported natively by Alpaca and via workarounds on
    other brokers (see broker-specific notes).
    """
    ticker = ticker.upper()
    manager = OrderManager(db)
    result = await manager.submit_bracket_order(
        ticker=ticker,
        qty=qty,
        entry_type=entry_type,
        entry_price=entry_price,
        stop_price=stop_price,
        target_price=target_price,
        notes=notes,
    )
    if result["status"] == "halted":
        raise HTTPException(status_code=503, detail=result["reason"])
    return result


# ─── Stop order ───────────────────────────────────────────────────────────────

@router.post("/stop/{ticker}")
async def submit_stop_order(
    ticker: str,
    side: str = Body(..., description="BUY or SELL"),
    qty: float = Body(..., gt=0),
    stop_price: float = Body(..., description="Stop trigger price"),
    limit_price: Optional[float] = Body(None, description="If set → stop-limit; if None → stop-market"),
    notes: Optional[str] = Body(None),
    db: AsyncSession = Depends(get_db),
):
    """
    Place a stop or stop-limit order.

    - Stop-market: triggers at stop_price, fills at market (no limit_price)
    - Stop-limit: triggers at stop_price, fills at limit_price or better

    Common use cases:
    - Protective stop: SELL stop below current price to limit downside
    - Buy-stop: BUY stop above current price to enter breakout
    """
    manager = OrderManager(db)
    result = await manager.submit_stop_order(
        ticker=ticker.upper(),
        side=side.upper(),
        qty=qty,
        stop_price=stop_price,
        limit_price=limit_price,
        notes=notes,
    )
    if result.get("status") == "halted":
        raise HTTPException(status_code=503, detail=result["reason"])
    return result


# ─── Trailing stop order ──────────────────────────────────────────────────────

@router.post("/trailing-stop/{ticker}")
async def submit_trailing_stop_order(
    ticker: str,
    side: str = Body("SELL", description="BUY or SELL (SELL for long exit)"),
    qty: float = Body(..., gt=0),
    trail_amount: float = Body(..., gt=0, description="Trail distance"),
    trail_type: str = Body("ABSOLUTE", description="ABSOLUTE (dollar/rupee) or PERCENTAGE"),
    notes: Optional[str] = Body(None),
    db: AsyncSession = Depends(get_db),
):
    """
    Place a trailing stop order.

    The stop price automatically adjusts as the market moves in your favor:
    - ABSOLUTE: trail_amount is a fixed price distance (e.g., $2.50 or ₹50)
    - PERCENTAGE: trail_amount is a percentage (e.g., 2.0 for 2%)

    Supported natively by Alpaca and IBKR. Other brokers simulate via stop-market.
    """
    if trail_type.upper() not in ("ABSOLUTE", "PERCENTAGE"):
        raise HTTPException(status_code=422, detail="trail_type must be ABSOLUTE or PERCENTAGE")
    manager = OrderManager(db)
    result = await manager.submit_trailing_stop_order(
        ticker=ticker.upper(),
        side=side.upper(),
        qty=qty,
        trail_amount=trail_amount,
        trail_type=trail_type.upper(),
        notes=notes,
    )
    return result


# ─── Execution analysis ───────────────────────────────────────────────────────

@router.get("/execution/analyze")
async def analyze_execution(
    ticker: str = Query(...),
    qty: float = Query(..., gt=0),
    side: str = Query("BUY"),
    urgency: str = Query("NORMAL", description="LOW, NORMAL, HIGH"),
    db: AsyncSession = Depends(get_db),
):
    """
    Analyze the optimal execution strategy for an order before placing it.

    Returns recommended strategy (DIRECT/TWAP/VWAP/ICEBERG), estimated slippage,
    execution plan with time slices, and market impact estimate.

    Use this before placing large orders to minimize market impact.
    """
    try:
        from app.engines.smart_execution import SmartExecutionEngine
        engine = SmartExecutionEngine(db)
        plan = await engine.analyze_order(ticker.upper(), side.upper(), qty, urgency.upper())
        return {
            "ticker": plan.ticker,
            "side": plan.side,
            "total_qty": plan.total_qty,
            "strategy": plan.strategy,
            "estimated_slippage_bps": plan.estimated_slippage_bps,
            "estimated_market_impact_bps": plan.estimated_market_impact_bps,
            "adv_usd": plan.adv_usd,
            "duration_minutes": plan.duration_minutes,
            "reasoning": plan.reasoning,
            "n_slices": len(plan.slices),
            "slices": [
                {
                    "slice_index": s.slice_index,
                    "qty": round(s.qty, 4),
                    "delay_seconds": s.delay_seconds,
                    "order_type": s.order_type,
                    "limit_price_offset_pct": s.limit_price_offset_pct,
                }
                for s in plan.slices
            ],
        }
    except Exception as e:
        logger.error("Execution analysis failed: %s", e)
        raise HTTPException(status_code=500, detail=str(e))


# ─── Execution quality report ─────────────────────────────────────────────────

@router.get("/execution/quality")
async def execution_quality_report(
    days: int = Query(30, ge=1, le=365),
    db: AsyncSession = Depends(get_db),
):
    """
    Historical execution quality report.

    Analyzes past filled orders to measure:
    - Average slippage vs reference price at order submission
    - Fill time distribution
    - Quality breakdown by broker
    """
    try:
        from app.engines.smart_execution import SmartExecutionEngine
        engine = SmartExecutionEngine(db)
        report = await engine.get_execution_quality_report(days=days)
        return report
    except Exception as e:
        logger.error("Execution quality report failed: %s", e)
        return {"error": str(e), "total_orders": 0}
