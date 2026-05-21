"""
services/broker
===============
Service-layer broker abstraction for OmniTrader AI.

Public API::

    from app.services.broker import get_broker, broker_status
    from app.services.broker.base import (
        BaseBroker, BrokerOrder, BrokerPosition, BrokerAccount,
        OrderSide, OrderType, OrderStatus,
    )

Supported brokers
-----------------
- Alpaca Markets (US equities) — ``AlpacaBroker``
- Zerodha Kite Connect (Indian equities) — ``ZerodhaBroker``
"""
from app.services.broker.factory import get_broker, broker_status

__all__ = ["get_broker", "broker_status"]
