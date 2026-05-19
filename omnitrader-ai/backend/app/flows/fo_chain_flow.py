"""
flows/fo_chain_flow.py
======================
NSE F&O option chain snapshot flows.
Scheduled every 15 minutes during NSE session: 04:00–10:00 UTC Mon-Fri.
"""
import logging
from prefect import flow, task

from app.ingestion.institutional.fo_chain import FoChainService

logger = logging.getLogger(__name__)


@task(name="NSE F&O Chain Snapshot", retries=2, retry_delay_seconds=30)
async def task_fo_chain():
    svc = FoChainService()
    result = await svc.run_all()
    logger.info("[FoChain] %s", result)
    return result


@flow(name="NSE F&O Chain Snapshot Flow", log_prints=True)
async def fo_chain_flow():
    """Single snapshot capture — called every 15 minutes during NSE session."""
    await task_fo_chain()
