"""
price_ingestion_flow.py — re-export shim
=========================================
Price flows have moved to prices_flow.py.
This module re-exports them under their original names so that
deploy_and_serve.py and any other existing imports continue to work.

Canonical file: app/flows/prices_flow.py
"""
import asyncio
from app.flows.prices_flow import (
    prices_initial_flow          as initial_backfill_flow,
    prices_intraday_flow         as intraday_refresh_flow,
    prices_india_eod_flow        as india_eod_flow,
    prices_us_eod_flow           as us_eod_flow,
    prices_nightly_gap_fill_flow,
)

__all__ = [
    "initial_backfill_flow",
    "intraday_refresh_flow",
    "india_eod_flow",
    "us_eod_flow",
    "prices_nightly_gap_fill_flow",
]

if __name__ == "__main__":
    asyncio.run(initial_backfill_flow())
