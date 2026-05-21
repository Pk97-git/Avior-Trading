"""
services/broker/factory.py
===========================
BrokerFactory — returns the right service-layer broker instance based on
country and environment variables.

Resolution:
  country="US" → AlpacaBroker  (requires ALPACA_API_KEY + ALPACA_SECRET_KEY)
  country="IN" → ZerodhaBroker (requires KITE_API_KEY + KITE_ACCESS_TOKEN)

Returns ``None`` (never raises) when credentials are not configured so that
callers can handle the unconfigured case gracefully.

Usage::

    from app.services.broker.factory import get_broker, broker_status

    broker = get_broker("US")
    if broker:
        account = await broker.get_account()

Note: This factory is **separate** from ``app.brokers.factory`` which serves
the lower-level order-manager pipeline.  The service-layer factory is
intended for the ``broker_connect`` API router and any service that needs
richer ``BrokerOrder`` / ``BrokerPosition`` / ``BrokerAccount`` types.
"""
import logging
import os
from typing import Optional

from app.services.broker.base import BaseBroker

logger = logging.getLogger(__name__)


def get_broker(country: str = "US") -> Optional[BaseBroker]:
    """
    Return a configured service-layer broker for the given country, or
    ``None`` if credentials are not set.

    Args:
        country: ``"US"`` for Alpaca, ``"IN"`` for Zerodha.

    Returns:
        A ``BaseBroker`` instance ready for use, or ``None``.
    """
    country = country.upper()

    if country == "US":
        key    = os.getenv("ALPACA_API_KEY")
        secret = os.getenv("ALPACA_SECRET_KEY")
        if not key or not secret:
            logger.debug(
                "[ServiceBrokerFactory] ALPACA_API_KEY / ALPACA_SECRET_KEY not set — "
                "returning None for country=US"
            )
            return None
        from app.services.broker.alpaca_broker import AlpacaBroker
        paper = os.getenv("ALPACA_PAPER", "true").lower() == "true"
        logger.debug("[ServiceBrokerFactory] Returning AlpacaBroker (paper=%s)", paper)
        return AlpacaBroker(api_key=key, secret_key=secret, paper=paper)

    if country == "IN":
        key   = os.getenv("KITE_API_KEY")
        token = os.getenv("KITE_ACCESS_TOKEN")
        if not key or not token:
            logger.debug(
                "[ServiceBrokerFactory] KITE_API_KEY / KITE_ACCESS_TOKEN not set — "
                "returning None for country=IN"
            )
            return None
        from app.services.broker.zerodha_broker import ZerodhaBroker
        logger.debug("[ServiceBrokerFactory] Returning ZerodhaBroker")
        return ZerodhaBroker(api_key=key, access_token=token)

    logger.warning("[ServiceBrokerFactory] Unknown country=%r — returning None", country)
    return None


def broker_status() -> dict:
    """
    Return a summary of which brokers are configured (without testing
    live connectivity — that is done by the API router).

    Returns:
        Dict with ``"alpaca"`` and ``"zerodha"`` sub-dicts containing:
        - ``configured`` (bool): whether required env vars are present.
        - ``paper`` (bool, Alpaca only): whether paper-trading mode is active.
        - ``login_url`` (str or None, Zerodha only): Kite OAuth login URL.
    """
    alpaca_key     = os.getenv("ALPACA_API_KEY")
    kite_key       = os.getenv("KITE_API_KEY")
    kite_token     = os.getenv("KITE_ACCESS_TOKEN")

    return {
        "alpaca": {
            "configured": bool(alpaca_key and os.getenv("ALPACA_SECRET_KEY")),
            "paper":      os.getenv("ALPACA_PAPER", "true").lower() == "true",
        },
        "zerodha": {
            "configured": bool(kite_key and kite_token),
            "login_url": (
                f"https://kite.trade/connect/login?api_key={kite_key}&v=3"
                if kite_key
                else None
            ),
        },
    }
