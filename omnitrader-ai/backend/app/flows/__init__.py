"""
app/flows — public API
======================
Consumers (deploy_and_serve.py, api/ingestion.py, run_initial_load.py)
should import exclusively from this module.  Internal data-type files
(prices_flow.py, macro_flow.py, …) are implementation details.

Public flows
────────────
Orchestrator (composite):
  full_initial_load_flow   — one-time bootstrap of all data types
  daily_ingest_flow        — nightly post-market (macro, FII/DII, sentiment, snapshot)
  weekly_ingest_flow       — Sunday deep refresh (fundamentals, FRED, institutional, charts)
  monthly_ingest_flow      — 1st-of-month quarterly filings (13F, promoter)

Prices (scheduled individually):
  prices_initial_flow      — one-time full-history backfill, all tiers
  prices_intraday_flow     — HIGH-tier refresh during live sessions (5× per weekday)
  prices_india_eod_flow    — HIGH + MEDIUM after NSE close
  prices_us_eod_flow       — HIGH + MEDIUM after NYSE close
  prices_nightly_gap_fill_flow — all tiers, nightly gap detection + fill
"""

# ── Orchestrator (composite) ───────────────────────────────────────────────────
from app.flows.orchestrator import (
    full_initial_load_flow,
    daily_ingest_flow,
    weekly_ingest_flow,
    monthly_ingest_flow,
)

# ── Price flows (independently scheduled) ─────────────────────────────────────
from app.flows.prices_flow import (
    prices_initial_flow,
    prices_intraday_flow,
    prices_india_eod_flow,
    prices_us_eod_flow,
    prices_nightly_gap_fill_flow,
)

__all__ = [
    # Orchestrator
    "full_initial_load_flow",
    "daily_ingest_flow",
    "weekly_ingest_flow",
    "monthly_ingest_flow",
    # Prices
    "prices_initial_flow",
    "prices_intraday_flow",
    "prices_india_eod_flow",
    "prices_us_eod_flow",
    "prices_nightly_gap_fill_flow",
]
