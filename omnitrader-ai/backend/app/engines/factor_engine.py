"""
engines/factor_engine.py
=========================
Compute factor exposures for individual stocks and portfolios.

Factors (all computed from price data — no premium subscriptions needed):
  momentum:    12-1 month return (industry standard Fama-French momentum)
  volatility:  Annualised 30-day rolling std dev (lower = more stable)
  quality:     AI score from DB as proxy (60-100 = high quality)
  value:       1 - (price / 52w_high) — stocks near 52w low are "cheap"
  trend:       Price vs SMA200 — above = uptrend, below = downtrend

Each factor is z-score normalised across the universe for comparability.
Portfolio exposure = weighted average of individual stock exposures.
"""
import logging
import numpy as np
import pandas as pd
from typing import Optional

logger = logging.getLogger(__name__)


def compute_stock_factors(
    ticker: str,
    prices: pd.Series,          # daily close prices, at least 252 days
    ai_score: Optional[float] = None,
) -> Optional[dict]:
    """
    Compute factor scores for a single stock.
    Returns None if insufficient data.
    """
    if prices is None or len(prices) < 60:
        return None

    prices = prices.dropna().sort_index()
    current_price = float(prices.iloc[-1])

    # ── Momentum (12-1 month) ──────────────────────────────────────────────
    try:
        if len(prices) >= 252:
            price_12m_ago = float(prices.iloc[-252])
            price_1m_ago  = float(prices.iloc[-21])
            momentum_raw  = (price_1m_ago - price_12m_ago) / price_12m_ago
        elif len(prices) >= 60:
            momentum_raw = (current_price - float(prices.iloc[0])) / float(prices.iloc[0])
        else:
            momentum_raw = 0.0
    except Exception:
        momentum_raw = 0.0

    # ── Volatility (annualised 30-day) ────────────────────────────────────
    try:
        returns_30d = prices.pct_change().iloc[-30:].dropna()
        vol_raw = float(returns_30d.std() * np.sqrt(252)) if len(returns_30d) >= 20 else 0.3
    except Exception:
        vol_raw = 0.3

    # ── Value proxy (distance from 52-week high) ──────────────────────────
    try:
        high_52w = float(prices.iloc[-252:].max()) if len(prices) >= 252 else float(prices.max())
        # 0 = at 52w high (expensive), 1 = far below (cheap)
        value_raw = 1.0 - (current_price / high_52w) if high_52w > 0 else 0.5
    except Exception:
        value_raw = 0.5

    # ── Trend (price vs SMA200) ───────────────────────────────────────────
    try:
        sma200 = float(prices.iloc[-200:].mean()) if len(prices) >= 200 else float(prices.mean())
        trend_raw = (current_price - sma200) / sma200 if sma200 > 0 else 0.0
    except Exception:
        trend_raw = 0.0

    # ── Quality (AI score proxy, normalised to 0-1) ───────────────────────
    quality_raw = (ai_score or 50.0) / 100.0

    return {
        "ticker":       ticker,
        "momentum_raw": round(momentum_raw, 4),
        "vol_raw":      round(vol_raw, 4),
        "value_raw":    round(value_raw, 4),
        "trend_raw":    round(trend_raw, 4),
        "quality_raw":  round(quality_raw, 4),
    }


def normalise_factors(factor_rows: list) -> list:
    """Z-score normalise each factor across all stocks."""
    if not factor_rows:
        return []

    df = pd.DataFrame(factor_rows)
    raw_cols = ["momentum_raw", "vol_raw", "value_raw", "trend_raw", "quality_raw"]
    factor_names = ["momentum", "volatility", "value", "trend", "quality"]

    for raw_col, factor_name in zip(raw_cols, factor_names):
        col = df[raw_col].replace([np.inf, -np.inf], np.nan)
        mean = col.mean()
        std  = col.std()
        if std > 0:
            df[factor_name] = ((col - mean) / std).clip(-3, 3).round(3)
        else:
            df[factor_name] = 0.0

    result = df[["ticker"] + factor_names].to_dict("records")
    return result


def compute_portfolio_exposure(
    holdings: list,       # [{ticker, weight_pct, factor scores...}]
) -> dict:
    """
    Compute weighted portfolio factor exposure.
    Compares to a neutral benchmark (0.0 = market average).
    """
    if not holdings:
        return {}

    factor_names = ["momentum", "volatility", "value", "trend", "quality"]
    portfolio_exposure = {}

    for factor in factor_names:
        total_weight = sum(h.get("weight_pct", 0) for h in holdings)
        if total_weight == 0:
            portfolio_exposure[factor] = 0.0
            continue
        weighted_sum = sum(
            h.get(factor, 0) * h.get("weight_pct", 0)
            for h in holdings
        )
        portfolio_exposure[factor] = round(weighted_sum / total_weight, 3)

    # Interpretation
    interpretations = {}
    thresholds = {
        "momentum":   ("High momentum exposure — will hurt when momentum reverses", "Low momentum — defensive positioning", "Balanced momentum exposure"),
        "volatility": ("High volatility exposure — portfolio will be volatile", "Low volatility — defensive/stable portfolio", "Average volatility"),
        "value":      ("Value-tilted — stocks trading below their highs", "Growth/momentum tilt — stocks near highs", "Balanced value/growth"),
        "trend":      ("Strong uptrend exposure — well above key moving averages", "Downtrend exposure — portfolio below MAs", "Mixed trend signals"),
        "quality":    ("High quality — strong AI scores across portfolio", "Lower quality — weaker signals", "Mixed quality"),
    }

    for factor, exposure in portfolio_exposure.items():
        high_msg, low_msg, neutral_msg = thresholds.get(factor, ("", "", ""))
        if exposure > 0.5:
            interp = f"OVERWEIGHT: {high_msg}"
            risk = "HIGH"
        elif exposure < -0.5:
            interp = f"UNDERWEIGHT: {low_msg}"
            risk = "LOW"
        else:
            interp = f"NEUTRAL: {neutral_msg}"
            risk = "MODERATE"
        interpretations[factor] = {"interpretation": interp, "risk_level": risk}

    return {
        "exposures":        portfolio_exposure,
        "interpretations":  interpretations,
        "dominant_factor":  max(portfolio_exposure.items(), key=lambda x: abs(x[1]))[0] if portfolio_exposure else None,
    }
