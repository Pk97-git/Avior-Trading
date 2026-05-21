"""
Options Greeks — Black-Scholes implementation using scipy.stats.norm.
Pure numpy/scipy math only.
"""
from __future__ import annotations
import math
import numpy as np
from scipy.stats import norm


def black_scholes_greeks(
    S: float,
    K: float,
    T: float,
    r: float,
    sigma: float,
    option_type: str = "call",
) -> dict:
    """
    Black-Scholes Greeks:
    - delta, gamma, theta (per day), vega (per 1% vol), rho
    - option_price, intrinsic_value, time_value
    - moneyness: ITM/ATM/OTM
    - breakeven price

    Parameters
    ----------
    S     : Current stock price
    K     : Strike price
    T     : Time to expiry in years
    r     : Risk-free rate (e.g. 0.05 for 5%)
    sigma : Implied volatility (e.g. 0.20 for 20%)
    option_type : 'call' or 'put'
    """
    if T <= 0:
        # Handle expiry edge case
        intrinsic = max(S - K, 0.0) if option_type.lower() == "call" else max(K - S, 0.0)
        return {
            "option_price": intrinsic,
            "intrinsic_value": intrinsic,
            "time_value": 0.0,
            "delta": (1.0 if S > K else 0.0) if option_type.lower() == "call" else (-1.0 if S < K else 0.0),
            "gamma": 0.0,
            "theta": 0.0,
            "vega": 0.0,
            "rho": 0.0,
            "moneyness": _moneyness(S, K),
            "breakeven": K + intrinsic if option_type.lower() == "call" else K - intrinsic,
        }

    opt = option_type.lower()
    d1 = (math.log(S / K) + (r + 0.5 * sigma ** 2) * T) / (sigma * math.sqrt(T))
    d2 = d1 - sigma * math.sqrt(T)

    nd1 = norm.cdf(d1)
    nd2 = norm.cdf(d2)
    n_d1 = norm.cdf(-d1)
    n_d2 = norm.cdf(-d2)
    pdf_d1 = norm.pdf(d1)

    disc = math.exp(-r * T)

    if opt == "call":
        price = S * nd1 - K * disc * nd2
        delta = nd1
        rho = K * T * disc * nd2 / 100.0   # per 1% rate change
        intrinsic = max(S - K, 0.0)
        breakeven = K + price
    else:
        price = K * disc * n_d2 - S * n_d1
        delta = nd1 - 1.0
        rho = -K * T * disc * n_d2 / 100.0
        intrinsic = max(K - S, 0.0)
        breakeven = K - price

    gamma = pdf_d1 / (S * sigma * math.sqrt(T))

    # Theta per day (divide by 252)
    theta_annual = (
        -(S * pdf_d1 * sigma) / (2.0 * math.sqrt(T))
        - r * K * disc * (nd2 if opt == "call" else n_d2)
    )
    theta = theta_annual / 252.0

    # Vega per 1% vol move (divide by 100)
    vega = S * pdf_d1 * math.sqrt(T) / 100.0

    time_value = max(price - intrinsic, 0.0)
    moneyness = _moneyness(S, K)

    return {
        "option_price": round(price, 4),
        "intrinsic_value": round(intrinsic, 4),
        "time_value": round(time_value, 4),
        "delta": round(delta, 6),
        "gamma": round(gamma, 6),
        "theta": round(theta, 6),
        "vega": round(vega, 6),
        "rho": round(rho, 6),
        "d1": round(d1, 6),
        "d2": round(d2, 6),
        "moneyness": moneyness,
        "breakeven": round(breakeven, 4),
        "option_type": opt,
        "inputs": {"S": S, "K": K, "T_years": T, "r": r, "sigma": sigma},
    }


def _moneyness(S: float, K: float) -> str:
    ratio = S / K
    if abs(ratio - 1.0) <= 0.02:
        return "ATM"
    if ratio > 1.0:
        return "ITM"
    return "OTM"


def compute_portfolio_greeks(positions: list[dict]) -> dict:
    """
    positions: list of {ticker, option_type, S, K, T_days, sigma, quantity, r=0.05}

    Returns aggregate delta, gamma, theta, vega for entire options book.
    Plus delta_dollars (delta * S * quantity * 100 for standard lots).
    """
    agg = {"delta": 0.0, "gamma": 0.0, "theta": 0.0, "vega": 0.0, "delta_dollars": 0.0}
    per_position: list[dict] = []

    for pos in positions:
        ticker = pos.get("ticker", "UNKNOWN")
        opt_type = pos.get("option_type", "call")
        S = float(pos.get("S", 100.0))
        K = float(pos.get("K", 100.0))
        T_days = float(pos.get("T_days", 30.0))
        sigma = float(pos.get("sigma", 0.20))
        quantity = float(pos.get("quantity", 1.0))
        r = float(pos.get("r", 0.05))

        T_years = max(T_days / 365.0, 1e-6)
        greeks = black_scholes_greeks(S, K, T_years, r, sigma, opt_type)

        # Standard lot = 100 shares
        delta_dollars = greeks["delta"] * S * quantity * 100.0

        scaled = {
            "ticker": ticker,
            "option_type": opt_type,
            "quantity": quantity,
            "option_price": greeks["option_price"],
            "delta": round(greeks["delta"] * quantity, 6),
            "gamma": round(greeks["gamma"] * quantity, 6),
            "theta": round(greeks["theta"] * quantity, 6),
            "vega": round(greeks["vega"] * quantity, 6),
            "delta_dollars": round(delta_dollars, 2),
            "moneyness": greeks["moneyness"],
            "breakeven": greeks["breakeven"],
        }
        per_position.append(scaled)

        agg["delta"] += greeks["delta"] * quantity
        agg["gamma"] += greeks["gamma"] * quantity
        agg["theta"] += greeks["theta"] * quantity
        agg["vega"] += greeks["vega"] * quantity
        agg["delta_dollars"] += delta_dollars

    return {
        "aggregate": {
            "delta": round(agg["delta"], 6),
            "gamma": round(agg["gamma"], 6),
            "theta": round(agg["theta"], 6),
            "vega": round(agg["vega"], 6),
            "delta_dollars": round(agg["delta_dollars"], 2),
        },
        "positions": per_position,
        "n_positions": len(per_position),
    }
