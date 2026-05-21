"""
brokers/ibkr.py
===============
Interactive Brokers broker connector via Client Portal Gateway REST API.

The IBKR Client Portal Gateway is a local process that the user runs
separately. This connector communicates with it via HTTP on localhost.

Required env vars:
    IBKR_GATEWAY_URL  — URL of the running IBKR Client Portal Gateway
                        (default: http://localhost:5000)
    IBKR_ACCOUNT_ID   — IB account ID (optional, auto-detected if not set)

Note: The gateway typically uses a self-signed SSL certificate; this
connector uses verify=False for all requests.
"""
import logging
import os
import uuid
from typing import Optional

import httpx

from app.brokers.base import BrokerInterface, OrderResult, Position, AccountBalance, BracketOrderResult

logger = logging.getLogger(__name__)


class IBKRBroker(BrokerInterface):
    """
    Interactive Brokers broker via Client Portal Gateway REST API.
    Requires: IBKR_GATEWAY_URL env var (and optionally IBKR_ACCOUNT_ID).
    The gateway must be running and authenticated before using this broker.
    """

    name = "IBKR"

    def __init__(self) -> None:
        self.gateway_url = os.getenv("IBKR_GATEWAY_URL", "http://localhost:5000").rstrip("/")
        self._account_id: Optional[str] = os.getenv("IBKR_ACCOUNT_ID")
        self._conid_cache: dict[str, str] = {}

    # ── Internal helpers ───────────────────────────────────────────────────────

    def _headers(self) -> dict:
        return {"Content-Type": "application/json"}

    def _url(self, path: str) -> str:
        """Build a full URL from a path relative to /v1/api."""
        return f"{self.gateway_url}/v1/api{path}"

    async def _get_account_id(self) -> str:
        """Auto-detect IBKR account ID from the gateway if not set."""
        if self._account_id:
            return self._account_id

        try:
            async with httpx.AsyncClient(timeout=10, verify=False) as client:
                resp = await client.get(
                    self._url("/iserver/accounts"),
                    headers=self._headers(),
                )
                resp.raise_for_status()
                data = resp.json()
                accounts = data.get("accounts", [])
                if accounts:
                    self._account_id = accounts[0]
                    logger.info("[IBKR] Auto-detected account ID: %s", self._account_id)
                    return self._account_id
                raise ValueError("No IBKR accounts found from gateway")
        except Exception as exc:
            logger.error("[IBKR] _get_account_id failed: %s", exc)
            raise

    async def _get_conid(self, ticker: str) -> Optional[str]:
        """
        Look up the IBKR contract ID (conid) for a ticker symbol.
        Results are cached in self._conid_cache to avoid repeated lookups.
        """
        clean_ticker = ticker.replace(".US", "").upper()

        if clean_ticker in self._conid_cache:
            return self._conid_cache[clean_ticker]

        try:
            async with httpx.AsyncClient(timeout=10, verify=False) as client:
                resp = await client.get(
                    self._url(f"/iserver/secdef/search?symbol={clean_ticker}"),
                    headers=self._headers(),
                )
                resp.raise_for_status()
                results = resp.json()
                if results and isinstance(results, list):
                    conid = str(results[0]["conid"])
                    self._conid_cache[clean_ticker] = conid
                    logger.debug("[IBKR] conid for %s: %s", clean_ticker, conid)
                    return conid
                logger.warning("[IBKR] No conid found for %s", clean_ticker)
                return None
        except Exception as exc:
            logger.error("[IBKR] _get_conid failed for %s: %s", ticker, exc)
            return None

    async def _place_raw_order(
        self, account_id: str, order: dict
    ) -> dict:
        """
        POST a single order (wrapped in {"orders": [order]}) to the gateway.
        Handles the confirmation flow if the gateway requires it.
        Returns the first element of the response list.
        """
        async with httpx.AsyncClient(timeout=15, verify=False) as client:
            resp = await client.post(
                self._url(f"/iserver/account/{account_id}/orders"),
                headers=self._headers(),
                json={"orders": [order]},
            )
            resp.raise_for_status()
            data = resp.json()

            # data is a list; grab first item
            if not data or not isinstance(data, list):
                raise ValueError(f"Unexpected IBKR order response: {data}")

            result = data[0]

            # If gateway returns a confirmation challenge, reply with confirmed=true
            if "message" in result and "id" in result:
                confirm_id = result["id"]
                logger.info("[IBKR] Confirming order, id=%s", confirm_id)
                confirm_resp = await client.post(
                    self._url(f"/iserver/reply/{confirm_id}"),
                    headers=self._headers(),
                    json={"confirmed": True},
                )
                confirm_resp.raise_for_status()
                confirm_data = confirm_resp.json()
                if confirm_data and isinstance(confirm_data, list):
                    result = confirm_data[0]

            return result

    @staticmethod
    def _map_ibkr_status(status: str) -> str:
        mapping = {
            "filled":        "FILLED",
            "cancelled":     "CANCELLED",
            "inactive":      "CANCELLED",
            "submitted":     "PENDING",
            "presubmitted":  "PENDING",
            "pendingsubmit": "PENDING",
            "pendingcancel": "PENDING",
            "apipending":    "PENDING",
            "unknown":       "UNKNOWN",
        }
        return mapping.get(status.lower(), "PENDING")

    # ── BrokerInterface implementation ────────────────────────────────────────

    async def place_order(
        self,
        ticker: str,
        side: str,
        qty: float,
        order_type: str = "MARKET",
        limit_price: Optional[float] = None,
    ) -> OrderResult:
        try:
            account_id = await self._get_account_id()
            conid = await self._get_conid(ticker)
            if conid is None:
                return OrderResult(
                    broker_order_id="",
                    status="REJECTED",
                    message=f"Could not resolve conid for ticker: {ticker}",
                )

            order: dict = {
                "conid": conid,
                "orderType": "MKT" if order_type.upper() == "MARKET" else "LMT",
                "side": side.upper(),
                "quantity": qty,
                "tif": "DAY",
            }

            if order_type.upper() == "LIMIT" and limit_price is not None:
                order["price"] = limit_price

            result = await self._place_raw_order(account_id, order)

            order_id = str(result.get("order_id", result.get("orderId", "")))
            order_status = result.get("order_status", result.get("orderStatus", "Submitted"))

            return OrderResult(
                broker_order_id=order_id,
                status=self._map_ibkr_status(order_status),
                message="Order placed on IBKR",
            )
        except Exception as exc:
            logger.error("[IBKR] place_order failed: %s", exc)
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
        Place a stop order on IBKR.
        If limit_price is None → STP (stop-market).
        If limit_price is set → STP LMT (stop-limit).
        """
        try:
            account_id = await self._get_account_id()
            conid = await self._get_conid(ticker)
            if conid is None:
                return OrderResult(
                    broker_order_id="",
                    status="REJECTED",
                    message=f"Could not resolve conid for ticker: {ticker}",
                )

            order: dict = {
                "conid": conid,
                "side": side.upper(),
                "quantity": qty,
                "tif": "DAY",
                "auxPrice": stop_price,
            }

            if limit_price is None:
                order["orderType"] = "STP"
            else:
                order["orderType"] = "STP LMT"
                order["price"] = limit_price

            result = await self._place_raw_order(account_id, order)

            order_id = str(result.get("order_id", result.get("orderId", "")))
            order_status = result.get("order_status", result.get("orderStatus", "Submitted"))

            return OrderResult(
                broker_order_id=order_id,
                status=self._map_ibkr_status(order_status),
                message="Stop order placed on IBKR",
            )
        except Exception as exc:
            logger.error("[IBKR] place_stop_order failed: %s", exc)
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
        Place a trailing stop order on IBKR.
        trail_type: "ABSOLUTE" (dollar amount) or "PERCENTAGE" (percent).
        """
        try:
            account_id = await self._get_account_id()
            conid = await self._get_conid(ticker)
            if conid is None:
                return OrderResult(
                    broker_order_id="",
                    status="REJECTED",
                    message=f"Could not resolve conid for ticker: {ticker}",
                )

            order: dict = {
                "conid": conid,
                "orderType": "TRAIL",
                "side": side.upper(),
                "quantity": qty,
                "tif": "DAY",
            }

            if trail_type.upper() == "ABSOLUTE":
                order["auxPrice"] = trail_amount
                order["trailingType"] = "amt"
            else:  # PERCENTAGE
                order["trailingAmt"] = trail_amount
                order["trailingType"] = "pct"

            result = await self._place_raw_order(account_id, order)

            order_id = str(result.get("order_id", result.get("orderId", "")))
            order_status = result.get("order_status", result.get("orderStatus", "Submitted"))

            return OrderResult(
                broker_order_id=order_id,
                status=self._map_ibkr_status(order_status),
                message="Trailing stop order placed on IBKR",
            )
        except Exception as exc:
            logger.error("[IBKR] place_trailing_stop_order failed: %s", exc)
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
        Place a bracket order on IBKR using OCA (One-Cancels-All) group.
        Three separate orders are placed with the same ocaGroup UUID:
          1. Entry order (MARKET or LIMIT)
          2. Stop loss (STP) with OCA
          3. Take profit (LMT) with OCA
        """
        try:
            account_id = await self._get_account_id()
            conid = await self._get_conid(ticker)
            if conid is None:
                return BracketOrderResult(
                    parent_order_id="",
                    stop_leg_id="",
                    target_leg_id="",
                    status="REJECTED",
                    message=f"Could not resolve conid for ticker: {ticker}",
                )

            oca_group = str(uuid.uuid4())
            # Opposite side for stop loss and take profit legs
            exit_side = "SELL" if side.upper() == "BUY" else "BUY"

            # Entry order
            entry_order: dict = {
                "conid": conid,
                "orderType": "MKT" if entry_type.upper() == "MARKET" else "LMT",
                "side": side.upper(),
                "quantity": qty,
                "tif": "DAY",
            }
            if entry_type.upper() == "LIMIT" and entry_price is not None:
                entry_order["price"] = entry_price

            # Stop loss leg
            stop_order: dict = {
                "conid": conid,
                "orderType": "STP",
                "side": exit_side,
                "quantity": qty,
                "tif": "DAY",
                "auxPrice": stop_price,
                "ocaGroup": oca_group,
                "ocaType": 1,  # Cancel all remaining on fill
            }

            # Take profit leg
            target_order: dict = {
                "conid": conid,
                "orderType": "LMT",
                "side": exit_side,
                "quantity": qty,
                "tif": "DAY",
                "price": target_price,
                "ocaGroup": oca_group,
                "ocaType": 1,
            }

            # Place entry order first
            entry_result = await self._place_raw_order(account_id, entry_order)
            parent_order_id = str(
                entry_result.get("order_id", entry_result.get("orderId", ""))
            )

            # Place stop loss leg
            stop_result = await self._place_raw_order(account_id, stop_order)
            stop_leg_id = str(
                stop_result.get("order_id", stop_result.get("orderId", ""))
            )

            # Place take profit leg
            target_result = await self._place_raw_order(account_id, target_order)
            target_leg_id = str(
                target_result.get("order_id", target_result.get("orderId", ""))
            )

            entry_status = entry_result.get(
                "order_status", entry_result.get("orderStatus", "Submitted")
            )

            return BracketOrderResult(
                parent_order_id=parent_order_id,
                stop_leg_id=stop_leg_id,
                target_leg_id=target_leg_id,
                status=self._map_ibkr_status(entry_status),
                message=f"Bracket order placed on IBKR (OCA group: {oca_group})",
            )
        except Exception as exc:
            logger.error("[IBKR] place_bracket_order failed: %s", exc)
            return BracketOrderResult(
                parent_order_id="",
                stop_leg_id="",
                target_leg_id="",
                status="REJECTED",
                message=str(exc),
            )

    async def get_order_status(self, broker_order_id: str) -> OrderResult:
        try:
            async with httpx.AsyncClient(timeout=10, verify=False) as client:
                resp = await client.get(
                    self._url(f"/iserver/account/order/status/{broker_order_id}"),
                    headers=self._headers(),
                )
                resp.raise_for_status()
                data = resp.json()
                raw_status = data.get("status", "Unknown")
                return OrderResult(
                    broker_order_id=broker_order_id,
                    status=self._map_ibkr_status(raw_status),
                    filled_qty=float(data.get("filled", 0) or 0),
                    filled_price=float(data.get("avgPrice", 0) or 0),
                )
        except Exception as exc:
            logger.error("[IBKR] get_order_status failed: %s", exc)
            return OrderResult(
                broker_order_id=broker_order_id, status="UNKNOWN", message=str(exc)
            )

    async def cancel_order(self, broker_order_id: str) -> bool:
        try:
            account_id = await self._get_account_id()
            async with httpx.AsyncClient(timeout=10, verify=False) as client:
                resp = await client.delete(
                    self._url(f"/iserver/account/{account_id}/order/{broker_order_id}"),
                    headers=self._headers(),
                )
                return resp.status_code in (200, 204)
        except Exception as exc:
            logger.error("[IBKR] cancel_order failed: %s", exc)
            return False

    async def get_positions(self) -> list[Position]:
        try:
            account_id = await self._get_account_id()
            async with httpx.AsyncClient(timeout=10, verify=False) as client:
                resp = await client.get(
                    self._url(f"/portfolio/{account_id}/positions/0"),
                    headers=self._headers(),
                )
                resp.raise_for_status()
                return [
                    Position(
                        ticker=p.get("contractDesc", "UNKNOWN"),
                        qty=float(p.get("position", 0) or 0),
                        avg_price=float(p.get("avgCost", 0) or 0),
                        current_price=float(p.get("mktPrice", 0) or 0),
                        unrealized_pnl=float(p.get("unrealizedPnl", 0) or 0),
                    )
                    for p in resp.json()
                ]
        except Exception as exc:
            logger.error("[IBKR] get_positions failed: %s", exc)
            return []

    async def get_account_balance(self) -> AccountBalance:
        try:
            account_id = await self._get_account_id()
            async with httpx.AsyncClient(timeout=10, verify=False) as client:
                resp = await client.get(
                    self._url(f"/portfolio/{account_id}/summary"),
                    headers=self._headers(),
                )
                resp.raise_for_status()
                data = resp.json()
                return AccountBalance(
                    cash=float(
                        (data.get("totalcashvalue") or {}).get("amount", 0) or 0
                    ),
                    portfolio_value=float(
                        (data.get("netliquidation") or {}).get("amount", 0) or 0
                    ),
                    buying_power=float(
                        (data.get("buyingpower") or {}).get("amount", 0) or 0
                    ),
                    currency="USD",
                )
        except Exception as exc:
            logger.error("[IBKR] get_account_balance failed: %s", exc)
            return AccountBalance(cash=0, portfolio_value=0, buying_power=0, currency="USD")
