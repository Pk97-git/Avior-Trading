"""
engines/alpha_signals.py
=========================
Advanced alpha signal generators used by quantitative hedge funds:

1. Earnings Quality Score — detects earnings manipulation
   High accruals = company is inflating earnings. Will disappoint later.
   Signal: cash_flow_from_ops / net_income ratio
   Sloan (1996): stocks with low accruals outperform by 10%/year

2. Accruals Analysis — balance sheet accruals
   Accruals = Net Income - Cash Flow from Operations
   Normalised by total assets. High positive accruals = warning.

3. Cross-Sectional Momentum Ranking
   Rank all stocks by 12-1 month return (Jegadeesh & Titman 1993).
   Long top 10%, short bottom 10%. Works across all markets.

4. Filing Language Analysis (10-K/10-Q proxy)
   Uses management text from news/summaries to detect:
   - Uncertainty words (uncertain, challenging, headwinds)
   - Positive words (record, exceptional, outperform)
   - Net tone score as a signal
"""
import logging
import numpy as np
import pandas as pd
from typing import Optional

logger = logging.getLogger(__name__)

# Uncertainty/negative words from Loughran-McDonald financial sentiment dictionary
UNCERTAINTY_WORDS = [
    "uncertain", "uncertainty", "challenging", "headwind", "headwinds",
    "difficult", "challenging", "decline", "risk", "risks", "concern",
    "concerns", "volatile", "volatility", "pressure", "cautious",
    "slowdown", "weakness", "weak", "softer", "disappointing",
    "miss", "missed", "below", "shortfall", "warn", "warning",
]

POSITIVE_WORDS = [
    "record", "exceptional", "outstanding", "strong", "robust",
    "accelerating", "momentum", "growth", "outperform", "beat",
    "exceeded", "raised", "guidance", "confident", "opportunity",
    "innovative", "leadership", "market share", "expansion",
]


# ══════════════════════════════════════════════════════════════════════════════
# 1. EARNINGS QUALITY SCORE
# ══════════════════════════════════════════════════════════════════════════════

def compute_earnings_quality(
    net_income: Optional[float],
    cfo: Optional[float],          # cash flow from operations
    total_assets: Optional[float],
    prev_total_assets: Optional[float] = None,
) -> dict:
    """
    Sloan Accruals Score — the most predictive accounting signal.

    Accruals = Net Income - Cash Flow from Operations
    Accruals Ratio = Accruals / Avg Total Assets

    Score interpretation:
      < -0.05: HIGH QUALITY (cash exceeds earnings — conservative accounting)
      -0.05 to 0.05: NORMAL
      > 0.05: LOW QUALITY (earnings exceed cash — aggressive accounting)
      > 0.10: WARNING (possibly manipulated earnings)
    """
    if net_income is None or cfo is None:
        return {
            "score": None, "quality": "UNKNOWN",
            "accruals": None, "accruals_ratio": None,
            "cfo_to_ni": None, "note": "Missing financial data"
        }

    accruals = net_income - cfo
    avg_assets = None
    accruals_ratio = None

    if total_assets and total_assets > 0:
        denom = total_assets
        if prev_total_assets and prev_total_assets > 0:
            denom = (total_assets + prev_total_assets) / 2
        accruals_ratio = accruals / denom
        avg_assets = denom

    cfo_to_ni = cfo / net_income if net_income != 0 else None

    # Score 0-100: higher = better quality
    if accruals_ratio is not None:
        if accruals_ratio < -0.05:
            quality = "HIGH"
            score = min(100, 80 + abs(accruals_ratio) * 200)
        elif accruals_ratio <= 0.02:
            quality = "NORMAL"
            score = 60
        elif accruals_ratio <= 0.05:
            quality = "MODERATE"
            score = 45
        elif accruals_ratio <= 0.10:
            quality = "LOW"
            score = 30
        else:
            quality = "WARNING"
            score = max(0, 20 - (accruals_ratio - 0.10) * 100)
    elif cfo_to_ni is not None:
        if cfo_to_ni >= 1.2:
            quality, score = "HIGH", 80
        elif cfo_to_ni >= 0.8:
            quality, score = "NORMAL", 60
        elif cfo_to_ni >= 0.5:
            quality, score = "MODERATE", 40
        else:
            quality, score = "LOW", 20
    else:
        quality, score = "UNKNOWN", 50

    notes = []
    if quality == "HIGH":
        notes.append("Cash flow exceeds reported earnings — conservative accounting. Hedge funds LOVE this.")
    elif quality == "WARNING":
        notes.append("Reported earnings far exceed cash flow — possible earnings manipulation. High accruals historically predict future earnings disappointments.")
    elif quality == "LOW":
        notes.append("Earnings quality is weak. The company is booking profits but not collecting cash.")

    if cfo_to_ni is not None and cfo_to_ni < 0.5:
        notes.append(f"CFO/NI ratio: {cfo_to_ni:.2f} — only {cfo_to_ni*100:.0f}% of net income converts to real cash.")

    return {
        "score":          round(float(score), 1),
        "quality":        quality,
        "accruals":       round(float(accruals), 0) if accruals is not None else None,
        "accruals_ratio": round(float(accruals_ratio), 4) if accruals_ratio is not None else None,
        "cfo_to_ni":      round(float(cfo_to_ni), 3) if cfo_to_ni is not None else None,
        "net_income":     net_income,
        "cfo":            cfo,
        "notes":          notes,
    }


# ══════════════════════════════════════════════════════════════════════════════
# 2. CROSS-SECTIONAL MOMENTUM RANKING
# ══════════════════════════════════════════════════════════════════════════════

def compute_cross_sectional_momentum(
    price_series_map: dict,   # {ticker: pd.Series of close prices}
    lookback_months: int = 12,
    skip_months: int = 1,
) -> list:
    """
    Jegadeesh-Titman (1993) cross-sectional momentum.

    Rank ALL stocks by their 12-1 month return:
    - Return from 12 months ago to 1 month ago (skip last month to avoid reversal)
    - Top decile = LONG candidates
    - Bottom decile = SHORT candidates

    Returns sorted list with momentum score and decile assignment.
    """
    lookback_days = lookback_months * 21
    skip_days     = skip_months * 21

    results = []
    for ticker, prices in price_series_map.items():
        if prices is None or len(prices) < lookback_days + 5:
            continue

        prices_clean = prices.dropna().sort_index()
        n = len(prices_clean)

        try:
            price_end   = float(prices_clean.iloc[-(skip_days + 1)])    # 1 month ago
            price_start = float(prices_clean.iloc[-(lookback_days + 1)]) # 12 months ago
            momentum = (price_end - price_start) / price_start
        except (IndexError, ZeroDivisionError):
            continue

        results.append({
            "ticker":       ticker,
            "momentum_12_1": round(float(momentum), 4),
            "momentum_pct":  round(float(momentum) * 100, 2),
            "current_price": round(float(prices_clean.iloc[-1]), 2),
        })

    if not results:
        return []

    # Sort and assign deciles
    results.sort(key=lambda x: x["momentum_12_1"], reverse=True)
    n = len(results)

    for i, r in enumerate(results):
        rank = i + 1
        decile = min(10, int(rank / n * 10) + 1)
        r["rank"]   = rank
        r["decile"] = decile
        r["signal"] = (
            "STRONG_LONG"   if decile <= 1 else
            "LONG"          if decile <= 3 else
            "AVOID"         if decile >= 8 else
            "STRONG_SHORT"  if decile == 10 else
            "NEUTRAL"
        )

    return results


# ══════════════════════════════════════════════════════════════════════════════
# 3. FILING / TEXT TONE ANALYSIS (NO API REQUIRED)
# ══════════════════════════════════════════════════════════════════════════════

def analyse_filing_tone(text: str, ticker: str = "") -> dict:
    """
    Loughran-McDonald financial dictionary tone analysis.
    Works on any financial text: earnings releases, press releases, news summaries.
    No API required — pure word counting.
    """
    if not text:
        return {"error": "No text provided"}

    words = text.lower().split()
    total_words = max(len(words), 1)

    uncertainty_count = sum(1 for w in words if any(uw in w for uw in UNCERTAINTY_WORDS))
    positive_count    = sum(1 for w in words if any(pw in w for pw in POSITIVE_WORDS))

    uncertainty_pct = uncertainty_count / total_words * 100
    positive_pct    = positive_count    / total_words * 100
    net_tone        = positive_pct - uncertainty_pct

    if net_tone > 2:
        tone, score = "BULLISH", min(100, 60 + net_tone * 5)
    elif net_tone > 0:
        tone, score = "MILDLY_BULLISH", 55
    elif net_tone > -2:
        tone, score = "NEUTRAL", 50
    elif net_tone > -4:
        tone, score = "CAUTIOUS", 40
    else:
        tone, score = "BEARISH", max(0, 40 + net_tone * 5)

    matched_uncertainty = [w for w in UNCERTAINTY_WORDS if w in text.lower()][:5]
    matched_positive    = [w for w in POSITIVE_WORDS    if w in text.lower()][:5]

    return {
        "ticker":             ticker,
        "tone":               tone,
        "tone_score":         round(float(score), 1),
        "net_tone":           round(float(net_tone), 3),
        "positive_pct":       round(float(positive_pct), 3),
        "uncertainty_pct":    round(float(uncertainty_pct), 3),
        "word_count":         total_words,
        "matched_positive":   matched_positive,
        "matched_uncertainty": matched_uncertainty,
        "plain_english": [
            f"Text contains {positive_count} positive words ({positive_pct:.1f}%) and {uncertainty_count} uncertainty words ({uncertainty_pct:.1f}%)",
            f"Net tone: {net_tone:+.2f} → {tone}",
        ],
    }
