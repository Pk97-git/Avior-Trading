"""
services/broker/zerodha_broker.py
===================================
Zerodha Kite Connect broker integration.

Env vars:
  KITE_API_KEY      — from Kite Connect app
  KITE_API_SECRET   — from Kite Connect app
  KITE_ACCESS_TOKEN — obtained after OAuth login (refresh daily)

OAuth flow (manual — user does this once per day):
  1. Redirect to: https://kite.trade/connect/login?api_key={api_key}&v=3
  2. User logs in → redirected to your redirect URL with ?request_token=xxx
  3. POST https://api.kite.trade/session/token with {api_key, request_token, checksum}
     where checksum = sha256(api_key + request_token + api_secret)
  4. Store access_token — valid for one trading day

IMPORTANT: Zerodha access tokens expire at the end of every trading day.
The token must be refreshed via the OAuth flow each morning before placing
any orders.  See ``generate_login_url()`` and ``generate_session()`` below.
"""
import hashlib
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

BASE_URL = "https://api.kite.trade"

# ---------------------------------------------------------------------------
# Status mapping
# ---------------------------------------------------------------------------

_STATUS_MAP: dict[str, OrderStatus] = {
    "COMPLETE":                  OrderStatus.FILLED,
    "CANCELLED":                 OrderStatus.CANCELLED,
    "REJECTED":                  OrderStatus.REJECTED,
    "OPEN":                      OrderStatus.OPEN,
    "PENDING":                   OrderStatus.PENDING,
    "AMO REQ RECEIVED":          OrderStatus.PENDING,
    "VALIDATION PENDING":        OrderStatus.PENDING,
    "PUT ORDER REQ RECEIVED":    OrderStatus.PENDING,
    "MODIFY VALIDATION PENDING": OrderStatus.PENDING,
    "MODIFY REQ RECEIVED":       OrderStatus.PENDING,
    "TRIGGER PENDING":           OrderStatus.PENDING,
}

_ORDER_TYPE_MAP: dict[OrderType, str] = {
    OrderType.MARKET:     "MARKET",
    OrderType.LIMIT:      "LIMIT",
    OrderType.STOP:       "SL-M",
    OrderType.STOP_LIMIT: "SL",
}


def _map_status(raw: str) -> OrderStatus:
    return _STATUS_MAP.get(raw.upper(), OrderStatus.PENDING)


def _exchange_and_symbol(ticker: str) -> tuple[str, str]:
    """
    Convert a ticker to (exchange, tradingsymbol).

    Rules:
      - Ticker ends with ``.NS`` → exchange="NSE", strip suffix.
      - Ticker ends with ``.BO`` → exchange="BSE", strip suffix.
      - Otherwise               → exchange="NSE", symbol unchanged.
    """
    t = ticker.upper()
    if t.endswith(".NS"):
        return "NSE", t[:-3]
    if t.endswith(".BO"):
        return "BSE", t[:-3]
    return "NSE", t


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


# ---------------------------------------------------------------------------
# Module-level OAuth helpers
# ---------------------------------------------------------------------------

def generate_login_url(api_key: str) -> str:
    """
    Return the Kite Connect login URL for the given API key.

    The user opens this URL in a browser, logs in, and is redirected to
    the configured redirect URL with ``?request_token=<token>`` appended.

    Args:
        api_key: Kite Connect API key.

    Returns:
        Full login URL string.
    """
    return f"https://kite.trade/connect/login?api_key={api_key}&v=3"


def generate_session(api_key: str, api_secret: str, request_token: str) -> str:
    """
    Exchange a Kite request_token for a session access_token.

    This is step 3 of the OAuth flow.  The returned access_token should be
    stored in ``KITE_ACCESS_TOKEN`` and is valid until the end of the trading
    day.

    Args:
        api_key:       Kite Connect API key.
        api_secret:    Kite Connect API secret.
        request_token: The one-time token from the OAuth redirect URL.

    Returns:
        The session ``access_token`` string.

    Raises:
        RuntimeError: If the Kite API rejects the token exchange.
    """
    checksum = hashlib.sha256(
        (api_key + request_token + api_secret).encode()
    ).hexdigest()

    import httpx as _httpx  # local import so callers without httpx still import the module
    with _httpx.Client(timeout=10) as client:
        resp = client.post(
            f"{BASE_URL}/session/token",
            data={
                "api_key":       api_key,
                "request_token": request_token,
                "checksum":      checksum,
            },
            headers={"X-Kite-Version": "3"},
        )
        data = resp.json()
        if resp.status_code == 200 and data.get("status") == "success":
            return data["data"]["access_token"]
        raise RuntimeError(
            f"Kite session exchange failed ({resp.status_code}): "
            f"{data.get('message', resp.text)}"
        )


# ---------------------------------------------------------------------------
# ZerodhaBroker
# ---------------------------------------------------------------------------

class ZerodhaBroker(BaseBroker):
    """
    Zerodha Kite Connect service-layer broker.

    Communicates with the Kite Connect REST API v3 using ``httpx``.
    Credentials are read from environment variables or supplied to
    ``__init__``.

    IMPORTANT: ``access_token`` expires daily.  Refresh it each morning using
    ``generate_login_url()`` + ``generate_session()`` and update the
    ``KITE_ACCESS_TOKEN`` environment variable (or your secrets store).

    Args:
        api_key:      Kite API key.  Defaults to ``KITE_API_KEY`` env var.
        access_token: Kite session token.  Defaults to ``KITE_ACCESS_TOKEN`` env var.
    """

    def __init__(
        self,
        api_key:      Optional[str] = None,
        access_token: Optional[str] = None,
    ) -> None:
        self.api_key      = api_key      or os.getenv("KITE_API_KEY", "")
        self.access_token = access_token or os.getenv("KITE_ACCESS_TOKEN", "")

        if not self.api_key or not self.access_token:
            raise ValueError(
                "ZerodhaBroker requires KITE_API_KEY and KITE_ACCESS_TOKEN "
                "(set as env vars or pass to __init__)"
            )

    # ── Helpers ────────────────────────────────────────────────────────────────

    def _headers(self) -> dict:
        return {
            "X-Kite-Version": "3",
            "Authorization":  f"token {self.api_key}:{self.access_token}",
        }

    def _order_from_raw(
        self,
        data:        dict,
        ticker:      str               = "",
        side:        Optional[OrderSide]  = None,
        qty:         float             = 0,
        order_type:  Optional[OrderType] = None,
        limit_price: Optional[float]   = None,
        stop_price:  Optional[float]   = None,
    ) -> BrokerOrder:
        raw_side = data.get("transaction_type", "")
        parsed_side = (
            OrderSide.BUY if raw_side.upper() == "BUY" else OrderSide.SELL
        ) if raw_side else (side or OrderSide.BUY)

        raw_otype = data.get("order_type", "")
        parsed_otype: OrderType
        if raw_otype:
            _otype_reverse = {
                "MARKET": OrderType.MARKET,
                "LIMIT":  OrderType.LIMIT,
                "SL-M":   OrderType.STOP,
                "SL":     OrderType.STOP_LIMIT,
            }
            parsed_otype = _otype_reverse.get(raw_otype.upper(), OrderType.MARKET)
        else:
            parsed_otype = order_type or OrderType.MARKET

        sym = data.get("tradingsymbol", "")
        exch = data.get("exchange", "NSE")
        full_ticker = f"{sym}.NS" if exch == "NSE" else (f"{sym}.BO" if exch == "BSE" else sym)

        return BrokerOrder(
            broker_order_id=str(data.get("order_id", "")),
            ticker=full_ticker or ticker,
            side=parsed_side,
            qty=float(data.get("quantity") or qty or 0),
            order_type=parsed_otype,
            limit_price=float(data["price"]) if data.get("price") else limit_price,
            stop_price=float(data["trigger_price"]) if data.get("trigger_price") else stop_price,
            status=_map_status(data.get("status", "")),
            filled_qty=float(data.get("filled_quantity") or 0),
            avg_fill_price=float(data["average_price"]) if data.get("average_price") else None,
            created_at=str(data.get("order_timestamp") or _now_iso()),
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
        exchange, symbol = _exchange_and_symbol(ticker)
        kite_order_type  = _ORDER_TYPE_MAP.get(order_type, "MARKET")

        payload: dict = {
            "exchange":         exchange,
            "tradingsymbol":    symbol,
            "transaction_type": side.value,
            "quantity":         int(qty),
            "product":          "CNC",     # delivery; use "MIS" for intraday
            "order_type":       kite_order_type,
            "validity":         "DAY",
            "price":            limit_price or 0,
            "trigger_price":    stop_price  or 0,
        }

        try:
            async with httpx.AsyncClient(timeout=10) as client:
                resp = await client.post(
                    f"{BASE_URL}/orders/regular",
                    headers=self._headers(),
                    data=payload,
                )
                data = resp.json()
                if resp.status_code == 200 and data.get("status") == "success":
                    order_id = str(data["data"]["order_id"])
                    return BrokerOrder(
                        broker_order_id=order_id,
                        ticker=ticker,
                        side=side,
                        qty=qty,
                        order_type=order_type,
                        limit_price=limit_price,
                        stop_price=stop_price,
                        status=OrderStatus.PENDING,
                        filled_qty=0,
                        avg_fill_price=None,
                        created_at=_now_iso(),
                        raw=data,
                    )
                logger.error("[ZerodhaBroker] place_order rejected %d: %s", resp.status_code, data)
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
            logger.error("[ZerodhaBroker] place_order error: %s", exc)
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
                    f"{BASE_URL}/orders/regular/{broker_order_id}",
                    headers=self._headers(),
                )
                data = resp.json()
                return resp.status_code == 200 and data.get("status") == "success"
        except Exception as exc:
            logger.error("[ZerodhaBroker] cancel_order error: %s", exc)
            return False

    async def get_order(self, broker_order_id: str) -> BrokerOrder:
        try:
            async with httpx.AsyncClient(timeout=10) as client:
                resp = await client.get(
                    f"{BASE_URL}/orders/{broker_order_id}",
                    headers=self._headers(),
                )
                data = resp.json()
                if resp.status_code == 200:
                    orders = data.get("data", [])
                    if orders:
                        # Last element is the most recent status update
                        return self._order_from_raw(orders[-1])
                logger.warning("[ZerodhaBroker] get_order %s → %d", broker_order_id, resp.status_code)
        except Exception as exc:
            logger.error("[ZerodhaBroker] get_order error: %s", exc)

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
        """
        Fetch portfolio holdings from Kite.

        Returns both the ``/portfolio/holdings`` (long-term delivery holdings)
        and the ``/portfolio/positions`` day positions, merged and de-duplicated
        by ticker.
        """
        positions: list[BrokerPosition] = []
        try:
            async with httpx.AsyncClient(timeout=10) as client:
                # Long-term delivery holdings
                resp = await client.get(
                    f"{BASE_URL}/portfolio/holdings",
                    headers=self._headers(),
                )
                data = resp.json()
                for h in data.get("data", []):
                    qty = float(h.get("quantity") or 0)
                    if qty <= 0:
                        continue
                    sym  = h.get("tradingsymbol", "")
                    exch = h.get("exchange", "NSE")
                    ticker = f"{sym}.NS" if exch == "NSE" else (f"{sym}.BO" if exch == "BSE" else sym)
                    avg_cost      = float(h.get("average_price") or 0)
                    current_price = float(h.get("last_price") or 0)
                    positions.append(BrokerPosition(
                        ticker=ticker,
                        qty=qty,
                        avg_cost=avg_cost,
                        current_price=current_price,
                        unrealized_pnl=float(h.get("pnl") or 0),
                        market_value=qty * current_price,
                    ))

                # Day / intraday net positions
                resp2 = await client.get(
                    f"{BASE_URL}/portfolio/positions",
                    headers=self._headers(),
                )
                data2 = resp2.json()
                net_positions = data2.get("data", {}).get("net", [])
                existing_tickers = {p.ticker for p in positions}
                for p in net_positions:
                    qty = float(p.get("quantity") or 0)
                    if qty <= 0:
                        continue
                    sym  = p.get("tradingsymbol", "")
                    exch = p.get("exchange", "NSE")
                    ticker = f"{sym}.NS" if exch == "NSE" else (f"{sym}.BO" if exch == "BSE" else sym)
                    if ticker in existing_tickers:
                        continue
                    avg_cost      = float(p.get("average_price") or 0)
                    current_price = float(p.get("last_price") or 0)
                    positions.append(BrokerPosition(
                        ticker=ticker,
                        qty=qty,
                        avg_cost=avg_cost,
                        current_price=current_price,
                        unrealized_pnl=float(p.get("pnl") or 0),
                        market_value=qty * current_price,
                    ))

        except Exception as exc:
            logger.error("[ZerodhaBroker] get_positions error: %s", exc)

        return positions

    async def get_account(self) -> BrokerAccount:
        """
        Fetch account margin data from Kite.

        Maps equity margins to the ``BrokerAccount`` structure.
        ``cash`` = available cash, ``buying_power`` = intraday payin,
        ``portfolio_value`` = net equity.
        """
        try:
            async with httpx.AsyncClient(timeout=10) as client:
                resp = await client.get(
                    f"{BASE_URL}/user/margins",
                    headers=self._headers(),
                )
                resp.raise_for_status()
                equity    = resp.json().get("data", {}).get("equity", {})
                net       = equity.get("net", {})
                available = net.get("available", {})
                return BrokerAccount(
                    account_id=self.api_key,
                    cash=float(available.get("cash") or 0),
                    portfolio_value=float(net.get("net") or 0),
                    buying_power=float(available.get("intraday_payin") or 0),
                    currency="INR",
                )
        except Exception as exc:
            logger.error("[ZerodhaBroker] get_account error: %s", exc)
            return BrokerAccount(
                account_id=self.api_key,
                cash=0,
                portfolio_value=0,
                buying_power=0,
                currency="INR",
            )

    async def is_connected(self) -> bool:
        """
        Check connectivity by fetching the user profile.

        Returns ``True`` if Kite responds with status 200, ``False`` otherwise.
        """
        try:
            async with httpx.AsyncClient(timeout=10) as client:
                resp = await client.get(
                    f"{BASE_URL}/user/profile",
                    headers=self._headers(),
                )
                return resp.status_code == 200
        except Exception as exc:
            logger.warning("[ZerodhaBroker] is_connected check failed: %s", exc)
            return False
