"""
orchestrator.py
===============
Composite ingestion flows — composes the six data-type flows into
time-based pipeline runs.

Each composite flow imports from the dedicated data-type modules and
calls their sub-flows in the correct dependency order.

Import map:
  prices_flow.py        → prices_*_flow()
  fundamentals_flow.py  → fundamentals_*_flow()
  macro_flow.py         → macro_*_flow()
  institutional_flow.py → institutional_*_flow()
  sentiment_flow.py     → sentiment_*_flow()
  computed_flow.py      → computed_*_flow()

──────────────────────────────────────────────────────────────
 FULL INITIAL LOAD  (run once — fresh install)
──────────────────────────────────────────────────────────────
  full_initial_load_flow()
      Bootstraps the entire database in correct dependency order:
        1. Prices       (max history — populates stocks table first)
        2. Fundamentals (needs tickers in DB)
        3. Macro        (independent)
        4. Institutional (independent)
        5. Sentiment    (needs tickers in DB)
        6. Computed     (needs price history + all above)

──────────────────────────────────────────────────────────────
 DAILY  (22:00 UTC weekdays — after both markets close)
──────────────────────────────────────────────────────────────
  daily_ingest_flow()
      Fast-moving data that changes every trading day:
        1. Macro (global only — VIX, Oil, Gold, INR)
        2. Institutional (FII/DII only)
        3. Sentiment (RSS + Reddit + Stocktwits)
        4. Computed (daily snapshot)
      Prices are already handled by prices_flow.py EOD deployments.

──────────────────────────────────────────────────────────────
 WEEKLY  (02:00 UTC Sundays)
──────────────────────────────────────────────────────────────
  weekly_ingest_flow()
      Slower-moving data meaningful at a weekly cadence:
        1. Fundamentals (new quarterly filings check)
        2. Macro (FRED + RBI series)
        3. Institutional (bulk deals + ETF flows + options P/C)
        4. Computed (chart regeneration)

──────────────────────────────────────────────────────────────
 MONTHLY  (03:00 UTC — 1st of every month)
──────────────────────────────────────────────────────────────
  monthly_ingest_flow()
      Quarterly-cadence filings; monthly check catches them within
      30 days of release:
        1. Institutional (SEC 13F + NSE promoter holdings)
──────────────────────────────────────────────────────────────
"""
import logging

from prefect import flow

# ── Data-type flow imports ─────────────────────────────────────────────────────
from app.flows.prices_flow import (
    prices_initial_flow,
)
from app.flows.fundamentals_flow import (
    fundamentals_initial_flow,
    fundamentals_weekly_flow,
)
from app.flows.macro_flow import (
    macro_initial_flow,
    macro_daily_flow,
    macro_weekly_flow,
)
from app.flows.institutional_flow import (
    institutional_initial_flow,
    institutional_daily_flow,
    institutional_weekly_flow,
    institutional_monthly_flow,
)
from app.flows.sentiment_flow import (
    sentiment_initial_flow,
    sentiment_daily_flow,
)
from app.flows.computed_flow import (
    computed_initial_flow,
    computed_daily_flow,
    computed_weekly_flow,
)

logger = logging.getLogger(__name__)


# ══════════════════════════════════════════════════════════════
# FULL INITIAL LOAD — run once on fresh install
# ══════════════════════════════════════════════════════════════

@flow(name="Full Initial Load — All Data Types", log_prints=True)
async def full_initial_load_flow():
    """
    One-time comprehensive bootstrap for a fresh database.
    Runs ALL six data-type initial flows in dependency order.
    Safe to re-run at any time — all writes are upserts.

    Estimated runtime on first run (1,200 stocks):
      Prices       — several hours (rate-limited yfinance, parallel workers)
      Fundamentals — 1–2 hours
      Macro        — 10–20 minutes
      Institutional — 20–40 minutes
      Sentiment    — 5–10 minutes
      Computed     — 10–20 minutes
    """
    logger.info("=" * 60)
    logger.info("  FULL INITIAL LOAD — ALL DATA TYPES")
    logger.info("=" * 60)

    logger.info("\n[1/6] ── PRICES ─────────────────────────────────────────")
    await prices_initial_flow()

    logger.info("\n[2/6] ── FUNDAMENTALS ───────────────────────────────────")
    await fundamentals_initial_flow()

    logger.info("\n[3/6] ── MACRO ──────────────────────────────────────────")
    await macro_initial_flow()

    logger.info("\n[4/6] ── INSTITUTIONAL ──────────────────────────────────")
    await institutional_initial_flow()

    logger.info("\n[5/6] ── SENTIMENT ──────────────────────────────────────")
    await sentiment_initial_flow()

    logger.info("\n[6/6] ── COMPUTED ───────────────────────────────────────")
    await computed_initial_flow()

    logger.info("\n" + "=" * 60)
    logger.info("  FULL INITIAL LOAD COMPLETE")
    logger.info("=" * 60)


# ══════════════════════════════════════════════════════════════
# DAILY — 22:00 UTC weekdays (after both markets close)
# ══════════════════════════════════════════════════════════════

@flow(name="Daily Ingest — Post-Market", log_prints=True)
async def daily_ingest_flow():
    """
    Runs nightly at 22:00 UTC on weekdays (03:30 IST next morning).
    Both India (NSE) and US (NYSE/NASDAQ) markets have settled by then.

    Data updated daily:
      1. Global macro  — VIX, Oil, Gold, INR/USD (period=2d)
      2. FII/DII flows — India institutional daily net flows
      3. Sentiment     — RSS news + Reddit + Stocktwits
      4. Snapshots     — today's point-in-time market state snapshot

    Prices are NOT in this flow — they are handled by the dedicated
    EOD price flows (prices_india_eod_flow, prices_us_eod_flow).
    """
    logger.info("=== DAILY INGEST — POST-MARKET ===")
    await macro_daily_flow()
    await institutional_daily_flow()
    await sentiment_daily_flow()
    await computed_daily_flow()
    logger.info("=== DAILY INGEST COMPLETE ===")


# ══════════════════════════════════════════════════════════════
# WEEKLY — 02:00 UTC every Sunday
# ══════════════════════════════════════════════════════════════

@flow(name="Weekly Ingest — Deep Refresh", log_prints=True)
async def weekly_ingest_flow():
    """
    Runs every Sunday at 02:00 UTC (07:30 IST Sunday morning).
    Both markets have been closed for over 24 hours.

    Data updated weekly:
      1. Fundamentals  — checks for new quarterly filings (>180 days old)
      2. FRED + RBI    — US and India macro series (monthly prints, weekly check)
      3. Bulk deals    — NSE bulk/block deal disclosures for the week
      4. Sector ETFs   — sector rotation proxy flows
      5. Options P/C   — Put/Call ratio refresh for HIGH-tier US equities
      6. Charts        — regenerate mplfinance charts with latest price action
    """
    logger.info("=== WEEKLY INGEST — DEEP REFRESH ===")
    await fundamentals_weekly_flow()
    await macro_weekly_flow()
    await institutional_weekly_flow()
    await computed_weekly_flow()
    logger.info("=== WEEKLY INGEST COMPLETE ===")


# ══════════════════════════════════════════════════════════════
# MONTHLY — 03:00 UTC on the 1st of every month
# ══════════════════════════════════════════════════════════════

@flow(name="Monthly Ingest — Quarterly Filings", log_prints=True)
async def monthly_ingest_flow():
    """
    Runs on the 1st of each month at 03:00 UTC (08:30 IST).
    Targets quarterly-cadence filings that don't fit a weekly schedule.

    Data updated monthly:
      1. SEC 13F filings     — US institutional holdings (quarterly, 45-day lag)
      2. Promoter holdings   — NSE shareholding pattern (quarterly)

    Running monthly ensures filings are captured within 30 days of release,
    regardless of which quarter they belong to.
    """
    logger.info("=== MONTHLY INGEST — QUARTERLY FILINGS ===")
    await institutional_monthly_flow()
    logger.info("=== MONTHLY INGEST COMPLETE ===")
