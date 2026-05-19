"""
run_initial_load.py
====================
Manual trigger for the one-time comprehensive data bootstrap.

Runs ALL data types in dependency order (via orchestrator.py):
  1. Prices       (max history — HIGH → MEDIUM → LOW)
  2. Fundamentals (income statement, balance sheet, cash flow)
  3. Macro        (US FRED + India RBI/CPI + Global yfinance)
  4. Institutional (FII/DII, bulk deals, 13F, options, ETFs, promoter)
  5. Sentiment    (RSS, Reddit, Stocktwits)
  6. Computed     (mplfinance charts + market snapshots)

For ongoing automated ingestion, run deploy_and_serve.py instead.
"""
import asyncio
from app.flows.orchestrator import full_initial_load_flow

if __name__ == "__main__":
    asyncio.run(full_initial_load_flow())
