"""
flows/corporate_actions_flow.py
================================
India corporate actions ingestion flows.

  Weekly: Refresh splits/bonuses/dividends for India equities.
  Initial: Full backfill for all India HIGH equities.
"""
import logging
from sqlalchemy import text
from prefect import flow, task

from app.ingestion.core.corporate_actions import CorporateActionsService
from app.db.session import AsyncSessionLocal

logger = logging.getLogger(__name__)


async def _get_india_tickers() -> list[str]:
    async with AsyncSessionLocal() as db:
        res = await db.execute(text(
            "SELECT ticker FROM stocks WHERE country = 'IN' ORDER BY ticker"
        ))
        return [r.ticker for r in res.fetchall()]


@task(name="India Corporate Actions Refresh", retries=2, retry_delay_seconds=120)
async def task_corporate_actions(tickers: list[str]):
    svc = CorporateActionsService()
    result = await svc.run_batch(tickers)
    logger.info("[CorporateActions] %s", result)
    return result


@flow(name="Corporate Actions Initial Load", log_prints=True)
async def corporate_actions_initial_flow():
    """Full backfill for all India equity corporate actions."""
    tickers = await _get_india_tickers()
    logger.info("[CorporateActions] Initial load for %d India tickers", len(tickers))
    await task_corporate_actions(tickers)


@flow(name="Corporate Actions Weekly Refresh", log_prints=True)
async def corporate_actions_weekly_flow():
    """Weekly refresh — picks up new splits/bonuses announced this week."""
    tickers = await _get_india_tickers()
    await task_corporate_actions(tickers)
