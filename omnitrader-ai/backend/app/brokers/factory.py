"""
brokers/factory.py
==================
Broker factory — returns the correct broker instance based on environment
variables and the target country.

Resolution order:
  India (IN):  ZerodhaKiteBroker → PaperBroker
  US (default): AlpacaBroker     → PaperBroker
"""
import logging
import os

from app.brokers.base import BrokerInterface
from app.brokers.paper import PaperBroker

logger = logging.getLogger(__name__)


def get_broker(country: str = "US") -> BrokerInterface:
    """
    Return the appropriate broker for the given country.

    Falls back silently to PaperBroker when credentials are missing or
    the real broker raises during initialisation.

    Args:
        country: "IN" for India (Zerodha), anything else for US (Alpaca).

    Returns:
        A concrete BrokerInterface instance.
    """
    if country == "IN":
        if os.getenv("ZERODHA_API_KEY") and os.getenv("ZERODHA_ACCESS_TOKEN"):
            try:
                from app.brokers.zerodha import ZerodhaKiteBroker
                broker = ZerodhaKiteBroker()
                logger.info("[BrokerFactory] Using ZerodhaKiteBroker for IN")
                return broker
            except Exception as exc:
                logger.warning(
                    "[BrokerFactory] Zerodha init failed, falling back to PaperBroker: %s", exc
                )
    else:  # US
        if os.getenv("ALPACA_API_KEY") and os.getenv("ALPACA_SECRET_KEY"):
            try:
                from app.brokers.alpaca import AlpacaBroker
                broker = AlpacaBroker()
                logger.info(
                    "[BrokerFactory] Using AlpacaBroker for US (base_url=%s)", broker.base_url
                )
                return broker
            except Exception as exc:
                logger.warning(
                    "[BrokerFactory] Alpaca init failed, falling back to PaperBroker: %s", exc
                )

    logger.info(
        "[BrokerFactory] Using PaperBroker for %s (no real broker credentials configured)",
        country,
    )
    return PaperBroker()
