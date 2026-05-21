"""
engines/portfolio_optimizer.py
================================
Portfolio optimization engine implementing:
  1. Mean-Variance Optimization (Markowitz 1952)
  2. Efficient Frontier computation
  3. Maximum Sharpe Ratio portfolio
  4. Minimum Variance portfolio
  5. Risk Parity (Equal Risk Contribution)
  6. Black-Litterman model (market equilibrium + investor views)

All methods use only numpy/scipy — no cvxpy or external optimizers needed
beyond scipy.optimize which is in the standard scientific stack.
"""
import numpy as np
import pandas as pd
import logging
from typing import Optional
from scipy.optimize import minimize

logger = logging.getLogger(__name__)

RISK_FREE_RATE = 0.065  # 6.5% India risk-free (10Y G-Sec proxy); override for US


# ══════════════════════════════════════════════════════════════════════════════
# HELPERS
# ══════════════════════════════════════════════════════════════════════════════

def _portfolio_stats(weights: np.ndarray, mu: np.ndarray, cov: np.ndarray, rf: float = RISK_FREE_RATE) -> tuple:
    """Return (annual_return, annual_vol, sharpe)."""
    ret = float(weights @ mu) * 252
    vol = float(np.sqrt(weights @ cov @ weights)) * np.sqrt(252)
    sharpe = (ret - rf) / vol if vol > 0 else 0.0
    return ret, vol, sharpe


def _weights_to_dict(weights: np.ndarray, tickers: list) -> dict:
    return {t: round(float(w), 4) for t, w in zip(tickers, weights)}


# ══════════════════════════════════════════════════════════════════════════════
# 1. MEAN-VARIANCE OPTIMIZATION
# ══════════════════════════════════════════════════════════════════════════════

def compute_efficient_frontier(
    returns: pd.DataFrame,       # columns = tickers, daily returns
    n_points: int = 30,
    rf: float = RISK_FREE_RATE,
    allow_short: bool = False,
) -> dict:
    """
    Compute the Markowitz efficient frontier.

    Returns:
      - frontier: list of (return, vol, sharpe, weights) points
      - max_sharpe: optimal portfolio weights
      - min_variance: minimum variance portfolio weights
      - equal_weight: naive 1/N portfolio for comparison
    """
    tickers = list(returns.columns)
    n = len(tickers)

    returns_clean = returns.dropna()
    if len(returns_clean) < 30 or n < 2:
        return {"error": "Need at least 2 assets and 30 days of returns"}

    mu  = returns_clean.mean().values       # daily mean returns
    cov = returns_clean.cov().values        # daily covariance matrix

    # Bounds: no short selling by default
    bounds = [(-1, 1) if allow_short else (0, 1)] * n
    constraints = [{"type": "eq", "fun": lambda w: np.sum(w) - 1}]
    w0 = np.ones(n) / n  # equal weight start

    # ── Max Sharpe ──────────────────────────────────────────────────────────
    def neg_sharpe(w):
        ret, vol, _ = _portfolio_stats(w, mu, cov, rf)
        return -ret / vol if vol > 0 else 0

    res_sharpe = minimize(neg_sharpe, w0, method="SLSQP", bounds=bounds, constraints=constraints,
                          options={"ftol": 1e-9, "maxiter": 1000})
    w_sharpe = np.clip(res_sharpe.x, 0, 1)
    w_sharpe /= w_sharpe.sum()

    # ── Min Variance ────────────────────────────────────────────────────────
    def portfolio_vol(w):
        return float(np.sqrt(w @ cov @ w)) * np.sqrt(252)

    res_minvar = minimize(portfolio_vol, w0, method="SLSQP", bounds=bounds, constraints=constraints,
                          options={"ftol": 1e-9, "maxiter": 1000})
    w_minvar = np.clip(res_minvar.x, 0, 1)
    w_minvar /= w_minvar.sum()

    # ── Efficient Frontier: sweep target returns ─────────────────────────────
    ret_max, vol_max, _ = _portfolio_stats(w_sharpe, mu, cov, rf)
    ret_min, vol_min, _ = _portfolio_stats(w_minvar, mu, cov, rf)

    target_returns = np.linspace(ret_min, ret_max * 1.05, n_points)
    frontier = []

    for target_ret in target_returns:
        constraints_ef = [
            {"type": "eq", "fun": lambda w: np.sum(w) - 1},
            {"type": "eq", "fun": lambda w, t=target_ret: _portfolio_stats(w, mu, cov, rf)[0] - t},
        ]
        res = minimize(portfolio_vol, w0, method="SLSQP", bounds=bounds, constraints=constraints_ef,
                       options={"ftol": 1e-8, "maxiter": 500})
        if res.success:
            w = np.clip(res.x, 0, 1)
            if w.sum() > 0:
                w /= w.sum()
            ret, vol, sharpe = _portfolio_stats(w, mu, cov, rf)
            frontier.append({
                "annual_return_pct": round(ret * 100, 2),
                "annual_vol_pct":    round(vol * 100, 2),
                "sharpe":            round(sharpe, 3),
                "weights":           _weights_to_dict(w, tickers),
            })

    # ── Equal weight benchmark ───────────────────────────────────────────────
    w_eq = np.ones(n) / n
    ret_eq, vol_eq, sr_eq = _portfolio_stats(w_eq, mu, cov, rf)

    # Stats for all portfolios
    ret_s, vol_s, sr_s = _portfolio_stats(w_sharpe, mu, cov, rf)
    ret_v, vol_v, sr_v = _portfolio_stats(w_minvar, mu, cov, rf)

    def _fmt_portfolio(weights, ret, vol, sr, label):
        return {
            "label":             label,
            "weights":           _weights_to_dict(weights, tickers),
            "annual_return_pct": round(ret * 100, 2),
            "annual_vol_pct":    round(vol * 100, 2),
            "sharpe_ratio":      round(sr, 3),
        }

    return {
        "tickers":       tickers,
        "n_assets":      n,
        "data_days":     len(returns_clean),
        "risk_free_rate": rf,
        "frontier":      frontier,
        "max_sharpe":    _fmt_portfolio(w_sharpe, ret_s, vol_s, sr_s, "Maximum Sharpe Ratio"),
        "min_variance":  _fmt_portfolio(w_minvar, ret_v, vol_v, sr_v, "Minimum Variance"),
        "equal_weight":  _fmt_portfolio(w_eq,     ret_eq, vol_eq, sr_eq, "Equal Weight (1/N)"),
        "correlation_matrix": {
            t1: {t2: round(float(returns_clean[t1].corr(returns_clean[t2])), 3) for t2 in tickers}
            for t1 in tickers
        },
        "plain_english": _ef_plain_english(w_sharpe, tickers, ret_s, vol_s, sr_s, ret_eq, sr_eq),
    }


def _ef_plain_english(w, tickers, ret, vol, sr, ret_eq, sr_eq):
    top = sorted(zip(tickers, w), key=lambda x: -x[1])[:3]
    top_str = ", ".join(f"{t} ({w*100:.0f}%)" for t, w in top)
    lines = [
        f"Optimal portfolio (max Sharpe): {top_str}",
        f"Expected annual return: {ret*100:.1f}% | Volatility: {vol*100:.1f}% | Sharpe: {sr:.2f}",
        f"vs Equal Weight: return {ret_eq*100:.1f}%, Sharpe {sr_eq:.2f}",
    ]
    if sr > sr_eq * 1.2:
        lines.append(f"Optimization improves Sharpe by {((sr/sr_eq)-1)*100:.0f}% vs equal weighting.")
    return lines


# ══════════════════════════════════════════════════════════════════════════════
# 2. RISK PARITY
# ══════════════════════════════════════════════════════════════════════════════

def compute_risk_parity(returns: pd.DataFrame, rf: float = RISK_FREE_RATE) -> dict:
    """
    Risk Parity: each asset contributes equally to total portfolio risk.

    Unlike Markowitz (capital-weighted), Risk Parity allocates by risk —
    low-volatility assets get MORE capital so their risk contribution equals
    high-volatility assets.
    """
    tickers = list(returns.columns)
    n = len(tickers)
    returns_clean = returns.dropna()

    if len(returns_clean) < 30:
        return {"error": "Insufficient data"}

    cov = returns_clean.cov().values
    mu  = returns_clean.mean().values

    def risk_contribution(w):
        port_var = w @ cov @ w
        marginal = cov @ w
        rc = w * marginal / port_var if port_var > 0 else w
        return rc

    def risk_parity_objective(w):
        rc = risk_contribution(w)
        target_rc = np.ones(n) / n
        return float(np.sum((rc - target_rc) ** 2))

    bounds = [(0.01, 1)] * n
    constraints = [{"type": "eq", "fun": lambda w: np.sum(w) - 1}]
    w0 = np.ones(n) / n

    res = minimize(risk_parity_objective, w0, method="SLSQP", bounds=bounds, constraints=constraints,
                   options={"ftol": 1e-10, "maxiter": 1000})

    w_rp = np.clip(res.x, 0, 1)
    w_rp /= w_rp.sum()

    # Risk contributions
    rc = risk_contribution(w_rp)
    port_vol = float(np.sqrt(w_rp @ cov @ w_rp)) * np.sqrt(252)
    ret, vol, sr = _portfolio_stats(w_rp, mu, cov, rf)

    holdings = []
    for i, t in enumerate(tickers):
        holdings.append({
            "ticker":             t,
            "weight_pct":         round(float(w_rp[i]) * 100, 2),
            "risk_contribution_pct": round(float(rc[i]) * 100, 2),
            "daily_vol_pct":      round(float(np.sqrt(cov[i, i])) * 100, 3),
        })

    holdings.sort(key=lambda x: -x["weight_pct"])

    return {
        "label":             "Risk Parity",
        "weights":           _weights_to_dict(w_rp, tickers),
        "annual_return_pct": round(ret * 100, 2),
        "annual_vol_pct":    round(vol * 100, 2),
        "sharpe_ratio":      round(sr, 3),
        "holdings":          holdings,
        "plain_english": [
            "Risk Parity allocates capital so each stock contributes equally to portfolio risk.",
            "Low-volatility stocks get more capital; high-volatility stocks get less.",
            "Result: " + ", ".join(f"{h['ticker']} {h['weight_pct']:.0f}%" for h in holdings[:4]),
        ],
    }


# ══════════════════════════════════════════════════════════════════════════════
# 3. BLACK-LITTERMAN
# ══════════════════════════════════════════════════════════════════════════════

def compute_black_litterman(
    returns: pd.DataFrame,
    market_caps: dict,           # {ticker: market_cap} for equilibrium weights
    views: list,                 # [{"assets": ["AAPL"], "expected_return": 0.15, "confidence": 0.6}]
    rf: float = RISK_FREE_RATE,
    risk_aversion: float = 2.5,
    tau: float = 0.05,
) -> dict:
    """
    Black-Litterman model.

    Combines:
      - Market equilibrium (CAPM implied returns from market cap weights)
      - Investor views (from AI signals / analyst forecasts)

    views format: [{"assets": ["RELIANCE.NS"], "expected_return": 0.18, "confidence": 0.7}]
    confidence: 0-1 (1 = very certain, 0.3 = uncertain view)
    """
    tickers = list(returns.columns)
    n = len(tickers)
    returns_clean = returns.dropna()

    if len(returns_clean) < 30:
        return {"error": "Insufficient data"}

    cov = returns_clean.cov().values * 252  # annualised

    # Market cap weights (equilibrium)
    total_mc = sum(market_caps.get(t, 1e9) for t in tickers)
    w_mkt = np.array([market_caps.get(t, 1e9) / total_mc for t in tickers])
    w_mkt /= w_mkt.sum()

    # Implied equilibrium returns: π = λ·Σ·w_mkt
    pi = risk_aversion * cov @ w_mkt  # annualised

    if not views:
        # No views — return market equilibrium
        mu_bl = pi
        w_bl = w_mkt.copy()
    else:
        # Build pick matrix P and view vector q
        n_views = len(views)
        P = np.zeros((n_views, n))
        q = np.zeros(n_views)
        omega_diag = np.zeros(n_views)

        for k, view in enumerate(views):
            assets = view.get("assets", [])
            exp_ret = view.get("expected_return", 0.10)
            conf = max(0.01, min(0.99, view.get("confidence", 0.5)))

            for asset in assets:
                if asset in tickers:
                    idx = tickers.index(asset)
                    P[k, idx] = 1.0 / len(assets)

            q[k] = exp_ret
            omega_diag[k] = tau * (1 - conf) / conf * float(P[k] @ cov @ P[k])

        Omega = np.diag(omega_diag)
        tau_cov = tau * cov

        # BL combined return: μ_BL = [(τΣ)^-1 + P'Ω^-1P]^-1 [(τΣ)^-1 π + P'Ω^-1 q]
        try:
            A = np.linalg.inv(tau_cov) + P.T @ np.linalg.inv(Omega) @ P
            b = np.linalg.inv(tau_cov) @ pi + P.T @ np.linalg.inv(Omega) @ q
            mu_bl = np.linalg.solve(A, b)
        except np.linalg.LinAlgError:
            mu_bl = pi  # fallback to equilibrium

        # Optimal weights given BL returns
        try:
            w_bl = np.linalg.solve(risk_aversion * cov, mu_bl)
            w_bl = np.clip(w_bl, 0, 1)
            if w_bl.sum() > 0:
                w_bl /= w_bl.sum()
            else:
                w_bl = w_mkt.copy()
        except Exception:
            w_bl = w_mkt.copy()

    mu_daily = mu_bl / 252
    ret, vol, sr = _portfolio_stats(w_bl, mu_daily, cov / 252, rf)

    holdings = []
    for i, t in enumerate(tickers):
        holdings.append({
            "ticker":                  t,
            "bl_weight_pct":           round(float(w_bl[i]) * 100, 2),
            "market_weight_pct":       round(float(w_mkt[i]) * 100, 2),
            "implied_return_pct":      round(float(pi[i]) * 100, 2),
            "bl_expected_return_pct":  round(float(mu_bl[i]) * 100, 2),
            "tilt_pct":                round(float(w_bl[i] - w_mkt[i]) * 100, 2),
        })

    holdings.sort(key=lambda x: -x["bl_weight_pct"])

    return {
        "label":             "Black-Litterman",
        "n_views":           len(views),
        "weights":           _weights_to_dict(w_bl, tickers),
        "annual_return_pct": round(ret * 100, 2),
        "annual_vol_pct":    round(vol * 100, 2),
        "sharpe_ratio":      round(sr, 3),
        "holdings":          holdings,
        "plain_english": [
            "Black-Litterman starts with what the market already prices in, then tilts toward your AI-driven views.",
            f"Applied {len(views)} view(s) to tilt from market-cap weights.",
            "Tilted holdings: " + ", ".join(
                f"{h['ticker']} {h['tilt_pct']:+.0f}%" for h in sorted(holdings, key=lambda x: -abs(x['tilt_pct']))[:3]
            ),
        ],
    }
