"""
Drawdown Manager — hedge-fund-grade drawdown computation engine.
Pure numpy math only.
"""
from __future__ import annotations
import math
import numpy as np


# ─── Constants ────────────────────────────────────────────────────────────────

ALERT_THRESHOLDS = {
    "OK":       (0.0,  0.05),
    "WARNING":  (0.05, 0.10),
    "CRITICAL": (0.10, 0.15),
    "HALT":     (0.15, float("inf")),
}

POSITION_MULTIPLIERS = {
    "OK":       1.0,
    "WARNING":  0.75,
    "CRITICAL": 0.50,
    "HALT":     0.0,
}


def _alert_level(drawdown_pct: float) -> str:
    """Return alert level string for an absolute drawdown fraction."""
    dd = abs(drawdown_pct)
    if dd >= 0.15:
        return "HALT"
    if dd >= 0.10:
        return "CRITICAL"
    if dd >= 0.05:
        return "WARNING"
    return "OK"


def compute_drawdown_metrics(returns: list[float]) -> dict:
    """
    Given a list of daily P&L returns (e.g. [0.01, -0.02, ...]):
    - Rolling max, drawdown series, current drawdown %
    - Max drawdown %, average drawdown, recovery days estimate
    - Calmar ratio (annual return / max drawdown)
    - Drawdown alert level: OK / WARNING / CRITICAL / HALT
    - Position size multiplier: 1.0 / 0.75 / 0.5 / 0.0
    - Plain English bullets
    """
    if not returns:
        return {"error": "No returns provided"}

    rets = np.array(returns, dtype=float)
    n = len(rets)

    # Cumulative wealth index (starting at 1.0)
    wealth = np.cumprod(1.0 + rets)
    rolling_max = np.maximum.accumulate(wealth)

    # Drawdown series (negative values)
    drawdown_series = (wealth - rolling_max) / rolling_max

    current_dd = float(drawdown_series[-1])
    max_dd = float(drawdown_series.min())           # most negative
    avg_dd = float(drawdown_series[drawdown_series < 0].mean()) if (drawdown_series < 0).any() else 0.0

    # Recovery days estimate: average length of drawdown periods
    in_dd = drawdown_series < -1e-8
    dd_lengths: list[int] = []
    count = 0
    for flag in in_dd:
        if flag:
            count += 1
        elif count > 0:
            dd_lengths.append(count)
            count = 0
    if count > 0:
        dd_lengths.append(count)
    recovery_days_est = int(round(np.mean(dd_lengths))) if dd_lengths else 0

    # Annualised return (assuming 252 trading days)
    total_return = float(wealth[-1]) - 1.0
    annual_return = (1.0 + total_return) ** (252.0 / n) - 1.0 if n > 0 else 0.0

    # Calmar ratio
    max_dd_abs = abs(max_dd)
    calmar = annual_return / max_dd_abs if max_dd_abs > 1e-9 else float("nan")

    alert = _alert_level(current_dd)
    pos_multiplier = POSITION_MULTIPLIERS[alert]

    # Plain-English bullets
    bullets: list[str] = []
    bullets.append(f"Current drawdown is {current_dd * 100:.2f}% from the recent peak.")
    bullets.append(f"Maximum historical drawdown: {max_dd * 100:.2f}%.")
    bullets.append(f"Average drawdown depth: {avg_dd * 100:.2f}%.")
    if recovery_days_est:
        bullets.append(f"Estimated recovery period: ~{recovery_days_est} trading days.")
    if not math.isnan(calmar):
        bullets.append(f"Calmar ratio: {calmar:.2f} (annual return / max drawdown).")
    else:
        bullets.append("Calmar ratio: N/A (max drawdown is zero).")
    bullets.append(
        f"Alert level: {alert} — position size multiplier set to {pos_multiplier:.0%}."
    )
    if alert == "HALT":
        bullets.append("Trading HALTED: drawdown exceeds 15%. Reduce all risk immediately.")
    elif alert == "CRITICAL":
        bullets.append("CRITICAL drawdown: cut position sizes by 50% and review all open positions.")
    elif alert == "WARNING":
        bullets.append("WARNING: drawdown approaching risk limits. Consider reducing exposure.")

    return {
        "n_days": n,
        "total_return_pct": round(total_return * 100, 4),
        "annual_return_pct": round(annual_return * 100, 4),
        "current_drawdown_pct": round(current_dd * 100, 4),
        "max_drawdown_pct": round(max_dd * 100, 4),
        "avg_drawdown_pct": round(avg_dd * 100, 4),
        "recovery_days_estimate": recovery_days_est,
        "calmar_ratio": round(calmar, 4) if not math.isnan(calmar) else None,
        "alert_level": alert,
        "position_size_multiplier": pos_multiplier,
        "drawdown_series": [round(float(x) * 100, 4) for x in drawdown_series],
        "wealth_index": [round(float(x), 6) for x in wealth],
        "bullets": bullets,
    }


def compute_portfolio_drawdown(
    positions: list[dict],
    nav_history: list[dict],
) -> dict:
    """
    positions: list of {ticker, weight, current_pnl_pct}
    nav_history: list of {date, nav}
    Returns drawdown metrics + per-position contribution to drawdown.
    """
    if not nav_history:
        return {"error": "nav_history is empty"}

    # Extract NAV series
    nav_values = [float(entry["nav"]) for entry in nav_history]
    nav_arr = np.array(nav_values, dtype=float)

    # Compute NAV-based returns
    if len(nav_arr) > 1:
        nav_returns = np.diff(nav_arr) / nav_arr[:-1]
    else:
        nav_returns = np.array([0.0])

    nav_metrics = compute_drawdown_metrics(nav_returns.tolist())

    # Per-position drawdown contribution
    per_position = []
    total_weight = sum(abs(float(p.get("weight", 0))) for p in positions)
    for pos in positions:
        ticker = pos.get("ticker", "UNKNOWN")
        weight = float(pos.get("weight", 0))
        pnl_pct = float(pos.get("current_pnl_pct", 0))
        contribution = weight * (pnl_pct / 100.0)   # weighted contribution to portfolio P&L
        per_position.append({
            "ticker": ticker,
            "weight": round(weight, 4),
            "current_pnl_pct": round(pnl_pct, 4),
            "drawdown_contribution_pct": round(contribution * 100, 4),
        })

    # Sort by worst contribution
    per_position.sort(key=lambda x: x["drawdown_contribution_pct"])

    nav_metrics["per_position_contributions"] = per_position
    nav_metrics["n_positions"] = len(positions)
    nav_metrics["nav_start"] = nav_values[0]
    nav_metrics["nav_latest"] = nav_values[-1]

    return nav_metrics
