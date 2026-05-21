"""
Tail Risk Hedging Rules — composite tail-risk scoring and hedge recommendations.
Pure numpy math; no external ML libraries.
"""
from __future__ import annotations
import math


# ─── Scoring weights ───────────────────────────────────────────────────────────

# Each component contributes up to 25 points (total = 100)
_DRAWDOWN_WEIGHT    = 25.0
_CORRELATION_WEIGHT = 25.0
_VAR_WEIGHT         = 25.0
_REGIME_WEIGHT      = 25.0


def _drawdown_component(max_dd_pct: float, current_dd_pct: float) -> float:
    """Score 0-25 based on drawdown severity."""
    # Use the worse of max/current
    dd = max(abs(max_dd_pct), abs(current_dd_pct))
    # 0% dd → 0pts, 20%+ dd → 25pts
    score = min(dd / 20.0, 1.0) * _DRAWDOWN_WEIGHT
    return score


def _correlation_component(avg_correlation: float) -> float:
    """Score 0-25 based on portfolio average correlation.
    High correlation → diversification failing → more tail risk.
    """
    # correlation ranges from -1 to 1; dangerous zone is > 0.6
    clamped = max(min(avg_correlation, 1.0), -1.0)
    # Map [-1, 1] → [0, 25], with emphasis on the 0.5-1.0 range
    normalized = (clamped + 1.0) / 2.0   # 0 to 1
    score = normalized ** 1.5 * _CORRELATION_WEIGHT
    return score


def _var_component(var_95_pct: float) -> float:
    """Score 0-25 based on 95% VaR magnitude (expressed as positive %).
    VaR 0% → 0pts, VaR 10%+ → 25pts.
    """
    var = abs(var_95_pct)
    score = min(var / 10.0, 1.0) * _VAR_WEIGHT
    return score


def _regime_component(regime: str, vix_level: float | None, beta: float | None) -> float:
    """Score 0-25 based on market regime, VIX, and portfolio beta."""
    regime_scores = {"BULL": 5.0, "NEUTRAL": 12.5, "BEAR": 22.0}
    base = regime_scores.get(regime.upper(), 12.5)

    # VIX adjustment: normal ~15, elevated ~25, fearful ~35+
    vix_adj = 0.0
    if vix_level is not None:
        if vix_level >= 35:
            vix_adj = 3.0
        elif vix_level >= 25:
            vix_adj = 1.5

    # Beta adjustment: high-beta portfolios amplify tail risk
    beta_adj = 0.0
    if beta is not None:
        if beta >= 1.5:
            beta_adj = 2.0
        elif beta >= 1.2:
            beta_adj = 1.0

    return min(base + vix_adj + beta_adj, _REGIME_WEIGHT)


def _hedge_recommendation(score: float) -> str:
    if score >= 80:
        return "DEFENSIVE"
    if score >= 60:
        return "HEAVY"
    if score >= 40:
        return "MODERATE"
    if score >= 20:
        return "LIGHT"
    return "NONE"


def compute_tail_risk_score(portfolio_data: dict) -> dict:
    """
    portfolio_data keys:
      max_drawdown_pct    : float (e.g. -12.5 or 12.5)
      current_drawdown_pct: float
      avg_correlation     : float (e.g. 0.65)
      var_95_pct          : float (positive, e.g. 3.5 means 3.5% daily VaR)
      regime              : str (BULL / NEUTRAL / BEAR)
      vix_level           : float | None (optional)
      beta                : float | None (optional)
    """
    max_dd      = float(portfolio_data.get("max_drawdown_pct", 0.0))
    current_dd  = float(portfolio_data.get("current_drawdown_pct", 0.0))
    avg_corr    = float(portfolio_data.get("avg_correlation", 0.5))
    var_95      = float(portfolio_data.get("var_95_pct", 2.0))
    regime      = str(portfolio_data.get("regime", "NEUTRAL")).upper()
    vix_level   = portfolio_data.get("vix_level")
    beta        = portfolio_data.get("beta")

    vix_float   = float(vix_level) if vix_level is not None else None
    beta_float  = float(beta) if beta is not None else None

    # Component scores
    dd_score    = _drawdown_component(max_dd, current_dd)
    corr_score  = _correlation_component(avg_corr)
    var_score   = _var_component(var_95)
    regime_score = _regime_component(regime, vix_float, beta_float)

    total_score = dd_score + corr_score + var_score + regime_score
    total_score = max(0.0, min(100.0, total_score))

    hedge_rec = _hedge_recommendation(total_score)

    # Specific action rules
    actions: list[str] = []
    reasoning: list[str] = []

    # Drawdown actions
    if abs(current_dd) >= 15:
        actions.append("Halt new position opens. Drawdown exceeds 15% — activate risk-off protocol.")
        reasoning.append(f"Current drawdown ({abs(current_dd):.1f}%) has breached the 15% HALT threshold.")
    elif abs(current_dd) >= 10:
        actions.append("Reduce all positions by 50%. Critical drawdown zone.")
        reasoning.append(f"Current drawdown ({abs(current_dd):.1f}%) is in the CRITICAL 10-15% zone.")
    elif abs(current_dd) >= 5:
        actions.append("Reduce position sizes by 25%. Drawdown warning triggered.")

    # Tail hedge actions based on score
    if total_score > 60:
        actions.append("Buy 5% OTM puts on SPY (30 DTE) — hedge broad market tail risk.")
        reasoning.append(f"Tail risk score {total_score:.0f}/100 exceeds 60 — protective puts recommended.")
    if total_score > 70:
        actions.append("Buy VIX calls (ATM, 30-45 DTE) to hedge volatility spike.")
    if total_score > 80:
        actions.append("Consider long/short collar strategy on top holdings.")
        reasoning.append("Extreme tail risk score — full defensive posture required.")

    # Regime-based actions
    if regime == "BEAR":
        actions.append("Reduce position sizes by 25% — bear market regime active.")
        reasoning.append("Bear market regime detected. Historical drawdowns are deeper and longer.")
        if beta_float and beta_float > 1.0:
            actions.append(
                f"Portfolio beta {beta_float:.2f} amplifies bear-market losses. "
                "Reduce high-beta names or add inverse ETF exposure."
            )
    elif regime == "NEUTRAL":
        actions.append("Maintain current hedge ratio. Neutral regime — stay balanced.")

    # Correlation actions
    if avg_corr > 0.7:
        actions.append(
            "Diversification is severely impaired (avg corr > 0.7). "
            "Add uncorrelated assets: gold, Treasuries, or managed futures."
        )
        reasoning.append(
            f"Average pairwise correlation {avg_corr:.2f} is dangerously high — "
            "risk-off selling will hit all positions simultaneously."
        )
    elif avg_corr > 0.5:
        actions.append("Consider adding low-corr assets (commodities, REITs) to reduce concentration risk.")

    # Cash buffer rule: +2% cash for every 10 points above 50
    if total_score > 50:
        extra_cash_pct = math.ceil((total_score - 50) / 10) * 2
        actions.append(f"Add {extra_cash_pct}% cash buffer (rule: +2% per 10pts above score 50).")
        reasoning.append(f"Score {total_score:.0f} → +{extra_cash_pct}% cash buffer recommended.")

    # VaR actions
    if var_95 > 5:
        actions.append(
            f"Daily 95% VaR is {var_95:.1f}% — reduce gross exposure. "
            "Target VaR < 3% for normal markets."
        )
        reasoning.append(f"95% VaR of {var_95:.1f}% exceeds the 5% threshold.")

    # VIX actions
    if vix_float and vix_float >= 30:
        actions.append(
            f"VIX at {vix_float:.0f} — market fear elevated. "
            "Consider selling into strength and building dry powder."
        )
        reasoning.append(f"VIX={vix_float:.0f} signals elevated fear; options are expensive but protection is needed.")

    if not actions:
        actions.append("No immediate hedging actions required. Continue monitoring.")
        reasoning.append(f"Tail risk score {total_score:.0f}/100 is within acceptable range.")

    return {
        "tail_risk_score": round(total_score, 1),
        "components": {
            "drawdown_risk":     round(dd_score, 2),
            "correlation_risk":  round(corr_score, 2),
            "var_risk":          round(var_score, 2),
            "regime_risk":       round(regime_score, 2),
        },
        "hedge_recommendation": hedge_rec,
        "specific_actions": actions,
        "reasoning": reasoning,
        "inputs": {
            "max_drawdown_pct":     max_dd,
            "current_drawdown_pct": current_dd,
            "avg_correlation":      avg_corr,
            "var_95_pct":           var_95,
            "regime":               regime,
            "vix_level":            vix_float,
            "beta":                 beta_float,
        },
    }
