"""
services/broker/base.py
=======================
Abstract base class and shared dataclasses for the broker abstraction layer.

This module defines the canonical data types used across all broker
integrations in ``app/services/broker/``.  It is intentionally separate from
``app/brokers/base.py`` (the older, lower-level interface) so that higher-
level services can depend on richer, typed structures without coupling to
any specific broker SDK.
"""
from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Optional
from enum import Enum


class OrderSide(str, Enum):
    BUY  = "BUY"
    SELL = "SELL"


class OrderType(str, Enum):
    MARKET     = "MARKET"
    LIMIT      = "LIMIT"
    STOP       = "STOP"
    STOP_LIMIT = "STOP_LIMIT"


class OrderStatus(str, Enum):
    PENDING   = "PENDING"
    OPEN      = "OPEN"
    FILLED    = "FILLED"
    CANCELLED = "CANCELLED"
    REJECTED  = "REJECTED"


@dataclass
class BrokerOrder:
    broker_order_id: str
    ticker:          str
    side:            OrderSide
    qty:             float
    order_type:      OrderType
    limit_price:     Optional[float]
    stop_price:      Optional[float]
    status:          OrderStatus
    filled_qty:      float
    avg_fill_price:  Optional[float]
    created_at:      str
    raw:             dict  # original broker response


@dataclass
class BrokerPosition:
    ticker:         str
    qty:            float
    avg_cost:       float
    current_price:  float
    unrealized_pnl: float
    market_value:   float


@dataclass
class BrokerAccount:
    account_id:      str
    cash:            float
    portfolio_value: float
    buying_power:    float
    currency:        str


class BaseBroker(ABC):
    """
    Abstract base class that all service-layer broker adapters must implement.

    Each method must be async.  Implementations should never raise unhandled
    exceptions — log the error and return a sensible default or re-raise with
    a clear, human-readable message.
    """

    @abstractmethod
    async def place_order(
        self,
        ticker:      str,
        side:        OrderSide,
        qty:         float,
        order_type:  OrderType,
        limit_price: Optional[float] = None,
        stop_price:  Optional[float] = None,
    ) -> BrokerOrder: ...

    @abstractmethod
    async def cancel_order(self, broker_order_id: str) -> bool: ...

    @abstractmethod
    async def get_order(self, broker_order_id: str) -> BrokerOrder: ...

    @abstractmethod
    async def get_positions(self) -> list[BrokerPosition]: ...

    @abstractmethod
    async def get_account(self) -> BrokerAccount: ...

    @abstractmethod
    async def is_connected(self) -> bool: ...
