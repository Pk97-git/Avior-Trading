"""
Correlation Breakdown Detection — hedge fund regime-change signal.
Detects when short-term correlations spike vs long-term baseline (crisis signal).
Pure numpy/pandas math only.
"""
from __future__ import annotations
import numpy as np
import pandas as pd


# ─── Helpers ──────────────────────────────────────────────────────────────────

def _avg_pairwise_corr(corr_matrix: pd.DataFrame) -> float:
    """Average of upper-triangle off-diagonal elements of a correlation matrix."""
    mat = corr_matrix.values.astype(float)
    n = mat.shape[0]
    if n < 2:
        return float("nan")
    upper_idx = np.triu_indices(n, k=1)
    vals = mat[upper_idx]
    return float(np.nanmean(vals))


def _alert_level(spike_ratio: float) -> str:
    if spike_ratio >= 1.5:
        return "CRASH_WARNING"
    if spike_ratio >= 1.2:
        return "ELEVATED"
    return "NORMAL"


# ─── Main functions ────────────────────────────────────────────────────────────

def detect_correlation_breakdown(
    returns_df: pd.DataFrame,
    lookback_short: int = 20,
    lookback_long: int = 60,
) -> dict:
    """
    Detects when short-term correlations spike vs long-term baseline.

    Parameters
    ----------
    returns_df     : DataFrame of ticker returns (columns = tickers, rows = dates)
    lookback_short : window for short-term correlation (default 20)
    lookback_long  : window for long-term baseline correlation (default 60)

    Returns
    -------
    dict with alert level, spike ratio, per-pair breakdown, plain-English explanation
    """
    if returns_df.empty or returns_df.shape[1] < 2:
        return {"error": "Need at least 2 tickers and non-empty returns"}

    # Drop tickers with insufficient data
    valid = returns_df.dropna(axis=1, how="all")
    if valid.shape[1] < 2:
        return {"error": "Insufficient non-null tickers"}

    n = len(valid)
    if n < lookback_short:
        return {"error": f"Need at least {lookback_short} rows; got {n}"}

    short_window = valid.iloc[-lookback_short:]
    long_window  = valid.iloc[-min(lookback_long, n):]

    corr_short = short_window.corr()
    corr_long  = long_window.corr()

    avg_short = _avg_pairwise_corr(corr_short)
    avg_long  = _avg_pairwise_corr(corr_long)

    spike_ratio = avg_short / avg_long if abs(avg_long) > 1e-9 else float("inf")
    alert = _alert_level(spike_ratio)

    # Per-pair breakdown
    tickers = list(valid.columns)
    pairs = []
    for i in range(len(tickers)):
        for j in range(i + 1, len(tickers)):
            t1, t2 = tickers[i], tickers[j]
            c_short = float(corr_short.loc[t1, t2]) if t1 in corr_short.index and t2 in corr_short.columns else float("nan")
            c_long  = float(corr_long.loc[t1, t2])  if t1 in corr_long.index  and t2 in corr_long.columns  else float("nan")
            delta   = c_short - c_long if not (np.isnan(c_short) or np.isnan(c_long)) else float("nan")
            pairs.append({
                "ticker_a": t1,
                "ticker_b": t2,
                "corr_short": round(c_short, 4),
                "corr_long":  round(c_long, 4),
                "delta":      round(delta, 4) if not np.isnan(delta) else None,
            })

    # Sort by biggest positive delta (biggest correlation spike)
    pairs_sorted = sorted(
        [p for p in pairs if p["delta"] is not None],
        key=lambda x: x["delta"],
        reverse=True,
    )
    top5 = pairs_sorted[:5]

    # Plain-English explanation
    explanation: list[str] = []
    explanation.append(
        f"Short-term ({lookback_short}d) avg correlation: {avg_short:.3f}. "
        f"Long-term ({min(lookback_long, n)}d) baseline: {avg_long:.3f}."
    )
    explanation.append(f"Correlation spike ratio: {spike_ratio:.2f}x.")
    if alert == "CRASH_WARNING":
        explanation.append(
            "CRASH WARNING: Correlations have spiked >50% above baseline. "
            "Portfolio diversification is breaking down — a risk-off event may be underway. "
            "Consider reducing gross exposure and adding tail hedges."
        )
    elif alert == "ELEVATED":
        explanation.append(
            "ELEVATED: Short-term correlations are 20-50% above baseline. "
            "Diversification benefits are diminishing. Monitor closely."
        )
    else:
        explanation.append(
            "NORMAL: Short-term correlations are in line with the long-term baseline. "
            "Diversification is functioning as expected."
        )

    if top5:
        top_pair = top5[0]
        explanation.append(
            f"Largest spike: {top_pair['ticker_a']} / {top_pair['ticker_b']} "
            f"correlation jumped {top_pair['delta']:+.3f} vs baseline."
        )

    return {
        "alert": alert,
        "avg_corr_short": round(avg_short, 4),
        "avg_corr_long":  round(avg_long, 4),
        "spike_ratio": round(spike_ratio, 4),
        "lookback_short": lookback_short,
        "lookback_long":  min(lookback_long, n),
        "n_tickers": len(tickers),
        "tickers": tickers,
        "top5_spiking_pairs": top5,
        "all_pairs": pairs,
        "explanation": explanation,
    }


def compute_rolling_correlation_history(
    returns_df: pd.DataFrame,
    window: int = 20,
) -> dict:
    """
    Returns rolling average pairwise correlation over time.

    Returns
    -------
    dict with list of {date, avg_corr}
    """
    if returns_df.empty or returns_df.shape[1] < 2:
        return {"error": "Need at least 2 tickers and non-empty returns"}

    valid = returns_df.dropna(axis=1, how="all")
    if valid.shape[1] < 2:
        return {"error": "Insufficient non-null tickers"}

    n = len(valid)
    if n < window:
        return {"error": f"Need at least {window} rows; got {n}"}

    tickers = list(valid.columns)
    dates = list(valid.index)
    history: list[dict] = []

    for i in range(window - 1, n):
        chunk = valid.iloc[i - window + 1 : i + 1]
        corr = chunk.corr()
        avg = _avg_pairwise_corr(corr)
        date_val = str(dates[i]) if not isinstance(dates[i], str) else dates[i]
        history.append({"date": date_val, "avg_corr": round(avg, 4)})

    return {
        "window": window,
        "n_tickers": len(tickers),
        "tickers": tickers,
        "history": history,
    }
