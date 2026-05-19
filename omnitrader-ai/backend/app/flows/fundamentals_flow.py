"""
fundamentals_flow.py
====================
All company financial statement ingestion: tasks + flows.

Data type : Income statement, balance sheet, cash flow, key ratios
            Revenue, Net Income, FCF, EPS, D/E, ROE, ROIC, Op. Margin
Sources   : yfinance (US + India .NS)
Coverage  : MEDIUM tier equities only
            (excludes crypto -USD, futures =F, indices ^, .NYB)

──────────────────────────────────────────────────────────────
 HISTORICAL (initial / backfill)
──────────────────────────────────────────────────────────────
  fundamentals_initial_flow()
      Fetches the full available history of financial statements for
      every equity ticker in the MEDIUM universe.
      yfinance provides up to ~4 years of annual + quarterly reports.
      Uses the completeness monitor — skips tickers already up-to-date.

──────────────────────────────────────────────────────────────
 INCREMENTAL (scheduled — every Sunday)
──────────────────────────────────────────────────────────────
  fundamentals_weekly_flow()
      Re-checks every equity ticker for new quarterly filings.
      Flags tickers whose most recent fiscal_date is older than 180 days
      and re-fetches. Catches new earnings reports as they land.
──────────────────────────────────────────────────────────────
"""
import logging
import time

from prefect import task, flow

from app.db.session import AsyncSessionLocal
from app.ingestion.infra.universe import UniverseManager
from app.ingestion.core.completeness import DataCompletenessMonitor

logger = logging.getLogger(__name__)

_NON_EQUITY_SUFFIXES = ("-USD", "=F", ".NYB")


def _equity_universe() -> list:
    """MEDIUM-tier tickers, equities only (no crypto, futures, or indices)."""
    mgr = UniverseManager(use_cache=True, cache_ttl_hours=24)
    return [
        t for t in mgr.get_all_tickers("MEDIUM")
        if not any(t.endswith(x) for x in _NON_EQUITY_SUFFIXES) and "^" not in t
    ]


# ══════════════════════════════════════════════════════════════
# TASKS
# ══════════════════════════════════════════════════════════════

@task(name="Fundamentals — Equity Universe", retries=1)
async def task_fundamentals() -> dict:
    """
    Scans company_financials for gaps (missing or older than 180 days)
    and fetches income statement, balance sheet, and cash flow for each.
    """
    tickers = _equity_universe()
    _t = time.monotonic()
    async with AsyncSessionLocal() as session:
        monitor = DataCompletenessMonitor(session)
        await monitor.run_fundamental_completeness_check(tickers)
    return {"tickers": len(tickers), "duration_s": round(time.monotonic() - _t, 1)}


# ══════════════════════════════════════════════════════════════
# HISTORICAL — run once on fresh install
# ══════════════════════════════════════════════════════════════

@flow(name="Fundamentals — Initial Load", log_prints=True)
async def fundamentals_initial_flow():
    """
    Fetches financial statements for all MEDIUM-tier equities.
    The completeness monitor identifies every ticker with no data or
    stale data (>180 days) and fetches from yfinance.
    Safe to re-run: all writes are upserts.
    """
    logger.info("=== [Fundamentals] Initial Load ===")
    result = await task_fundamentals()
    logger.info("Fundamentals: %s", result)
    logger.info("=== [Fundamentals] Initial Load Complete ===")


# ══════════════════════════════════════════════════════════════
# INCREMENTAL — scheduled every Sunday
# ══════════════════════════════════════════════════════════════

@flow(name="Fundamentals — Weekly Refresh", log_prints=True)
async def fundamentals_weekly_flow():
    """
    Checks the entire MEDIUM equity universe for new quarterly filings.
    Tickers with fiscal_date older than 180 days are re-fetched.
    Runs every Sunday — catches new earnings within 7 days of release.
    """
    logger.info("=== [Fundamentals] Weekly Refresh ===")
    result = await task_fundamentals()
    logger.info("Fundamentals: %s", result)
    logger.info("=== [Fundamentals] Weekly Refresh Complete ===")
