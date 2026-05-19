"""
flows/intraday_flow.py
======================
Intraday 15-minute price bar ingestion flows.

India session:  09:15–15:30 IST → 03:45–10:00 UTC
US session:     09:30–16:00 EST → 14:30–21:00 UTC

Scheduled from main.py at:
  India: 04:00, 06:00, 08:00, 10:15 UTC (Mon-Fri)
  US:    14:45, 17:00, 19:00, 21:15 UTC (Mon-Fri)
"""
import logging
from prefect import flow, task

from app.ingestion.core.intraday import IntradayPriceService, INDIA_INTRADAY_TICKERS, US_INTRADAY_TICKERS

logger = logging.getLogger(__name__)


@task(name="Intraday India Refresh", retries=2, retry_delay_seconds=60)
async def task_intraday_india(period: str = "5d"):
    svc = IntradayPriceService()
    result = await svc.run_batch(INDIA_INTRADAY_TICKERS, period=period)
    logger.info("[Intraday] India: %s", result)
    return result


@task(name="Intraday US Refresh", retries=2, retry_delay_seconds=60)
async def task_intraday_us(period: str = "5d"):
    svc = IntradayPriceService()
    result = await svc.run_batch(US_INTRADAY_TICKERS, period=period)
    logger.info("[Intraday] US: %s", result)
    return result


@flow(name="Intraday Initial Load", log_prints=True)
async def intraday_initial_flow():
    """Backfill 60 days of 15m bars (max yfinance allows for 15m interval)."""
    logger.info("[Intraday] Initial backfill (60d) starting...")
    await task_intraday_india(period="60d")
    await task_intraday_us(period="60d")
    logger.info("[Intraday] Initial backfill complete.")


@flow(name="Intraday India Session Refresh", log_prints=True)
async def intraday_india_flow():
    """Incremental refresh during/after India market session."""
    await task_intraday_india(period="5d")


@flow(name="Intraday US Session Refresh", log_prints=True)
async def intraday_us_flow():
    """Incremental refresh during/after US market session."""
    await task_intraday_us(period="5d")
