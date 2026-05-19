"""
insiders_flow.py
================
SEC Form 4 insider transaction ingestion: tasks + flows.

Data type : Insider purchases, sales, and awards (Form 4 filings)
Source    : yfinance insider_transactions (last 90 days per ticker)
Coverage  : HIGH-tier equities (US primarily; India via yfinance if available)

──────────────────────────────────────────────────────────────
 HISTORICAL (initial / backfill)
──────────────────────────────────────────────────────────────
  insiders_initial_flow()
      Fetches the last 90 days of Form 4 transactions for ALL HIGH-tier
      equities. yfinance insider_transactions exposes up to 90 days.

──────────────────────────────────────────────────────────────
 INCREMENTAL (scheduled — every weekday via daily_ingest_flow)
──────────────────────────────────────────────────────────────
  insiders_daily_flow()
      Refreshes the last 90 days for the top 50 HIGH-tier equities.
      Called inside daily_ingest_flow() in orchestrator.py.
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


@task(name="Insiders — Batch Fetch", retries=1)
async def task_insiders(tickers: list) -> dict:
    _t = time.monotonic()
    async with AsyncSessionLocal() as db:
        from app.ingestion.insider.form4 import SecForm4Service
        svc = SecForm4Service(db)
        result = await svc.run_batch(tickers)
    return {**result, "duration_s": round(time.monotonic() - _t, 1)}


@flow(name="Insiders — Initial Load", log_prints=True)
async def insiders_initial_flow():
    """
    Fetches last 90 days of Form 4 insider transactions for all HIGH-tier equities.
    Safe to re-run: all writes are upserts.
    """
    logger.info("=== [Insiders] Initial Load ===")
    tickers = _high_equity_tickers()
    result = await task_insiders(tickers)
    logger.info("Insiders: %s", result)
    logger.info("=== [Insiders] Initial Load Complete ===")


@flow(name="Insiders — Daily Refresh", log_prints=True)
async def insiders_daily_flow():
    """
    Refreshes insider transactions for the top 50 HIGH-tier equities.
    Runs nightly as part of daily_ingest_flow.
    """
    logger.info("=== [Insiders] Daily Refresh ===")
    tickers = _high_equity_tickers()[:50]
    result = await task_insiders(tickers)
    logger.info("Insiders: %s", result)
    logger.info("=== [Insiders] Daily Refresh Complete ===")
