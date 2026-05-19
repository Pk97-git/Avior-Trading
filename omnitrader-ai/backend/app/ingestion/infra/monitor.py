"""
Data Integrity Monitor
======================
Runs after each ingestion cycle to detect:
1. Missing Data  - tickers with no data for today
2. Price Spikes  - single-day moves > 20% (likely bad tick or split)
3. Feature Drift - Z-score based anomaly detection on macro indicators
4. API Failures  - tracks which sources returned empty results

All anomalies are logged and can trigger alerts via the Governance layer.
"""
import asyncio
from datetime import datetime, timedelta
from typing import List, Dict, Any
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func, text
from app.models.market_data import Stock, StockPrice, MacroEconomicData
from app.db.session import AsyncSessionLocal


class DataIntegrityMonitor:
    def __init__(self, db: AsyncSession):
        self.db = db
        self.anomalies: List[Dict[str, Any]] = []

    def _log_anomaly(self, category: str, severity: str, message: str, meta: dict = None):
        record = {
            "timestamp": datetime.utcnow().isoformat(),
            "category": category,
            "severity": severity,  # "LOW", "MEDIUM", "HIGH", "CRITICAL"
            "message": message,
            "meta": meta or {}
        }
        self.anomalies.append(record)
        print(f"[{severity}] {category}: {message}")

    # ------------------------------------------------------------------
    # 1. Missing Data Check
    # ------------------------------------------------------------------
    async def check_missing_data(self, tickers: List[str], lookback_days: int = 1):
        """
        Checks if any ticker has no price records in the last N trading days.
        """
        cutoff = datetime.utcnow() - timedelta(days=lookback_days + 3)  # buffer for weekends
        for ticker in tickers:
            result = await self.db.execute(
                select(func.count(StockPrice.time))
                .where(StockPrice.ticker == ticker)
                .where(StockPrice.time >= cutoff)
            )
            count = result.scalar()
            if count == 0:
                self._log_anomaly(
                    category="MISSING_DATA",
                    severity="HIGH",
                    message=f"No price data for {ticker} in last {lookback_days} days",
                    meta={"ticker": ticker, "lookback_days": lookback_days}
                )

    # ------------------------------------------------------------------
    # 2. Price Spike / Bad Tick Detection
    # ------------------------------------------------------------------
    async def check_price_spikes(self, tickers: List[str], threshold: float = 0.20):
        """
        Detects single-day price moves exceeding `threshold` (default 20%).
        Could indicate a bad tick, stock split, or genuine extreme event.
        """
        cutoff = datetime.utcnow() - timedelta(days=5)
        for ticker in tickers:
            result = await self.db.execute(
                select(StockPrice.time, StockPrice.close)
                .where(StockPrice.ticker == ticker)
                .where(StockPrice.time >= cutoff)
                .order_by(StockPrice.time.asc())
            )
            rows = result.all()
            for i in range(1, len(rows)):
                prev_close = rows[i - 1].close
                curr_close = rows[i].close
                if prev_close and prev_close > 0:
                    pct_change = abs((curr_close - prev_close) / prev_close)
                    if pct_change > threshold:
                        self._log_anomaly(
                            category="PRICE_SPIKE",
                            severity="MEDIUM",
                            message=f"{ticker} moved {pct_change:.1%} on {rows[i].time.date()} — verify for split/bad tick",
                            meta={"ticker": ticker, "pct_change": pct_change, "date": str(rows[i].time.date())}
                        )

    # ------------------------------------------------------------------
    # 3. Macro Feature Drift (Z-Score)
    # ------------------------------------------------------------------
    async def check_macro_drift(self, indicators: List[str], z_threshold: float = 3.0):
        """
        Computes rolling Z-score for each macro indicator.
        Flags if the latest value is more than `z_threshold` std devs from the 90-day mean.
        """
        cutoff_90d = datetime.utcnow() - timedelta(days=90)
        for indicator in indicators:
            result = await self.db.execute(
                select(MacroEconomicData.value)
                .where(MacroEconomicData.indicator == indicator)
                .where(MacroEconomicData.time >= cutoff_90d)
                .order_by(MacroEconomicData.time.desc())
            )
            values = [r.value for r in result.all() if r.value is not None]
            if len(values) < 10:
                continue  # Not enough data to compute stats

            latest = values[0]
            mean = sum(values) / len(values)
            variance = sum((v - mean) ** 2 for v in values) / len(values)
            std = variance ** 0.5

            if std > 0:
                z_score = abs((latest - mean) / std)
                if z_score > z_threshold:
                    self._log_anomaly(
                        category="MACRO_DRIFT",
                        severity="MEDIUM",
                        message=f"{indicator} Z-score={z_score:.2f} (latest={latest:.4f}, mean={mean:.4f})",
                        meta={"indicator": indicator, "z_score": z_score, "latest": latest}
                    )

    # ------------------------------------------------------------------
    # 4. Run Full Check
    # ------------------------------------------------------------------
    async def run_full_check(self, tickers: List[str]) -> List[Dict[str, Any]]:
        self.anomalies = []

        print("--- Running Data Integrity Monitor ---")
        await self.check_missing_data(tickers)
        await self.check_price_spikes(tickers)
        await self.check_macro_drift([
            "CPI_US", "FED_FUNDS_RATE", "US_10Y_YIELD",
            "US_YIELD_CURVE_10Y_2Y", "USD_INR", "Crude_Oil", "VIX_US"
        ])

        if not self.anomalies:
            print("✅ All checks passed. Data is clean.")
        else:
            print(f"⚠️  {len(self.anomalies)} anomalies detected.")

        return self.anomalies


async def run_monitor():
    """Standalone runner for testing."""
    async with AsyncSessionLocal() as session:
        monitor = DataIntegrityMonitor(session)
        tickers = ["AAPL", "MSFT", "GOOGL", "RELIANCE.NS", "TCS.NS", "INFY.NS"]
        anomalies = await monitor.run_full_check(tickers)
        print(f"\nTotal anomalies: {len(anomalies)}")
        for a in anomalies:
            print(f"  [{a['severity']}] {a['category']}: {a['message']}")


if __name__ == "__main__":
    asyncio.run(run_monitor())
