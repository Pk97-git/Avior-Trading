"""
brokers/alpaca.py
=================
Alpaca Markets broker connector for US equities.

Required env vars:
    ALPACA_API_KEY    — Alpaca API key ID
    ALPACA_SECRET_KEY — Alpaca secret key

Optional:
    ALPACA_PAPER=true   Use paper trading endpoint (default: true)
    ALPACA_PAPER=false  Use live trading endpoint
"""
import logging
import os
from typing import Optional

import httpx

from app.brokers.base import BrokerInterface, OrderResult, Position, AccountBalance

logger = logging.getLogger(__name__)


class AlpacaBroker(BrokerInterface):
    """
    Alpaca Markets broker for US equities.
    Requires: ALPACA_API_KEY, ALPACA_SECRET_KEY env vars.
    Set ALPACA_PAPER=false for live trading (default: paper).
    """

    name = "ALPACA"

    def __init__(self) -> None:
        self.api_key = os.getenv("ALPACA_API_KEY")
        self.secret_key = os.getenv("ALPACA_SECRET_KEY")
        if not self.api_key or not self.secret_key:
            raise ValueError(
                "ALPACA_API_KEY and ALPACA_SECRET_KEY must be set in environment"
            )
        paper = os.getenv("ALPACA_PAPER", "true").lower() != "false"
        self.base_url = (
            "https://paper-api.alpaca.markets"
            if paper
            else "https://api.alpaca.markets"
        )

    # ── Internal helpers ───────────────────────────────────────────────────────

    def _headers(self) -> dict:
        return {
            "APCA-API-KEY-ID":     self.api_key,
            "APCA-API-SECRET-KEY": self.secret_key,
        }

    @staticmethod
    def _map_alpaca_status(alpaca_status: str) -> str:
        mapping = {
            "filled":           "FILLED",
            "canceled":         "CANCELLED",
            "cancelled":        "CANCELLED",
            "rejected":         "REJECTED",
            "expired":          "CANCELLED",
            "new":              "PENDING",
            "accepted":         "PENDING",
            "pending_new":      "PENDING",
            "partially_filled": "PENDING",
            "held":             "PENDING",
            "accepted_for_bidding": "PENDING",
        }
        return mapping.get(alpaca_status.lower(), "PENDING")

    # ── BrokerInterface implementation ────────────────────────────────────────

    async def place_order(
        self,
        ticker: str,
        side: str,
        qty: float,
        order_type: str = "MARKET",
        limit_price: Optional[float] = None,
    ) -> OrderResult:
        # Alpaca symbols don't have ".US" suffix
        clean_ticker = ticker.replace(".US", "").upper()
        payload: dict = {
            "symbol":        clean_ticker,
            "qty":           str(qty),
            "side":          side.lower(),
            "type":          order_type.lower(),
            "time_in_force": "day",
        }
        if order_type.upper() == "LIMIT" and limit_price is not None:
            payload["limit_price"] = str(limit_price)

        try:
            async with httpx.AsyncClient(timeout=10) as client:
                resp = await client.post(
                    f"{self.base_url}/v2/orders",
                    headers=self._headers(),
                    json=payload,
                )
                data = resp.json()
                if resp.status_code in (200, 201):
                    return OrderResult(
                        broker_order_id=data["id"],
                        status=self._map_alpaca_status(data.get("status", "")),
                        filled_qty=float(data.get("filled_qty") or 0),
                        filled_price=float(data.get("filled_avg_price") or 0),
                        message="Order placed on Alpaca",
                    )
                return OrderResult(
                    broker_order_id="",
                    status="REJECTED",
                    message=data.get("message", resp.text),
                )
        except Exception as exc:
            logger.error("[Alpaca] place_order failed: %s", exc)
            return OrderResult(broker_order_id="", status="REJECTED", message=str(exc))

    async def get_order_status(self, broker_order_id: str) -> OrderResult:
        try:
            async with httpx.AsyncClient(timeout=10) as client:
                resp = await client.get(
                    f"{self.base_url}/v2/orders/{broker_order_id}",
                    headers=self._headers(),
                )
                data = resp.json()
                if resp.status_code == 200:
                    return OrderResult(
                        broker_order_id=broker_order_id,
                        status=self._map_alpaca_status(data.get("status", "")),
                        filled_qty=float(data.get("filled_qty") or 0),
                        filled_price=float(data.get("filled_avg_price") or 0),
                    )
                return OrderResult(
                    broker_order_id=broker_order_id,
                    status="UNKNOWN",
                    message=data.get("message", ""),
                )
        except Exception as exc:
            logger.error("[Alpaca] get_order_status failed: %s", exc)
            return OrderResult(
                broker_order_id=broker_order_id, status="UNKNOWN", message=str(exc)
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
            logger.error("[Alpaca] cancel_order failed: %s", exc)
            return False

    async def get_positions(self) -> list[Position]:
        try:
            async with httpx.AsyncClient(timeout=10) as client:
                resp = await client.get(
                    f"{self.base_url}/v2/positions",
                    headers=self._headers(),
                )
                resp.raise_for_status()
                return [
                    Position(
                        ticker=p["symbol"],
                        qty=float(p["qty"]),
                        avg_price=float(p["avg_entry_price"]),
                        current_price=float(p.get("current_price") or 0),
                        unrealized_pnl=float(p.get("unrealized_pl") or 0),
                    )
                    for p in resp.json()
                ]
        except Exception as exc:
            logger.error("[Alpaca] get_positions failed: %s", exc)
            return []

    async def get_account_balance(self) -> AccountBalance:
        try:
            async with httpx.AsyncClient(timeout=10) as client:
                resp = await client.get(
                    f"{self.base_url}/v2/account",
                    headers=self._headers(),
                )
                resp.raise_for_status()
                data = resp.json()
                return AccountBalance(
                    cash=float(data.get("cash", 0) or 0),
                    portfolio_value=float(data.get("portfolio_value", 0) or 0),
                    buying_power=float(data.get("buying_power", 0) or 0),
                    currency="USD",
                )
        except Exception as exc:
            logger.error("[Alpaca] get_account_balance failed: %s", exc)
            return AccountBalance(cash=0, portfolio_value=0, buying_power=0, currency="USD")
