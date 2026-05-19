"""
institutional_flow.py
=====================
All institutional money-flow data ingestion: tasks + flows.

Data type : Smart-money tracking — who is buying, selling, and holding

Sub-categories:
  India Daily   — FII / DII net flows (NSE publishes every trading day)
  India Weekly  — Bulk deals + Block deals (NSE)
                  Sector ETF proxy flows (yfinance)
                  Options Put/Call ratios (CBOE — US equities)
  India Quarterly — NSE promoter / shareholding pattern
  US Quarterly    — SEC EDGAR 13F institutional holdings

Sources:
  NSE India API / Playwright browser (FII/DII, bulk deals, promoter)
  yfinance (sector ETF OHLCV as flow proxy)
  SEC EDGAR (13F XML filings)

──────────────────────────────────────────────────────────────
 HISTORICAL (initial / backfill)
──────────────────────────────────────────────────────────────
  institutional_initial_flow()
      Fetches all six sub-categories in sequence.
      FII/DII defaults to 30 days back; 13F and promoter holdings
      go as far back as the API provides.

──────────────────────────────────────────────────────────────
 INCREMENTAL (scheduled)
──────────────────────────────────────────────────────────────
  institutional_daily_flow()     ← nightly (22:00 UTC weekdays)
      FII/DII only — the only institutional series that changes daily.

  institutional_weekly_flow()    ← every Sunday (02:00 UTC)
      Bulk deals, sector ETF flows, options P/C ratios.
      These are meaningful on a weekly, not daily, basis.

  institutional_monthly_flow()   ← 1st of each month (03:00 UTC)
      SEC 13F filings (quarterly, filed within 45 days of quarter end).
      NSE promoter holdings (quarterly shareholding pattern).
      Monthly fetch ensures we capture filings within 30 days of release.
──────────────────────────────────────────────────────────────
"""
import logging
import time

from prefect import task, flow

from app.db.session import AsyncSessionLocal
from app.ingestion.infra.universe import UniverseManager
from app.ingestion.infra.rate_limiter import RateLimiterRegistry
from app.ingestion.institutional.us_india import InstitutionalService
from app.ingestion.institutional.promoter import PromoterHoldingService

logger = logging.getLogger(__name__)


def _india_equity_tickers() -> list:
    """HIGH-tier India equities (.NS and .BO only)."""
    mgr = UniverseManager(use_cache=True, cache_ttl_hours=24)
    return [t for t in mgr.get_all_tickers("HIGH") if ".NS" in t or ".BO" in t]


def _us_equity_tickers() -> list:
    """HIGH-tier US equities (no crypto, futures, indices)."""
    mgr = UniverseManager(use_cache=True, cache_ttl_hours=24)
    return [
        t for t in mgr.get_all_tickers("HIGH")
        if not any(t.endswith(x) for x in ("-USD", "=F", ".NS", ".BO", ".NYB"))
        and "^" not in t
    ]


# ══════════════════════════════════════════════════════════════
# TASKS
# ══════════════════════════════════════════════════════════════

@task(name="Institutional — India FII-DII Flows", retries=1)
async def task_fii_dii() -> dict:
    """
    Fetches FII + DII net buy/sell values for the past 30 trading days.
    Primary: Playwright browser (bypasses NSE bot detection).
    Fallback: requests.Session with browser-like headers.
    """
    _t = time.monotonic()
    async with AsyncSessionLocal() as session:
        await RateLimiterRegistry.acquire("nse")
        svc = InstitutionalService(session)
        await svc.fetch_india_fii_dii()
    return {"source": "NSE FII/DII", "duration_s": round(time.monotonic() - _t, 1)}


@task(name="Institutional — India Bulk-Block Deals", retries=1)
async def task_bulk_deals() -> dict:
    """
    Fetches NSE bulk and block deal disclosures.
    Published by NSE; available same day after market close.
    """
    _t = time.monotonic()
    async with AsyncSessionLocal() as session:
        await RateLimiterRegistry.acquire("nse")
        svc = InstitutionalService(session)
        await svc.fetch_india_bulk_deals()
    return {"source": "NSE bulk/block deals", "duration_s": round(time.monotonic() - _t, 1)}


@task(name="Institutional — Sector ETF Flows", retries=1)
async def task_sector_etfs() -> dict:
    """
    Uses sector ETF price + volume (yfinance) as a proxy for sector rotation.
    e.g. XLF (Financials), XLK (Tech), XLE (Energy), NIFTYBEES.NS (India).
    """
    _t = time.monotonic()
    async with AsyncSessionLocal() as session:
        await RateLimiterRegistry.acquire("yfinance")
        svc = InstitutionalService(session)
        await svc.fetch_sector_etf_flows()
    return {"source": "sector ETFs", "duration_s": round(time.monotonic() - _t, 1)}


@task(name="Institutional — Options P-C Ratios", retries=1)
async def task_options_pc() -> dict:
    """
    Fetches Put/Call open-interest ratios for US equities in the HIGH tier.
    Crypto, futures, and index tickers are excluded.
    """
    tickers = _us_equity_tickers()
    _t = time.monotonic()
    async with AsyncSessionLocal() as session:
        svc = InstitutionalService(session)
        await svc.fetch_options_put_call(tickers)
    return {"tickers": len(tickers), "duration_s": round(time.monotonic() - _t, 1)}


@task(name="Institutional — US SEC 13F Filings", retries=1)
async def task_sec_13f() -> dict:
    """
    Fetches quarterly SEC 13F institutional holdings from EDGAR.
    13F is filed within 45 days of quarter end; monthly fetch catches all.
    """
    _t = time.monotonic()
    async with AsyncSessionLocal() as session:
        await RateLimiterRegistry.acquire("sec_edgar")
        svc = InstitutionalService(session)
        await svc.fetch_us_13f()
    return {"source": "SEC EDGAR 13F", "duration_s": round(time.monotonic() - _t, 1)}


@task(name="Institutional — India Promoter Holdings", retries=1)
async def task_promoter_holdings() -> dict:
    """
    Fetches NSE shareholding pattern (promoter %, FII %, DII %, public %)
    for all India equities in the HIGH tier.
    Published quarterly; per-ticker fetch with a short-lived session per ticker
    to avoid holding a connection open across NSE rate-limit sleeps.
    """
    india_tickers = _india_equity_tickers()
    failed = []
    _t = time.monotonic()

    for ticker in india_tickers:
        try:
            await RateLimiterRegistry.acquire("nse")
            async with AsyncSessionLocal() as session:
                svc = PromoterHoldingService(session)
                await svc.fetch_nse_shareholding(ticker)
        except Exception as e:
            logger.error("Promoter holdings for %s: %s", ticker, e)
            failed.append(ticker)

    processed = len(india_tickers) - len(failed)
    if failed:
        logger.warning("Promoter holdings: %d/%d tickers failed: %s",
                       len(failed), len(india_tickers), failed)
    return {
        "processed": processed,
        "failed": len(failed),
        "duration_s": round(time.monotonic() - _t, 1),
    }


# ══════════════════════════════════════════════════════════════
# HISTORICAL — run once on fresh install
# ══════════════════════════════════════════════════════════════

@flow(name="Institutional — Initial Load", log_prints=True)
async def institutional_initial_flow():
    """
    Bootstraps all six institutional sub-categories in one go.
    Safe to re-run: upserts use on_conflict_do_nothing.
    """
    logger.info("=== [Institutional] Initial Load ===")
    r1 = await task_fii_dii()
    logger.info("FII/DII: %s", r1)
    r2 = await task_bulk_deals()
    logger.info("Bulk deals: %s", r2)
    r3 = await task_sector_etfs()
    logger.info("Sector ETFs: %s", r3)
    r4 = await task_options_pc()
    logger.info("Options P/C: %s", r4)
    r5 = await task_sec_13f()
    logger.info("SEC 13F: %s", r5)
    r6 = await task_promoter_holdings()
    logger.info("Promoter holdings: %s", r6)
    logger.info("=== [Institutional] Initial Load Complete ===")


# ══════════════════════════════════════════════════════════════
# INCREMENTAL — scheduled recurring
# ══════════════════════════════════════════════════════════════

@flow(name="Institutional — Daily (FII-DII)", log_prints=True)
async def institutional_daily_flow():
    """
    FII/DII net flows — the only institutional series that updates every day.
    Runs nightly at 22:00 UTC (weekdays), after both markets have closed.
    """
    logger.info("=== [Institutional] Daily FII/DII Update ===")
    result = await task_fii_dii()
    logger.info("FII/DII: %s", result)
    logger.info("=== [Institutional] Daily FII/DII Update Complete ===")


@flow(name="Institutional — Weekly (Bulk Deals, ETFs, Options)", log_prints=True)
async def institutional_weekly_flow():
    """
    Weekly refresh for deal disclosures, ETF flows, and options sentiment.
    Bulk deals accumulate through the week; ETF and P/C ratio trends
    are most meaningful on a weekly aggregation.
    Runs every Sunday at 02:00 UTC.
    """
    logger.info("=== [Institutional] Weekly Refresh ===")
    r1 = await task_bulk_deals()
    logger.info("Bulk deals: %s", r1)
    r2 = await task_sector_etfs()
    logger.info("Sector ETFs: %s", r2)
    r3 = await task_options_pc()
    logger.info("Options P/C: %s", r3)
    logger.info("=== [Institutional] Weekly Refresh Complete ===")


@flow(name="Institutional — Monthly (13F + Promoter Holdings)", log_prints=True)
async def institutional_monthly_flow():
    """
    Monthly fetch for quarterly-cadence filings.
    SEC 13F: filed within 45 days of quarter end.
    NSE Promoter holdings: quarterly shareholding pattern.
    Running monthly ensures filings are captured within 30 days of release.
    Runs on the 1st of each month at 03:00 UTC.
    """
    logger.info("=== [Institutional] Monthly Filings Refresh ===")
    r1 = await task_sec_13f()
    logger.info("SEC 13F: %s", r1)
    r2 = await task_promoter_holdings()
    logger.info("Promoter holdings: %s", r2)
    logger.info("=== [Institutional] Monthly Filings Refresh Complete ===")
