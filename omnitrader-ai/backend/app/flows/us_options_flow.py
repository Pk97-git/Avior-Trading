"""
flows/us_options_flow.py
=========================
US equity options chain snapshot flows.

Daily after close (21:30 UTC) for HIGH-tier US equities.
Weekly for MEDIUM-tier equities.
"""
import logging
from prefect import flow, task

from app.ingestion.core.us_options import UsOptionsService

logger = logging.getLogger(__name__)

HIGH_US_OPTIONS_TICKERS = [
    "AAPL", "MSFT", "NVDA", "GOOGL", "AMZN", "META", "TSLA",
    "JPM", "V", "JNJ", "WMT", "MA", "PG", "HD", "AVGO",
    "NFLX", "AMD", "CRM", "QCOM", "BAC", "GS", "XOM", "CVX",
    "LLY", "UNH", "ABBV", "MRK", "SPY", "QQQ", "IWM",
]


@task(name="US Options Chain Snapshot", retries=2, retry_delay_seconds=120)
async def task_us_options(tickers: list[str]):
    svc = UsOptionsService()
    result = await svc.run_batch(tickers)
    logger.info("[US Options] %s", result)
    return result


@flow(name="US Options Initial Load", log_prints=True)
async def us_options_initial_flow():
    """Capture today's options chain for HIGH-tier US equities."""
    await task_us_options(HIGH_US_OPTIONS_TICKERS)


@flow(name="US Options Daily Snapshot", log_prints=True)
async def us_options_daily_flow():
    """Daily options snapshot after US close."""
    await task_us_options(HIGH_US_OPTIONS_TICKERS)
