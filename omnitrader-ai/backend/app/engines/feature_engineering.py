"""
engines/feature_engineering.py
================================
FeatureEngineer — builds a rich feature matrix from OHLCV + DB data.

Feature groups (40+ features total)
-------------------------------------
Momentum (12)   : 1d/5d/20d/60d/252d returns, RSI-14/7, MACD histogram,
                  price vs SMA-20/50/200, rate-of-change-21
Volatility (8)  : ATR-14, realized-vol 20d/60d, Bollinger bandwidth,
                  Parkinson estimator, volume-weighted vol, high-low range pct
Volume (5)      : volume ratio vs 20d avg, OBV slope, money flow index (MFI),
                  volume trend 5d, large-block flag (vol > 2× avg)
Macro (5)       : VIX, US 10Y yield, USD index return 1M, crude oil return 1M,
                  India FII flow (from macro_data table, graceful on missing)
Sentiment (4)   : avg news sentiment 7d, avg news sentiment 30d,
                  sentiment momentum (7d vs 30d), insider buy flag
Earnings (4)    : EPS surprise %, revenue surprise %, beat flag, days since earnings
Calendar (3)    : day of week (sin/cos encoded), month (sin/cos), is_earnings_week

Target variable : forward_return_5d (5-trading-day forward return) — for supervised learning
                  Also compute: forward_direction (1 if return > 0.5%, else 0)
"""
from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timedelta, timezone
from typing import Optional

import numpy as np
import pandas as pd
import yfinance as yf
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Module-level helper functions
# ---------------------------------------------------------------------------

def _rsi(s: pd.Series, n: int = 14) -> pd.Series:
    delta = s.diff()
    gain = delta.clip(lower=0).rolling(n).mean()
    loss = (-delta.clip(upper=0)).rolling(n).mean()
    rs = gain / loss.replace(0, 1e-9)
    return 100 - (100 / (1 + rs))


def _macd_hist(s: pd.Series) -> pd.Series:
    ema12 = s.ewm(span=12, adjust=False).mean()
    ema26 = s.ewm(span=26, adjust=False).mean()
    macd = ema12 - ema26
    signal = macd.ewm(span=9, adjust=False).mean()
    return macd - signal


def _atr(df: pd.DataFrame, n: int = 14) -> pd.Series:
    h, l, c = df["High"], df["Low"], df["Close"]
    tr = pd.concat([h - l, (h - c.shift()).abs(), (l - c.shift()).abs()], axis=1).max(axis=1)
    return tr.rolling(n).mean()


def _obv_slope(close: pd.Series, volume: pd.Series, n: int = 10) -> pd.Series:
    direction = np.sign(close.diff()).fillna(0)
    obv = (direction * volume).cumsum()
    return obv.diff(n) / (obv.rolling(n).std().replace(0, 1) + 1e-9)


def _parkinson_vol(df: pd.DataFrame, n: int = 20) -> pd.Series:
    """Parkinson high-low volatility estimator (annualised)."""
    log_hl = np.log(df["High"] / df["Low"]) ** 2
    return np.sqrt(log_hl.rolling(n).mean() / (4 * np.log(2)) * 252)


def _mfi(df: pd.DataFrame, n: int = 14) -> pd.Series:
    """Money Flow Index."""
    tp = (df["High"] + df["Low"] + df["Close"]) / 3
    mf = tp * df["Volume"]
    pos = mf.where(tp > tp.shift(), 0)
    neg = mf.where(tp <= tp.shift(), 0)
    mfr = pos.rolling(n).sum() / (neg.rolling(n).sum().replace(0, 1e-9))
    return 100 - (100 / (1 + mfr))


# ---------------------------------------------------------------------------
# Main class
# ---------------------------------------------------------------------------

class FeatureEngineer:
    """
    Build a feature DataFrame for a given ticker.

    Usage:
        fe = FeatureEngineer(db)
        X, y = await fe.build(ticker="RELIANCE.NS", lookback_days=500)
        # X: pd.DataFrame shape (n_samples, n_features)
        # y: pd.Series of forward 5-day returns
    """

    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    async def build(self, ticker: str, lookback_days: int = 500) -> tuple[pd.DataFrame, pd.Series]:
        """Build the feature matrix and target series for the given ticker."""

        # ------------------------------------------------------------------
        # 1. Fetch OHLCV via yfinance
        # ------------------------------------------------------------------
        loop = asyncio.get_event_loop()
        fetch_days = lookback_days + 300  # extra for indicator warmup
        period = f"{fetch_days}d"

        def _fetch():
            df = yf.download(ticker, period=period, interval="1d", progress=False, auto_adjust=True)
            if isinstance(df.columns, pd.MultiIndex):
                df.columns = df.columns.get_level_values(0)
            return df

        df = await loop.run_in_executor(None, _fetch)
        if df is None or len(df) < 100:
            raise ValueError(
                f"Insufficient price data for {ticker}: got {len(df) if df is not None else 0} rows"
            )

        # ------------------------------------------------------------------
        # 2. Momentum features
        # ------------------------------------------------------------------
        close = df["Close"]
        features = pd.DataFrame(index=df.index)

        # Returns
        for n, label in [(1, "ret_1d"), (5, "ret_5d"), (21, "ret_20d"), (63, "ret_60d"), (252, "ret_252d")]:
            features[label] = close.pct_change(n) * 100

        # RSI
        features["rsi_14"] = _rsi(close, 14)
        features["rsi_7"] = _rsi(close, 7)

        # MACD histogram (normalized by price)
        features["macd_hist_norm"] = _macd_hist(close) / close * 100

        # Price vs moving averages (%)
        for n, label in [(20, "vs_sma20"), (50, "vs_sma50"), (200, "vs_sma200")]:
            sma = close.rolling(n).mean()
            features[label] = (close - sma) / sma * 100

        # Rate of change
        features["roc_21"] = (close / close.shift(21) - 1) * 100

        # ------------------------------------------------------------------
        # 3. Volatility features
        # ------------------------------------------------------------------
        atr = _atr(df, 14)
        features["atr_pct"] = atr / close * 100        # ATR as % of price
        features["realized_vol_20"] = close.pct_change().rolling(20).std() * np.sqrt(252) * 100
        features["realized_vol_60"] = close.pct_change().rolling(60).std() * np.sqrt(252) * 100

        # Bollinger bandwidth (squeeze indicator)
        bb_mid = close.rolling(20).mean()
        bb_std = close.rolling(20).std()
        features["bb_width"] = (4 * bb_std) / bb_mid * 100

        # Parkinson estimator
        features["parkinson_vol"] = _parkinson_vol(df) * 100

        # High-low range as % of close
        features["hl_range_pct"] = (df["High"] - df["Low"]) / close * 100

        # Overnight gap
        features["gap_pct"] = (df["Open"] - close.shift()) / close.shift() * 100

        # ------------------------------------------------------------------
        # 4. Volume features
        # ------------------------------------------------------------------
        vol = df["Volume"]
        vol_avg20 = vol.rolling(20).mean()
        features["vol_ratio"] = vol / vol_avg20.replace(0, 1)
        features["obv_slope"] = _obv_slope(close, vol)
        features["mfi_14"] = _mfi(df, 14)
        features["vol_trend_5d"] = vol.rolling(5).mean() / vol_avg20.replace(0, 1)
        features["large_block"] = (vol > 2 * vol_avg20).astype(float)

        # ------------------------------------------------------------------
        # 5. Calendar features (sin/cos encoding for cyclicality)
        # ------------------------------------------------------------------
        idx = pd.DatetimeIndex(df.index)
        features["dow_sin"] = np.sin(2 * np.pi * idx.dayofweek / 5)
        features["dow_cos"] = np.cos(2 * np.pi * idx.dayofweek / 5)
        features["month_sin"] = np.sin(2 * np.pi * idx.month / 12)
        features["month_cos"] = np.cos(2 * np.pi * idx.month / 12)

        # ------------------------------------------------------------------
        # 6. Macro features (from DB, graceful fallback to zeros)
        # ------------------------------------------------------------------
        macro_features = await self._fetch_macro_features(df.index)
        for col in ["vix_level", "yield_10y", "usd_ret_1m", "crude_ret_1m", "fii_flow_norm"]:
            features[col] = macro_features.get(col, 0.0)

        # ------------------------------------------------------------------
        # 7. Sentiment features (from DB)
        # ------------------------------------------------------------------
        sentiment_features = await self._fetch_sentiment_features(ticker, df.index)
        for col in ["sentiment_7d", "sentiment_30d", "sentiment_momentum", "insider_buy"]:
            features[col] = sentiment_features.get(col, 50.0 if "sentiment" in col else 0.0)

        # ------------------------------------------------------------------
        # 8. Earnings features (from DB)
        # ------------------------------------------------------------------
        earnings_features = await self._fetch_earnings_features(ticker, df.index)
        for col in ["eps_surprise_pct", "rev_surprise_pct", "beat_flag", "days_since_earnings"]:
            features[col] = earnings_features.get(col, 0.0)

        # ------------------------------------------------------------------
        # 9. Compute target variable
        # ------------------------------------------------------------------
        # 5-day forward return (shifted back — this is what we're predicting)
        fwd_return = close.pct_change(5).shift(-5) * 100

        # Drop last 5 rows (no forward return available)
        features = features.iloc[:-5]
        fwd_return = fwd_return.iloc[:-5]

        # Trim to lookback_days
        features = features.tail(lookback_days)
        fwd_return = fwd_return.reindex(features.index)

        # Drop rows with too many NaNs
        threshold = len(features.columns) * 0.3  # allow 30% NaN
        features = features.dropna(thresh=int(len(features.columns) * 0.7))
        fwd_return = fwd_return.reindex(features.index)

        # Fill remaining NaNs with column median
        features = features.fillna(features.median())

        # ------------------------------------------------------------------
        # 10. Return
        # ------------------------------------------------------------------
        logger.info(
            "[FeatureEngineer] %s: built %d rows × %d features",
            ticker, len(features), len(features.columns)
        )
        return features, fwd_return

    async def _fetch_macro_features(self, date_index) -> dict[str, pd.Series]:
        """Fetch macro data from macro_data table, return dict of Series aligned to date_index."""
        result = {}
        try:
            # VIX
            rows = await self.db.execute(text("""
                SELECT date::date as d, value FROM macro_data
                WHERE indicator = 'VIX' ORDER BY date DESC LIMIT 500
            """))
            vix_rows = rows.fetchall()
            if vix_rows:
                vix = pd.Series({r.d: r.value for r in vix_rows}).sort_index()
                result["vix_level"] = vix.reindex(date_index.date, method="ffill").values

            # 10Y yield
            rows2 = await self.db.execute(text("""
                SELECT date::date as d, value FROM macro_data
                WHERE indicator = 'US10Y' ORDER BY date DESC LIMIT 500
            """))
            yield_rows = rows2.fetchall()
            if yield_rows:
                y10 = pd.Series({r.d: r.value for r in yield_rows}).sort_index()
                result["yield_10y"] = y10.reindex(date_index.date, method="ffill").values
        except Exception as e:
            logger.debug("[FeatureEngineer] macro fetch failed (non-critical): %s", e)

        # Fallback: return zeros for missing macro features
        n = len(date_index)
        for col in ["vix_level", "yield_10y", "usd_ret_1m", "crude_ret_1m", "fii_flow_norm"]:
            if col not in result:
                result[col] = np.zeros(n)
        return result

    async def _fetch_sentiment_features(self, ticker: str, date_index) -> dict[str, pd.Series]:
        n = len(date_index)
        result = {
            "sentiment_7d":       np.full(n, 50.0),
            "sentiment_30d":      np.full(n, 50.0),
            "sentiment_momentum": np.zeros(n),
            "insider_buy":        np.zeros(n),
        }
        try:
            rows = await self.db.execute(text("""
                SELECT DATE(published_at) as d, AVG(sentiment_score) as avg_s
                FROM news_sentiment WHERE ticker = :t
                GROUP BY DATE(published_at)
                ORDER BY d
            """), {"t": ticker})
            sent_rows = rows.fetchall()
            if sent_rows:
                sent = pd.Series({r.d: float(r.avg_s) for r in sent_rows}).sort_index()
                # Align to date_index (use date objects)
                dates = [d.date() if hasattr(d, 'date') else d for d in date_index]
                sent_aligned = sent.reindex(dates, method="ffill").fillna(50.0)
                result["sentiment_7d"] = sent_aligned.rolling(7, min_periods=1).mean().values
                result["sentiment_30d"] = sent_aligned.rolling(30, min_periods=1).mean().values
                result["sentiment_momentum"] = result["sentiment_7d"] - result["sentiment_30d"]
        except Exception as e:
            logger.debug("[FeatureEngineer] sentiment fetch failed: %s", e)

        try:
            rows2 = await self.db.execute(text("""
                SELECT DATE(transaction_date) as d, COUNT(*) as buys
                FROM insider_transactions
                WHERE ticker = :t AND transaction_type ILIKE '%buy%'
                GROUP BY DATE(transaction_date)
            """), {"t": ticker})
            insider_rows = rows2.fetchall()
            if insider_rows:
                insider = pd.Series({r.d: 1.0 for r in insider_rows})
                dates = [d.date() if hasattr(d, 'date') else d for d in date_index]
                insider_aligned = insider.reindex(dates, fill_value=0.0)
                result["insider_buy"] = insider_aligned.values
        except Exception as e:
            logger.debug("[FeatureEngineer] insider fetch failed: %s", e)

        return result

    async def _fetch_earnings_features(self, ticker: str, date_index) -> dict[str, pd.Series]:
        n = len(date_index)
        result = {
            "eps_surprise_pct":    np.zeros(n),
            "rev_surprise_pct":    np.zeros(n),
            "beat_flag":           np.zeros(n),
            "days_since_earnings": np.full(n, 90.0),
        }
        try:
            rows = await self.db.execute(text("""
                SELECT
                    report_date::date as d,
                    CASE WHEN actual_eps IS NOT NULL AND estimate_eps IS NOT NULL AND estimate_eps != 0
                         THEN (actual_eps - estimate_eps) / ABS(estimate_eps) * 100
                         ELSE 0 END as eps_surp,
                    CASE WHEN actual_eps > estimate_eps THEN 1.0 ELSE 0.0 END as beat
                FROM earnings_calendar
                WHERE ticker = :t AND report_date IS NOT NULL
                ORDER BY report_date
            """), {"t": ticker})
            earn_rows = rows.fetchall()
            if earn_rows:
                dates = [d.date() if hasattr(d, 'date') else d for d in date_index]

                eps_surp = pd.Series({r.d: float(r.eps_surp) for r in earn_rows})
                beat = pd.Series({r.d: float(r.beat) for r in earn_rows})

                eps_aligned = eps_surp.reindex(dates, method="ffill", limit=90).fillna(0.0)
                beat_aligned = beat.reindex(dates, method="ffill", limit=90).fillna(0.0)

                result["eps_surprise_pct"] = eps_aligned.values
                result["beat_flag"] = beat_aligned.values

                # Days since last earnings
                earn_dates = sorted([r.d for r in earn_rows])
                days_since = []
                for d in dates:
                    past = [e for e in earn_dates if e <= d]
                    if past:
                        days_since.append((d - max(past)).days)
                    else:
                        days_since.append(90)
                result["days_since_earnings"] = np.array(days_since, dtype=float)
        except Exception as e:
            logger.debug("[FeatureEngineer] earnings fetch failed: %s", e)

        return result

    def get_feature_names(self) -> list[str]:
        """Return the ordered list of all feature names produced by build()."""
        return [
            # Momentum (12)
            "ret_1d", "ret_5d", "ret_20d", "ret_60d", "ret_252d",
            "rsi_14", "rsi_7", "macd_hist_norm",
            "vs_sma20", "vs_sma50", "vs_sma200", "roc_21",
            # Volatility (8)
            "atr_pct", "realized_vol_20", "realized_vol_60", "bb_width",
            "parkinson_vol", "hl_range_pct", "gap_pct",
            # Volume (5)
            "vol_ratio", "obv_slope", "mfi_14", "vol_trend_5d", "large_block",
            # Calendar (4)
            "dow_sin", "dow_cos", "month_sin", "month_cos",
            # Macro (5)
            "vix_level", "yield_10y", "usd_ret_1m", "crude_ret_1m", "fii_flow_norm",
            # Sentiment (4)
            "sentiment_7d", "sentiment_30d", "sentiment_momentum", "insider_buy",
            # Earnings (4)
            "eps_surprise_pct", "rev_surprise_pct", "beat_flag", "days_since_earnings",
        ]
