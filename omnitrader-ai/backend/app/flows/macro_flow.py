"""
macro_flow.py
=============
All macroeconomic data ingestion: tasks + flows.

Data type : Economic indicators + global market proxies
Sources   : FRED (US + India), yfinance (global market tickers)

Sub-categories:
  US Macro   — CPI, Fed Funds Rate, 10Y + 2Y Treasury, Yield Curve,
                M2 Money Supply, Unemployment, PCE Inflation
  India Macro — India CPI (FRED), RBI Repo Rate (RBI DBIE API)
  Global Macro — Oil (WTI + Brent), Gold, Silver, VIX (US + India),
                 INR/USD, DXY Dollar Index, S&P 500, Nifty 50,
                 NASDAQ, BankNifty, Bitcoin, Ethereum, Bond ETFs

──────────────────────────────────────────────────────────────
 HISTORICAL (initial / backfill)
──────────────────────────────────────────────────────────────
  macro_initial_flow()
      Fetches full history for all three sub-categories.
      FRED series go back to year 2000.
      Global macro via yfinance uses period="max".

──────────────────────────────────────────────────────────────
 INCREMENTAL (scheduled)
──────────────────────────────────────────────────────────────
  macro_daily_flow()        ← runs nightly (22:00 UTC weekdays)
      Global macro only — VIX, Oil, Gold, INR/USD update every trading day.
      Fetches period="2d" to catch same-day and prior-day values.

  macro_weekly_flow()       ← runs every Sunday (02:00 UTC)
      FRED + RBI series — most FRED indicators update monthly,
      weekly fetch catches revisions and newly-released prints.
──────────────────────────────────────────────────────────────
"""
import logging
import time

from prefect import task, flow

from app.db.session import AsyncSessionLocal
from app.ingestion.infra.rate_limiter import RateLimiterRegistry
from app.ingestion.core.macro_fundamental import MacroService

logger = logging.getLogger(__name__)


# ══════════════════════════════════════════════════════════════
# TASKS
# ══════════════════════════════════════════════════════════════

@task(name="Macro — US (FRED)", retries=2)
async def task_macro_us() -> dict:
    """
    Fetches US macro series from FRED:
    CPI, Fed Funds Rate, 10Y + 2Y Treasury yields, Yield Curve (T10Y2Y),
    M2 Money Supply, Unemployment Rate, PCE Inflation.
    """
    _t = time.monotonic()
    async with AsyncSessionLocal() as session:
        await RateLimiterRegistry.acquire("fred")
        svc = MacroService(session)
        await svc.fetch_all_us_macro()
    return {"source": "FRED US", "duration_s": round(time.monotonic() - _t, 1)}


@task(name="Macro — India (FRED + RBI)", retries=2)
async def task_macro_india() -> dict:
    """
    Fetches India macro:
    - India CPI via FRED (INDCPMINDKSN series)
    - RBI Repo Rate via RBI DBIE API (falls back to env RBI_REPO_RATE_FALLBACK)
    """
    _t = time.monotonic()
    async with AsyncSessionLocal() as session:
        await RateLimiterRegistry.acquire("fred")
        svc = MacroService(session)
        await svc.fetch_all_india_macro()
    return {"source": "FRED India + RBI", "duration_s": round(time.monotonic() - _t, 1)}


@task(name="Macro — Global (yfinance)", retries=2)
async def task_macro_global(period: str = "2d") -> dict:
    """
    Fetches global macro time series via yfinance:
    Oil (WTI + Brent), Gold, Silver, VIX (US + India), INR/USD, DXY,
    S&P 500, Nifty 50, NASDAQ, BankNifty, Bitcoin, Ethereum,
    US 7-10Y Treasury ETF (IEF), TIPS ETF.

    period="max"  → initial load (full history)
    period="2d"   → daily update (last 2 trading days only)
    """
    _t = time.monotonic()
    async with AsyncSessionLocal() as session:
        await RateLimiterRegistry.acquire("yfinance")
        svc = MacroService(session)
        await svc.fetch_global_macro(period=period)
    return {"source": "yfinance global", "period": period,
            "duration_s": round(time.monotonic() - _t, 1)}


# ══════════════════════════════════════════════════════════════
# HISTORICAL — run once on fresh install
# ══════════════════════════════════════════════════════════════

@flow(name="Macro — Initial Full Load", log_prints=True)
async def macro_initial_flow():
    """
    Fetches complete history for all three macro sub-categories.
    US + India FRED series go back to 2000.
    Global yfinance series use period="max".
    Safe to re-run: all writes use on_conflict_do_nothing.
    """
    logger.info("=== [Macro] Initial Full Load ===")
    r1 = await task_macro_us()
    logger.info("US macro: %s", r1)
    r2 = await task_macro_india()
    logger.info("India macro: %s", r2)
    r3 = await task_macro_global(period="max")
    logger.info("Global macro: %s", r3)
    logger.info("=== [Macro] Initial Full Load Complete ===")


# ══════════════════════════════════════════════════════════════
# INCREMENTAL — scheduled recurring
# ══════════════════════════════════════════════════════════════

@flow(name="Macro — Daily Update (Global)", log_prints=True)
async def macro_daily_flow():
    """
    Updates fast-moving global macro indicators after both markets close.
    Fetches period="2d" to reliably capture the latest trading day value.
    Runs nightly at 22:00 UTC (weekdays), after US market has settled.
    """
    logger.info("=== [Macro] Daily Global Macro Update ===")
    result = await task_macro_global(period="2d")
    logger.info("Global macro: %s", result)
    logger.info("=== [Macro] Daily Global Macro Update Complete ===")


@flow(name="Macro — Weekly Refresh (FRED + RBI)", log_prints=True)
async def macro_weekly_flow():
    """
    Re-fetches FRED series (US + India) and RBI Repo Rate.
    Most FRED series publish monthly but revisions appear frequently.
    Weekly fetch ensures no print is missed by more than 7 days.
    Runs every Sunday at 02:00 UTC.
    """
    logger.info("=== [Macro] Weekly FRED + RBI Refresh ===")
    r1 = await task_macro_us()
    logger.info("US macro: %s", r1)
    r2 = await task_macro_india()
    logger.info("India macro: %s", r2)
    logger.info("=== [Macro] Weekly FRED + RBI Refresh Complete ===")
