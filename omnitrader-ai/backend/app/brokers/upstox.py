"""
brokers/upstox.py
=================
Upstox API v2 broker connector for Indian markets.

Required env vars:
    UPSTOX_API_KEY       — Upstox API key
    UPSTOX_ACCESS_TOKEN  — Bearer access token (from OAuth2 flow)
"""
import logging
import os
from typing import Optional

import httpx

from app.brokers.base import (
    BrokerInterface,
    OrderResult,
    BracketOrderResult,
    Position,
    AccountBalance,
)

logger = logging.getLogger(__name__)


class UpstoxBroker(BrokerInterface):
    """
    Upstox API v2 broker for Indian markets.
    Requires: UPSTOX_API_KEY, UPSTOX_ACCESS_TOKEN env vars.
    Access token must be refreshed via OAuth2 flow.
    """

    name = "UPSTOX"
    BASE_URL = "https://api.upstox.com/v2"

    def __init__(self) -> None:
        self.api_key = os.getenv("UPSTOX_API_KEY")
        self.access_token = os.getenv("UPSTOX_ACCESS_TOKEN")
        if not self.api_key or not self.access_token:
            raise ValueError(
                "UPSTOX_API_KEY and UPSTOX_ACCESS_TOKEN must be set in environment"
            )

    # ── Internal helpers ───────────────────────────────────────────────────────

    def _headers(self) -> dict:
        return {
            "Authorization": f"Bearer {self.access_token}",
            "Accept": "application/json",
            "Content-Type": "application/json",
        }

    def _instrument_key(self, ticker: str) -> str:
        """
        Convert ticker to Upstox instrument_key format.
        - Tickers ending in '.NS' → 'NSE_EQ|SYMBOL'
        - Tickers ending in '.BO' → 'BSE_EQ|SYMBOL'
        - Bare symbol → 'NSE_EQ|SYMBOL' (default NSE)
        """
        if ticker.endswith(".NS"):
            return f"NSE_EQ|{ticker[:-3]}"
        if ticker.endswith(".BO"):
            return f"BSE_EQ|{ticker[:-3]}"
        return f"NSE_EQ|{ticker}"

    @staticmethod
    def _map_upstox_status(upstox_status: str) -> str:
        mapping = {
            "complete":  "FILLED",
            "cancelled": "CANCELLED",
            "rejected":  "REJECTED",
            "open":      "PENDING",
            "pending":   "PENDING",
        }
        return mapping.get(upstox_status.lower(), "PENDING")

    # ── BrokerInterface implementation ────────────────────────────────────────

    async def place_order(
        self,
        ticker: str,
        side: str,
        qty: float,
        order_type: str = "MARKET",
        limit_price: Optional[float] = None,
    ) -> OrderResult:
        instrument_key = self._instrument_key(ticker)
        transaction_type = "BUY" if side.upper() == "BUY" else "SELL"
        upstox_order_type = "MARKET" if order_type.upper() == "MARKET" else "LIMIT"
        price = limit_price if upstox_order_type == "LIMIT" and limit_price is not None else 0

        payload = {
            "quantity": int(qty),
            "product": "D",                  # Delivery
            "validity": "DAY",
            "price": price,
            "instrument_token": instrument_key,
            "order_type": upstox_order_type,
            "transaction_type": transaction_type,
            "disclosed_quantity": 0,
            "trigger_price": 0,
            "is_amo": False,
        }

        try:
            async with httpx.AsyncClient(timeout=10) as client:
                resp = await client.post(
                    f"{self.BASE_URL}/order/place",
                    headers=self._headers(),
                    json=payload,
                )
                data = resp.json()
                if data.get("status") == "success":
                    return OrderResult(
                        broker_order_id=str(data["data"]["order_id"]),
                        status="PENDING",
                        message="Order placed on Upstox",
                    )
                return OrderResult(
                    broker_order_id="",
                    status="REJECTED",
                    message=data.get("message", resp.text),
                )
        except Exception as exc:
            logger.error("[Upstox] place_order failed: %s", exc)
            return OrderResult(broker_order_id="", status="REJECTED", message=str(exc))

    async def place_stop_order(
        self,
        ticker: str,
        side: str,
        qty: float,
        stop_price: float,
        limit_price: Optional[float] = None,
    ) -> OrderResult:
        """
        Place a stop order on Upstox.
        - limit_price is None → SL-M (stop-market), price=0
        - limit_price is set  → SL   (stop-limit), price=limit_price
        """
        instrument_key = self._instrument_key(ticker)
        transaction_type = "BUY" if side.upper() == "BUY" else "SELL"

        if limit_price is None:
            upstox_order_type = "SL-M"
            price = 0
        else:
            upstox_order_type = "SL"
            price = limit_price

        payload = {
            "quantity": int(qty),
            "product": "D",
            "validity": "DAY",
            "price": price,
            "instrument_token": instrument_key,
            "order_type": upstox_order_type,
            "transaction_type": transaction_type,
            "disclosed_quantity": 0,
            "trigger_price": stop_price,
            "is_amo": False,
        }

        try:
            async with httpx.AsyncClient(timeout=10) as client:
                resp = await client.post(
                    f"{self.BASE_URL}/order/place",
                    headers=self._headers(),
                    json=payload,
                )
                data = resp.json()
                if data.get("status") == "success":
                    return OrderResult(
                        broker_order_id=str(data["data"]["order_id"]),
                        status="PENDING",
                        message=f"Stop order placed on Upstox ({upstox_order_type})",
                    )
                return OrderResult(
                    broker_order_id="",
                    status="REJECTED",
                    message=data.get("message", resp.text),
                )
        except Exception as exc:
            logger.error("[Upstox] place_stop_order failed: %s", exc)
            return OrderResult(broker_order_id="", status="REJECTED", message=str(exc))

    async def place_trailing_stop_order(
        self,
        ticker: str,
        side: str,
        qty: float,
        trail_amount: float,
        trail_type: str = "ABSOLUTE",
    ) -> OrderResult:
        """
        Upstox v2 does not support native trailing stop orders.
        Falls back to a regular SL-M order with the trail_amount as trigger price.
        For PERCENTAGE trail_type, trigger_price is computed as trail_amount percent
        of trail_amount (requires live price feed for precision — manual trailing required).
        """
        instrument_key = self._instrument_key(ticker)
        transaction_type = "BUY" if side.upper() == "BUY" else "SELL"

        if trail_type.upper() == "PERCENTAGE":
            # Without a live price, use trail_amount directly as the trigger offset.
            # Callers should provide trail_amount as a percent (e.g. 1.0 for 1%).
            trigger_price = trail_amount
            note = (
                f"Trailing stop placed as SL-M (PERCENTAGE mode: {trail_amount}% "
                "expressed as trigger — manual trailing required)"
            )
        else:
            trigger_price = trail_amount
            note = "Trailing stop placed as SL-M (manual trailing required)"

        payload = {
            "quantity": int(qty),
            "product": "I",            # Intraday (CO/trailing only available intraday)
            "validity": "DAY",
            "price": 0,
            "instrument_token": instrument_key,
            "order_type": "SL-M",
            "transaction_type": transaction_type,
            "disclosed_quantity": 0,
            "trigger_price": trigger_price,
            "is_amo": False,
        }

        try:
            async with httpx.AsyncClient(timeout=10) as client:
                resp = await client.post(
                    f"{self.BASE_URL}/order/place",
                    headers=self._headers(),
                    json=payload,
                )
                data = resp.json()
                if data.get("status") == "success":
                    return OrderResult(
                        broker_order_id=str(data["data"]["order_id"]),
                        status="PENDING",
                        message=note,
                    )
                return OrderResult(
                    broker_order_id="",
                    status="REJECTED",
                    message=data.get("message", resp.text),
                )
        except Exception as exc:
            logger.error("[Upstox] place_trailing_stop_order failed: %s", exc)
            return OrderResult(broker_order_id="", status="REJECTED", message=str(exc))

    async def place_bracket_order(
        self,
        ticker: str,
        side: str,
        qty: float,
        entry_type: str,
        entry_price: Optional[float],
        stop_price: float,
        target_price: float,
    ) -> BracketOrderResult:
        """
        Upstox v2 does not support bracket orders directly.
        Places the entry order only and returns a BracketOrderResult noting
        that stop/target legs require manual placement.
        """
        instrument_key = self._instrument_key(ticker)
        transaction_type = "BUY" if side.upper() == "BUY" else "SELL"
        upstox_order_type = "LIMIT" if entry_type.upper() == "LIMIT" else "MARKET"
        price = entry_price if upstox_order_type == "LIMIT" and entry_price is not None else 0

        payload = {
            "quantity": int(qty),
            "product": "D",
            "validity": "DAY",
            "price": price,
            "instrument_token": instrument_key,
            "order_type": upstox_order_type,
            "transaction_type": transaction_type,
            "disclosed_quantity": 0,
            "trigger_price": 0,
            "is_amo": False,
        }

        try:
            async with httpx.AsyncClient(timeout=10) as client:
                resp = await client.post(
                    f"{self.BASE_URL}/order/place",
                    headers=self._headers(),
                    json=payload,
                )
                data = resp.json()
                if data.get("status") == "success":
                    order_id = str(data["data"]["order_id"])
                    return BracketOrderResult(
                        parent_order_id=order_id,
                        stop_leg_id="",
                        target_leg_id="",
                        status="PENDING",
                        message=(
                            "Bracket order: entry placed. "
                            "Stop/target legs require manual placement on Upstox."
                        ),
                    )
                return BracketOrderResult(
                    parent_order_id="",
                    stop_leg_id="",
                    target_leg_id="",
                    status="REJECTED",
                    message=data.get("message", resp.text),
                )
        except Exception as exc:
            logger.error("[Upstox] place_bracket_order failed: %s", exc)
            return BracketOrderResult(
                parent_order_id="",
                stop_leg_id="",
                target_leg_id="",
                status="REJECTED",
                message=str(exc),
            )

    async def get_order_status(self, broker_order_id: str) -> OrderResult:
        try:
            async with httpx.AsyncClient(timeout=10) as client:
                resp = await client.get(
                    f"{self.BASE_URL}/order/details",
                    headers=self._headers(),
                    params={"order_id": broker_order_id},
                )
                data = resp.json()
                orders = data.get("data", [])
                if orders:
                    o = orders[0]
                    return OrderResult(
                        broker_order_id=broker_order_id,
                        status=self._map_upstox_status(o.get("status", "")),
                        filled_qty=float(o.get("quantity", 0) or 0),
                        filled_price=float(o.get("average_price", 0) or 0),
                    )
                return OrderResult(
                    broker_order_id=broker_order_id,
                    status="UNKNOWN",
                    message=data.get("message", "No order data returned"),
                )
        except Exception as exc:
            logger.error("[Upstox] get_order_status failed: %s", exc)
            return OrderResult(
                broker_order_id=broker_order_id, status="UNKNOWN", message=str(exc)
            )

    async def cancel_order(self, broker_order_id: str) -> bool:
        try:
            async with httpx.AsyncClient(timeout=10) as client:
                resp = await client.delete(
                    f"{self.BASE_URL}/order/cancel",
                    headers=self._headers(),
                    params={"order_id": broker_order_id},
                )
                data = resp.json()
                return data.get("status") == "success"
        except Exception as exc:
            logger.error("[Upstox] cancel_order failed: %s", exc)
            return False

    async def get_positions(self) -> list[Position]:
        try:
            async with httpx.AsyncClient(timeout=10) as client:
                resp = await client.get(
                    f"{self.BASE_URL}/portfolio/long-term-holdings",
                    headers=self._headers(),
                )
                data = resp.json()
                positions: list[Position] = []
                for h in data.get("data", []):
                    qty = float(h.get("quantity", 0) or 0)
                    if qty > 0:
                        exchange = h.get("exchange", "NSE")
                        symbol = h.get("tradingsymbol", "")
                        suffix = ".BO" if exchange == "BSE" else ".NS"
                        ticker = symbol + suffix
                        positions.append(
                            Position(
                                ticker=ticker,
                                qty=qty,
                                avg_price=float(h.get("average_price", 0) or 0),
                                current_price=float(h.get("last_price", 0) or 0),
                                unrealized_pnl=float(h.get("pnl", 0) or 0),
                            )
                        )
                return positions
        except Exception as exc:
            logger.error("[Upstox] get_positions failed: %s", exc)
            return []

    async def get_account_balance(self) -> AccountBalance:
        try:
            async with httpx.AsyncClient(timeout=10) as client:
                resp = await client.get(
                    f"{self.BASE_URL}/user/fund-margin",
                    headers=self._headers(),
                )
                data = resp.json()
                equity = data.get("data", {}).get("equity", {})
                available_margin = float(equity.get("available_margin", 0) or 0)
                used_margin = float(equity.get("used_margin", 0) or 0)
                return AccountBalance(
                    cash=available_margin,
                    portfolio_value=available_margin + used_margin,
                    buying_power=available_margin,
                    currency="INR",
                )
        except Exception as exc:
            logger.error("[Upstox] get_account_balance failed: %s", exc)
            return AccountBalance(cash=0, portfolio_value=0, buying_power=0, currency="INR")
