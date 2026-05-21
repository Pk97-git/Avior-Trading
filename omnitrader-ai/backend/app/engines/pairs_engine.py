"""
engines/pairs_engine.py
=======================
Pairs Trading engine — finds correlated stock pairs and detects divergences.

Steps:
1. Fetch price history for all stocks in universe (or a curated shortlist by sector)
2. Compute correlation matrix
3. Find pairs with correlation > 0.7 over 1 year
4. For each high-correlation pair, compute spread and z-score
5. Return pairs where z-score > 2.0 (diverged) as trade signals

Spread = log(Price_A) - log(Price_B) * hedge_ratio
Z-score = (spread - mean) / std over 60-day rolling window

Signal:
  z > 2.0  → SHORT A, LONG B (A is expensive relative to B)
  z < -2.0 → LONG A, SHORT B (A is cheap relative to B)
  |z| < 0.5 → pair has converged — close the trade
"""
import logging
import numpy as np
import pandas as pd
from typing import Optional

logger = logging.getLogger(__name__)

# Curated sector pairs for Indian and US markets
SECTOR_PAIRS = {
    "IN_BANKS": ["HDFCBANK.NS", "KOTAKBANK.NS", "ICICIBANK.NS", "AXISBANK.NS", "SBIN.NS"],
    "IN_IT":    ["TCS.NS", "INFY.NS", "WIPRO.NS", "HCLTECH.NS", "TECHM.NS"],
    "IN_AUTO":  ["MARUTI.NS", "TATAMOTORS.NS", "M&M.NS", "BAJAJ-AUTO.NS"],
    "US_TECH":  ["AAPL", "MSFT", "GOOGL", "META", "AMZN"],
    "US_BANKS": ["JPM", "BAC", "GS", "MS", "C"],
    "US_OIL":   ["XOM", "CVX", "COP", "SLB", "OXY"],
}


def compute_hedge_ratio(series_a: pd.Series, series_b: pd.Series) -> float:
    """OLS regression of log prices to find hedge ratio (beta)."""
    log_a = np.log(series_a.dropna())
    log_b = np.log(series_b.dropna())
    common = log_a.index.intersection(log_b.index)
    if len(common) < 30:
        return 1.0
    la = log_a.loc[common].values
    lb = log_b.loc[common].values
    # OLS: la = beta * lb + alpha
    cov_matrix = np.cov(la, lb)
    beta = cov_matrix[0, 1] / cov_matrix[1, 1] if cov_matrix[1, 1] != 0 else 1.0
    return round(float(beta), 4)


def compute_spread_zscore(
    series_a: pd.Series,
    series_b: pd.Series,
    hedge_ratio: float,
    window: int = 60,
) -> pd.Series:
    """Compute rolling z-score of the log-price spread."""
    log_a = np.log(series_a)
    log_b = np.log(series_b)
    spread = log_a - hedge_ratio * log_b
    rolling_mean = spread.rolling(window=window).mean()
    rolling_std  = spread.rolling(window=window).std()
    zscore = (spread - rolling_mean) / rolling_std.replace(0, np.nan)
    return zscore


def analyze_pair(
    ticker_a: str,
    ticker_b: str,
    prices_a: pd.Series,
    prices_b: pd.Series,
) -> Optional[dict]:
    """Full analysis of a single pair. Returns None if pair is not suitable."""
    common_idx = prices_a.index.intersection(prices_b.index)
    if len(common_idx) < 60:
        return None

    pa = prices_a.loc[common_idx]
    pb = prices_b.loc[common_idx]

    # Correlation
    corr = pa.pct_change().corr(pb.pct_change())
    if corr < 0.65:
        return None  # Not correlated enough

    hedge_ratio = compute_hedge_ratio(pa, pb)
    zscore_series = compute_spread_zscore(pa, pb, hedge_ratio)
    current_zscore = float(zscore_series.iloc[-1]) if not zscore_series.empty else 0.0

    if np.isnan(current_zscore):
        return None

    # Half-life of mean reversion (Ornstein-Uhlenbeck)
    spread = np.log(pa) - hedge_ratio * np.log(pb)
    spread_lag = spread.shift(1).dropna()
    spread_diff = spread.diff().dropna()
    common2 = spread_lag.index.intersection(spread_diff.index)
    try:
        from numpy.polynomial import polynomial as P
        coef = np.polyfit(spread_lag.loc[common2].values, spread_diff.loc[common2].values, 1)
        half_life = -np.log(2) / coef[0] if coef[0] < 0 else None
        half_life = round(float(half_life), 1) if half_life and 1 < half_life < 200 else None
    except Exception:
        half_life = None

    # Signal
    if current_zscore > 2.0:
        signal = "SHORT_A_LONG_B"
        signal_label = f"SHORT {ticker_a}, LONG {ticker_b}"
        direction = f"{ticker_a} is expensive vs {ticker_b} — expect {ticker_a} to fall or {ticker_b} to rise"
    elif current_zscore < -2.0:
        signal = "LONG_A_SHORT_B"
        signal_label = f"LONG {ticker_a}, SHORT {ticker_b}"
        direction = f"{ticker_a} is cheap vs {ticker_b} — expect {ticker_a} to rise or {ticker_b} to fall"
    elif abs(current_zscore) < 0.5:
        signal = "CONVERGED"
        signal_label = "Pair has converged — close if in a trade"
        direction = "Spread is near historical mean"
    else:
        signal = "NEUTRAL"
        signal_label = "No trade signal"
        direction = "Spread is within normal range"

    # Strength: how far from mean
    strength = min(5, max(1, int(abs(current_zscore))))

    # Historical zscore distribution
    recent_zscores = zscore_series.dropna().iloc[-20:].tolist()

    return {
        "ticker_a":         ticker_a,
        "ticker_b":         ticker_b,
        "correlation":      round(corr, 4),
        "hedge_ratio":      hedge_ratio,
        "current_zscore":   round(current_zscore, 3),
        "signal":           signal,
        "signal_label":     signal_label,
        "direction":        direction,
        "strength":         strength,
        "half_life_days":   half_life,
        "price_a":          round(float(pa.iloc[-1]), 2),
        "price_b":          round(float(pb.iloc[-1]), 2),
        "is_tradeable":     signal in ("SHORT_A_LONG_B", "LONG_A_SHORT_B"),
        "recent_zscores":   [round(z, 3) for z in recent_zscores],
        "data_points":      len(common_idx),
    }
