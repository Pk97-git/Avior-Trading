"""
ingestion/core/google_trends.py
=================================
GoogleTrendsService — fetches Google Trends interest scores for tickers.

Uses pytrends (unofficial Google Trends API).
Rate limits: ~5–10 requests per minute before getting rate-limited.
We insert 60s waits between tickers.

Keyword strategy: "{COMPANY_NAME} stock" for US, "{TICKER}" for India.
Geo: "US" for US equities, "IN" for India equities, "" for crypto/global.

Interest is normalised to 0–100 by Google. We store the latest weekly value
and a 7-day rolling average.
"""
import asyncio
import logging
import time
from datetime import date, timedelta
from typing import Optional

from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy import text

from app.db.session import AsyncSessionLocal
from app.models.market_data import GoogleTrendsData

logger = logging.getLogger(__name__)

# Tickers to track (keep small — Google aggressively rate-limits pytrends)
TRENDS_US_TICKERS = [
    ("AAPL",  "Apple stock",  "US"),
    ("MSFT",  "Microsoft stock", "US"),
    ("NVDA",  "Nvidia stock", "US"),
    ("GOOGL", "Google stock", "US"),
    ("AMZN",  "Amazon stock", "US"),
    ("META",  "Meta stock",   "US"),
    ("TSLA",  "Tesla stock",  "US"),
    ("JPM",   "JPMorgan stock", "US"),
    ("AMD",   "AMD stock",    "US"),
    ("NFLX",  "Netflix stock", "US"),
]

TRENDS_INDIA_TICKERS = [
    ("RELIANCE.NS", "Reliance Industries stock", "IN"),
    ("TCS.NS",      "TCS stock",       "IN"),
    ("HDFCBANK.NS", "HDFC Bank stock", "IN"),
    ("INFY.NS",     "Infosys stock",   "IN"),
    ("ICICIBANK.NS","ICICI Bank stock","IN"),
]

TRENDS_ALL = TRENDS_US_TICKERS + TRENDS_INDIA_TICKERS


class GoogleTrendsService:
    """Fetches weekly Google Trends data for configured tickers."""

    async def run_batch(self, tickers_config: list[tuple] = None) -> dict:
        """
        tickers_config: list of (ticker, keyword, geo) tuples.
        Returns {"stored": int, "failed": list[str]}
        """
        if tickers_config is None:
            tickers_config = TRENDS_ALL

        stored_total = 0
        failed = []

        loop = asyncio.get_event_loop()
        for ticker, keyword, geo in tickers_config:
            try:
                rows = await loop.run_in_executor(
                    None, self._fetch_ticker_sync, ticker, keyword, geo
                )
                if rows:
                    await self._upsert(rows)
                    stored_total += len(rows)
                # Rate-limit pause — pytrends blocks heavily on rapid requests
                await asyncio.sleep(45)
            except Exception as e:
                logger.warning("Google Trends failed for %s: %s", ticker, e)
                failed.append(ticker)
                await asyncio.sleep(45)

        logger.info("GoogleTrendsService: %d rows stored, %d failed", stored_total, len(failed))
        return {"stored": stored_total, "failed": failed}

    def _fetch_ticker_sync(self, ticker: str, keyword: str, geo: str) -> list[dict]:
        try:
            from pytrends.request import TrendReq
        except ImportError:
            logger.error("pytrends not installed — run: pip install pytrends")
            return []

        try:
            pytrends = TrendReq(hl="en-US", tz=0, timeout=(10, 25))
            pytrends.build_payload(
                kw_list=[keyword],
                cat=0,
                timeframe="today 3-m",
                geo=geo,
                gprop="",
            )
            df = pytrends.interest_over_time()
            if df is None or df.empty:
                return []

            # Drop the isPartial column if present
            if "isPartial" in df.columns:
                df = df.drop(columns=["isPartial"])

            records = []
            scores = list(df[keyword].values) if keyword in df.columns else []

            for i, (ts, row) in enumerate(df.iterrows()):
                val = int(row.iloc[0]) if len(row) > 0 else 0
                row_date = ts.date() if hasattr(ts, "date") else ts

                # 7-day rolling avg (only weekly data, so this is just the value itself
                # but when we have daily data it smooths noise)
                window = scores[max(0, i-6):i+1]
                avg_7d = sum(window) / len(window) if window else None

                records.append({
                    "ticker":         ticker,
                    "date":           row_date,
                    "interest_score": val,
                    "keyword":        keyword,
                    "geo":            geo,
                    "trend_7d_avg":   round(float(avg_7d), 1) if avg_7d else None,
                })
            return records

        except Exception as e:
            logger.warning("pytrends fetch %s: %s", keyword, e)
            return []

    async def _upsert(self, records: list[dict]) -> None:
        async with AsyncSessionLocal() as db:
            stmt = pg_insert(GoogleTrendsData).values(records)
            stmt = stmt.on_conflict_do_update(
                constraint="uq_gtrends_ticker_date",
                set_={
                    "interest_score": stmt.excluded.interest_score,
                    "trend_7d_avg":   stmt.excluded.trend_7d_avg,
                },
            )
            await db.execute(stmt)
            await db.commit()
