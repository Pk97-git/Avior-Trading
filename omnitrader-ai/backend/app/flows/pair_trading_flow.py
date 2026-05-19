"""
flows/pair_trading_flow.py
===========================
Pair trading statistical arbitrage flows.
Runs weekly (Sunday) to refresh cointegration + spread z-scores.
"""
import logging
from prefect import flow, task

from app.services.pair_trading import PairTradingService
from app.db.session import AsyncSessionLocal

logger = logging.getLogger(__name__)


@task(name="Pair Trading Evaluation", retries=2, retry_delay_seconds=120)
async def task_pair_trading():
    async with AsyncSessionLocal() as db:
        svc = PairTradingService(db)
        result = await svc.run_all_pairs()
        logger.info("[PairTrade] %s", result)
        return result


@flow(name="Pair Trading Weekly Refresh", log_prints=True)
async def pair_trading_weekly_flow():
    """Weekly refresh of cointegration tests and spread z-scores."""
    await task_pair_trading()


@flow(name="Pair Trading Initial Load", log_prints=True)
async def pair_trading_initial_flow():
    """Initial evaluation of all defined sector pairs."""
    await task_pair_trading()
