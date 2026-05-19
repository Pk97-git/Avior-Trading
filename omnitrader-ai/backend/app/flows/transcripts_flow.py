"""
transcripts_flow.py
===================
Prefect flows for SEC 8-K earnings transcript ingestion + event extraction.

  transcripts_initial_flow()  — fetch last 90 days for all HIGH-tier US equities
  transcripts_daily_flow()    — refresh last 7 days (catch new 8-K filings)
  event_extraction_flow()     — classify unclassified news headlines into event types
"""
import logging
import time

from prefect import task, flow

from app.db.session import AsyncSessionLocal
from app.ingestion.infra.universe import UniverseManager

logger = logging.getLogger(__name__)


def _us_equity_tickers(tier: str = "HIGH") -> list[str]:
    mgr = UniverseManager(use_cache=True, cache_ttl_hours=24)
    return [
        t for t in mgr.get_all_tickers(tier)
        if "." not in t and "^" not in t  # US tickers only (no .NS, .BO, =F etc.)
    ]


@task(name="Transcripts — Batch Fetch & Summarize", retries=1)
async def task_transcripts(days_back: int = 90) -> dict:
    from app.ingestion.core.transcripts import TranscriptService
    tickers = _us_equity_tickers("HIGH")
    _t = time.monotonic()
    async with AsyncSessionLocal() as session:
        svc = TranscriptService(session)
        result = await svc.run_batch(tickers, days_back=days_back)
    return {**result, "duration_s": round(time.monotonic() - _t, 1)}


@task(name="Events — Classify News Headlines", retries=1)
async def task_event_extraction(days_back: int = 7) -> dict:
    from app.ingestion.core.event_extractor import EventExtractorService
    _t = time.monotonic()
    async with AsyncSessionLocal() as session:
        svc = EventExtractorService(session)
        result = await svc.run_batch(days_back=days_back)
    return {**result, "duration_s": round(time.monotonic() - _t, 1)}


@flow(name="Transcripts — Initial Load", log_prints=True)
async def transcripts_initial_flow():
    logger.info("=== [Transcripts] Initial Load (90-day backfill) ===")
    r1 = await task_transcripts(days_back=90)
    logger.info("Transcripts: %s", r1)
    r2 = await task_event_extraction(days_back=30)
    logger.info("Event extraction: %s", r2)
    logger.info("=== [Transcripts] Initial Load Complete ===")


@flow(name="Transcripts — Daily Refresh", log_prints=True)
async def transcripts_daily_flow():
    logger.info("=== [Transcripts] Daily Refresh ===")
    r1 = await task_transcripts(days_back=7)
    logger.info("Transcripts: %s", r1)
    r2 = await task_event_extraction(days_back=2)
    logger.info("Event extraction: %s", r2)
    logger.info("=== [Transcripts] Daily Refresh Complete ===")
