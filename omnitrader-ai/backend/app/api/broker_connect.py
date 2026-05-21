"""
api/broker_connect.py
=====================
FastAPI router for live broker management.

Endpoints
---------
GET  /broker/status              — configuration + live connection health for all brokers
POST /broker/zerodha/session     — exchange Kite request_token for access_token
GET  /broker/positions           — live open positions from the configured broker
GET  /broker/account             — live account balance / margin info
POST /broker/order               — place an order directly via the live broker (bypasses DB)

Query parameter ``country`` accepts ``"US"`` (Alpaca) or ``"IN"`` (Zerodha).
Returns HTTP 503 when the requested broker is not configured.
"""
import logging
from dataclasses import asdict
from typing import Optional

from fastapi import APIRouter, Body, HTTPException, Query

from app.services.broker.factory import broker_status, get_broker
from app.services.broker.base import OrderSide, OrderType

router = APIRouter()
logger = logging.getLogger(__name__)


# ─── Helpers ──────────────────────────────────────────────────────────────────

def _require_broker(country: str):
    """Return broker or raise 503."""
    broker = get_broker(country)
    if broker is None:
        raise HTTPException(
            status_code=503,
            detail=(
                f"Broker for country='{country}' is not configured. "
                "Set the required environment variables and restart the server."
            ),
        )
    return broker


# ─── GET /broker/status ───────────────────────────────────────────────────────

@router.get("/status")
async def get_broker_status():
    """
    Return configuration and live connectivity status for all supported brokers.

    Each broker entry includes:
    - ``configured``: whether credentials are present in the environment.
    - ``connected``:  live test result (``null`` when not configured).
    - ``account``:    account summary on success, ``null`` on failure.
    - ``paper``:      Alpaca only — whether paper-trading mode is active.
    - ``login_url``:  Zerodha only — OAuth login URL for daily token refresh.
    """
    status = broker_status()
    result: dict = {}

    # ── Alpaca ─────────────────────────────────────────────────────────────────
    alpaca_info: dict = {
        "configured": status["alpaca"]["configured"],
        "paper":      status["alpaca"]["paper"],
        "connected":  None,
        "account":    None,
    }
    if status["alpaca"]["configured"]:
        try:
            broker = get_broker("US")
            if broker:
                connected = await broker.is_connected()
                alpaca_info["connected"] = connected
                if connected:
                    account = await broker.get_account()
                    alpaca_info["account"] = asdict(account)
        except Exception as exc:
            logger.warning("[broker_connect] Alpaca connectivity check failed: %s", exc)
            alpaca_info["connected"] = False

    result["alpaca"] = alpaca_info

    # ── Zerodha ────────────────────────────────────────────────────────────────
    zerodha_info: dict = {
        "configured": status["zerodha"]["configured"],
        "login_url":  status["zerodha"]["login_url"],
        "connected":  None,
        "account":    None,
    }
    if status["zerodha"]["configured"]:
        try:
            broker = get_broker("IN")
            if broker:
                connected = await broker.is_connected()
                zerodha_info["connected"] = connected
                if connected:
                    account = await broker.get_account()
                    zerodha_info["account"] = asdict(account)
        except Exception as exc:
            logger.warning("[broker_connect] Zerodha connectivity check failed: %s", exc)
            zerodha_info["connected"] = False

    result["zerodha"] = zerodha_info

    return result


# ─── POST /broker/zerodha/session ────────────────────────────────────────────

@router.post("/zerodha/session")
async def exchange_zerodha_session(
    request_token: str = Body(..., description="One-time request token from Kite OAuth redirect"),
):
    """
    Exchange a Zerodha Kite ``request_token`` for a session ``access_token``.

    The ``request_token`` is obtained after the user completes the Kite
    OAuth login flow.  The returned ``access_token`` is valid for one trading
    day and must be stored as ``KITE_ACCESS_TOKEN`` in the server's environment.

    Body:
        ``{"request_token": "<token>"}``

    Returns:
        ``{"access_token": "<token>", "message": "..."}``

    Note: In production, persist the token to your secrets manager or ``.env``
    and restart (or reload) the server so that ``KITE_ACCESS_TOKEN`` is updated.
    """
    import os
    api_key    = os.getenv("KITE_API_KEY")
    api_secret = os.getenv("KITE_API_SECRET")

    if not api_key or not api_secret:
        raise HTTPException(
            status_code=503,
            detail=(
                "KITE_API_KEY and KITE_API_SECRET must be set to exchange a session token."
            ),
        )

    try:
        from app.services.broker.zerodha_broker import generate_session
        access_token = generate_session(
            api_key=api_key,
            api_secret=api_secret,
            request_token=request_token,
        )
        return {
            "access_token": access_token,
            "message": (
                "Session token obtained successfully. "
                "Store this as KITE_ACCESS_TOKEN in your .env file — "
                "it expires at the end of the trading day."
            ),
        }
    except Exception as exc:
        logger.error("[broker_connect] Zerodha session exchange failed: %s", exc)
        raise HTTPException(status_code=502, detail=str(exc))


# ─── GET /broker/positions ────────────────────────────────────────────────────

@router.get("/positions")
async def get_positions(
    country: str = Query("US", description="'US' for Alpaca, 'IN' for Zerodha"),
):
    """
    Return live open positions from the configured broker.

    Query params:
        country: ``"US"`` or ``"IN"``

    Returns 503 when the broker is not configured.
    """
    broker = _require_broker(country.upper())
    try:
        positions = await broker.get_positions()
        return {
            "country": country.upper(),
            "total":   len(positions),
            "items":   [asdict(p) for p in positions],
        }
    except Exception as exc:
        logger.error("[broker_connect] get_positions failed: %s", exc)
        raise HTTPException(status_code=502, detail=str(exc))


# ─── GET /broker/account ──────────────────────────────────────────────────────

@router.get("/account")
async def get_account(
    country: str = Query("US", description="'US' for Alpaca, 'IN' for Zerodha"),
):
    """
    Return the live account balance / margin info from the configured broker.

    Query params:
        country: ``"US"`` or ``"IN"``

    Returns 503 when the broker is not configured.
    """
    broker = _require_broker(country.upper())
    try:
        account = await broker.get_account()
        return asdict(account)
    except Exception as exc:
        logger.error("[broker_connect] get_account failed: %s", exc)
        raise HTTPException(status_code=502, detail=str(exc))


# ─── POST /broker/order ───────────────────────────────────────────────────────

@router.post("/order")
async def place_broker_order(
    ticker:      str            = Body(..., description="Instrument symbol, e.g. AAPL or RELIANCE.NS"),
    side:        str            = Body(..., description="BUY or SELL"),
    qty:         float          = Body(..., gt=0, description="Number of shares / units"),
    order_type:  str            = Body("MARKET", description="MARKET, LIMIT, STOP, or STOP_LIMIT"),
    limit_price: Optional[float]= Body(None, description="Required for LIMIT / STOP_LIMIT orders"),
    stop_price:  Optional[float]= Body(None, description="Required for STOP / STOP_LIMIT orders"),
    country:     str            = Body("US", description="'US' for Alpaca, 'IN' for Zerodha"),
):
    """
    Place an order directly through the live broker, bypassing the OmniTrader
    order database.

    Use this endpoint for quick manual trades or testing broker connectivity.
    For production order flow (with AI signal validation, circuit breakers,
    and DB persistence) use ``POST /api/v1/orders/manual`` instead.

    Returns the broker's ``BrokerOrder`` response as a dict.
    """
    broker = _require_broker(country.upper())

    try:
        b_side = OrderSide(side.upper())
    except ValueError:
        raise HTTPException(status_code=422, detail=f"Invalid side='{side}'. Must be BUY or SELL.")

    try:
        b_type = OrderType(order_type.upper())
    except ValueError:
        raise HTTPException(
            status_code=422,
            detail=f"Invalid order_type='{order_type}'. Must be MARKET, LIMIT, STOP, or STOP_LIMIT.",
        )

    try:
        b_order = await broker.place_order(
            ticker=ticker.upper(),
            side=b_side,
            qty=qty,
            order_type=b_type,
            limit_price=limit_price,
            stop_price=stop_price,
        )
        return asdict(b_order)
    except Exception as exc:
        logger.error("[broker_connect] place_broker_order failed: %s", exc)
        raise HTTPException(status_code=502, detail=str(exc))
