"""
brokers/base.py
===============
Abstract base class and shared dataclasses for all broker connectors.
"""
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Optional


@dataclass
class OrderResult:
    broker_order_id: str
    status: str          # PENDING / FILLED / REJECTED / CANCELLED / UNKNOWN / NOT_FOUND
    filled_qty: float = 0.0
    filled_price: Optional[float] = None
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
