"""
analysts_flow.py
================
Analyst ratings + short interest ingestion: tasks + flows.

Data type : Analyst upgrades/downgrades, initiations, price targets
Source    : yfinance upgrades_downgrades (last 90 days per ticker)
Coverage  : HIGH-tier equities (US + India)

──────────────────────────────────────────────────────────────
 HISTORICAL (initial / backfill)
──────────────────────────────────────────────────────────────
  analysts_initial_flow()
      Fetches the last 90 days of analyst ratings for ALL HIGH-tier
      equities (both US and India). yfinance only exposes 90 days,
      so this is the maximum historical depth available.

──────────────────────────────────────────────────────────────
 INCREMENTAL (scheduled — every weekday via daily_ingest_flow)
──────────────────────────────────────────────────────────────
  analysts_daily_flow()
      Refreshes the last 90 days for the top 50 HIGH-tier equities.
      Called inside daily_ingest_flow() in orchestrator.py.
      Catches upgrades and downgrades within 24 hours of publication.
──────────────────────────────────────────────────────────────
"""
import logging
import time

from prefect import task, flow

from app.db.session import AsyncSessionLocal
from app.ingestion.infra.universe import UniverseManager

logger = logging.getLogger(__name__)

_NON_EQUITY = ("-USD", "=F", ".NYB")


def _high_equity_tickers() -> list:
    mgr = UniverseManager(use_cache=True, cache_ttl_hours=24)
    return [
        t for t in mgr.get_all_tickers("HIGH")
        if not any(t.endswith(x) for x in _NON_EQUITY) and "^" not in t
    ]


@task(name="Analysts — Batch Fetch", retries=1)
async def task_analysts(tickers: list) -> dict:
    _t = time.monotonic()
    async with AsyncSessionLocal() as db:
        from app.ingestion.core.analyst_ratings import AnalystRatingService
        svc = AnalystRatingService(db)
        result = await svc.run_batch(tickers)
    return {**result, "duration_s": round(time.monotonic() - _t, 1)}


@flow(name="Analysts — Initial Load", log_prints=True)
async def analysts_initial_flow():
    """
    Fetches last 90 days of analyst ratings for all HIGH-tier equities.
    This is the maximum history yfinance exposes.
    Safe to re-run: all writes are upserts.
    """
    logger.info("=== [Analysts] Initial Load ===")
    tickers = _high_equity_tickers()
    result = await task_analysts(tickers)
    logger.info("Analysts: %s", result)
    logger.info("=== [Analysts] Initial Load Complete ===")


@flow(name="Analysts — Daily Refresh", log_prints=True)
async def analysts_daily_flow():
    """
    Refreshes analyst ratings for the top 50 HIGH-tier equities.
    Runs nightly as part of daily_ingest_flow.
    """
    logger.info("=== [Analysts] Daily Refresh ===")
    tickers = _high_equity_tickers()[:50]
    result = await task_analysts(tickers)
    logger.info("Analysts: %s", result)
    logger.info("=== [Analysts] Daily Refresh Complete ===")
