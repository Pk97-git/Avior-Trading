"""
Data Ingestion Service — Phase 1
=================================
Handles:
- Stock metadata upsert
- Price history (OHLCV) with upsert logic to avoid duplicates
- Crypto prices (BTC, ETH) via yfinance
- Initial historical load (period="max") vs daily incremental (period="2d")
"""
import yfinance as yf
import pandas as pd
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from app.models.market_data import Stock, StockPrice
from datetime import datetime, timedelta
from typing import List


# ─── Universe Definitions ────────────────────────────────────────────────────



CRYPTO_UNIVERSE = [
    "BTC-USD",   # Bitcoin — Macro Regime input
    "ETH-USD",   # Ethereum
]

INDEX_UNIVERSE = [
    "^GSPC",     # S&P 500
    "^NSEI",     # Nifty 50
    "^DJI",      # Dow Jones
    "^IXIC",     # NASDAQ
    "^NSEBANK",  # Bank Nifty
]


# ─── Service ─────────────────────────────────────────────────────────────────

from app.core.rate_limiter import yahoo_limiter

# ─── Service ─────────────────────────────────────────────────────────────────

class DataIngestionService:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def upsert_stock_metadata(self, tickers: List[str]):
        """
        Fetches metadata for a list of tickers and upserts into the Stocks table.
        Handles both equities and crypto (crypto won't have sector/industry).
        """
        for ticker_symbol in tickers:
            try:
                # Rate limit before fetch
                await yahoo_limiter.acquire()
                
                t = yf.Ticker(ticker_symbol)
                info = t.info
                
                # Normalize Country
                raw_country = info.get("country", "Unknown")
                country_code = "US" if raw_country in ["United States", "USA"] else "IN" if raw_country in ["India"] else raw_country
                
                stock_data = {
                    "ticker": ticker_symbol,
                    "name": info.get("longName", info.get("shortName", ticker_symbol)),
                    "sector": info.get("sector", "Crypto" if "-USD" in ticker_symbol else "Unknown"),
                    "industry": info.get("industry", "Cryptocurrency" if "-USD" in ticker_symbol else "Unknown"),
                    "country": country_code,
                    "meta_data": {k: v for k, v in info.items() if isinstance(v, (str, int, float, bool, type(None)))}
                }

                result = await self.db.execute(select(Stock).filter(Stock.ticker == ticker_symbol))
                existing = result.scalars().first()

                if not existing:
                    self.db.add(Stock(**stock_data))
                else:
                    existing.name = stock_data["name"]
                    existing.sector = stock_data["sector"]
                    existing.industry = stock_data["industry"]
                    existing.country = stock_data["country"]
                    existing.meta_data = stock_data["meta_data"]

                print(f"  Upserted metadata: {ticker_symbol}")
            except Exception as e:
                print(f"  [ERROR] Metadata for {ticker_symbol}: {e}")

        await self.db.commit()

    async def fetch_history(self, ticker_symbol: str, period: str = "max", start: str = None, end: str = None):
        """
        Fetches historical OHLCV data and upserts into stock_prices.
        Uses ON CONFLICT DO NOTHING to safely handle re-runs.
        period="max" for initial load (10-20 years), "2d" for daily incremental.
        If start and end are provided, fetches only that exact date range to fill missing gaps.
        """
        try:
            # Rate limit
            await yahoo_limiter.acquire()
            
            t = yf.Ticker(ticker_symbol)
            if start and end:
                hist = t.history(start=start, end=end, auto_adjust=True)
            else:
                hist = t.history(period=period, auto_adjust=True)

            if hist.empty:
                print(f"  [WARN] No price data for {ticker_symbol}")
                return

            records = []
            for index, row in hist.iterrows():
                records.append({
                    "time": index,
                    "ticker": ticker_symbol,
                    "open": float(row["Open"]) if pd.notna(row["Open"]) else None,
                    "high": float(row["High"]) if pd.notna(row["High"]) else None,
                    "low": float(row["Low"]) if pd.notna(row["Low"]) else None,
                    "close": float(row["Close"]) if pd.notna(row["Close"]) else None,
                    "volume": float(row["Volume"]) if pd.notna(row["Volume"]) else None,
                    "adj_close": float(row["Close"]) if pd.notna(row["Close"]) else None,
                })

            # Batch upsert in chunks to avoid asyncpg's 32767 bind-param limit.
            # Each row has 8 fields, so chunk size of 4000 → 32000 params max.
            CHUNK_SIZE = 4000
            if records:
                for i in range(0, len(records), CHUNK_SIZE):
                    chunk = records[i:i + CHUNK_SIZE]
                    stmt = pg_insert(StockPrice).values(chunk)
                    stmt = stmt.on_conflict_do_nothing(index_elements=["time", "ticker"])
                    await self.db.execute(stmt)
                await self.db.commit()
                print(f"  Ingested {len(records)} records for {ticker_symbol}")

        except Exception as e:
            print(f"  [ERROR] Price history for {ticker_symbol}: {e}")
            await self.db.rollback()

    async def initial_load(self, tickers: List[str]):
        """
        One-time historical load for all tickers (period=max = up to 20 years).
        """
        print(f"Starting initial historical load for {len(tickers)} tickers...")
        await self.upsert_stock_metadata(tickers)
        for ticker in tickers:
            await self.fetch_history(ticker, period="max")

    async def daily_update(self, tickers: List[str]):
        """
        Daily incremental update — only fetches last 2 days to catch any missed data.
        """
        print(f"Running daily update for {len(tickers)} tickers...")
        await self.upsert_stock_metadata(tickers)
        for ticker in tickers:
            await self.fetch_history(ticker, period="2d")
