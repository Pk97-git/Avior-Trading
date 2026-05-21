"""
services/broker/alpaca_broker.py
=================================
Alpaca Markets broker integration using httpx (async).

Env vars:
  ALPACA_API_KEY     — API key ID
  ALPACA_SECRET_KEY  — Secret key
  ALPACA_PAPER       — "true" for paper trading (default), "false" for live

Base URLs:
  Paper: https://paper-api.alpaca.markets
  Live:  https://api.alpaca.markets
  Data:  https://data.alpaca.markets

Note: The service-layer ``AlpacaBroker`` wraps the underlying
``app.brokers.alpaca.AlpacaBroker`` and translates its ``OrderResult`` /
``Position`` / ``AccountBalance`` structures into the richer
``BrokerOrder`` / ``BrokerPosition`` / ``BrokerAccount`` dataclasses
defined in ``services/broker/base.py``.
"""
import logging
import os
from datetime import datetime, timezone
from typing import Optional

import httpx

from app.services.broker.base import (
    BaseBroker,
    BrokerAccount,
    BrokerOrder,
    BrokerPosition,
    OrderSide,
    OrderStatus,
    OrderType,
)

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Alpaca order-type mapping
# ---------------------------------------------------------------------------

_ORDER_TYPE_MAP: dict[OrderType, str] = {
    OrderType.MARKET:     "market",
    OrderType.LIMIT:      "limit",
    OrderType.STOP:       "stop",
    OrderType.STOP_LIMIT: "stop_limit",
}

_STATUS_MAP: dict[str, OrderStatus] = {
    "filled":               OrderStatus.FILLED,
    "canceled":             OrderStatus.CANCELLED,
    "cancelled":            OrderStatus.CANCELLED,
    "rejected":             OrderStatus.REJECTED,
    "expired":              OrderStatus.CANCELLED,
    "new":                  OrderStatus.PENDING,
    "accepted":             OrderStatus.PENDING,
    "pending_new":          OrderStatus.PENDING,
    "partially_filled":     OrderStatus.OPEN,
    "held":                 OrderStatus.PENDING,
    "accepted_for_bidding": OrderStatus.PENDING,
    "done_for_day":         OrderStatus.CANCELLED,
    "replaced":             OrderStatus.CANCELLED,
}


def _map_status(raw: str) -> OrderStatus:
    return _STATUS_MAP.get(raw.lower(), OrderStatus.PENDING)


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


class AlpacaBroker(BaseBroker):
    """
    Alpaca Markets service-layer broker.

    Communicates directly with the Alpaca REST API v2 using ``httpx``.
    Credentials are read from environment variables or supplied to
    ``__init__``.

    Args:
        api_key:    Alpaca API key ID.  Defaults to ``ALPACA_API_KEY`` env var.
        secret_key: Alpaca secret key.  Defaults to ``ALPACA_SECRET_KEY`` env var.
        paper:      Use paper-trading endpoint when ``True`` (default ``True``).
    """

    def __init__(
        self,
        api_key:    Optional[str] = None,
        secret_key: Optional[str] = None,
        paper:      bool          = True,
    ) -> None:
        self.api_key    = api_key    or os.getenv("ALPACA_API_KEY", "")
        self.secret_key = secret_key or os.getenv("ALPACA_SECRET_KEY", "")

        if not self.api_key or not self.secret_key:
            raise ValueError(
                "AlpacaBroker requires ALPACA_API_KEY and ALPACA_SECRET_KEY "
                "(set as env vars or pass to __init__)"
            )

        self.paper = paper
        self.base_url = (
            "https://paper-api.alpaca.markets"
            if paper
            else "https://api.alpaca.markets"
        )

    # ── Helpers ────────────────────────────────────────────────────────────────

    def _headers(self) -> dict:
        return {
            "APCA-API-KEY-ID":     self.api_key,
            "APCA-API-SECRET-KEY": self.secret_key,
        }

    @staticmethod
    def _clean_ticker(ticker: str) -> str:
        """Strip unsupported suffixes (e.g. '.US') from Alpaca symbols."""
        return ticker.replace(".US", "").upper()

    def _order_from_raw(self, data: dict, ticker: str = "", side: Optional[OrderSide] = None,
                        qty: float = 0, order_type: Optional[OrderType] = None,
                        limit_price: Optional[float] = None,
                        stop_price: Optional[float] = None) -> BrokerOrder:
        raw_status = data.get("status", "")
        return BrokerOrder(
            broker_order_id=data.get("id", ""),
            ticker=data.get("symbol", ticker),
            side=OrderSide(data["side"].upper()) if "side" in data else (side or OrderSide.BUY),
            qty=float(data.get("qty") or qty or 0),
            order_type=OrderType(data["type"].upper()) if "type" in data else (order_type or OrderType.MARKET),
            limit_price=float(data["limit_price"]) if data.get("limit_price") else limit_price,
            stop_price=float(data["stop_price"])   if data.get("stop_price")  else stop_price,
            status=_map_status(raw_status),
            filled_qty=float(data.get("filled_qty") or 0),
            avg_fill_price=float(data["filled_avg_price"]) if data.get("filled_avg_price") else None,
            created_at=data.get("created_at") or _now_iso(),
            raw=data,
        )

    # ── BaseBroker interface ───────────────────────────────────────────────────

    async def place_order(
        self,
        ticker:      str,
        side:        OrderSide,
        qty:         float,
        order_type:  OrderType,
        limit_price: Optional[float] = None,
        stop_price:  Optional[float] = None,
    ) -> BrokerOrder:
        clean = self._clean_ticker(ticker)
        payload: dict = {
            "symbol":        clean,
            "qty":           str(qty),
            "side":          side.value.lower(),
            "type":          _ORDER_TYPE_MAP.get(order_type, "market"),
            "time_in_force": "day",
        }
        if limit_price is not None:
            payload["limit_price"] = str(limit_price)
        if stop_price is not None:
            payload["stop_price"] = str(stop_price)

        try:
            async with httpx.AsyncClient(timeout=10) as client:
                resp = await client.post(
                    f"{self.base_url}/v2/orders",
                    headers=self._headers(),
                    json=payload,
                )
                data = resp.json()
                if resp.status_code in (200, 201):
                    return self._order_from_raw(
                        data, ticker=ticker, side=side, qty=qty,
                        order_type=order_type, limit_price=limit_price,
                        stop_price=stop_price,
                    )
                logger.error("[AlpacaBroker] place_order rejected %d: %s", resp.status_code, data)
                return BrokerOrder(
                    broker_order_id="",
                    ticker=ticker,
                    side=side,
                    qty=qty,
                    order_type=order_type,
                    limit_price=limit_price,
                    stop_price=stop_price,
                    status=OrderStatus.REJECTED,
                    filled_qty=0,
                    avg_fill_price=None,
                    created_at=_now_iso(),
                    raw=data,
                )
        except Exception as exc:
            logger.error("[AlpacaBroker] place_order error: %s", exc)
            return BrokerOrder(
                broker_order_id="",
                ticker=ticker,
                side=side,
                qty=qty,
                order_type=order_type,
                limit_price=limit_price,
                stop_price=stop_price,
                status=OrderStatus.REJECTED,
                filled_qty=0,
                avg_fill_price=None,
                created_at=_now_iso(),
                raw={"error": str(exc)},
            )

    async def cancel_order(self, broker_order_id: str) -> bool:
        try:
            async with httpx.AsyncClient(timeout=10) as client:
                resp = await client.delete(
                    f"{self.base_url}/v2/orders/{broker_order_id}",
                    headers=self._headers(),
                )
                return resp.status_code in (200, 204)
        except Exception as exc:
            logger.error("[AlpacaBroker] cancel_order error: %s", exc)
            return False

    async def get_order(self, broker_order_id: str) -> BrokerOrder:
        try:
            async with httpx.AsyncClient(timeout=10) as client:
                resp = await client.get(
                    f"{self.base_url}/v2/orders/{broker_order_id}",
                    headers=self._headers(),
                )
                data = resp.json()
                if resp.status_code == 200:
                    return self._order_from_raw(data)
                logger.warning("[AlpacaBroker] get_order %s → %d", broker_order_id, resp.status_code)
        except Exception as exc:
            logger.error("[AlpacaBroker] get_order error: %s", exc)

        return BrokerOrder(
            broker_order_id=broker_order_id,
            ticker="",
            side=OrderSide.BUY,
            qty=0,
            order_type=OrderType.MARKET,
            limit_price=None,
            stop_price=None,
            status=OrderStatus.PENDING,
            filled_qty=0,
            avg_fill_price=None,
            created_at=_now_iso(),
            raw={},
        )

    async def get_positions(self) -> list[BrokerPosition]:
        try:
            async with httpx.AsyncClient(timeout=10) as client:
                resp = await client.get(
                    f"{self.base_url}/v2/positions",
                    headers=self._headers(),
                )
                resp.raise_for_status()
                positions = []
                for p in resp.json():
                    qty          = float(p.get("qty") or 0)
                    avg_cost     = float(p.get("avg_entry_price") or 0)
                    current      = float(p.get("current_price") or 0)
                    market_value = float(p.get("market_value") or qty * current)
                    unr_pnl      = float(p.get("unrealized_pl") or 0)
                    positions.append(BrokerPosition(
                        ticker=p.get("symbol", ""),
                        qty=qty,
                        avg_cost=avg_cost,
                        current_price=current,
                        unrealized_pnl=unr_pnl,
                        market_value=market_value,
                    ))
                return positions
        except Exception as exc:
            logger.error("[AlpacaBroker] get_positions error: %s", exc)
            return []

    async def get_account(self) -> BrokerAccount:
        try:
            async with httpx.AsyncClient(timeout=10) as client:
                resp = await client.get(
                    f"{self.base_url}/v2/account",
                    headers=self._headers(),
                )
                resp.raise_for_status()
                data = resp.json()
                return BrokerAccount(
                    account_id=data.get("id", ""),
                    cash=float(data.get("cash") or 0),
                    portfolio_value=float(data.get("portfolio_value") or 0),
                    buying_power=float(data.get("buying_power") or 0),
                    currency="USD",
                )
        except Exception as exc:
            logger.error("[AlpacaBroker] get_account error: %s", exc)
            return BrokerAccount(
                account_id="", cash=0, portfolio_value=0, buying_power=0, currency="USD"
            )

    async def is_connected(self) -> bool:
        try:
            account = await self.get_account()
            return bool(account.account_id)
        except Exception:
            return False
