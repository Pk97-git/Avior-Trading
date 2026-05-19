"""
prices_flow.py
==============
All price OHLCV ingestion: tasks + flows.

Data type : Daily OHLCV (US + India + Crypto + Indices + Macro futures)
Sources   : yfinance (.NS for India, standard tickers for US)
Coverage  : HIGH tier (top 50 US + Nifty 50 + Crypto + Indices)
            MEDIUM tier (S&P 500 + Nasdaq 100 + Nifty 500)
            LOW tier    (+ Russell 2000 ETF + Nifty Midcap)

──────────────────────────────────────────────────────────────
 HISTORICAL (initial / backfill)
──────────────────────────────────────────────────────────────
  prices_initial_flow()
      Downloads max history for ALL tickers across all three tiers.
      Run once on a fresh install, or on-demand to extend history.
      Uses period="max" → completeness monitor fetches everything.

──────────────────────────────────────────────────────────────
 INCREMENTAL (scheduled)
──────────────────────────────────────────────────────────────
  prices_intraday_flow()
      HIGH tier only. Runs 5× per weekday during live sessions.
      Keeps active-candidate prices near real-time.

  prices_india_eod_flow()
      HIGH + MEDIUM. Runs 45 min after NSE close (16:15 IST).
      Captures official closing prices for all India stocks.

  prices_us_eod_flow()
      HIGH + MEDIUM. Runs 30 min after NYSE close (02:30 IST).
      Captures official closing prices for all US stocks.

  prices_nightly_gap_fill_flow()
      All three tiers. Runs at midnight UTC each night.
      Detects and fills any gaps that intraday runs missed.
      The completeness monitor handles two gap cases automatically:
        • Tickers with NO data at all (newly added to universe, IPOs)
          → backfilled with period="max" regardless of the period arg.
        • Tickers with recent gaps (> 4 trading days missing)
          → filled over the exact missing date range.
──────────────────────────────────────────────────────────────
"""
import logging
import time

from prefect import task, flow

from app.db.session import AsyncSessionLocal
from app.ingestion.infra.universe import UniverseManager
from app.ingestion.infra.rate_limiter import RateLimiterRegistry
from app.ingestion.core.completeness import DataCompletenessMonitor

logger = logging.getLogger(__name__)


def _equity_tickers(tier: str) -> list:
    mgr = UniverseManager(use_cache=True, cache_ttl_hours=24)
    return mgr.get_all_tickers(tier)


def _priority_groups() -> dict:
    mgr = UniverseManager(use_cache=True, cache_ttl_hours=24)
    return mgr.get_priority_groups()


# ══════════════════════════════════════════════════════════════
# TASKS
# ══════════════════════════════════════════════════════════════

@task(name="Prices — HIGH tier", retries=2, retry_delay_seconds=30)
async def task_prices_high(period: str = "2d") -> dict:
    tickers = _equity_tickers("HIGH")
    _t = time.monotonic()
    async with AsyncSessionLocal() as session:
        monitor = DataCompletenessMonitor(session)
        await monitor.run_price_completeness_check(tickers, period=period)
    return {"tier": "HIGH", "tickers": len(tickers), "period": period,
            "duration_s": round(time.monotonic() - _t, 1)}


@task(name="Prices — MEDIUM tier", retries=2, retry_delay_seconds=60)
async def task_prices_medium(period: str = "2d") -> dict:
    groups = _priority_groups()
    tickers = groups.get("MEDIUM", [])
    _t = time.monotonic()
    async with AsyncSessionLocal() as session:
        monitor = DataCompletenessMonitor(session)
        await monitor.run_price_completeness_check(tickers, period=period)
    return {"tier": "MEDIUM", "tickers": len(tickers), "period": period,
            "duration_s": round(time.monotonic() - _t, 1)}


@task(name="Prices — LOW tier", retries=1)
async def task_prices_low(period: str = "2d") -> dict:
    groups = _priority_groups()
    tickers = groups.get("LOW", [])
    _t = time.monotonic()
    async with AsyncSessionLocal() as session:
        monitor = DataCompletenessMonitor(session)
        await monitor.run_price_completeness_check(tickers, period=period)
    return {"tier": "LOW", "tickers": len(tickers), "period": period,
            "duration_s": round(time.monotonic() - _t, 1)}


# ══════════════════════════════════════════════════════════════
# HISTORICAL — run once on fresh install
# ══════════════════════════════════════════════════════════════

@flow(name="Prices — Initial Full History", log_prints=True)
async def prices_initial_flow():
    """
    Downloads maximum available history for every ticker in the universe.
    HIGH → MEDIUM → LOW in priority order.
    Safe to re-run: all writes are upserts.
    """
    logger.info("=== [Prices] Initial Full History Backfill ===")
    r1 = await task_prices_high(period="max")
    logger.info("HIGH tier: %s", r1)
    r2 = await task_prices_medium(period="max")
    logger.info("MEDIUM tier: %s", r2)
    r3 = await task_prices_low(period="max")
    logger.info("LOW tier: %s", r3)
    logger.info("=== [Prices] Initial Backfill Complete ===")


# ══════════════════════════════════════════════════════════════
# INCREMENTAL — scheduled recurring
# ══════════════════════════════════════════════════════════════

@flow(name="Prices — Intraday Refresh", log_prints=True)
async def prices_intraday_flow():
    """
    Lightweight refresh for HIGH-priority tickers during live sessions.
    Fetches only the last 2 trading days to minimise rate-limit pressure.
    Runs 5× per weekday (India open, India mid, US open, US mid, US afternoon).
    """
    logger.info("=== [Prices] Intraday Refresh ===")
    result = await task_prices_high(period="2d")
    logger.info("HIGH tier: %s", result)
    logger.info("=== [Prices] Intraday Refresh Complete ===")


@flow(name="Prices — India End-of-Day", log_prints=True)
async def prices_india_eod_flow():
    """
    Syncs official NSE closing prices 45 minutes after India market close.
    NSE close: 15:30 IST → this flow runs at 16:15 IST (10:45 UTC).
    """
    logger.info("=== [Prices] India End-of-Day Sync ===")
    r1 = await task_prices_high(period="2d")
    logger.info("HIGH tier: %s", r1)
    r2 = await task_prices_medium(period="2d")
    logger.info("MEDIUM tier: %s", r2)
    logger.info("=== [Prices] India EOD Sync Complete ===")


@flow(name="Prices — US End-of-Day", log_prints=True)
async def prices_us_eod_flow():
    """
    Syncs official NYSE/NASDAQ closing prices 30 minutes after US market close.
    NYSE close: 16:00 EST (02:30 IST next day) → this flow runs at 21:00 UTC.
    """
    logger.info("=== [Prices] US End-of-Day Sync ===")
    r1 = await task_prices_high(period="2d")
    logger.info("HIGH tier: %s", r1)
    r2 = await task_prices_medium(period="2d")
    logger.info("MEDIUM tier: %s", r2)
    logger.info("=== [Prices] US EOD Sync Complete ===")


@flow(name="Prices — Nightly Gap Fill", log_prints=True)
async def prices_nightly_gap_fill_flow():
    """
    Scans all three tiers for data gaps and fills them.
    Runs once per night at 00:00 UTC after both markets have settled.

    The completeness monitor handles two gap cases transparently:
      • Tickers with NO data (newly added universe members, recent IPOs)
        → automatically backfilled with period="max" regardless of the
        period="2d" argument passed here.
      • Tickers with partial gaps (holiday, rate-limit failure, > 4 days missing)
        → filled over the exact missing date range only.

    This means any ticker added to the universe is fully bootstrapped
    the night it first appears — no manual intervention required.
    """
    logger.info("=== [Prices] Nightly Gap Fill ===")
    r1 = await task_prices_high(period="2d")
    logger.info("HIGH tier: %s", r1)
    r2 = await task_prices_medium(period="2d")
    logger.info("MEDIUM tier: %s", r2)
    r3 = await task_prices_low(period="2d")
    logger.info("LOW tier: %s", r3)
    logger.info("=== [Prices] Nightly Gap Fill Complete ===")
