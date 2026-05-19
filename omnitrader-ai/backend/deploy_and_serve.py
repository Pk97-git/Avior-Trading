"""
deploy_and_serve.py
===================
Main entry point for all OmniTrader AI Prefect background schedules.
Keep this process running 24/7 in a dedicated terminal.

═══════════════════════════════════════════════════════════════════
 PRICES  (prices_flow.py)
═══════════════════════════════════════════════════════════════════
 Nightly    00:00 UTC  Gap fill          (all 3 tiers, fills missed days)
 09:00 IST  03:30 UTC  Intraday #1       (India open — HIGH only)
 11:00 IST  05:30 UTC  Intraday #2       (India mid — HIGH only)
 16:15 IST  10:45 UTC  India EOD         (NSE close — HIGH + MEDIUM)
 19:30 IST  14:00 UTC  Intraday #3       (US open — HIGH only)
 21:30 IST  16:00 UTC  Intraday #4       (US mid — HIGH only)
 23:30 IST  18:00 UTC  Intraday #5       (US afternoon — HIGH only)
 02:30 IST  21:00 UTC  US EOD            (NYSE close — HIGH + MEDIUM)

═══════════════════════════════════════════════════════════════════
 DAILY POST-MARKET  (orchestrator.py — daily_ingest_flow)
 22:00 UTC weekdays = 03:30 IST next morning
═══════════════════════════════════════════════════════════════════
   macro_daily_flow          Global macro (VIX, Oil, Gold, INR/USD)
   institutional_daily_flow  FII/DII net flows
   sentiment_daily_flow      RSS + Reddit + Stocktwits
   computed_daily_flow       Market snapshots / embeddings

═══════════════════════════════════════════════════════════════════
 WEEKLY  (orchestrator.py — weekly_ingest_flow)
 02:00 UTC every Sunday = 07:30 IST Sunday
═══════════════════════════════════════════════════════════════════
   fundamentals_weekly_flow  New quarterly filings check
   macro_weekly_flow         FRED + RBI series
   institutional_weekly_flow Bulk deals + ETF flows + Options P/C
   computed_weekly_flow      Chart regeneration

═══════════════════════════════════════════════════════════════════
 MONTHLY  (orchestrator.py — monthly_ingest_flow)
 03:00 UTC on 1st of each month = 08:30 IST
═══════════════════════════════════════════════════════════════════
   institutional_monthly_flow  SEC 13F filings + NSE promoter holdings
═══════════════════════════════════════════════════════════════════

═══════════════════════════════════════════════════════════════════
 AGENTS  (agents_flow.py — agents_daily_flow)
 23:00 UTC weekdays = 04:30 IST next morning (after ingestion)
═══════════════════════════════════════════════════════════════════
   agents_daily_flow  Score all HIGH-tier equities, generate alerts
═══════════════════════════════════════════════════════════════════
"""
from prefect import serve

# ── Price flows (prices_flow.py) ──────────────────────────────────────────────
from app.flows.prices_flow import (
    prices_nightly_gap_fill_flow,
    prices_intraday_flow,
    prices_india_eod_flow,
    prices_us_eod_flow,
)

# ── Composite flows (orchestrator.py) ─────────────────────────────────────────
from app.flows.orchestrator import (
    daily_ingest_flow,
    weekly_ingest_flow,
    monthly_ingest_flow,
)

# ── Agent scoring (agents_flow.py) ────────────────────────────────────────────
from app.flows.agents_flow import agents_daily_flow

# ── DB Backup (backup_flow.py) ─────────────────────────────────────────────────
from app.flows.backup_flow import weekly_db_backup_flow

if __name__ == "__main__":
    print("=== OmniTrader AI — Starting Prefect Scheduler ===\n")

    # ═══════════════════════════════════════════════════════════
    # PRICE SCHEDULES
    # ═══════════════════════════════════════════════════════════

    gap_fill = prices_nightly_gap_fill_flow.to_deployment(
        name="prices-nightly-gap-fill",
        cron="0 0 * * *",
        description="Nightly: detect and fill price gaps across all 3 tiers"
    )
    intraday_india_open = prices_intraday_flow.to_deployment(
        name="prices-intraday-india-open",
        cron="30 3 * * 1-5",
        description="Intraday refresh — India open (09:00 IST)"
    )
    intraday_india_mid = prices_intraday_flow.to_deployment(
        name="prices-intraday-india-mid",
        cron="30 5 * * 1-5",
        description="Intraday refresh — India mid-session (11:00 IST)"
    )
    intraday_us_open = prices_intraday_flow.to_deployment(
        name="prices-intraday-us-open",
        cron="0 14 * * 1-5",
        description="Intraday refresh — US open (19:30 IST)"
    )
    intraday_us_mid = prices_intraday_flow.to_deployment(
        name="prices-intraday-us-mid",
        cron="0 16 * * 1-5",
        description="Intraday refresh — US mid-session (21:30 IST)"
    )
    intraday_us_afternoon = prices_intraday_flow.to_deployment(
        name="prices-intraday-us-afternoon",
        cron="0 18 * * 1-5",
        description="Intraday refresh — US afternoon (23:30 IST)"
    )
    india_eod = prices_india_eod_flow.to_deployment(
        name="prices-india-eod",
        cron="45 10 * * 1-5",
        description="India EOD sync — 45 min after NSE close (16:15 IST)"
    )
    us_eod = prices_us_eod_flow.to_deployment(
        name="prices-us-eod",
        cron="0 21 * * 1-5",
        description="US EOD sync — 30 min after NYSE close (02:30 IST)"
    )

    # ═══════════════════════════════════════════════════════════
    # COMPREHENSIVE INGESTION SCHEDULES
    # ═══════════════════════════════════════════════════════════

    daily = daily_ingest_flow.to_deployment(
        name="daily-post-market",
        cron="0 22 * * 1-5",
        description="Post-market daily: macro, FII/DII, sentiment, snapshots"
    )
    weekly = weekly_ingest_flow.to_deployment(
        name="weekly-deep-refresh",
        cron="0 2 * * 0",
        description="Weekly: fundamentals, FRED/RBI, bulk deals, ETFs, options, charts"
    )
    monthly = monthly_ingest_flow.to_deployment(
        name="monthly-filings-refresh",
        cron="0 3 1 * *",
        description="Monthly: SEC 13F filings, NSE promoter holdings"
    )
    agents_daily = agents_daily_flow.to_deployment(
        name="agents-daily-scoring",
        cron="0 23 * * 1-5",
        description="Daily agent scoring: all HIGH-tier equities → signals + alerts"
    )
    weekly_backup = weekly_db_backup_flow.to_deployment(
        name="weekly-db-backup",
        cron="30 0 * * 0",   # Sunday 00:30 UTC = 06:00 IST
        description="Weekly: dump all DB tables to compressed CSV backups (keeps 4 weeks)"
    )

    # ═══════════════════════════════════════════════════════════
    # SERVE ALL
    # ═══════════════════════════════════════════════════════════

    print("[Prices]")
    print("  [00:00 UTC daily]     prices-nightly-gap-fill")
    print("  [03:30 UTC weekdays]  prices-intraday-india-open")
    print("  [05:30 UTC weekdays]  prices-intraday-india-mid")
    print("  [10:45 UTC weekdays]  prices-india-eod")
    print("  [14:00 UTC weekdays]  prices-intraday-us-open")
    print("  [16:00 UTC weekdays]  prices-intraday-us-mid")
    print("  [18:00 UTC weekdays]  prices-intraday-us-afternoon")
    print("  [21:00 UTC weekdays]  prices-us-eod")
    print()
    print("[Comprehensive Data]")
    print("  [22:00 UTC weekdays]   daily-post-market        (macro+FII/DII+sentiment+snapshots)")
    print("  [02:00 UTC Sundays]    weekly-deep-refresh      (fundamentals+FRED+institutional+charts)")
    print("  [03:00 UTC 1st/month]  monthly-filings-refresh  (13F+promoter)")
    print()
    print("[Agents]")
    print("  [23:00 UTC weekdays]   agents-daily-scoring     (5-agent score → signals + alerts)")
    print()
    print("[Backup]")
    print("  [00:30 UTC Sundays]    weekly-db-backup         (compressed CSV → backups/ folder, 4-week retention)")
    print()
    print("Serving — press Ctrl+C to stop.\n")

    serve(
        gap_fill,
        intraday_india_open,
        intraday_india_mid,
        intraday_us_open,
        intraday_us_mid,
        intraday_us_afternoon,
        india_eod,
        us_eod,
        daily,
        weekly,
        monthly,
        agents_daily,
        weekly_backup,
    )
