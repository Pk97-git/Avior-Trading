"""
computed_flow.py
================
All derived / computed data: tasks + flows.

Data type : Outputs derived from ingested raw data — not raw source fetches.
            These run AFTER the raw data layers have been populated.

Sub-categories:
  Charts   — mplfinance candlestick charts (6M, 1Y, 5Y) for HIGH-tier
              equities. Used by the Vision Agent (Phase 3) for
              pattern recognition. Crypto, futures, and indices excluded.
              Capped at 20 charts per run (chart generation is CPU-bound).

  Snapshots — Point-in-time snapshots of the combined market state
              (price, fundamentals, macro, sentiment scores) stored in
              the market_snapshots table + pgvector embeddings.
              Used by the Historical Memory Agent (Phase 3) for
              analog-finding and regime similarity search.

──────────────────────────────────────────────────────────────
 HISTORICAL (initial / backfill)
──────────────────────────────────────────────────────────────
  computed_initial_flow()
      Generates the first set of charts and today's market snapshot.
      Run after price history + fundamentals + macro are populated.

──────────────────────────────────────────────────────────────
 INCREMENTAL (scheduled)
──────────────────────────────────────────────────────────────
  computed_daily_flow()    ← nightly (22:00 UTC weekdays)
      Market snapshots only — captures the daily state of the market
      after all price, macro, and sentiment data for the day is ingested.

  computed_weekly_flow()   ← every Sunday (02:00 UTC)
      Regenerates charts — weekly ensures charts reflect the latest
      price action and structural changes without running every day.
──────────────────────────────────────────────────────────────
"""
import logging
import time
from datetime import datetime, timezone

from prefect import task, flow

from app.db.session import AsyncSessionLocal
from app.ingestion.infra.universe import UniverseManager
from app.ingestion.computed.charts import ChartGenerationService
from app.ingestion.computed.features import MarketSnapshotService
from app.ingestion.computed.technicals import TechnicalIndicatorService
from app.ingestion.computed.candlesticks import CandlestickPatternService
from app.ingestion.computed.valuations import ValuationService

logger = logging.getLogger(__name__)

_NON_CHART_SUFFIXES = ("-USD", "=F", ".NYB")
_CHARTS_PER_RUN = 20   # Chart generation is CPU-bound; cap per run


def _chart_tickers() -> list:
    """HIGH-tier equity tickers suitable for candlestick chart generation."""
    mgr = UniverseManager(use_cache=True, cache_ttl_hours=24)
    return [
        t for t in mgr.get_all_tickers("HIGH")
        if not any(t.endswith(x) for x in _NON_CHART_SUFFIXES) and "^" not in t
    ]


# ══════════════════════════════════════════════════════════════
# TASKS
# ══════════════════════════════════════════════════════════════

@task(name="Computed — Generate mplfinance Charts", retries=1)
async def task_charts() -> dict:
    """
    Generates 6M / 1Y / 5Y candlestick charts for up to 20 HIGH-tier
    equity tickers using mplfinance. Charts are stored for the Vision
    Agent (Phase 3) to perform image-based pattern recognition.

    The cap of 20 per run is intentional — chart generation is
    CPU-bound and would dominate the process if uncapped.
    The 20 tickers are the first returned by the universe manager
    (ranked by priority), so the most important stocks are always covered.
    """
    tickers = _chart_tickers()[:_CHARTS_PER_RUN]
    _t = time.monotonic()
    async with AsyncSessionLocal() as session:
        svc = ChartGenerationService(session)
        await svc.generate_all(tickers)
    return {"charts": len(tickers), "duration_s": round(time.monotonic() - _t, 1)}


@task(name="Computed — Market Snapshots", retries=1)
async def task_snapshots() -> dict:
    """
    Stores a point-in-time market snapshot for today's date.
    Captures the combined state of: price action, fundamentals,
    macro regime, and sentiment scores into the market_snapshots table.
    Also generates pgvector embeddings for Historical Memory Agent analog-search.
    """
    _t = time.monotonic()
    async with AsyncSessionLocal() as session:
        svc = MarketSnapshotService(session)
        today = datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)
        await svc.store_snapshot(today)
    return {"snapshot_date": today.date().isoformat(),
            "duration_s": round(time.monotonic() - _t, 1)}


@task(name="Computed — Technical Indicators", retries=1)
async def task_technicals(start_date=None) -> dict:
    """
    Computes SMA 20/50/200, EMA 9/21, RSI 14, MACD, ATR 14, Bollinger Bands,
    volume ratio, 52-week high/low, and RS vs benchmark for all HIGH + MEDIUM
    equity tickers. Upserts into stock_technicals table.

    start_date=None  → full backfill (initial load)
    start_date=today → incremental (only today's values)
    """
    from app.ingestion.infra.universe import UniverseManager
    mgr = UniverseManager(use_cache=True, cache_ttl_hours=24)
    _NON_EQUITY = ("-USD", "=F", ".NYB")
    tickers = [
        t for t in mgr.get_all_tickers("MEDIUM")
        if not any(t.endswith(x) for x in _NON_EQUITY) and "^" not in t
    ]
    _t = time.monotonic()
    async with AsyncSessionLocal() as session:
        svc = TechnicalIndicatorService(session)
        result = await svc.run_batch(tickers, start_date=start_date)
    return {**result, "duration_s": round(time.monotonic() - _t, 1)}


# ══════════════════════════════════════════════════════════════
# HISTORICAL — run once on fresh install
# ══════════════════════════════════════════════════════════════

@flow(name="Computed — Initial Load", log_prints=True)
async def computed_initial_flow():
    """
    Generates the first batch of charts and records today's market snapshot.
    Must be run AFTER prices, fundamentals, macro, and sentiment are populated.
    """
    logger.info("=== [Computed] Initial Load ===")
    r1 = await task_charts()
    logger.info("Charts: %s", r1)
    r2 = await task_snapshots()
    logger.info("Snapshots: %s", r2)
    r3 = await task_technicals(start_date=None)
    logger.info("Technicals (full backfill): %s", r3)
    r4 = await task_candlesticks()
    logger.info("Candlestick patterns: %s", r4)
    r5 = await task_valuations()
    logger.info("Valuation models: %s", r5)
    logger.info("=== [Computed] Initial Load Complete ===")


# ══════════════════════════════════════════════════════════════
# INCREMENTAL — scheduled recurring
# ══════════════════════════════════════════════════════════════

@flow(name="Computed — Daily Snapshots", log_prints=True)
async def computed_daily_flow():
    """
    Records today's market snapshot after all daily data is ingested.
    Runs nightly at 22:00 UTC (weekdays), as the last step in the
    daily pipeline — after prices, macro, FII/DII, and sentiment.
    """
    logger.info("=== [Computed] Daily Snapshots ===")
    result = await task_snapshots()
    logger.info("Snapshots: %s", result)
    from datetime import date as _date
    today = _date.today()
    result2 = await task_technicals(start_date=today)
    logger.info("Technicals (today): %s", result2)
    result3 = await task_candlesticks(start_date=today)
    logger.info("Candlesticks (today): %s", result3)
    logger.info("=== [Computed] Daily Snapshots Complete ===")


@task(name="Computed — Candlestick Patterns", retries=1)
async def task_candlesticks(start_date=None) -> dict:
    """
    Detects 15 candlestick patterns (Doji, Hammer, Engulfing, etc.) for all
    HIGH+MEDIUM equity tickers. Upserts results into candlestick_patterns table.
    """
    from app.ingestion.infra.universe import UniverseManager
    mgr = UniverseManager(use_cache=True, cache_ttl_hours=24)
    _NON_EQUITY = ("-USD", "=F", ".NYB")
    tickers = [
        t for t in mgr.get_all_tickers("MEDIUM")
        if not any(t.endswith(x) for x in _NON_EQUITY) and "^" not in t
    ]
    _t = time.monotonic()
    async with AsyncSessionLocal() as session:
        svc = CandlestickPatternService(session)
        result = await svc.run_batch(tickers, start_date=start_date)
    return {**result, "duration_s": round(time.monotonic() - _t, 1)}


@task(name="Computed — Valuation Models", retries=1)
async def task_valuations() -> dict:
    """
    Computes DCF intrinsic value, EV/EBITDA, P/B, P/S, PEG, margin of safety,
    and composite valuation score for all HIGH-tier equities. Upserts to
    valuation_metrics table.
    """
    from app.ingestion.infra.universe import UniverseManager
    mgr = UniverseManager(use_cache=True, cache_ttl_hours=24)
    tickers = mgr.get_all_tickers("HIGH")
    _t = time.monotonic()
    async with AsyncSessionLocal() as session:
        svc = ValuationService(session)
        result = await svc.run_batch(tickers)
    return {**result, "duration_s": round(time.monotonic() - _t, 1)}


@flow(name="Computed — Weekly Charts", log_prints=True)
async def computed_weekly_flow():
    """
    Regenerates mplfinance charts for the top 20 HIGH-tier equities.
    Weekly cadence ensures charts reflect the latest price structure
    without the overhead of running chart generation every day.
    Runs every Sunday at 02:00 UTC.
    """
    logger.info("=== [Computed] Weekly Chart Regeneration ===")
    result = await task_charts()
    logger.info("Charts: %s", result)
    r2 = await task_candlesticks()
    logger.info("Candlesticks: %s", r2)
    r3 = await task_valuations()
    logger.info("Valuations: %s", r3)
    logger.info("=== [Computed] Weekly Chart Regeneration Complete ===")
