"""
brokers/factory.py
==================
Broker factory — returns the correct broker instance based on environment
variables and the target country/market.

Resolution order
----------------
India (IN):   ZerodhaKiteBroker → INDmoneyBroker → UpstoxBroker → Angel One → PaperBroker
US (default): AlpacaBroker      → IBKRBroker      → RobinhoodBroker → PaperBroker

Priority override
-----------------
Set PREFERRED_BROKER to one of:
    ZERODHA | INDMONEY | UPSTOX | ANGEL | ALPACA | IBKR | ROBINHOOD | PAPER
When set, the factory skips priority scanning and tries that broker directly,
still falling back to PaperBroker on failure.

Convenience helper
------------------
get_broker_for_ticker(ticker) automatically infers country from the ticker
suffix (.NS / .BO → IN, everything else → US) and delegates to get_broker().
"""
import logging
import os

from app.brokers.base import BrokerInterface
from app.brokers.paper import PaperBroker

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Internal broker constructors (each returns a BrokerInterface or raises)
# ---------------------------------------------------------------------------

def _try_zerodha() -> BrokerInterface:
    if not (os.getenv("ZERODHA_API_KEY") and os.getenv("ZERODHA_ACCESS_TOKEN")):
        raise EnvironmentError("ZERODHA_API_KEY / ZERODHA_ACCESS_TOKEN not set")
    from app.brokers.zerodha import ZerodhaKiteBroker
    return ZerodhaKiteBroker()


def _try_indmoney() -> BrokerInterface:
    if not (os.getenv("INDMONEY_API_KEY") and os.getenv("INDMONEY_ACCESS_TOKEN")):
        raise EnvironmentError("INDMONEY_API_KEY / INDMONEY_ACCESS_TOKEN not set")
    from app.brokers.indmoney import INDmoneyBroker
    return INDmoneyBroker()


def _try_upstox() -> BrokerInterface:
    if not (os.getenv("UPSTOX_API_KEY") and os.getenv("UPSTOX_ACCESS_TOKEN")):
        raise EnvironmentError("UPSTOX_API_KEY / UPSTOX_ACCESS_TOKEN not set")
    from app.brokers.upstox import UpstoxBroker
    return UpstoxBroker()


def _try_angel() -> BrokerInterface:
    if not (
        os.getenv("ANGEL_API_KEY")
        and os.getenv("ANGEL_CLIENT_ID")
        and os.getenv("ANGEL_JWT_TOKEN")
    ):
        raise EnvironmentError(
            "ANGEL_API_KEY / ANGEL_CLIENT_ID / ANGEL_JWT_TOKEN not set"
        )
    # Angel One broker module — may be added by another agent simultaneously
    from app.brokers.angel import AngelOneBroker  # type: ignore[import]
    return AngelOneBroker()


def _try_alpaca() -> BrokerInterface:
    if not (os.getenv("ALPACA_API_KEY") and os.getenv("ALPACA_SECRET_KEY")):
        raise EnvironmentError("ALPACA_API_KEY / ALPACA_SECRET_KEY not set")
    from app.brokers.alpaca import AlpacaBroker
    return AlpacaBroker()


def _try_ibkr() -> BrokerInterface:
    # IBKR is usable as long as the gateway URL is configured; the gateway
    # handles authentication internally, so no API key is required here.
    if not os.getenv("IBKR_GATEWAY_URL"):
        raise EnvironmentError("IBKR_GATEWAY_URL not set")
    from app.brokers.ibkr import IBKRBroker
    return IBKRBroker()


def _try_robinhood() -> BrokerInterface:
    if not (
        os.getenv("ROBINHOOD_ACCESS_TOKEN")
        and os.getenv("ROBINHOOD_ACCOUNT_NUMBER")
    ):
        raise EnvironmentError(
            "ROBINHOOD_ACCESS_TOKEN / ROBINHOOD_ACCOUNT_NUMBER not set"
        )
    from app.brokers.robinhood import RobinhoodBroker
    return RobinhoodBroker()


# ---------------------------------------------------------------------------
# Priority chains per country
# ---------------------------------------------------------------------------

_IN_CHAIN = [
    ("ZerodhaKiteBroker", _try_zerodha),
    ("INDmoneyBroker",    _try_indmoney),
    ("UpstoxBroker",      _try_upstox),
    ("AngelOneBroker",    _try_angel),
]

_US_CHAIN = [
    ("AlpacaBroker",    _try_alpaca),
    ("IBKRBroker",      _try_ibkr),
    ("RobinhoodBroker", _try_robinhood),
]

# Map PREFERRED_BROKER value → constructor
_BROKER_MAP: dict[str, tuple[str, callable]] = {
    "ZERODHA":   ("ZerodhaKiteBroker", _try_zerodha),
    "INDMONEY":  ("INDmoneyBroker",    _try_indmoney),
    "UPSTOX":    ("UpstoxBroker",      _try_upstox),
    "ANGEL":     ("AngelOneBroker",    _try_angel),
    "ALPACA":    ("AlpacaBroker",      _try_alpaca),
    "IBKR":      ("IBKRBroker",        _try_ibkr),
    "ROBINHOOD": ("RobinhoodBroker",   _try_robinhood),
    "PAPER":     ("PaperBroker",       PaperBroker),
}


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def get_broker(country: str = "US") -> BrokerInterface:
    """
    Return the appropriate broker for the given country.

    Falls back silently to PaperBroker when credentials are missing or the
    real broker raises during initialisation.

    Args:
        country: "IN" for India, anything else for US markets.

    Returns:
        A concrete BrokerInterface instance (never None).
    """
    # ── PREFERRED_BROKER override ──────────────────────────────────────────
    preferred = os.getenv("PREFERRED_BROKER", "").strip().upper()
    if preferred and preferred != "PAPER":
        entry = _BROKER_MAP.get(preferred)
        if entry is None:
            logger.warning(
                "[BrokerFactory] Unknown PREFERRED_BROKER=%r — ignoring override",
                preferred,
            )
        else:
            class_name, constructor = entry
            try:
                broker = constructor()
                logger.info(
                    "[BrokerFactory] PREFERRED_BROKER=%s → using %s",
                    preferred,
                    class_name,
                )
                return broker
            except Exception as exc:
                logger.warning(
                    "[BrokerFactory] PREFERRED_BROKER=%s (%s) init failed, "
                    "falling back to priority chain: %s",
                    preferred,
                    class_name,
                    exc,
                )

    # ── Priority chain ─────────────────────────────────────────────────────
    chain = _IN_CHAIN if country == "IN" else _US_CHAIN

    for class_name, constructor in chain:
        try:
            broker = constructor()
            logger.info(
                "[BrokerFactory] Using %s for %s", class_name, country
            )
            return broker
        except EnvironmentError:
            # Expected when credentials are not configured — skip silently
            logger.debug(
                "[BrokerFactory] %s skipped (credentials not configured)", class_name
            )
        except Exception as exc:
            logger.warning(
                "[BrokerFactory] %s init failed: %s", class_name, exc
            )

    # ── Final fallback ─────────────────────────────────────────────────────
    logger.info(
        "[BrokerFactory] No real broker available for %s — using PaperBroker",
        country,
    )
    return PaperBroker()


def get_broker_for_ticker(ticker: str) -> BrokerInterface:
    """
    Convenience wrapper that infers country from the ticker suffix and
    delegates to get_broker().

    Rules:
        - Ticker ends in .NS or .BO → country="IN" (NSE / BSE)
        - Everything else           → country="US"

    Args:
        ticker: Instrument symbol, e.g. "RELIANCE.NS", "AAPL", "MSFT.US".

    Returns:
        A concrete BrokerInterface instance.
    """
    upper = ticker.upper()
    if upper.endswith(".NS") or upper.endswith(".BO"):
        country = "IN"
    else:
        country = "US"

    logger.debug(
        "[BrokerFactory] get_broker_for_ticker(%s) → country=%s", ticker, country
    )
    return get_broker(country)
