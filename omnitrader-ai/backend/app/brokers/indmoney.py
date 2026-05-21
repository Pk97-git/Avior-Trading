"""
brokers/indmoney.py
===================
INDmoney (IndMoney Trader API) broker connector for Indian markets.

INDmoney supports NSE/BSE equities, US stocks, and mutual funds.
This connector covers Indian equities (NSE/BSE).

Required env vars:
    INDMONEY_API_KEY      — your INDmoney developer API key
    INDMONEY_ACCESS_TOKEN — OAuth2 bearer token (from login flow)

Optional:
    INDMONEY_CLIENT_ID    — your registered client/user ID

API reference: https://api.indmoney.com (developer portal)
"""
import logging
import os
from typing import Optional

import httpx

from app.brokers.base import (
    BrokerInterface,
    BracketOrderResult,
    OrderResult,
    Position,
    AccountBalance,
)

logger = logging.getLogger(__name__)


class INDmoneyBroker(BrokerInterface):
    """
    INDmoney Trader API broker for Indian markets (NSE / BSE equities).

    Required env vars: INDMONEY_API_KEY, INDMONEY_ACCESS_TOKEN
    """

    name = "INDMONEY"
    BASE_URL = "https://api.indmoney.com"

    def __init__(self) -> None:
        self.api_key = os.getenv("INDMONEY_API_KEY")
        self.access_token = os.getenv("INDMONEY_ACCESS_TOKEN")
        self.client_id = os.getenv("INDMONEY_CLIENT_ID", "")
        if not self.api_key or not self.access_token:
            raise ValueError(
                "INDMONEY_API_KEY and INDMONEY_ACCESS_TOKEN must be set in environment"
            )

    # ── Internal helpers ───────────────────────────────────────────────────────

    def _headers(self) -> dict:
        return {
            "Authorization": f"Bearer {self.access_token}",
            "x-api-key": self.api_key,
            "Content-Type": "application/json",
            "Accept": "application/json",
        }

    def _instrument_key(self, ticker: str) -> tuple[str, str]:
        """
        Convert a yfinance-style ticker to (exchange, tradingsymbol).
        INFY.NS  → ("NSE", "INFY")
        INFY.BO  → ("BSE", "INFY")
        INFY     → ("NSE", "INFY")  (default NSE)
        """
        if ticker.upper().endswith(".NS"):
            return "NSE", ticker[:-3].upper()
        if ticker.upper().endswith(".BO"):
            return "BSE", ticker[:-3].upper()
        return "NSE", ticker.upper()

    @staticmethod
    def _map_status(raw: str) -> str:
        mapping = {
            "complete":     "FILLED",
            "filled":       "FILLED",
            "executed":     "FILLED",
            "cancelled":    "CANCELLED",
            "canceled":     "CANCELLED",
            "rejected":     "REJECTED",
            "failed":       "REJECTED",
            "open":         "PENDING",
            "pending":      "PENDING",
            "placed":       "PENDING",
            "trigger_pending": "PENDING",
            "amo_req_received": "PENDING",
        }
        return mapping.get(raw.lower(), "PENDING")

    # ── BrokerInterface implementation ────────────────────────────────────────

    async def place_order(
        self,
        ticker: str,
        side: str,
        qty: float,
        order_type: str = "MARKET",
        limit_price: Optional[float] = None,
    ) -> OrderResult:
        exchange, symbol = self._instrument_key(ticker)
        otype = order_type.upper()

        payload: dict = {
            "exchange":         exchange,
            "trading_symbol":   symbol,
            "transaction_type": side.upper(),   # BUY / SELL
            "quantity":         int(qty),
            "order_type":       otype,          # MARKET / LIMIT
            "product":          "CNC",          # CNC = delivery (not intraday)
            "validity":         "DAY",
            "price":            float(limit_price) if otype == "LIMIT" and limit_price else 0.0,
        }

        try:
            async with httpx.AsyncClient(timeout=10) as client:
                resp = await client.post(
                    f"{self.BASE_URL}/stocks/v1/orders",
                    headers=self._headers(),
                    json=payload,
                )
                data = resp.json()
                if resp.status_code in (200, 201) and data.get("success"):
                    order_id = str(data.get("data", {}).get("order_id", ""))
                    return OrderResult(
                        broker_order_id=order_id,
                        status="PENDING",
                        message="Order placed on INDmoney",
                    )
                return OrderResult(
                    broker_order_id="",
                    status="REJECTED",
                    message=data.get("message") or data.get("error") or resp.text,
                )
        except Exception as exc:
            logger.error("[INDmoney] place_order failed: %s", exc)
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
        Stop-market (limit_price=None) or stop-limit order.
        INDmoney uses order_type=SL (stop-limit) or SL-M (stop-market)
        and trigger_price for the stop level.
        """
        exchange, symbol = self._instrument_key(ticker)
        otype = "SL" if limit_price is not None else "SL-M"

        payload: dict = {
            "exchange":         exchange,
            "trading_symbol":   symbol,
            "transaction_type": side.upper(),
            "quantity":         int(qty),
            "order_type":       otype,
            "product":          "CNC",
            "validity":         "DAY",
            "trigger_price":    float(stop_price),
            "price":            float(limit_price) if limit_price else 0.0,
        }

        try:
            async with httpx.AsyncClient(timeout=10) as client:
                resp = await client.post(
                    f"{self.BASE_URL}/stocks/v1/orders",
                    headers=self._headers(),
                    json=payload,
                )
                data = resp.json()
                if resp.status_code in (200, 201) and data.get("success"):
                    return OrderResult(
                        broker_order_id=str(data.get("data", {}).get("order_id", "")),
                        status="PENDING",
                        message=f"Stop order ({otype}) placed on INDmoney",
                    )
                return OrderResult(
                    broker_order_id="",
                    status="REJECTED",
                    message=data.get("message") or resp.text,
                )
        except Exception as exc:
            logger.error("[INDmoney] place_stop_order failed: %s", exc)
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
        INDmoney does not currently support native trailing stop orders.
        Places a regular SL-M order as a best-effort fallback.
        """
        logger.info(
            "[INDmoney] Trailing stop not natively supported — "
            "placing SL-M at trail_amount=%.4f as fallback for %s",
            trail_amount, ticker,
        )
        return await self.place_stop_order(
            ticker=ticker,
            side=side,
            qty=qty,
            stop_price=trail_amount,
            limit_price=None,
        )

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
        INDmoney does not natively support bracket orders via API.
        Places the entry leg only and returns a partial BracketOrderResult.
        Stop and target legs must be placed manually on the INDmoney app.
        """
        entry_result = await self.place_order(
            ticker=ticker,
            side=side,
            qty=qty,
            order_type=entry_type,
            limit_price=entry_price if entry_type.upper() == "LIMIT" else None,
        )
        return BracketOrderResult(
            parent_order_id=entry_result.broker_order_id,
            stop_leg_id="",
            target_leg_id="",
            status=entry_result.status,
            message=(
                "Bracket entry placed on INDmoney. "
                "Stop/target legs are not supported via API — "
                "place them manually in the INDmoney app."
            ),
        )

    async def get_order_status(self, broker_order_id: str) -> OrderResult:
        try:
            async with httpx.AsyncClient(timeout=10) as client:
                resp = await client.get(
                    f"{self.BASE_URL}/stocks/v1/orders/{broker_order_id}",
                    headers=self._headers(),
                )
                data = resp.json()
                if resp.status_code == 200:
                    order_data = data.get("data") or {}
                    status_raw = (order_data.get("status") or "").lower()
                    filled_qty = float(order_data.get("filled_quantity") or 0)
                    avg_price = float(order_data.get("average_price") or 0)
                    return OrderResult(
                        broker_order_id=broker_order_id,
                        status=self._map_status(status_raw),
                        filled_qty=filled_qty,
                        filled_price=avg_price if avg_price else None,
                    )
                return OrderResult(
                    broker_order_id=broker_order_id,
                    status="UNKNOWN",
                    message=data.get("message", ""),
                )
        except Exception as exc:
            logger.error("[INDmoney] get_order_status failed: %s", exc)
            return OrderResult(broker_order_id=broker_order_id, status="UNKNOWN", message=str(exc))

    async def cancel_order(self, broker_order_id: str) -> bool:
        try:
            async with httpx.AsyncClient(timeout=10) as client:
                resp = await client.delete(
                    f"{self.BASE_URL}/stocks/v1/orders/{broker_order_id}",
                    headers=self._headers(),
                )
                return resp.status_code in (200, 204)
        except Exception as exc:
            logger.error("[INDmoney] cancel_order failed: %s", exc)
            return False

    async def get_positions(self) -> list[Position]:
        try:
            async with httpx.AsyncClient(timeout=10) as client:
                resp = await client.get(
                    f"{self.BASE_URL}/stocks/v1/holdings",
                    headers=self._headers(),
                )
                data = resp.json()
                positions: list[Position] = []
                for h in data.get("data") or []:
                    qty = float(h.get("quantity") or 0)
                    if qty <= 0:
                        continue
                    symbol = h.get("trading_symbol") or h.get("symbol", "")
                    exchange = h.get("exchange", "NSE")
                    suffix = ".NS" if exchange == "NSE" else ".BO"
                    ticker = symbol + suffix
                    positions.append(
                        Position(
                            ticker=ticker,
                            qty=qty,
                            avg_price=float(h.get("average_price") or 0),
                            current_price=float(h.get("last_price") or h.get("ltp") or 0) or None,
                            unrealized_pnl=float(h.get("pnl") or h.get("unrealised_pnl") or 0) or None,
                        )
                    )
                return positions
        except Exception as exc:
            logger.error("[INDmoney] get_positions failed: %s", exc)
            return []

    async def get_account_balance(self) -> AccountBalance:
        try:
            async with httpx.AsyncClient(timeout=10) as client:
                resp = await client.get(
                    f"{self.BASE_URL}/stocks/v1/funds",
                    headers=self._headers(),
                )
                data = resp.json().get("data") or {}
                available = float(data.get("available_cash") or data.get("available_margin") or 0)
                net = float(data.get("net") or data.get("total_balance") or available)
                buying_power = float(data.get("buying_power") or available)
                return AccountBalance(
                    cash=available,
                    portfolio_value=net,
                    buying_power=buying_power,
                    currency="INR",
                )
        except Exception as exc:
            logger.error("[INDmoney] get_account_balance failed: %s", exc)
            return AccountBalance(cash=0, portfolio_value=0, buying_power=0, currency="INR")
