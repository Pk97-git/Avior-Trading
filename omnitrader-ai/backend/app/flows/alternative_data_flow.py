"""
flows/alternative_data_flow.py
================================
Alternative data ingestion flows:
  - RBI announcements (daily)
  - Google Trends (weekly — due to aggressive rate limits)
"""
import logging
from prefect import flow, task

from app.ingestion.core.rbi_announcements import RbiAnnouncementsService
from app.ingestion.core.google_trends import GoogleTrendsService, TRENDS_ALL

logger = logging.getLogger(__name__)


@task(name="RBI Announcements Scrape", retries=3, retry_delay_seconds=120)
async def task_rbi_announcements():
    svc = RbiAnnouncementsService()
    result = await svc.fetch_and_store()
    logger.info("[RBI] %s", result)
    return result


@task(name="Google Trends Fetch", retries=1, retry_delay_seconds=300)
async def task_google_trends():
    svc = GoogleTrendsService()
    result = await svc.run_batch(TRENDS_ALL)
    logger.info("[Google Trends] %s", result)
    return result


@flow(name="Alternative Data Initial Load", log_prints=True)
async def alternative_data_initial_flow():
    """Initial load: RBI history + Google Trends backfill (3 months)."""
    await task_rbi_announcements()
    await task_google_trends()


@flow(name="Alternative Data Daily", log_prints=True)
async def alternative_data_daily_flow():
    """Daily: RBI press releases only (fast, no rate limits)."""
    await task_rbi_announcements()


@flow(name="Alternative Data Weekly", log_prints=True)
async def alternative_data_weekly_flow():
    """Weekly: Google Trends (rate-limited — runs slowly over ~15 min)."""
    await task_google_trends()
