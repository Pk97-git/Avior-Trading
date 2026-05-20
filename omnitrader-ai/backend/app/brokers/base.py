"""
brokers/base.py
===============
Abstract base class and shared dataclasses for all broker connectors.
"""
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import List, Optional


@dataclass
class OrderResult:
    broker_order_id: str
    status: str          # PENDING / FILLED / REJECTED / CANCELLED / UNKNOWN / NOT_FOUND
    filled_qty: float = 0.0
    filled_price: Optional[float] = None
    message: str = ""


@dataclass
class BracketOrderResult:
    parent_order_id: str
    stop_leg_id: str
    target_leg_id: str
    status: str
    message: str = ""


@dataclass
class Position:
    ticker: str
    qty: float
    avg_price: float
    current_price: Optional[float] = None
    unrealized_pnl: Optional[float] = None


@dataclass
class AccountBalance:
    cash: float
    portfolio_value: float
    buying_power: float
    currency: str = "USD"


class BrokerInterface(ABC):
    name: str = "BASE"

    @abstractmethod
    async def place_order(
        self,
        ticker: str,
        side: str,
        qty: float,
        order_type: str = "MARKET",
        limit_price: Optional[float] = None,
    ) -> OrderResult: ...

    @abstractmethod
    async def place_stop_order(
        self,
        ticker: str,
        side: str,
        qty: float,
        stop_price: float,
        limit_price: Optional[float] = None,
    ) -> OrderResult:
        """
        Place a stop order.
        If limit_price is None → stop-market (triggers at stop_price, fills at market).
        If limit_price is set → stop-limit (triggers at stop_price, fills at or better than limit_price).
        """
        ...

    @abstractmethod
    async def place_trailing_stop_order(
        self,
        ticker: str,
        side: str,
        qty: float,
        trail_amount: float,
        trail_type: str = "ABSOLUTE",
    ) -> OrderResult:
        """
        Place a trailing stop order.
        trail_type: "ABSOLUTE" (dollar/rupee amount) or "PERCENTAGE" (percent of price).
        side is typically "SELL" for long positions, "BUY" for short.
        """
        ...

    @abstractmethod
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
        Place a bracket order (entry + stop loss + take profit as one atomic order).
        entry_type: "MARKET" or "LIMIT"
        entry_price: required if entry_type == "LIMIT"
        stop_price: stop loss trigger price
        target_price: take profit limit price
        """
        ...

    @abstractmethod
    async def get_order_status(self, broker_order_id: str) -> OrderResult: ...

    @abstractmethod
    async def cancel_order(self, broker_order_id: str) -> bool: ...

    @abstractmethod
    async def get_positions(self) -> list[Position]: ...

    @abstractmethod
    async def get_account_balance(self) -> AccountBalance: ...

    def is_market_open(self, country: str = "US") -> bool:
        """Check if the relevant market is currently open based on country."""
        from datetime import datetime, timezone, time as dtime
        import zoneinfo

        now_utc = datetime.now(timezone.utc)
        weekday = now_utc.weekday()
        if weekday >= 5:  # Saturday / Sunday
            return False

        if country == "IN":
            ist = zoneinfo.ZoneInfo("Asia/Kolkata")
            now_ist = now_utc.astimezone(ist)
            return dtime(9, 15) <= now_ist.time() <= dtime(15, 30)
        else:  # US (default)
            et = zoneinfo.ZoneInfo("America/New_York")
            now_et = now_utc.astimezone(et)
            return dtime(9, 30) <= now_et.time() <= dtime(16, 0)
