"""
brokers/angel.py
================
Angel One SmartAPI broker connector for Indian markets.

Required env vars:
    ANGEL_API_KEY    — SmartAPI API key (X-PrivateKey header)
    ANGEL_CLIENT_ID  — Client/User ID
    ANGEL_JWT_TOKEN  — JWT session token (pre-authenticated)

Optional:
    ANGEL_FEED_TOKEN     — WebSocket feed token
    ANGEL_SYMBOL_TOKENS  — JSON dict of {tradingsymbol: token} for custom mappings
                           e.g. '{"INFY": "1594", "TCS": "11536"}'
                           If a symbol is not found, falls back to "0".
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


class AngelOneBroker(BrokerInterface):
    """
    Angel One SmartAPI broker for Indian markets.
    Requires: ANGEL_API_KEY, ANGEL_CLIENT_ID, ANGEL_JWT_TOKEN env vars.
    JWT token must be refreshed via SmartAPI login flow.
    """

    name = "ANGEL"
    BASE_URL = "https://apiconnect.angelone.in"

    def __init__(self) -> None:
        self.api_key = os.getenv("ANGEL_API_KEY")
        self.client_id = os.getenv("ANGEL_CLIENT_ID")
        self.jwt_token = os.getenv("ANGEL_JWT_TOKEN")
        if not self.api_key or not self.client_id or not self.jwt_token:
            raise ValueError(
                "ANGEL_API_KEY, ANGEL_CLIENT_ID, and ANGEL_JWT_TOKEN must be set in environment"
            )

    # ── Internal helpers ───────────────────────────────────────────────────────

    def _headers(self) -> dict:
        return {
            "Authorization": f"Bearer {self.jwt_token}",
            "Content-Type": "application/json",
            "Accept": "application/json",
            "X-UserType": "USER",
            "X-SourceID": "WEB",
            "X-ClientLocalIP": "127.0.0.1",
            "X-ClientPublicIP": "127.0.0.1",
            "X-MACAddress": "00:00:00:00:00:00",
            "X-PrivateKey": self.api_key,
        }

    def _get_symbol_token(self, tradingsymbol: str) -> str:
        """
        Look up the Angel One symboltoken for a given tradingsymbol.
        Set ANGEL_SYMBOL_TOKENS env var as a JSON dict for custom mappings,
        e.g. '{"INFY": "1594", "TCS": "11536"}'.
        Falls back to "0" if symbol not found (order will likely be rejected by Angel).
        """
        import json
        tokens_env = os.getenv("ANGEL_SYMBOL_TOKENS", "{}")
        try:
            tokens = json.loads(tokens_env)
            return str(tokens.get(tradingsymbol, "0"))
        except Exception:
            return "0"

    def _parse_ticker(self, ticker: str) -> tuple[str, str]:
        """
        Convert ticker to (exchange, tradingsymbol) for Angel One.
        - '.NS' suffix → 'NSE'
        - '.BO' suffix → 'BSE'
        - Bare symbol → 'NSE' (default)
        """
        if ticker.endswith(".NS"):
            return "NSE", ticker[:-3]
        if ticker.endswith(".BO"):
            return "BSE", ticker[:-3]
        return "NSE", ticker

    @staticmethod
    def _map_angel_status(angel_status: str) -> str:
        mapping = {
            "complete":  "FILLED",
            "cancelled": "CANCELLED",
            "rejected":  "REJECTED",
            "open":      "PENDING",
            "pending":   "PENDING",
        }
        return mapping.get(angel_status.lower(), "PENDING")

    # ── BrokerInterface implementation ────────────────────────────────────────

    async def place_order(
        self,
        ticker: str,
        side: str,
        qty: float,
        order_type: str = "MARKET",
        limit_price: Optional[float] = None,
    ) -> OrderResult:
        exchange, tradingsymbol = self._parse_ticker(ticker)
        symboltoken = self._get_symbol_token(tradingsymbol)
        transaction_type = "BUY" if side.upper() == "BUY" else "SELL"
        angel_order_type = "MARKET" if order_type.upper() == "MARKET" else "LIMIT"
        price = str(limit_price) if angel_order_type == "LIMIT" and limit_price is not None else "0"

        payload = {
            "variety": "NORMAL",
            "tradingsymbol": tradingsymbol,
            "symboltoken": symboltoken,
            "transactiontype": transaction_type,
            "exchange": exchange,
            "ordertype": angel_order_type,
            "producttype": "DELIVERY",
            "duration": "DAY",
            "price": price,
            "squareoff": "0",
            "stoploss": "0",
            "quantity": str(int(qty)),
        }

        try:
            async with httpx.AsyncClient(timeout=10) as client:
                resp = await client.post(
                    f"{self.BASE_URL}/rest/secure/angelbroking/order/v1/placeOrder",
                    headers=self._headers(),
                    json=payload,
                )
                data = resp.json()
                if data.get("status") is True:
                    return OrderResult(
                        broker_order_id=str(data["data"]["orderid"]),
                        status="PENDING",
                        message="Order placed on Angel One SmartAPI",
                    )
                return OrderResult(
                    broker_order_id="",
                    status="REJECTED",
                    message=data.get("message", resp.text),
                )
        except Exception as exc:
            logger.error("[Angel] place_order failed: %s", exc)
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
        Place a stop order on Angel One SmartAPI.
        - limit_price is None → STOPLOSS_MARKET (trigger only)
        - limit_price is set  → STOPLOSS_LIMIT  (trigger + limit price)
        """
        exchange, tradingsymbol = self._parse_ticker(ticker)
        symboltoken = self._get_symbol_token(tradingsymbol)
        transaction_type = "BUY" if side.upper() == "BUY" else "SELL"

        if limit_price is None:
            angel_order_type = "STOPLOSS_MARKET"
            price = "0"
        else:
            angel_order_type = "STOPLOSS_LIMIT"
            price = str(limit_price)

        payload = {
            "variety": "STOPLOSS",
            "tradingsymbol": tradingsymbol,
            "symboltoken": symboltoken,
            "transactiontype": transaction_type,
            "exchange": exchange,
            "ordertype": angel_order_type,
            "producttype": "DELIVERY",
            "duration": "DAY",
            "price": price,
            "triggerprice": str(stop_price),
            "squareoff": "0",
            "stoploss": "0",
            "quantity": str(int(qty)),
        }

        try:
            async with httpx.AsyncClient(timeout=10) as client:
                resp = await client.post(
                    f"{self.BASE_URL}/rest/secure/angelbroking/order/v1/placeOrder",
                    headers=self._headers(),
                    json=payload,
                )
                data = resp.json()
                if data.get("status") is True:
                    return OrderResult(
                        broker_order_id=str(data["data"]["orderid"]),
                        status="PENDING",
                        message=f"Stop order placed on Angel One ({angel_order_type})",
                    )
                return OrderResult(
                    broker_order_id="",
                    status="REJECTED",
                    message=data.get("message", resp.text),
                )
        except Exception as exc:
            logger.error("[Angel] place_stop_order failed: %s", exc)
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
        Place a trailing stop via Angel One ROBO (bracket) order variety.
        ROBO is intraday-only (producttype=INTRADAY). The trailing_stoploss and
        trailing_squareoff fields define the trailing behaviour.
        NOTE: ROBO orders are for intraday only; positions auto-square off at EOD.
        """
        exchange, tradingsymbol = self._parse_ticker(ticker)
        symboltoken = self._get_symbol_token(tradingsymbol)
        transaction_type = "BUY" if side.upper() == "BUY" else "SELL"

        if trail_type.upper() == "PERCENTAGE":
            trail_value = trail_amount
            note = (
                f"Trailing stop placed as ROBO (PERCENTAGE: {trail_amount}% expressed as points). "
                "ROBO is intraday only — positions auto-square at EOD."
            )
        else:
            trail_value = trail_amount
            note = (
                f"Trailing stop placed as ROBO (ABSOLUTE: {trail_amount} pts). "
                "ROBO is intraday only — positions auto-square at EOD."
            )

        payload = {
            "variety": "ROBO",
            "tradingsymbol": tradingsymbol,
            "symboltoken": symboltoken,
            "transactiontype": transaction_type,
            "exchange": exchange,
            "ordertype": "MARKET",
            "producttype": "INTRADAY",
            "duration": "DAY",
            "price": "0",
            "squareoff": str(trail_value),
            "stoploss": str(trail_value),
            "trailing_squareoff": str(trail_value),
            "trailing_stoploss": str(trail_value),
            "quantity": str(int(qty)),
        }

        try:
            async with httpx.AsyncClient(timeout=10) as client:
                resp = await client.post(
                    f"{self.BASE_URL}/rest/secure/angelbroking/order/v1/placeOrder",
                    headers=self._headers(),
                    json=payload,
                )
                data = resp.json()
                if data.get("status") is True:
                    return OrderResult(
                        broker_order_id=str(data["data"]["orderid"]),
                        status="PENDING",
                        message=note,
                    )
                return OrderResult(
                    broker_order_id="",
                    status="REJECTED",
                    message=data.get("message", resp.text),
                )
        except Exception as exc:
            logger.error("[Angel] place_trailing_stop_order failed: %s", exc)
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
        Place a bracket (ROBO) order on Angel One SmartAPI.
        squareoff = target_price - entry_price (for BUY)
        stoploss  = entry_price - stop_price   (for BUY)
        For SELL: squareoff = entry_price - target_price, stoploss = stop_price - entry_price
        Angel bundles stop and target legs under the same order ID; stop/target leg IDs are empty.
        NOTE: ROBO orders are intraday only (producttype=INTRADAY).
        """
        exchange, tradingsymbol = self._parse_ticker(ticker)
        symboltoken = self._get_symbol_token(tradingsymbol)
        transaction_type = "BUY" if side.upper() == "BUY" else "SELL"
        angel_order_type = "LIMIT" if entry_type.upper() == "LIMIT" else "MARKET"

        ref_price = entry_price if entry_price is not None else 0.0

        if side.upper() == "BUY":
            squareoff = max(target_price - ref_price, 0.0)
            stoploss = max(ref_price - stop_price, 0.0)
        else:
            squareoff = max(ref_price - target_price, 0.0)
            stoploss = max(stop_price - ref_price, 0.0)

        price = str(entry_price) if angel_order_type == "LIMIT" and entry_price is not None else "0"

        payload = {
            "variety": "ROBO",
            "tradingsymbol": tradingsymbol,
            "symboltoken": symboltoken,
            "transactiontype": transaction_type,
            "exchange": exchange,
            "ordertype": angel_order_type,
            "producttype": "INTRADAY",
            "duration": "DAY",
            "price": price,
            "squareoff": str(squareoff),
            "stoploss": str(stoploss),
            "quantity": str(int(qty)),
        }

        try:
            async with httpx.AsyncClient(timeout=10) as client:
                resp = await client.post(
                    f"{self.BASE_URL}/rest/secure/angelbroking/order/v1/placeOrder",
                    headers=self._headers(),
                    json=payload,
                )
                data = resp.json()
                if data.get("status") is True:
                    order_id = str(data["data"]["orderid"])
                    return BracketOrderResult(
                        parent_order_id=order_id,
                        # Angel bundles stop & target legs into the same order
                        stop_leg_id="",
                        target_leg_id="",
                        status="PENDING",
                        message=(
                            "Bracket (ROBO) order placed on Angel One SmartAPI. "
                            "ROBO is intraday only — positions auto-square at EOD."
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
            logger.error("[Angel] place_bracket_order failed: %s", exc)
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
                    f"{self.BASE_URL}/rest/secure/angelbroking/order/v1/details/{broker_order_id}",
                    headers=self._headers(),
                )
                data = resp.json()
                order_data = data.get("data", {})
                if order_data:
                    return OrderResult(
                        broker_order_id=broker_order_id,
                        status=self._map_angel_status(order_data.get("status", "")),
                        filled_qty=float(order_data.get("filledshares", 0) or 0),
                        filled_price=float(order_data.get("averageprice", 0) or 0),
                    )
                return OrderResult(
                    broker_order_id=broker_order_id,
                    status="UNKNOWN",
                    message=data.get("message", "No order data returned"),
                )
        except Exception as exc:
            logger.error("[Angel] get_order_status failed: %s", exc)
            return OrderResult(
                broker_order_id=broker_order_id, status="UNKNOWN", message=str(exc)
            )

    async def cancel_order(self, broker_order_id: str) -> bool:
        payload = {
            "variety": "NORMAL",
            "orderid": broker_order_id,
        }
        try:
            async with httpx.AsyncClient(timeout=10) as client:
                resp = await client.post(
                    f"{self.BASE_URL}/rest/secure/angelbroking/order/v1/cancelOrder",
                    headers=self._headers(),
                    json=payload,
                )
                data = resp.json()
                return data.get("status") is True
        except Exception as exc:
            logger.error("[Angel] cancel_order failed: %s", exc)
            return False

    async def get_positions(self) -> list[Position]:
        try:
            async with httpx.AsyncClient(timeout=10) as client:
                resp = await client.get(
                    f"{self.BASE_URL}/rest/secure/angelbroking/portfolio/v1/getAllHolding",
                    headers=self._headers(),
                )
                data = resp.json()
                holdings = data.get("data", {}).get("holdings", [])
                positions: list[Position] = []
                for h in holdings:
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
                                avg_price=float(h.get("averageprice", 0) or 0),
                                current_price=float(h.get("ltp", 0) or 0),
                                unrealized_pnl=None,
                            )
                        )
                return positions
        except Exception as exc:
            logger.error("[Angel] get_positions failed: %s", exc)
            return []

    async def get_account_balance(self) -> AccountBalance:
        try:
            async with httpx.AsyncClient(timeout=10) as client:
                resp = await client.get(
                    f"{self.BASE_URL}/rest/secure/angelbroking/user/v1/getRMS",
                    headers=self._headers(),
                )
                data = resp.json()
                rms_data = data.get("data", {})
                net = float(rms_data.get("net", 0) or 0)
                available_cash = float(rms_data.get("availablecash", 0) or 0)
                return AccountBalance(
                    cash=available_cash,
                    portfolio_value=net,
                    buying_power=available_cash,
                    currency="INR",
                )
        except Exception as exc:
            logger.error("[Angel] get_account_balance failed: %s", exc)
            return AccountBalance(cash=0, portfolio_value=0, buying_power=0, currency="INR")
