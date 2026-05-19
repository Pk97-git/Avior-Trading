"""
agents_flow.py
==============
Prefect batch scoring flow — runs all 5 agents + ExecutiveTrader for
every HIGH-tier ticker and persists results to ai_analysis + alerts.

Schedule: 23:00 UTC weekdays (1 hour after daily ingestion completes).

──────────────────────────────────────────────────────────────
 BATCH SCORING
──────────────────────────────────────────────────────────────
  agents_daily_flow()
      Fetches all HIGH-tier equity tickers.
      Runs run_all_agents() for each ticker sequentially.
      (Sequential to avoid overwhelming the DB with concurrent sessions.)
      Logs a summary: N scored, M new alerts generated.
──────────────────────────────────────────────────────────────
"""
import logging
import time

from prefect import task, flow

from app.db.session import AsyncSessionLocal
from app.ingestion.infra.universe import UniverseManager
from app.agents.runner import run_all_agents

logger = logging.getLogger(__name__)

_NON_EQUITY_SUFFIXES = ("-USD", "=F", ".NYB")


def _equity_tickers_high() -> list[str]:
    """HIGH-tier equity tickers only (no crypto, futures, or indices)."""
    mgr = UniverseManager(use_cache=True, cache_ttl_hours=24)
    return [
        t for t in mgr.get_all_tickers("HIGH")
        if not any(t.endswith(x) for x in _NON_EQUITY_SUFFIXES) and "^" not in t
    ]


@task(name="Agents — Score Ticker", retries=1, retry_delay_seconds=10)
async def task_score_ticker(ticker: str) -> dict:
    """Run all agents for a single ticker and persist the result."""
    async with AsyncSessionLocal() as session:
        result = await run_all_agents(session, ticker)
    return {
        "ticker":      ticker,
        "signal":      result.get("signal"),
        "final_score": result.get("final_score"),
    }


@flow(name="Agents — Daily Batch Scoring", log_prints=True)
async def agents_daily_flow() -> dict:
    """
    Score all HIGH-tier equity tickers. Runs after daily ingestion (23:00 UTC).
    Returns a summary dict with counts.
    """
    tickers = _equity_tickers_high()
    logger.info("=== [Agents] Daily Batch Scoring — %d tickers ===", len(tickers))

    scored = 0
    failed = []
    signal_counts: dict[str, int] = {}
    _t = time.monotonic()

    for ticker in tickers:
        try:
            result = await task_score_ticker(ticker)
            scored += 1
            sig = result.get("signal") or "UNKNOWN"
            signal_counts[sig] = signal_counts.get(sig, 0) + 1
        except Exception as e:
            logger.error("Batch scoring failed for %s: %s", ticker, e)
            failed.append(ticker)

    elapsed = round(time.monotonic() - _t, 1)
    summary = {
        "scored":        scored,
        "failed":        len(failed),
        "signal_counts": signal_counts,
        "duration_s":    elapsed,
    }

    if failed:
        logger.warning("Batch scoring: %d tickers failed: %s", len(failed), failed)
    logger.info("=== [Agents] Batch Scoring Complete: %s ===", summary)
    return summary
