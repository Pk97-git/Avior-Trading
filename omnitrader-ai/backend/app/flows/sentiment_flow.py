"""
sentiment_flow.py
=================
All news and market sentiment ingestion: tasks + flows.

Data type : Headline sentiment scores attached to tickers
Sources   : RSS feeds, Reddit public API, Stocktwits public API
Scoring   : Rule-based keyword matching (Phase 1)
            Gemini Pro / OpenAI LLM batch scoring (Phase 4, if key set)

Sub-categories:
  RSS     — Moneycontrol, CNBC, Reuters Markets, Economic Times,
             Livemint, BBC Business
            Extracts ticker mentions from headlines; scores sentiment.
            Covers both US and India markets.

  Reddit  — r/investing, r/stocks, r/IndiaInvestments, r/IndianStockMarket
            Public JSON API — no auth needed.
            Filters posts with < 10 upvotes (low-signal noise).
            Maps to index tickers (^GSPC or ^NSEI) by subreddit.

  Stocktwits — Per-ticker message stream for US equities in HIGH tier.
               Excludes India (.NS/.BO), crypto (-USD), futures (=F),
               and indices (^) — Stocktwits uses plain US ticker symbols.

──────────────────────────────────────────────────────────────
 HISTORICAL (initial / backfill)
──────────────────────────────────────────────────────────────
  sentiment_initial_flow()
      Fetches the current-window data from all three sources.
      Note: RSS/Reddit/Stocktwits APIs only return recent data
      (no historical archive). Historical sentiment = what was
      collected during the initial ingestion run.
      Run as early as possible in the overall setup to start
      building the sentiment time series.

──────────────────────────────────────────────────────────────
 INCREMENTAL (scheduled — every weekday, 22:00 UTC)
──────────────────────────────────────────────────────────────
  sentiment_daily_flow()
      Fetches fresh headlines and social posts after both markets
      have closed. Builds the daily sentiment time series that the
      Sentiment Agent uses for score calculation.
──────────────────────────────────────────────────────────────
"""
import logging
import time

from prefect import task, flow

from app.db.session import AsyncSessionLocal
from app.ingestion.infra.universe import UniverseManager
from app.ingestion.infra.rate_limiter import RateLimiterRegistry
from app.ingestion.sentiment.feeds import SentimentService

logger = logging.getLogger(__name__)


def _known_ticker_symbols() -> list:
    """
    Strips exchange suffixes from HIGH-tier tickers to build a clean
    symbol list for ticker-mention extraction from news headlines.
    e.g. RELIANCE.NS → RELIANCE, BTC-USD → BTC, ^NSEI → NSEI
    """
    mgr = UniverseManager(use_cache=True, cache_ttl_hours=24)
    raw = mgr.get_all_tickers("HIGH")
    return [
        t.replace(".NS", "").replace(".BO", "").replace("-USD", "").replace("^", "")
        for t in raw
    ]


def _us_equity_tickers() -> list:
    """HIGH-tier US equities only (Stocktwits doesn't know .NS/.BO/^/futures)."""
    mgr = UniverseManager(use_cache=True, cache_ttl_hours=24)
    return [
        t for t in mgr.get_all_tickers("HIGH")
        if not any(t.endswith(x) for x in ("-USD", "=F", ".NS", ".BO", ".NYB"))
        and "^" not in t
    ]


# ══════════════════════════════════════════════════════════════
# TASKS
# ══════════════════════════════════════════════════════════════

@task(name="Sentiment — RSS News Feeds", retries=1)
async def task_sentiment_rss() -> dict:
    """
    Parses the six RSS feeds and scores each headline.
    Ticker mentions are extracted using regex word-boundary matching
    against the full HIGH-tier universe (with suffixes stripped).
    Headlines with no ticker match are tagged as 'MARKET'.
    """
    known = _known_ticker_symbols()
    _t = time.monotonic()
    async with AsyncSessionLocal() as session:
        await RateLimiterRegistry.acquire("default")
        svc = SentimentService(session)
        await svc.fetch_rss_news(known_tickers=known)
    return {"source": "RSS", "symbols": len(known),
            "duration_s": round(time.monotonic() - _t, 1)}


@task(name="Sentiment — Reddit", retries=1)
async def task_sentiment_reddit() -> dict:
    """
    Fetches the 'hot' posts from investing subreddits.
    Uses Reddit's public JSON endpoint (no OAuth).
    Posts are mapped to ^GSPC (US) or ^NSEI (India) by subreddit.
    """
    _t = time.monotonic()
    async with AsyncSessionLocal() as session:
        await RateLimiterRegistry.acquire("reddit")
        svc = SentimentService(session)
        await svc.fetch_reddit_sentiment()
    return {"source": "Reddit", "duration_s": round(time.monotonic() - _t, 1)}


@task(name="Sentiment — Stocktwits", retries=1)
async def task_sentiment_stocktwits() -> dict:
    """
    Fetches Stocktwits message stream for US equity tickers in HIGH tier.
    Each message carries a Bullish / Bearish / Neutral tag from the user.
    India tickers are excluded — Stocktwits uses plain US symbols only.
    """
    tickers = _us_equity_tickers()
    _t = time.monotonic()
    async with AsyncSessionLocal() as session:
        svc = SentimentService(session)
        await svc.fetch_stocktwits_sentiment(tickers)
    return {"source": "Stocktwits", "tickers": len(tickers),
            "duration_s": round(time.monotonic() - _t, 1)}


# ══════════════════════════════════════════════════════════════
# HISTORICAL — run once on fresh install
# ══════════════════════════════════════════════════════════════

@flow(name="Sentiment — Initial Load", log_prints=True)
async def sentiment_initial_flow():
    """
    Bootstraps the sentiment database with the earliest available data
    from all three sources. RSS/Reddit/Stocktwits only expose current
    windows, so this captures the starting point of the time series.
    Run as early as possible in the overall setup sequence.
    """
    logger.info("=== [Sentiment] Initial Load ===")
    r1 = await task_sentiment_rss()
    logger.info("RSS: %s", r1)
    r2 = await task_sentiment_reddit()
    logger.info("Reddit: %s", r2)
    r3 = await task_sentiment_stocktwits()
    logger.info("Stocktwits: %s", r3)
    logger.info("=== [Sentiment] Initial Load Complete ===")


# ══════════════════════════════════════════════════════════════
# INCREMENTAL — scheduled every weekday
# ══════════════════════════════════════════════════════════════

@flow(name="Sentiment — Daily Update", log_prints=True)
async def sentiment_daily_flow():
    """
    Fetches fresh sentiment data after both India and US markets close.
    Runs nightly at 22:00 UTC (weekdays).
    Builds the daily sentiment time series used by the Sentiment Agent.
    All three sources run in sequence to avoid concurrent rate-limit pressure.
    """
    logger.info("=== [Sentiment] Daily Update ===")
    r1 = await task_sentiment_rss()
    logger.info("RSS: %s", r1)
    r2 = await task_sentiment_reddit()
    logger.info("Reddit: %s", r2)
    r3 = await task_sentiment_stocktwits()
    logger.info("Stocktwits: %s", r3)
    logger.info("=== [Sentiment] Daily Update Complete ===")
