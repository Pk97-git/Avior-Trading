"""
brokers/zerodha.py
==================
Zerodha Kite Connect broker connector for Indian markets.

Required env vars:
    ZERODHA_API_KEY       — your Kite Connect API key
    ZERODHA_ACCESS_TOKEN  — session access token (refresh daily via login flow)

Optional:
    ZERODHA_API_SECRET    — API secret (needed only for the login/token exchange flow)
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


class ZerodhaKiteBroker(BrokerInterface):
    """
    Zerodha Kite Connect broker for Indian markets.
    Requires: ZERODHA_API_KEY, ZERODHA_ACCESS_TOKEN env vars.
    Access token must be refreshed daily via Zerodha login flow.
    """

    name = "ZERODHA"
    BASE_URL = "https://api.kite.trade"

    def __init__(self) -> None:
        self.api_key = os.getenv("ZERODHA_API_KEY")
        self.access_token = os.getenv("ZERODHA_ACCESS_TOKEN")
        if not self.api_key or not self.access_token:
            raise ValueError(
                "ZERODHA_API_KEY and ZERODHA_ACCESS_TOKEN must be set in environment"
            )

    # ── Internal helpers ───────────────────────────────────────────────────────

    def _headers(self) -> dict:
        return {
            "X-Kite-Version": "3",
            "Authorization": f"token {self.api_key}:{self.access_token}",
        }

    def _kite_exchange(self, ticker: str) -> tuple[str, str]:
        """Convert ticker symbol to (exchange, tradingsymbol) for Kite API."""
        if ticker.endswith(".NS"):
            return "NSE", ticker[:-3]
        if ticker.endswith(".BO"):
            return "BSE", ticker[:-3]
        return "NSE", ticker

    @staticmethod
    def _map_kite_status(kite_status: str) -> str:
        mapping = {
            "COMPLETE":  "FILLED",
            "CANCELLED": "CANCELLED",
            "REJECTED":  "REJECTED",
            "OPEN":      "PENDING",
            "PENDING":   "PENDING",
            "AMO REQ RECEIVED": "PENDING",
            "VALIDATION PENDING": "PENDING",
            "PUT ORDER REQ RECEIVED": "PENDING",
        }
        return mapping.get(kite_status.upper(), "PENDING")

    # ── BrokerInterface implementation ────────────────────────────────────────

    async def place_order(
        self,
        ticker: str,
        side: str,
        qty: float,
        order_type: str = "MARKET",
        limit_price: Optional[float] = None,
    ) -> OrderResult:
        exchange, symbol = self._kite_exchange(ticker)
        transaction_type = "BUY" if side.upper() == "BUY" else "SELL"
        kite_order_type = "MARKET" if order_type.upper() == "MARKET" else "LIMIT"

        payload: dict = {
            "exchange":         exchange,
            "tradingsymbol":    symbol,
            "transaction_type": transaction_type,
            "quantity":         int(qty),
            "product":          "CNC",        # delivery (not intraday MIS)
            "order_type":       kite_order_type,
            "validity":         "DAY",
        }
        if kite_order_type == "LIMIT" and limit_price is not None:
            payload["price"] = limit_price

        try:
            async with httpx.AsyncClient(timeout=10) as client:
                resp = await client.post(
                    f"{self.BASE_URL}/orders/regular",
                    headers=self._headers(),
                    data=payload,
                )
                data = resp.json()
                if resp.status_code == 200 and data.get("status") == "success":
                    return OrderResult(
                        broker_order_id=str(data["data"]["order_id"]),
                        status="PENDING",
                        message="Order placed on Kite",
                    )
                return OrderResult(
                    broker_order_id="",
                    status="REJECTED",
                    message=data.get("message", resp.text),
                )
        except Exception as exc:
            logger.error("[Zerodha] place_order failed: %s", exc)
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
        Place a stop order on Kite.
        - limit_price is None  → SL-M (stop-market)
        - limit_price is set   → SL   (stop-limit)
        """
        exchange, symbol = self._kite_exchange(ticker)
        transaction_type = "BUY" if side.upper() == "BUY" else "SELL"

        if limit_price is None:
            kite_order_type = "SL-M"
        else:
            kite_order_type = "SL"

        payload: dict = {
            "exchange":         exchange,
            "tradingsymbol":    symbol,
            "transaction_type": transaction_type,
            "quantity":         int(qty),
            "product":          "CNC",
            "order_type":       kite_order_type,
            "validity":         "DAY",
            "trigger_price":    stop_price,
        }
        if limit_price is not None:
            payload["price"] = limit_price

        try:
            async with httpx.AsyncClient(timeout=10) as client:
                resp = await client.post(
                    f"{self.BASE_URL}/orders/regular",
                    headers=self._headers(),
                    data=payload,
                )
                data = resp.json()
                if resp.status_code == 200 and data.get("status") == "success":
                    return OrderResult(
                        broker_order_id=str(data["data"]["order_id"]),
                        status="PENDING",
                        message=f"Stop order placed on Kite ({kite_order_type})",
                    )
                return OrderResult(
                    broker_order_id="",
                    status="REJECTED",
                    message=data.get("message", resp.text),
                )
        except Exception as exc:
            logger.error("[Zerodha] place_stop_order failed: %s", exc)
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
        Place a trailing stop via Zerodha Bracket Order (BO variety).
        Kite trailing stops are only supported within bracket orders.
        trailing_stoploss field is expressed in price points (rupees).
        """
        exchange, symbol = self._kite_exchange(ticker)
        transaction_type = "BUY" if side.upper() == "BUY" else "SELL"

        # For a pure trailing stop we need an entry reference price.
        # We place a MARKET bracket order; squareoff=0 means no fixed target.
        # trail_type PERCENTAGE: trailing_stoploss = price * trail_amount / 100
        # trail_type ABSOLUTE:   trailing_stoploss = trail_amount (in points)
        if trail_type.upper() == "PERCENTAGE":
            # Without a live price feed here, we set trailing_stoploss proportionally.
            # Callers should provide trail_amount as a percent (e.g. 1.0 for 1%).
            # We use trail_amount directly and note manual adjustment may be needed.
            trailing_stoploss = trail_amount
            note = (
                f"Trailing stop placed as BO (PERCENTAGE mode: {trail_amount}% "
                "expressed as points — verify with live price)"
            )
        else:
            trailing_stoploss = trail_amount
            note = f"Trailing stop placed as BO (ABSOLUTE: {trail_amount} pts)"

        payload: dict = {
            "exchange":           exchange,
            "tradingsymbol":      symbol,
            "transaction_type":   transaction_type,
            "quantity":           int(qty),
            "product":            "MIS",          # BO is intraday only on Kite
            "order_type":         "MARKET",
            "validity":           "DAY",
            "squareoff":          0,               # no fixed profit target
            "stoploss":           trailing_stoploss,
            "trailing_stoploss":  trailing_stoploss,
        }

        try:
            async with httpx.AsyncClient(timeout=10) as client:
                resp = await client.post(
                    f"{self.BASE_URL}/orders/bo",
                    headers=self._headers(),
                    data=payload,
                )
                data = resp.json()
                if resp.status_code == 200 and data.get("status") == "success":
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
            logger.error("[Zerodha] place_trailing_stop_order failed: %s", exc)
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
        Place a Bracket Order (BO) on Kite Connect.
        squareoff and stoploss are in price points (not absolute prices).
        """
        exchange, symbol = self._kite_exchange(ticker)
        transaction_type = "BUY" if side.upper() == "BUY" else "SELL"
        kite_order_type = "LIMIT" if entry_type.upper() == "LIMIT" else "MARKET"

        # Derive reference entry price for point calculations.
        ref_price = entry_price if entry_price is not None else 0.0

        if side.upper() == "BUY":
            squareoff = target_price - ref_price   # points above entry
            stoploss = ref_price - stop_price       # points below entry
        else:  # SELL
            squareoff = ref_price - target_price    # points below entry for short
            stoploss = stop_price - ref_price       # points above entry for short

        # Clamp to non-negative — guard against inverted inputs
        squareoff = max(squareoff, 0.0)
        stoploss = max(stoploss, 0.0)

        payload: dict = {
            "exchange":         exchange,
            "tradingsymbol":    symbol,
            "transaction_type": transaction_type,
            "quantity":         int(qty),
            "product":          "MIS",     # Kite BO is always intraday (MIS)
            "order_type":       kite_order_type,
            "validity":         "DAY",
            "squareoff":        squareoff,
            "stoploss":         stoploss,
            "trailing_stoploss": 0,        # no trailing in plain bracket
        }
        if kite_order_type == "LIMIT" and entry_price is not None:
            payload["price"] = entry_price

        try:
            async with httpx.AsyncClient(timeout=10) as client:
                resp = await client.post(
                    f"{self.BASE_URL}/orders/bo",
                    headers=self._headers(),
                    data=payload,
                )
                data = resp.json()
                if resp.status_code == 200 and data.get("status") == "success":
                    order_id = str(data["data"]["order_id"])
                    return BracketOrderResult(
                        parent_order_id=order_id,
                        # Kite bundles stop & target legs under the same parent
                        stop_leg_id=order_id,
                        target_leg_id=order_id,
                        status="PENDING",
                        message="Bracket order placed on Kite (BO variety)",
                    )
                return BracketOrderResult(
                    parent_order_id="",
                    stop_leg_id="",
                    target_leg_id="",
                    status="REJECTED",
                    message=data.get("message", resp.text),
                )
        except Exception as exc:
            logger.error("[Zerodha] place_bracket_order failed: %s", exc)
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
                    f"{self.BASE_URL}/orders/{broker_order_id}",
                    headers=self._headers(),
                )
                data = resp.json()
                if resp.status_code == 200:
                    orders = data.get("data", [])
                    if orders:
                        o = orders[-1]  # last entry = latest status
                        return OrderResult(
                            broker_order_id=broker_order_id,
                            status=self._map_kite_status(o.get("status", "")),
                            filled_qty=float(o.get("filled_quantity", 0) or 0),
                            filled_price=float(o.get("average_price", 0) or 0),
                        )
                return OrderResult(
                    broker_order_id=broker_order_id,
                    status="UNKNOWN",
                    message=data.get("message", ""),
                )
        except Exception as exc:
            logger.error("[Zerodha] get_order_status failed: %s", exc)
            return OrderResult(
                broker_order_id=broker_order_id, status="UNKNOWN", message=str(exc)
            )

    async def cancel_order(self, broker_order_id: str) -> bool:
        try:
            async with httpx.AsyncClient(timeout=10) as client:
                resp = await client.delete(
                    f"{self.BASE_URL}/orders/regular/{broker_order_id}",
                    headers=self._headers(),
                )
                return resp.status_code == 200
        except Exception as exc:
            logger.error("[Zerodha] cancel_order failed: %s", exc)
            return False

    async def get_positions(self) -> list[Position]:
        try:
            async with httpx.AsyncClient(timeout=10) as client:
                resp = await client.get(
                    f"{self.BASE_URL}/portfolio/holdings",
                    headers=self._headers(),
                )
                data = resp.json()
                positions: list[Position] = []
                for h in data.get("data", []):
                    qty = float(h.get("quantity", 0) or 0)
                    if qty > 0:
                        ticker = h.get("tradingsymbol", "") + ".NS"
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
            logger.error("[Zerodha] get_positions failed: %s", exc)
            return []

    async def get_account_balance(self) -> AccountBalance:
        try:
            async with httpx.AsyncClient(timeout=10) as client:
                resp = await client.get(
                    f"{self.BASE_URL}/user/margins",
                    headers=self._headers(),
                )
                equity = resp.json().get("data", {}).get("equity", {})
                net = equity.get("net", {})
                available = net.get("available", {})
                return AccountBalance(
                    cash=float(available.get("cash", 0) or 0),
                    portfolio_value=float(net.get("net", 0) or 0),
                    buying_power=float(available.get("intraday_payin", 0) or 0),
                    currency="INR",
                )
        except Exception as exc:
            logger.error("[Zerodha] get_account_balance failed: %s", exc)
            return AccountBalance(cash=0, portfolio_value=0, buying_power=0, currency="INR")
