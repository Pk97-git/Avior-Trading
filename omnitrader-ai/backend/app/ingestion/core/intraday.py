"""
ingestion/core/intraday.py
===========================
IntradayPriceService — fetches 15-minute OHLCV bars for equities.

Uses yfinance with interval='15m'. Maximum lookback is 60 days for 15m data.

India market hours:  09:15–15:30 IST (03:45–10:00 UTC)
US market hours:     09:30–16:00 EST (14:30–21:00 UTC)
"""
import logging
from datetime import date, timedelta
from typing import Optional

import yfinance as yf
import pandas as pd
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy import text

from app.db.session import AsyncSessionLocal
from app.models.market_data import IntradayPrice

logger = logging.getLogger(__name__)

# Universe for intraday tracking (HIGH tier only — largest liquid names)
INDIA_INTRADAY_TICKERS = [
    "RELIANCE.NS", "TCS.NS", "HDFCBANK.NS", "INFY.NS", "ICICIBANK.NS",
    "HINDUNILVR.NS", "SBIN.NS", "BAJFINANCE.NS", "BHARTIARTL.NS", "KOTAKBANK.NS",
    "LT.NS", "WIPRO.NS", "AXISBANK.NS", "ASIANPAINT.NS", "TITAN.NS",
    "MARUTI.NS", "SUNPHARMA.NS", "ULTRACEMCO.NS", "NESTLEIND.NS", "TATAMOTORS.NS",
    # Indices
    "^NSEI", "^NSEBANK",
]

US_INTRADAY_TICKERS = [
    "AAPL", "MSFT", "NVDA", "GOOGL", "AMZN", "META", "TSLA", "BRK-B",
    "JPM", "V", "JNJ", "WMT", "MA", "PG", "HD",
    # ETFs + indices
    "SPY", "QQQ", "IWM", "^VIX",
]


class IntradayPriceService:
    """Fetches and stores 15-minute intraday bars."""

    def __init__(self, db: Optional[AsyncSession] = None):
        self.db = db

    async def run_batch(self, tickers: list[str], period: str = "5d") -> dict:
        """
        Fetch 15m bars for a list of tickers and upsert into intraday_prices.
        period: '5d' for incremental, '60d' for initial backfill.
        Returns: {"stored": int, "failed": list[str]}
        """
        stored_total = 0
        failed = []

        for ticker in tickers:
            try:
                rows = await self._fetch_and_store(ticker, period)
                stored_total += rows
            except Exception as e:
                logger.warning("Intraday fetch failed for %s: %s", ticker, e)
                failed.append(ticker)

        logger.info("IntradayPriceService: %d rows stored, %d failed", stored_total, len(failed))
        return {"stored": stored_total, "failed": failed}

    async def _fetch_and_store(self, ticker: str, period: str) -> int:
        df = await _download_15m(ticker, period)
        if df is None or df.empty:
            return 0

        rows = []
        for ts, row in df.iterrows():
            if pd.isna(row.get("Close")):
                continue
            rows.append({
                "ticker": ticker,
                "time":   ts.to_pydatetime(),
                "open":   float(row["Open"])  if not pd.isna(row.get("Open"))  else None,
                "high":   float(row["High"])  if not pd.isna(row.get("High"))  else None,
                "low":    float(row["Low"])   if not pd.isna(row.get("Low"))   else None,
                "close":  float(row["Close"]),
                "volume": float(row["Volume"]) if not pd.isna(row.get("Volume")) else None,
            })

        if not rows:
            return 0

        async with AsyncSessionLocal() as db:
            stmt = pg_insert(IntradayPrice).values(rows)
            stmt = stmt.on_conflict_do_update(
                constraint="uq_intraday_ticker_time",
                set_={
                    "open":   stmt.excluded.open,
                    "high":   stmt.excluded.high,
                    "low":    stmt.excluded.low,
                    "close":  stmt.excluded.close,
                    "volume": stmt.excluded.volume,
                },
            )
            await db.execute(stmt)
            await db.commit()

        return len(rows)


async def _download_15m(ticker: str, period: str) -> Optional[pd.DataFrame]:
    """Download 15-minute bars via yfinance (runs in threadpool to avoid blocking)."""
    import asyncio
    loop = asyncio.get_event_loop()

    def _fetch():
        try:
            t = yf.Ticker(ticker)
            df = t.history(period=period, interval="15m", auto_adjust=True, prepost=False)
            return df
        except Exception as e:
            logger.warning("yfinance 15m download %s: %s", ticker, e)
            return None

    return await loop.run_in_executor(None, _fetch)
