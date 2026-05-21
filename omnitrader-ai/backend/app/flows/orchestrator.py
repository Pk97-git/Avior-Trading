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
from app.flows.analysts_flow import analysts_initial_flow, analysts_daily_flow, analysts_weekly_flow
from app.flows.insiders_flow import insiders_initial_flow, insiders_daily_flow
from app.flows.intraday_flow import intraday_initial_flow
from app.flows.corporate_actions_flow import corporate_actions_initial_flow, corporate_actions_weekly_flow
from app.flows.mutual_funds_flow import mutual_funds_initial_flow, mutual_funds_daily_flow
from app.flows.sec_filings_flow import sec_filings_initial_flow, sec_filings_weekly_flow, sec_filings_monthly_flow
from app.flows.us_options_flow import us_options_initial_flow, us_options_daily_flow
from app.flows.alternative_data_flow import (
    alternative_data_initial_flow, alternative_data_daily_flow, alternative_data_weekly_flow
)
from app.flows.pair_trading_flow import pair_trading_initial_flow, pair_trading_weekly_flow
from app.flows.transcripts_flow import transcripts_initial_flow, transcripts_daily_flow

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

    logger.info("\n[1/8] ── PRICES ─────────────────────────────────────────")
    await prices_initial_flow()

    logger.info("\n[2/8] ── FUNDAMENTALS ───────────────────────────────────")
    await fundamentals_initial_flow()

    logger.info("\n[3/8] ── MACRO ──────────────────────────────────────────")
    await macro_initial_flow()

    logger.info("\n[4/8] ── INSTITUTIONAL ──────────────────────────────────")
    await institutional_initial_flow()

    logger.info("\n[5/8] ── SENTIMENT ──────────────────────────────────────")
    await sentiment_initial_flow()

    logger.info("\n[6/8] ── INSIDERS ───────────────────────────────────────")
    await insiders_initial_flow()

    logger.info("\n[7/8] ── ANALYSTS ───────────────────────────────────────")
    await analysts_initial_flow()

    logger.info("\n[8/8] ── COMPUTED ───────────────────────────────────────")
    await computed_initial_flow()

    logger.info("\n[9/11] ── INTRADAY 15M BARS ────────────────────────────")
    try:
        await intraday_initial_flow()
    except Exception as e:
        logger.error("[Initial] Intraday bars failed: %s", e)

    logger.info("\n[10/11] ── INDIA CORPORATE ACTIONS ─────────────────────")
    try:
        await corporate_actions_initial_flow()
    except Exception as e:
        logger.error("[Initial] Corporate actions failed: %s", e)

    logger.info("\n[11/13] ── MUTUAL FUND NAV ──────────────────────────────")
    try:
        await mutual_funds_initial_flow()
    except Exception as e:
        logger.error("[Initial] Mutual fund NAV failed: %s", e)

    logger.info("\n[12/13] ── SEC FILINGS (10-K/10-Q) ──────────────────────")
    try:
        await sec_filings_initial_flow()
    except Exception as e:
        logger.error("[Initial] SEC filings failed: %s", e)

    logger.info("\n[13/13] ── ALTERNATIVE DATA (RBI + TRENDS) ───────────────")
    try:
        await alternative_data_initial_flow()
    except Exception as e:
        logger.error("[Initial] Alternative data failed: %s", e)

    logger.info("\n[14/15] ── PAIR TRADING (COINTEGRATION SCAN) ─────────────")
    try:
        await pair_trading_initial_flow()
    except Exception as e:
        logger.error("[Initial] Pair trading scan failed: %s", e)

    logger.info("\n[15/15] ── EARNINGS TRANSCRIPTS + EVENT EXTRACTION ────────")
    try:
        await transcripts_initial_flow()
    except Exception as e:
        logger.error("[Initial] Transcripts/event extraction failed: %s", e)

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

    # Insider transactions + analyst ratings (daily refresh)
    try:
        await insiders_daily_flow()
        await analysts_daily_flow()
    except Exception as e:
        logger.error("[Daily] Insider/Analyst refresh failed: %s", e)

    # Mutual fund NAV (daily — AMFI publishes after market close)
    try:
        await mutual_funds_daily_flow()
    except Exception as e:
        logger.error("[Daily] Mutual fund NAV failed: %s", e)

    # RBI announcements + US options chain (daily)
    try:
        await alternative_data_daily_flow()
        await us_options_daily_flow()
    except Exception as e:
        logger.error("[Daily] Alternative data / US options failed: %s", e)

    # Earnings transcripts + event type classification (daily — catch new 8-K filings)
    try:
        await transcripts_daily_flow()
    except Exception as e:
        logger.error("[Daily] Transcripts/event extraction failed: %s", e)

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
    # Analyst ratings + short interest weekly refresh
    try:
        await analysts_weekly_flow()
        logger.info("[Weekly] Analysts + short interest refreshed.")
    except Exception as e:
        logger.error("[Weekly] Analysts/short interest failed: %s", e)

    # India corporate actions — splits, bonuses, rights
    try:
        await corporate_actions_weekly_flow()
        logger.info("[Weekly] Corporate actions refreshed.")
    except Exception as e:
        logger.error("[Weekly] Corporate actions failed: %s", e)

    # SEC 10-K/10-Q filings weekly check
    try:
        await sec_filings_weekly_flow()
        logger.info("[Weekly] SEC filings refreshed.")
    except Exception as e:
        logger.error("[Weekly] SEC filings failed: %s", e)

    # Google Trends (rate-limited — weekly cadence)
    try:
        await alternative_data_weekly_flow()
        logger.info("[Weekly] Google Trends refreshed.")
    except Exception as e:
        logger.error("[Weekly] Google Trends failed: %s", e)

    # Pair trading cointegration scan (weekly — re-evaluate all sector pairs)
    try:
        await pair_trading_weekly_flow()
        logger.info("[Weekly] Pair trading signals refreshed.")
    except Exception as e:
        logger.error("[Weekly] Pair trading scan failed: %s", e)

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

    # SEC filings monthly broad sweep (all US equities)
    try:
        await sec_filings_monthly_flow()
        logger.info("[Monthly] SEC filings broad sweep complete.")
    except Exception as e:
        logger.error("[Monthly] SEC filings broad sweep failed: %s", e)

    logger.info("=== MONTHLY INGEST COMPLETE ===")
