"""
services/pair_trading.py
=========================
PairTradingService — statistical arbitrage via cointegrated stock pairs.

Methodology:
  1. Pre-defined sector peer pairs (same industry, similar market cap)
  2. Engle-Granger cointegration test on 252-day daily close prices
  3. OLS hedge ratio: B = cov(A,B) / var(B)
  4. Spread = A - hedge_ratio * B
  5. Z-score = (spread - mean) / std
  6. Signal: |z| > 2 triggers entry; |z| > 3 triggers strong signal

Stored in pair_trades table, refreshed weekly.
"""
import logging
from datetime import date, timedelta, datetime, timezone
from typing import Optional

import numpy as np
import pandas as pd
from sqlalchemy import text
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import AsyncSessionLocal
from app.models.market_data import PairTrade

logger = logging.getLogger(__name__)

# Pre-defined sector pairs — cointegration tested on correlated peers
SECTOR_PAIRS = [
    # US Technology
    ("AAPL",  "MSFT",  "Technology"),
    ("NVDA",  "AMD",   "Semiconductors"),
    ("GOOGL", "META",  "Internet"),
    ("AMZN",  "MSFT",  "Cloud"),
    ("CRM",   "ORCL",  "Enterprise Software"),
    # US Financials
    ("JPM",   "BAC",   "Banking"),
    ("GS",    "MS",    "Investment Banking"),
    ("V",     "MA",    "Payments"),
    # US Energy
    ("XOM",   "CVX",   "Oil Majors"),
    ("COP",   "EOG",   "E&P"),
    # US Pharma
    ("LLY",   "UNH",   "Healthcare"),
    ("ABBV",  "MRK",   "Pharma"),
    # India IT
    ("TCS.NS",    "INFY.NS",     "India IT"),
    ("WIPRO.NS",  "HCLTECH.NS",  "India IT"),
    # India Banking
    ("HDFCBANK.NS", "ICICIBANK.NS", "India Banking"),
    ("AXISBANK.NS", "KOTAKBANK.NS", "India Banking"),
    ("SBIN.NS",     "BANKBARODA.NS","India PSU Banking"),
    # India Consumer
    ("HINDUNILVR.NS", "NESTLEIND.NS", "India FMCG"),
    ("MARUTI.NS",     "TATAMOTORS.NS","India Auto"),
]


def _engle_granger_pvalue(series_a: pd.Series, series_b: pd.Series) -> Optional[float]:
    """Simplified Engle-Granger cointegration test using statsmodels."""
    try:
        from statsmodels.tsa.stattools import coint
        _, pvalue, _ = coint(series_a, series_b)
        return float(pvalue)
    except ImportError:
        logger.warning("statsmodels not installed — skipping cointegration test")
        return None
    except Exception as e:
        logger.debug("Cointegration test failed: %s", e)
        return None


def _ols_hedge_ratio(a: pd.Series, b: pd.Series) -> float:
    """OLS beta: cov(a,b)/var(b)."""
    try:
        cov = np.cov(a, b)
        return float(cov[0, 1] / cov[1, 1])
    except Exception:
        return 1.0


class PairTradingService:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def run_all_pairs(self) -> dict:
        """Evaluate all sector pairs and update pair_trades table."""
        updated = 0
        skipped = 0

        for sym_a, sym_b, sector in SECTOR_PAIRS:
            try:
                result = await self._evaluate_pair(sym_a, sym_b, sector)
                if result:
                    updated += 1
                else:
                    skipped += 1
            except Exception as e:
                logger.warning("[PairTrade] %s/%s: %s", sym_a, sym_b, e)
                skipped += 1

        logger.info("PairTradingService: %d updated, %d skipped", updated, skipped)
        return {"updated": updated, "skipped": skipped}

    async def _evaluate_pair(self, sym_a: str, sym_b: str, sector: str) -> bool:
        since = date.today() - timedelta(days=365)
        prices_a = await self._get_prices(sym_a, since)
        prices_b = await self._get_prices(sym_b, since)

        if len(prices_a) < 60 or len(prices_b) < 60:
            return False

        # Align on common dates
        merged = pd.DataFrame({"a": prices_a, "b": prices_b}).dropna()
        if len(merged) < 60:
            return False

        a = merged["a"]
        b = merged["b"]

        # Correlation
        corr = float(a.corr(b))

        # Cointegration (only test if correlation > 0.7)
        p_value = _engle_granger_pvalue(a, b) if corr > 0.7 else 1.0

        # Hedge ratio and spread
        hedge_ratio = _ols_hedge_ratio(a, b)
        spread = a - hedge_ratio * b
        spread_mean = float(spread.mean())
        spread_std  = float(spread.std())

        if spread_std == 0:
            return False

        current_spread = float(spread.iloc[-1])
        z_score = (current_spread - spread_mean) / spread_std

        # Signal
        signal = "NEUTRAL"
        strength = "WEAK"
        if abs(z_score) >= 2.0:
            signal = "LONG_A_SHORT_B" if z_score < 0 else "LONG_B_SHORT_A"
            strength = "STRONG" if abs(z_score) >= 3.0 else "MODERATE"

        record = {
            "symbol_a":             sym_a,
            "symbol_b":             sym_b,
            "sector":               sector,
            "cointegration_pvalue": p_value,
            "correlation_90d":      corr,
            "spread_mean":          spread_mean,
            "spread_std":           spread_std,
            "spread_zscore":        round(z_score, 3),
            "hedge_ratio":          round(hedge_ratio, 4),
            "signal":               signal,
            "signal_strength":      strength,
            "last_updated":         datetime.now(timezone.utc),
        }

        stmt = pg_insert(PairTrade).values([record])
        stmt = stmt.on_conflict_do_update(
            constraint="uq_pair_trade",
            set_={k: stmt.excluded[k] for k in record if k not in ("symbol_a", "symbol_b")},
        )
        await self.db.execute(stmt)
        await self.db.commit()
        return True

    async def _get_prices(self, ticker: str, since: date) -> pd.Series:
        result = await self.db.execute(text("""
            SELECT time::date AS dt, close
            FROM stock_prices
            WHERE ticker = :t AND time >= :since AND close IS NOT NULL
            ORDER BY time ASC
        """), {"t": ticker, "since": since})
        rows = result.fetchall()
        if not rows:
            return pd.Series(dtype=float)
        df = pd.DataFrame(rows, columns=["dt", "close"])
        return df.set_index("dt")["close"]

    async def get_active_signals(self) -> list[dict]:
        """Return all pairs with non-NEUTRAL signals, sorted by |z-score|."""
        result = await self.db.execute(text("""
            SELECT symbol_a, symbol_b, sector, spread_zscore, hedge_ratio,
                   signal, signal_strength, correlation_90d, cointegration_pvalue,
                   last_updated
            FROM pair_trades
            WHERE signal != 'NEUTRAL'
            ORDER BY ABS(spread_zscore) DESC
        """))
        rows = result.fetchall()
        return [
            {
                "symbol_a": r.symbol_a, "symbol_b": r.symbol_b,
                "sector": r.sector, "spread_zscore": r.spread_zscore,
                "hedge_ratio": r.hedge_ratio, "signal": r.signal,
                "signal_strength": r.signal_strength,
                "correlation_90d": r.correlation_90d,
                "cointegration_pvalue": r.cointegration_pvalue,
                "last_updated": r.last_updated.isoformat() if r.last_updated else None,
            }
            for r in rows
        ]
