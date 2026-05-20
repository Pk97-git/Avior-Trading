"""
brokers/robinhood.py
====================
Robinhood broker connector for US equities.

IMPORTANT NOTE: Robinhood has no official public API for production use. This
implementation uses their unofficial REST API endpoints (the same ones used by
the robin_stocks library). This is provided for educational and research
purposes only. Use at your own risk and in compliance with Robinhood's terms
of service.

Full OAuth2 login flow (username/password/MFA/device-token) is complex and
outside the scope of this connector. Users must pre-authenticate via another
means (e.g., robin_stocks, the mobile app session, or Robinhood's OAuth2
flow) and supply the resulting bearer token via the ROBINHOOD_ACCESS_TOKEN
environment variable.

Required env vars:
    ROBINHOOD_ACCESS_TOKEN   — OAuth2 bearer token (pre-authenticated)
    ROBINHOOD_ACCOUNT_NUMBER — Account number (e.g. "5QR12345")
"""
import logging
import os
from typing import Optional

import httpx

from app.brokers.base import (
    AccountBalance,
    BracketOrderResult,
    BrokerInterface,
    OrderResult,
    Position,
)

logger = logging.getLogger(__name__)

_BASE_URL = "https://api.robinhood.com"


class RobinhoodBroker(BrokerInterface):
    """
    Robinhood broker using the unofficial REST API.

    Requires:
        ROBINHOOD_ACCESS_TOKEN   — pre-obtained OAuth2 bearer token
        ROBINHOOD_ACCOUNT_NUMBER — e.g. "5QR12345"

    Limitations:
        - Trailing stops are not supported natively; a stop-market order is
          placed at (current_price - trail_amount) as a best-effort substitute.
        - Bracket orders are not supported; only the entry leg is placed.
    """

    name = "ROBINHOOD"

    def __init__(self) -> None:
        self.access_token = os.getenv("ROBINHOOD_ACCESS_TOKEN")
        self.account_number = os.getenv("ROBINHOOD_ACCOUNT_NUMBER")
        if not self.access_token or not self.account_number:
            raise ValueError(
                "ROBINHOOD_ACCESS_TOKEN and ROBINHOOD_ACCOUNT_NUMBER must be set "
                "in environment"
            )
        # In-process cache: ticker → instrument UUID
        self._instrument_cache: dict[str, str] = {}

    # ── Internal helpers ───────────────────────────────────────────────────────

    def _headers(self) -> dict:
        return {
            "Authorization": f"Bearer {self.access_token}",
            "Content-Type": "application/json",
        }

    @staticmethod
    def _map_rh_status(rh_status: str) -> str:
        mapping = {
            "filled":           "FILLED",
            "cancelled":        "CANCELLED",
            "failed":           "REJECTED",
            "rejected":         "REJECTED",
            "queued":           "PENDING",
            "unconfirmed":      "PENDING",
            "confirmed":        "PENDING",
            "partially_filled": "PENDING",
        }
        return mapping.get(rh_status.lower(), "PENDING")

    async def _get_instrument_id(self, ticker: str) -> Optional[str]:
        """
        Look up the Robinhood instrument UUID for a ticker symbol.
        Results are cached in self._instrument_cache to avoid repeated lookups.
        """
        clean_ticker = ticker.replace(".US", "").upper()

        if clean_ticker in self._instrument_cache:
            return self._instrument_cache[clean_ticker]

        try:
            async with httpx.AsyncClient(timeout=10) as client:
                resp = await client.get(
                    f"{_BASE_URL}/instruments/",
                    headers=self._headers(),
                    params={"symbol": clean_ticker},
                )
                resp.raise_for_status()
                data = resp.json()
                results = data.get("results", [])
                if results:
                    instrument_id = results[0]["id"]
                    self._instrument_cache[clean_ticker] = instrument_id
                    logger.debug(
                        "[Robinhood] instrument_id for %s: %s", clean_ticker, instrument_id
                    )
                    return instrument_id
                logger.warning("[Robinhood] No instrument found for %s", clean_ticker)
                return None
        except Exception as exc:
            logger.error("[Robinhood] _get_instrument_id failed for %s: %s", ticker, exc)
            return None

    async def _get_current_price(self, ticker: str) -> Optional[float]:
        """
        Fetch the latest trade price for a ticker via the quotes endpoint.
        Used as a fallback when placing trailing stops as stop-market orders.
        """
        clean_ticker = ticker.replace(".US", "").upper()
        try:
            async with httpx.AsyncClient(timeout=10) as client:
                resp = await client.get(
                    f"{_BASE_URL}/quotes/{clean_ticker}/",
                    headers=self._headers(),
                )
                resp.raise_for_status()
                data = resp.json()
                price_str = data.get("last_trade_price") or data.get("last_extended_hours_trade_price")
                return float(price_str) if price_str else None
        except Exception as exc:
            logger.error("[Robinhood] _get_current_price failed for %s: %s", ticker, exc)
            return None

    async def _post_order(self, payload: dict) -> OrderResult:
        """
        POST /orders/ with the given payload and return an OrderResult.
        """
        try:
            async with httpx.AsyncClient(timeout=10) as client:
                resp = await client.post(
                    f"{_BASE_URL}/orders/",
                    headers=self._headers(),
                    json=payload,
                )
                data = resp.json()
                if resp.status_code in (200, 201):
                    return OrderResult(
                        broker_order_id=data["id"],
                        status=self._map_rh_status(data.get("state", "")),
                        filled_qty=float(data.get("cumulative_quantity") or 0),
                        filled_price=float(data.get("average_price") or 0),
                        message="Order placed on Robinhood",
                    )
                return OrderResult(
                    broker_order_id="",
                    status="REJECTED",
                    message=data.get("detail", str(data)),
                )
        except Exception as exc:
            logger.error("[Robinhood] _post_order failed: %s", exc)
            return OrderResult(broker_order_id="", status="REJECTED", message=str(exc))

    # ── BrokerInterface implementation ────────────────────────────────────────

    async def place_order(
        self,
        ticker: str,
        side: str,
        qty: float,
        order_type: str = "MARKET",
        limit_price: Optional[float] = None,
    ) -> OrderResult:
        clean_ticker = ticker.replace(".US", "").upper()
        instrument_id = await self._get_instrument_id(clean_ticker)
        if instrument_id is None:
            return OrderResult(
                broker_order_id="",
                status="REJECTED",
                message=f"Could not resolve instrument for ticker: {ticker}",
            )

        payload: dict = {
            "account": f"{_BASE_URL}/accounts/{self.account_number}/",
            "instrument": f"{_BASE_URL}/instruments/{instrument_id}/",
            "symbol": clean_ticker,
            "type": order_type.lower(),   # "market" or "limit"
            "side": side.lower(),          # "buy" or "sell"
            "quantity": str(qty),
            "time_in_force": "gfd",        # good for day
            "trigger": "immediate",
        }

        if order_type.upper() == "LIMIT" and limit_price is not None:
            payload["price"] = str(limit_price)

        return await self._post_order(payload)

    async def place_stop_order(
        self,
        ticker: str,
        side: str,
        qty: float,
        stop_price: float,
        limit_price: Optional[float] = None,
    ) -> OrderResult:
        """
        Place a stop or stop-limit order on Robinhood.
        - limit_price is None  → stop_loss order (stop-market)
        - limit_price is set   → stop_limit order
        """
        clean_ticker = ticker.replace(".US", "").upper()
        instrument_id = await self._get_instrument_id(clean_ticker)
        if instrument_id is None:
            return OrderResult(
                broker_order_id="",
                status="REJECTED",
                message=f"Could not resolve instrument for ticker: {ticker}",
            )

        payload: dict = {
            "account": f"{_BASE_URL}/accounts/{self.account_number}/",
            "instrument": f"{_BASE_URL}/instruments/{instrument_id}/",
            "symbol": clean_ticker,
            "side": side.lower(),
            "quantity": str(qty),
            "time_in_force": "gfd",
            "trigger": "stop",
            "stop_price": str(stop_price),
        }

        if limit_price is None:
            payload["type"] = "stop_loss"
        else:
            payload["type"] = "stop_limit"
            payload["price"] = str(limit_price)

        return await self._post_order(payload)

    async def place_trailing_stop_order(
        self,
        ticker: str,
        side: str,
        qty: float,
        trail_amount: float,
        trail_type: str = "ABSOLUTE",
    ) -> OrderResult:
        """
        Robinhood does NOT support native trailing stop orders via their API.

        As a best-effort substitute, this method:
          1. Fetches the current market price of the ticker.
          2. Computes a fixed stop price:
             - ABSOLUTE:   stop_price = current_price - trail_amount
             - PERCENTAGE: stop_price = current_price * (1 - trail_amount / 100)
          3. Places a stop-market (stop_loss) order at that price.

        NOTE: The stop price is static — it will NOT trail the market
        automatically. Users should manage re-submission manually.
        """
        clean_ticker = ticker.replace(".US", "").upper()
        instrument_id = await self._get_instrument_id(clean_ticker)
        if instrument_id is None:
            return OrderResult(
                broker_order_id="",
                status="REJECTED",
                message=f"Could not resolve instrument for ticker: {ticker}",
            )

        # Determine a static stop price from the current market price
        current_price = await self._get_current_price(clean_ticker)
        if current_price is None:
            return OrderResult(
                broker_order_id="",
                status="REJECTED",
                message=(
                    "Could not fetch current price for trailing stop computation. "
                    "Robinhood does not support native trailing stops."
                ),
            )

        if trail_type.upper() == "ABSOLUTE":
            computed_stop = current_price - trail_amount
        else:  # PERCENTAGE
            computed_stop = current_price * (1.0 - trail_amount / 100.0)

        computed_stop = round(computed_stop, 2)
        logger.info(
            "[Robinhood] Trailing stop for %s: current=%.2f, trail=%s %s → stop=%.2f",
            clean_ticker,
            current_price,
            trail_amount,
            trail_type,
            computed_stop,
        )

        payload: dict = {
            "account": f"{_BASE_URL}/accounts/{self.account_number}/",
            "instrument": f"{_BASE_URL}/instruments/{instrument_id}/",
            "symbol": clean_ticker,
            "type": "stop_loss",
            "side": side.lower(),
            "quantity": str(qty),
            "time_in_force": "gfd",
            "trigger": "stop",
            "stop_price": str(computed_stop),
        }

        result = await self._post_order(payload)
        # Append the limitation notice to the message
        result.message = (
            "Trailing stop placed as stop-market (Robinhood does not support "
            "native trailing stops)"
        )
        return result

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
        Robinhood does NOT support bracket orders.

        Only the entry leg is placed. The stop-loss and take-profit legs are
        NOT submitted. Users must manage those orders separately.
        """
        clean_ticker = ticker.replace(".US", "").upper()

        # Place only the entry leg
        entry_result = await self.place_order(
            ticker=clean_ticker,
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
            message="Bracket order: entry placed only (Robinhood does not support bracket orders)",
        )

    async def get_order_status(self, broker_order_id: str) -> OrderResult:
        try:
            async with httpx.AsyncClient(timeout=10) as client:
                resp = await client.get(
                    f"{_BASE_URL}/orders/{broker_order_id}/",
                    headers=self._headers(),
                )
                data = resp.json()
                if resp.status_code == 200:
                    # Derive filled price from executions list if available
                    executions = data.get("executions", [])
                    filled_price = 0.0
                    if executions:
                        try:
                            filled_price = float(executions[-1].get("price", 0) or 0)
                        except (ValueError, TypeError):
                            filled_price = 0.0

                    return OrderResult(
                        broker_order_id=broker_order_id,
                        status=self._map_rh_status(data.get("state", "")),
                        filled_qty=float(data.get("cumulative_quantity") or 0),
                        filled_price=filled_price,
                    )
                return OrderResult(
                    broker_order_id=broker_order_id,
                    status="UNKNOWN",
                    message=data.get("detail", ""),
                )
        except Exception as exc:
            logger.error("[Robinhood] get_order_status failed: %s", exc)
            return OrderResult(
                broker_order_id=broker_order_id, status="UNKNOWN", message=str(exc)
            )

    async def cancel_order(self, broker_order_id: str) -> bool:
        try:
            async with httpx.AsyncClient(timeout=10) as client:
                resp = await client.post(
                    f"{_BASE_URL}/orders/{broker_order_id}/cancel/",
                    headers=self._headers(),
                )
                return resp.status_code in (200, 204)
        except Exception as exc:
            logger.error("[Robinhood] cancel_order failed: %s", exc)
            return False

    async def get_positions(self) -> list[Position]:
        try:
            async with httpx.AsyncClient(timeout=10) as client:
                resp = await client.get(
                    f"{_BASE_URL}/positions/",
                    headers=self._headers(),
                    params={"nonzero": "true"},
                )
                resp.raise_for_status()
                results = resp.json().get("results", [])

                positions: list[Position] = []
                for p in results:
                    # Resolve the instrument URL to get the ticker symbol
                    ticker = "UNKNOWN"
                    instrument_url = p.get("instrument", "")
                    if instrument_url:
                        try:
                            instr_resp = await client.get(
                                instrument_url,
                                headers=self._headers(),
                            )
                            if instr_resp.status_code == 200:
                                ticker = instr_resp.json().get("symbol", "UNKNOWN")
                        except Exception as exc:
                            logger.warning(
                                "[Robinhood] Could not resolve instrument URL %s: %s",
                                instrument_url,
                                exc,
                            )

                    positions.append(
                        Position(
                            ticker=ticker,
                            qty=float(p.get("quantity") or 0),
                            avg_price=float(p.get("average_buy_price") or 0),
                            current_price=None,   # Not returned in positions endpoint
                            unrealized_pnl=None,  # Not returned in positions endpoint
                        )
                    )
                return positions
        except Exception as exc:
            logger.error("[Robinhood] get_positions failed: %s", exc)
            return []

    async def get_account_balance(self) -> AccountBalance:
        try:
            async with httpx.AsyncClient(timeout=10) as client:
                resp = await client.get(
                    f"{_BASE_URL}/accounts/{self.account_number}/",
                    headers=self._headers(),
                )
                resp.raise_for_status()
                data = resp.json()
                return AccountBalance(
                    cash=float(data.get("portfolio_cash") or 0),
                    portfolio_value=float(data.get("portfolio_value") or 0),
                    buying_power=float(data.get("buying_power") or 0),
                    currency="USD",
                )
        except Exception as exc:
            logger.error("[Robinhood] get_account_balance failed: %s", exc)
            return AccountBalance(cash=0, portfolio_value=0, buying_power=0, currency="USD")
