"""
Chart Generation Service — Phase 4
=====================================
Generates candlestick charts via mplfinance for Vision LLM analysis.
Produces 6M, 1Y, and 5Y monthly charts for each stock.
"""
import os
import io
import asyncio
from datetime import datetime, timedelta
from typing import List, Optional
import pandas as pd
import yfinance as yf
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.dialects.postgresql import insert as pg_insert
from app.models.market_data import ChartSnapshot

try:
    import mplfinance as mpf
    MPLFINANCE_AVAILABLE = True
except ImportError:
    MPLFINANCE_AVAILABLE = False
    print("[WARN] mplfinance not installed. Run: pip install mplfinance")


CHART_OUTPUT_DIR = "/tmp/omnitrader_charts"
os.makedirs(CHART_OUTPUT_DIR, exist_ok=True)


class ChartGenerationService:
    def __init__(self, db: AsyncSession):
        self.db = db

    def _get_chart_path(self, ticker: str, timeframe: str) -> str:
        safe_ticker = ticker.replace(".", "_").replace("^", "")
        return os.path.join(CHART_OUTPUT_DIR, f"{safe_ticker}_{timeframe}.png")

    async def generate_chart(self, ticker_symbol: str, timeframe: str = "1Y") -> Optional[str]:
        """
        Generates a candlestick chart for a given ticker and timeframe.
        
        timeframe options: "6M", "1Y", "5Y"
        Returns the file path to the generated chart.
        """
        if not MPLFINANCE_AVAILABLE:
            print("[ERROR] mplfinance not available")
            return None

        period_map = {
            "6M": "6mo",
            "1Y": "1y",
            "5Y": "5y",
        }
        period = period_map.get(timeframe, "1y")

        try:
            t = yf.Ticker(ticker_symbol)
            hist = t.history(period=period, interval="1d")

            if hist.empty:
                print(f"  [WARN] No price data for chart: {ticker_symbol}")
                return None

            # mplfinance expects specific column names
            hist.index = pd.DatetimeIndex(hist.index)
            hist = hist[["Open", "High", "Low", "Close", "Volume"]]

            chart_path = self._get_chart_path(ticker_symbol, timeframe)

            # Style: dark background, institutional look
            style = mpf.make_mpf_style(
                base_mpf_style="nightclouds",
                gridstyle=":",
                y_on_right=True,
            )

            # Add 20, 50, 200 MA overlays
            add_plots = [
                mpf.make_addplot(hist["Close"].rolling(20).mean(), color="cyan", width=0.8),
                mpf.make_addplot(hist["Close"].rolling(50).mean(), color="orange", width=0.8),
                mpf.make_addplot(hist["Close"].rolling(200).mean(), color="red", width=0.8),
            ]

            mpf.plot(
                hist,
                type="candle",
                style=style,
                title=f"{ticker_symbol} — {timeframe}",
                volume=True,
                addplot=add_plots,
                savefig=dict(fname=chart_path, dpi=150, bbox_inches="tight"),
                figsize=(14, 8),
            )

            print(f"  Generated chart: {chart_path}")
            return chart_path

        except Exception as e:
            print(f"  [ERROR] Chart generation for {ticker_symbol} ({timeframe}): {e}")
            return None

    async def generate_and_store(self, ticker_symbol: str):
        """
        Generates all 3 timeframe charts and stores metadata in DB.
        Vision LLM analysis is triggered separately by the Vision Agent.
        """
        timeframes = ["6M", "1Y", "5Y"]
        records = []

        for tf in timeframes:
            path = await self.generate_chart(ticker_symbol, tf)
            if path:
                records.append({
                    "ticker": ticker_symbol,
                    "generated_at": datetime.utcnow(),
                    "timeframe": tf,
                    "image_path": path,
                    "pattern_json": None,   # Filled by Vision Agent
                    "vision_score": None,
                    "vision_summary": None,
                })

        if records:
            stmt = pg_insert(ChartSnapshot).values(records)
            stmt = stmt.on_conflict_do_update(
                index_elements=["ticker", "generated_at", "timeframe"],
                set_={"image_path": stmt.excluded.image_path}
            )
            await self.db.execute(stmt)
            await self.db.commit()
            print(f"  Stored {len(records)} chart records for {ticker_symbol}")

    async def generate_all(self, tickers: List[str]):
        """Generate charts for all tickers in the universe."""
        for ticker in tickers:
            await self.generate_and_store(ticker)
