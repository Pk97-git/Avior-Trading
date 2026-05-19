"""
flows/sec_filings_flow.py
==========================
SEC 10-K / 10-Q filing ingestion flows.

Initial: all HIGH-tier US equities (top 50 by market cap)
Weekly:  all HIGH-tier US equities (checks for new filings)
Monthly: expand to MEDIUM-tier US equities
"""
import logging
from sqlalchemy import text
from prefect import flow, task

from app.ingestion.core.sec_filings import SecFilingsService
from app.db.session import AsyncSessionLocal

logger = logging.getLogger(__name__)

# Top US equities for filing tracking
HIGH_US_TICKERS = [
    "AAPL", "MSFT", "NVDA", "GOOGL", "AMZN", "META", "TSLA", "BRK-B",
    "JPM", "V", "JNJ", "WMT", "MA", "PG", "HD", "AVGO", "ORCL", "COST",
    "NFLX", "AMD", "CRM", "QCOM", "INTC", "CSCO", "ADBE", "IBM", "GE",
    "BAC", "WFC", "GS", "MS", "C", "AXP", "BLK",
    "XOM", "CVX", "COP", "EOG", "SLB",
    "LLY", "UNH", "ABBV", "MRK", "PFE", "AMGN", "BMY", "GILD",
    "CAT", "DE", "HON", "MMM", "RTX",
]


async def _get_us_equity_tickers() -> list[str]:
    async with AsyncSessionLocal() as db:
        res = await db.execute(text(
            "SELECT ticker FROM stocks WHERE country = 'US' "
            "AND ticker NOT LIKE '%.%' ORDER BY ticker LIMIT 500"
        ))
        return [r.ticker for r in res.fetchall()]


@task(name="SEC 10-K/10-Q Filings Fetch", retries=2, retry_delay_seconds=300)
async def task_sec_filings(tickers: list[str]):
    svc = SecFilingsService()
    result = await svc.run_batch(tickers)
    logger.info("[SEC Filings] %s", result)
    return result


@flow(name="SEC Filings Initial Load", log_prints=True)
async def sec_filings_initial_flow():
    """Fetch last 2 years of 10-K/10-Q filings for HIGH-tier US equities."""
    logger.info("[SEC Filings] Initial load for %d tickers", len(HIGH_US_TICKERS))
    await task_sec_filings(HIGH_US_TICKERS)


@flow(name="SEC Filings Weekly Refresh", log_prints=True)
async def sec_filings_weekly_flow():
    """Weekly check for newly filed 10-K/10-Q."""
    await task_sec_filings(HIGH_US_TICKERS)


@flow(name="SEC Filings Monthly Broad Refresh", log_prints=True)
async def sec_filings_monthly_flow():
    """Monthly refresh — broader US equity universe."""
    tickers = await _get_us_equity_tickers()
    await task_sec_filings(tickers)
