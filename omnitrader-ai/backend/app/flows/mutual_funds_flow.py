"""
flows/mutual_funds_flow.py
===========================
Mutual fund NAV and portfolio ingestion flows.

  Daily:   NAV update (after 8:00 PM IST when AMFI publishes)
  Monthly: Holdings disclosure (portfolio released on 10th of each month)
  Initial: Full NAV backfill + first holdings load
"""
import logging
from prefect import flow, task

from app.ingestion.core.mutual_funds import MutualFundService

logger = logging.getLogger(__name__)


@task(name="Mutual Fund NAV Update", retries=2, retry_delay_seconds=120)
async def task_mf_nav():
    svc = MutualFundService()
    result = await svc.update_nav()
    logger.info("[MF NAV] %s", result)
    return result


@flow(name="Mutual Fund Initial Load", log_prints=True)
async def mutual_funds_initial_flow():
    """Initial NAV load — stores all schemes for today."""
    logger.info("[MF] Initial load starting...")
    await task_mf_nav()
    logger.info("[MF] Initial load complete.")


@flow(name="Mutual Fund Daily NAV", log_prints=True)
async def mutual_funds_daily_flow():
    """Daily NAV refresh — runs after AMFI publishes (14:30 UTC / 8:00 PM IST)."""
    await task_mf_nav()
