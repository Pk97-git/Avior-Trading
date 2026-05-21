"""
engines/stress_test.py
=======================
Portfolio stress tester. Given a set of open positions and price history,
simulates P&L under standard market crash scenarios.

Scenarios:
  - Market -10% (mild correction)
  - Market -20% (bear market entry)
  - Market -30% (severe bear / crash)
  - Market -40% (2008-style crash)
  - India-specific: Nifty -15% (typical India correction)
  - US tech selloff: Nasdaq -25%
  - Black swan: -50% (COVID March 2020 type)
  - Custom: user-defined shock

Each position's simulated loss considers:
  1. Beta to market (from price correlation with Nifty/SPX)
  2. Stop loss protection (if stop is set, loss is capped at stop)
  3. Portfolio concentration risk
"""
import logging
from typing import Optional
import numpy as np
import pandas as pd

logger = logging.getLogger(__name__)

SCENARIOS = [
    {"id": "mild_correction",   "label": "Mild Correction (-10%)",     "market_shock": -0.10},
    {"id": "bear_market",       "label": "Bear Market Entry (-20%)",    "market_shock": -0.20},
    {"id": "severe_bear",       "label": "Severe Bear Market (-30%)",   "market_shock": -0.30},
    {"id": "crash_2008",        "label": "2008-Style Crash (-40%)",     "market_shock": -0.40},
    {"id": "india_correction",  "label": "India Correction (-15%)",     "market_shock": -0.15},
    {"id": "black_swan",        "label": "Black Swan Event (-50%)",     "market_shock": -0.50},
]


def estimate_beta(ticker_prices: pd.Series, market_prices: pd.Series) -> float:
    """Estimate beta of a stock vs market using OLS regression on daily returns."""
    try:
        t_ret = ticker_prices.pct_change().dropna()
        m_ret = market_prices.pct_change().dropna()
        common = t_ret.index.intersection(m_ret.index)
        if len(common) < 20:
            return 1.0  # default to market beta
        t_r = t_ret.loc[common].values
        m_r = m_ret.loc[common].values
        cov = np.cov(t_r, m_r)
        beta = cov[0, 1] / cov[1, 1] if cov[1, 1] != 0 else 1.0
        return round(float(np.clip(beta, 0.1, 3.0)), 3)
    except Exception:
        return 1.0


def run_stress_test(
    positions: list,                   # [{ticker, shares, entry_price, current_price, stop_loss, market_value}]
    price_history: dict,               # {ticker: pd.Series of close prices}
    market_history: Optional[pd.Series] = None,   # benchmark prices (Nifty / SPX)
    custom_shock: Optional[float] = None,  # e.g. -0.25 for -25%
    portfolio_cash: float = 0.0,
) -> dict:
    """
    Run stress test across all scenarios.
    Returns per-scenario P&L and overall risk metrics.
    """
    if not positions:
        return {"error": "No positions to stress test"}

    total_market_value = sum(p.get("market_value", p.get("current_price", 0) * p.get("shares", 0)) for p in positions)
    total_portfolio    = total_market_value + portfolio_cash

    # Estimate beta for each position
    position_betas = {}
    for pos in positions:
        ticker = pos["ticker"]
        if market_history is not None and ticker in price_history:
            beta = estimate_beta(price_history[ticker], market_history)
        else:
            beta = 1.0  # assume market beta if no history
        position_betas[ticker] = beta

    scenarios_to_run = list(SCENARIOS)
    if custom_shock is not None:
        scenarios_to_run.append({
            "id": "custom",
            "label": f"Custom Shock ({custom_shock*100:+.0f}%)",
            "market_shock": custom_shock,
        })

    results = []
    for scenario in scenarios_to_run:
        shock = scenario["market_shock"]
        scenario_positions = []
        total_loss = 0.0
        total_protected_loss = 0.0

        for pos in positions:
            ticker         = pos["ticker"]
            shares         = pos.get("shares", 0)
            current_price  = pos.get("current_price", pos.get("entry_price", 0))
            stop_loss      = pos.get("stop_loss")
            market_value   = shares * current_price

            beta           = position_betas.get(ticker, 1.0)
            stock_shock    = shock * beta  # higher beta = amplified move

            # Simulated price after shock
            simulated_price = current_price * (1 + stock_shock)

            # If stop loss is set, cap the downside
            if stop_loss and stop_loss > 0:
                simulated_price_protected = max(simulated_price, stop_loss)
            else:
                simulated_price_protected = simulated_price

            raw_loss       = (simulated_price - current_price) * shares
            protected_loss = (simulated_price_protected - current_price) * shares
            protection_value = protected_loss - raw_loss  # how much stop saved

            total_loss           += raw_loss
            total_protected_loss += protected_loss

            scenario_positions.append({
                "ticker":           ticker,
                "beta":             beta,
                "current_price":    round(current_price, 2),
                "simulated_price":  round(simulated_price, 2),
                "stock_shock_pct":  round(stock_shock * 100, 2),
                "market_value":     round(market_value, 2),
                "raw_loss":         round(raw_loss, 2),
                "protected_loss":   round(protected_loss, 2),
                "stop_protection":  round(protection_value, 2),
                "has_stop":         bool(stop_loss and stop_loss > 0),
            })

        # Sort by worst loss first
        scenario_positions.sort(key=lambda x: x["raw_loss"])

        portfolio_loss_pct = (total_loss / total_portfolio * 100) if total_portfolio > 0 else 0
        protected_loss_pct = (total_protected_loss / total_portfolio * 100) if total_portfolio > 0 else 0

        results.append({
            "scenario_id":          scenario["id"],
            "scenario_label":       scenario["label"],
            "market_shock_pct":     round(shock * 100, 1),
            "total_raw_loss":       round(total_loss, 2),
            "total_protected_loss": round(total_protected_loss, 2),
            "portfolio_loss_pct":   round(portfolio_loss_pct, 2),
            "protected_loss_pct":   round(protected_loss_pct, 2),
            "stops_saved":          round(total_protected_loss - total_loss, 2),
            "positions":            scenario_positions,
        })

    # Overall risk metrics
    worst_scenario = min(results, key=lambda x: x["total_raw_loss"])
    avg_beta = np.mean([b for b in position_betas.values()])

    concentration = []
    for pos in positions:
        mv = pos.get("market_value", pos.get("current_price", 0) * pos.get("shares", 0))
        concentration.append({"ticker": pos["ticker"], "weight_pct": round(mv / total_market_value * 100, 1) if total_market_value > 0 else 0})
    concentration.sort(key=lambda x: -x["weight_pct"])

    top_concentration = concentration[0]["weight_pct"] if concentration else 0
    is_concentrated = top_concentration > 30

    return {
        "portfolio_value":    round(total_portfolio, 2),
        "equity_value":       round(total_market_value, 2),
        "cash":               round(portfolio_cash, 2),
        "position_count":     len(positions),
        "avg_portfolio_beta": round(float(avg_beta), 3),
        "concentration":      concentration,
        "is_concentrated":    is_concentrated,
        "worst_scenario":     worst_scenario["scenario_label"],
        "worst_case_loss":    worst_scenario["total_raw_loss"],
        "worst_case_loss_pct": worst_scenario["portfolio_loss_pct"],
        "scenarios":          results,
        "risk_notes": _generate_risk_notes(results, avg_beta, top_concentration, positions),
    }


def _generate_risk_notes(results, avg_beta, top_concentration, positions):
    notes = []
    stops_count = sum(1 for p in positions if p.get("stop_loss"))
    if stops_count < len(positions):
        notes.append(f"{len(positions) - stops_count} position(s) have no stop loss — they have unlimited downside in a crash.")
    if avg_beta > 1.3:
        notes.append(f"Portfolio beta is {avg_beta:.1f} — this portfolio is more volatile than the market. It falls harder in crashes.")
    if top_concentration > 40:
        notes.append(f"Top holding is {top_concentration:.0f}% of portfolio — dangerously concentrated. Professionals cap single positions at 10-15%.")
    elif top_concentration > 25:
        notes.append(f"Top holding is {top_concentration:.0f}% of portfolio — consider trimming for better diversification.")
    mild = next((r for r in results if r["scenario_id"] == "mild_correction"), None)
    if mild and abs(mild["portfolio_loss_pct"]) > 15:
        notes.append(f"Even a mild -10% correction would cost you {mild['portfolio_loss_pct']:.1f}% of portfolio — your positions are highly leveraged to market moves.")
    return notes
