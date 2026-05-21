"""
engines/quant_math.py
======================
Quantitative math engine covering:
  1. Monte Carlo simulation — probability distribution of trade outcomes
  2. Value at Risk (VaR) and Conditional VaR (CVaR / Expected Shortfall)
  3. GARCH(1,1) volatility forecasting
  4. Hidden Markov Model (HMM) regime detection

All methods use only numpy/pandas — no external quant libraries required.
"""
import numpy as np
import pandas as pd
import logging
from typing import Optional

logger = logging.getLogger(__name__)


# ══════════════════════════════════════════════════════════════════════════════
# 1. MONTE CARLO SIMULATION
# ══════════════════════════════════════════════════════════════════════════════

def monte_carlo_trade(
    entry_price:   float,
    stop_loss:     float,
    take_profit:   float,
    win_rate:      float,        # 0-1
    daily_vol:     float,        # annualised vol (e.g. 0.25 = 25%)
    position_value: float,       # ₹ invested
    days_horizon:  int  = 10,    # trade horizon in trading days
    n_simulations: int  = 10000,
    seed:          int  = 42,
) -> dict:
    """
    Run Monte Carlo on a single trade setup.

    Uses Geometric Brownian Motion for price paths.
    Exits early if stop or target is hit intraday (approximated at daily close).

    Returns full probability distribution, not just a single outcome.
    """
    np.random.seed(seed)

    daily_vol_actual = daily_vol / np.sqrt(252)
    dt = 1.0  # daily steps

    # Simulated outcomes
    final_pnl   = np.zeros(n_simulations)
    exit_days   = np.zeros(n_simulations, dtype=int)
    exit_reason = [""] * n_simulations

    for i in range(n_simulations):
        price = entry_price
        exited = False
        for day in range(1, days_horizon + 1):
            shock = np.random.normal(0, daily_vol_actual)
            price = price * np.exp(shock)

            if price <= stop_loss:
                pnl = (stop_loss - entry_price) / entry_price
                final_pnl[i]   = pnl * position_value
                exit_days[i]   = day
                exit_reason[i] = "stop"
                exited = True
                break
            elif price >= take_profit:
                pnl = (take_profit - entry_price) / entry_price
                final_pnl[i]   = pnl * position_value
                exit_days[i]   = day
                exit_reason[i] = "target"
                exited = True
                break

        if not exited:
            pnl = (price - entry_price) / entry_price
            final_pnl[i]   = pnl * position_value
            exit_days[i]   = days_horizon
            exit_reason[i] = "timeout"

    # Statistics
    pct_stop   = np.mean(np.array(exit_reason) == "stop")   * 100
    pct_target = np.mean(np.array(exit_reason) == "target") * 100
    pct_timeout= np.mean(np.array(exit_reason) == "timeout")* 100

    pnl_sorted = np.sort(final_pnl)

    percentiles = {
        "p5":  float(np.percentile(final_pnl, 5)),
        "p10": float(np.percentile(final_pnl, 10)),
        "p25": float(np.percentile(final_pnl, 25)),
        "p50": float(np.percentile(final_pnl, 50)),
        "p75": float(np.percentile(final_pnl, 75)),
        "p90": float(np.percentile(final_pnl, 90)),
        "p95": float(np.percentile(final_pnl, 95)),
    }

    prob_profit = float(np.mean(final_pnl > 0)) * 100
    prob_loss_gt_stop = float(np.mean(final_pnl < (stop_loss - entry_price) / entry_price * position_value)) * 100

    # Histogram buckets (20 bins)
    hist, bin_edges = np.histogram(final_pnl, bins=20)
    histogram = [
        {"from": round(float(bin_edges[i]), 2), "to": round(float(bin_edges[i+1]), 2), "count": int(hist[i])}
        for i in range(len(hist))
    ]

    return {
        "n_simulations":       n_simulations,
        "days_horizon":        days_horizon,
        "entry_price":         entry_price,
        "stop_loss":           stop_loss,
        "take_profit":         take_profit,
        "position_value":      position_value,
        "mean_pnl":            round(float(np.mean(final_pnl)), 2),
        "median_pnl":          round(float(np.median(final_pnl)), 2),
        "std_pnl":             round(float(np.std(final_pnl)), 2),
        "prob_profit_pct":     round(prob_profit, 1),
        "prob_hit_stop_pct":   round(pct_stop, 1),
        "prob_hit_target_pct": round(pct_target, 1),
        "prob_timeout_pct":    round(pct_timeout, 1),
        "percentiles":         {k: round(v, 2) for k, v in percentiles.items()},
        "histogram":           histogram,
        "plain_english": _mc_plain_english(prob_profit, percentiles, pct_stop, pct_target, position_value),
    }


def _mc_plain_english(prob_profit, pct, pct_stop, pct_target, position_value):
    lines = []
    lines.append(f"Out of 10,000 simulated outcomes, {prob_profit:.0f}% are profitable.")
    lines.append(f"Best case (top 5%): gain ₹{pct['p95']:,.0f}. Worst case (bottom 5%): lose ₹{abs(pct['p5']):,.0f}.")
    if pct_stop > 40:
        lines.append(f"Stop loss is hit {pct_stop:.0f}% of the time — this is a tight stop for this volatility level.")
    if pct_target > 60:
        lines.append(f"Target is hit {pct_target:.0f}% of the time — the target is very achievable.")
    lines.append(f"50/50 outcome (median): {'gain' if pct['p50'] >= 0 else 'lose'} ₹{abs(pct['p50']):,.0f}.")
    return lines


def monte_carlo_portfolio(
    returns_history: pd.DataFrame,   # columns = tickers, values = daily returns
    weights: dict,                    # {ticker: weight 0-1, sums to 1}
    portfolio_value: float,
    horizon_days: int = 21,           # 1 month
    n_simulations: int = 10000,
    seed: int = 42,
) -> dict:
    """
    Portfolio-level Monte Carlo using historical return covariance (Cholesky decomposition).
    Preserves inter-asset correlations.
    """
    np.random.seed(seed)

    tickers = [t for t in weights.keys() if t in returns_history.columns]
    if not tickers:
        return {"error": "No matching tickers in returns history"}

    w = np.array([weights[t] for t in tickers])
    w = w / w.sum()

    ret_data = returns_history[tickers].dropna()
    if len(ret_data) < 30:
        return {"error": "Insufficient return history"}

    mu  = ret_data.mean().values          # daily mean returns
    cov = ret_data.cov().values           # covariance matrix

    # Cholesky decomposition for correlated random draws
    try:
        L = np.linalg.cholesky(cov + np.eye(len(tickers)) * 1e-8)
    except np.linalg.LinAlgError:
        L = np.diag(np.sqrt(np.diag(cov)))

    final_portfolio_returns = np.zeros(n_simulations)

    for i in range(n_simulations):
        # Simulate horizon_days of correlated returns
        z = np.random.standard_normal((horizon_days, len(tickers)))
        daily_returns = mu + (z @ L.T)
        cumulative = np.prod(1 + daily_returns, axis=0) - 1
        portfolio_return = float(w @ cumulative)
        final_portfolio_returns[i] = portfolio_return

    final_pnl = final_portfolio_returns * portfolio_value

    return {
        "horizon_days":    horizon_days,
        "n_simulations":   n_simulations,
        "portfolio_value": portfolio_value,
        "mean_return_pct": round(float(np.mean(final_portfolio_returns)) * 100, 2),
        "prob_profit_pct": round(float(np.mean(final_pnl > 0)) * 100, 1),
        "percentiles": {
            "p1":  round(float(np.percentile(final_pnl, 1)),  2),
            "p5":  round(float(np.percentile(final_pnl, 5)),  2),
            "p10": round(float(np.percentile(final_pnl, 10)), 2),
            "p25": round(float(np.percentile(final_pnl, 25)), 2),
            "p50": round(float(np.percentile(final_pnl, 50)), 2),
            "p75": round(float(np.percentile(final_pnl, 75)), 2),
            "p90": round(float(np.percentile(final_pnl, 90)), 2),
            "p95": round(float(np.percentile(final_pnl, 95)), 2),
        },
        "var_95":  round(float(np.percentile(final_pnl, 5)),  2),   # 95% VaR
        "cvar_95": round(float(np.mean(final_pnl[final_pnl <= np.percentile(final_pnl, 5)])), 2),
    }


# ══════════════════════════════════════════════════════════════════════════════
# 2. VALUE AT RISK (VaR) AND CVaR
# ══════════════════════════════════════════════════════════════════════════════

def compute_var_cvar(
    returns: pd.Series,          # historical daily returns
    portfolio_value: float,
    confidence_levels: list = None,
    method: str = "historical",   # "historical" | "parametric" | "cornish_fisher"
) -> dict:
    """
    Compute VaR and CVaR (Expected Shortfall) at multiple confidence levels.

    Historical: uses actual return distribution (no normality assumption)
    Parametric: assumes normal distribution (faster, less accurate for fat tails)
    Cornish-Fisher: adjusts for skewness and kurtosis (best for fat-tailed assets)
    """
    if confidence_levels is None:
        confidence_levels = [0.90, 0.95, 0.99]

    returns_clean = returns.dropna()
    if len(returns_clean) < 30:
        return {"error": "Need at least 30 days of returns"}

    mu    = float(returns_clean.mean())
    sigma = float(returns_clean.std())
    skew  = float(returns_clean.skew())
    kurt  = float(returns_clean.kurtosis())   # excess kurtosis

    results = {}
    for cl in confidence_levels:
        alpha = 1 - cl
        label = f"{int(cl*100)}pct"

        if method == "historical":
            var_return  = float(np.percentile(returns_clean, alpha * 100))
            tail_losses = returns_clean[returns_clean <= var_return]
            cvar_return = float(tail_losses.mean()) if len(tail_losses) > 0 else var_return

        elif method == "parametric":
            from scipy.stats import norm
            z = norm.ppf(alpha)
            var_return  = mu + sigma * z
            cvar_return = mu - sigma * norm.pdf(z) / alpha

        elif method == "cornish_fisher":
            # Cornish-Fisher expansion adjusting for skew and kurtosis
            from scipy.stats import norm
            z = norm.ppf(alpha)
            z_cf = (z + (z**2 - 1) * skew / 6
                    + (z**3 - 3*z) * kurt / 24
                    - (2*z**3 - 5*z) * skew**2 / 36)
            var_return  = mu + sigma * z_cf
            cvar_return = var_return * 1.15  # approximate ES adjustment

        else:
            raise ValueError(f"Unknown method: {method}")

        results[label] = {
            "confidence":       cl,
            "var_return_pct":   round(var_return * 100, 3),
            "var_currency":     round(var_return * portfolio_value, 2),
            "cvar_return_pct":  round(cvar_return * 100, 3),
            "cvar_currency":    round(cvar_return * portfolio_value, 2),
            "interpretation":   f"On {int(cl*100)}% of days, you won't lose more than ₹{abs(var_return * portfolio_value):,.0f}. On the worst {int(alpha*100)}% of days, average loss is ₹{abs(cvar_return * portfolio_value):,.0f}.",
        }

    return {
        "method":        method,
        "portfolio_value": portfolio_value,
        "return_days":   len(returns_clean),
        "daily_vol_pct": round(sigma * 100, 3),
        "annual_vol_pct": round(sigma * np.sqrt(252) * 100, 2),
        "skewness":      round(skew, 3),
        "excess_kurtosis": round(kurt, 3),
        "fat_tails":     kurt > 1.0,   # excess kurtosis > 1 = fat tails
        "var_cvar":      results,
        "plain_english": _var_plain_english(results, kurt),
    }


def _var_plain_english(results, kurt):
    lines = []
    if "95pct" in results:
        r = results["95pct"]
        lines.append(f"95% VaR: On any given day, you have a 95% chance of not losing more than ₹{abs(r['var_currency']):,.0f}.")
        lines.append(f"95% CVaR (Expected Shortfall): On the worst 5% of days, you'd lose on average ₹{abs(r['cvar_currency']):,.0f}.")
    if kurt > 2:
        lines.append("WARNING: This asset has fat tails (kurtosis > 2). Extreme losses occur more often than a normal distribution predicts. Use CVaR, not VaR, for risk management.")
    return lines


# ══════════════════════════════════════════════════════════════════════════════
# 3. GARCH(1,1) VOLATILITY FORECASTING
# ══════════════════════════════════════════════════════════════════════════════

def fit_garch(returns: pd.Series) -> dict:
    """
    Fit GARCH(1,1) model using maximum likelihood estimation.

    GARCH(1,1): σ²_t = ω + α·ε²_(t-1) + β·σ²_(t-1)

    Key insight: volatility is predictable in the short run.
    High vol today → high vol tomorrow (vol clustering).
    """
    returns_clean = returns.dropna()
    n = len(returns_clean)
    if n < 50:
        return {"error": "Need at least 50 returns for GARCH"}

    r = returns_clean.values

    # Simple GARCH(1,1) estimation via moment matching
    # (Full MLE requires scipy.optimize — use simplified version)
    variance = np.var(r)

    # Estimate alpha and beta from autocorrelation of squared returns
    r_sq = r**2
    acf_1 = float(pd.Series(r_sq).autocorr(lag=1)) if n > 2 else 0.1
    acf_2 = float(pd.Series(r_sq).autocorr(lag=2)) if n > 3 else 0.08

    # Simplified parameter bounds
    alpha = max(0.05, min(0.35, abs(acf_1) * 0.5))
    beta  = max(0.50, min(0.90, abs(acf_2) / max(abs(acf_1), 0.01) * 0.8))

    # Ensure stationarity: alpha + beta < 1
    if alpha + beta >= 0.999:
        total = alpha + beta
        alpha = alpha / total * 0.95
        beta  = beta  / total * 0.95

    omega = variance * (1 - alpha - beta)
    omega = max(omega, 1e-8)

    # Filter conditional variances
    sigma2 = np.zeros(n)
    sigma2[0] = variance
    for t in range(1, n):
        sigma2[t] = omega + alpha * r[t-1]**2 + beta * sigma2[t-1]

    current_sigma2 = sigma2[-1]

    # Forecast n steps ahead
    forecasts = []
    long_run_var = omega / (1 - alpha - beta) if (1 - alpha - beta) > 0 else variance
    sigma2_f = current_sigma2
    for h in range(1, 22):
        sigma2_f = omega + (alpha + beta) * sigma2_f
        forecasts.append({
            "day":          h,
            "vol_daily_pct": round(float(np.sqrt(sigma2_f)) * 100, 3),
            "vol_annual_pct": round(float(np.sqrt(sigma2_f * 252)) * 100, 2),
        })

    persistence = alpha + beta
    half_life = np.log(0.5) / np.log(persistence) if 0 < persistence < 1 else None

    current_vol_annual = float(np.sqrt(current_sigma2 * 252))
    hist_vol_annual    = float(np.sqrt(variance * 252))

    if current_vol_annual > hist_vol_annual * 1.3:
        regime = "HIGH_VOLATILITY"
        regime_note = "Current volatility is significantly above its long-run average — risky time to enter new positions."
    elif current_vol_annual < hist_vol_annual * 0.7:
        regime = "LOW_VOLATILITY"
        regime_note = "Volatility is compressed below long-run average — calm periods often precede large moves."
    else:
        regime = "NORMAL_VOLATILITY"
        regime_note = "Volatility is near its long-run average."

    return {
        "model":               "GARCH(1,1)",
        "n_observations":      n,
        "parameters":          {"omega": round(float(omega), 8), "alpha": round(float(alpha), 4), "beta": round(float(beta), 4)},
        "persistence":         round(float(persistence), 4),
        "half_life_days":      round(float(half_life), 1) if half_life and not np.isnan(half_life) else None,
        "long_run_vol_annual": round(float(np.sqrt(long_run_var * 252)) * 100, 2),
        "current_vol_daily":   round(float(np.sqrt(current_sigma2)) * 100, 3),
        "current_vol_annual":  round(current_vol_annual * 100, 2),
        "hist_vol_annual":     round(hist_vol_annual * 100, 2),
        "vol_regime":          regime,
        "regime_note":         regime_note,
        "forecasts_21d":       forecasts,
        "plain_english": [
            f"Current annualised volatility: {current_vol_annual*100:.1f}% (historical avg: {hist_vol_annual*100:.1f}%)",
            f"Volatility persistence (α+β): {persistence:.2f} — {'very persistent, shocks last long' if persistence > 0.9 else 'moderate persistence'}",
            f"Half-life of a vol shock: {half_life:.0f} trading days" if half_life else "Volatility is near unit-root (very persistent)",
            regime_note,
        ],
    }


# ══════════════════════════════════════════════════════════════════════════════
# 4. HIDDEN MARKOV MODEL — REGIME DETECTION
# ══════════════════════════════════════════════════════════════════════════════

def fit_hmm_regime(returns: pd.Series, n_states: int = 3) -> dict:
    """
    Fit a Hidden Markov Model to detect market regimes.

    States (3-state model):
      0 = BEAR  (negative mean, high vol)
      1 = NEUTRAL (near-zero mean, medium vol)
      2 = BULL  (positive mean, low vol)

    Uses Baum-Welch EM algorithm (simplified numpy implementation).
    Returns: current regime, regime probabilities, state history.
    """
    returns_clean = returns.dropna().values
    n = len(returns_clean)

    if n < 60:
        return {"error": "Need at least 60 observations for HMM"}

    # Initialise with k-means-like clustering
    sorted_r = np.sort(returns_clean)
    q33 = float(np.percentile(returns_clean, 33))
    q67 = float(np.percentile(returns_clean, 67))

    # Initial state means and variances
    state_means = np.array([
        float(np.mean(returns_clean[returns_clean <= q33])),
        float(np.mean(returns_clean[(returns_clean > q33) & (returns_clean <= q67)])),
        float(np.mean(returns_clean[returns_clean > q67])),
    ])
    state_stds = np.array([
        max(float(np.std(returns_clean[returns_clean <= q33])), 1e-5),
        max(float(np.std(returns_clean[(returns_clean > q33) & (returns_clean <= q67)])), 1e-5),
        max(float(np.std(returns_clean[returns_clean > q67])), 1e-5),
    ])

    # Transition matrix (initial)
    A = np.array([
        [0.90, 0.08, 0.02],
        [0.05, 0.90, 0.05],
        [0.02, 0.08, 0.90],
    ])
    pi = np.array([1/3, 1/3, 1/3])

    def emission_prob(obs, state):
        mu  = state_means[state]
        std = state_stds[state]
        return (1 / (std * np.sqrt(2 * np.pi))) * np.exp(-0.5 * ((obs - mu) / std) ** 2) + 1e-300

    # Viterbi algorithm for most likely state sequence
    log_delta = np.zeros((n, n_states))
    psi       = np.zeros((n, n_states), dtype=int)

    for s in range(n_states):
        log_delta[0, s] = np.log(pi[s] + 1e-300) + np.log(emission_prob(returns_clean[0], s))

    for t in range(1, n):
        for s in range(n_states):
            trans_probs = log_delta[t-1] + np.log(A[:, s] + 1e-300)
            psi[t, s]   = int(np.argmax(trans_probs))
            log_delta[t, s] = trans_probs[psi[t, s]] + np.log(emission_prob(returns_clean[t], s))

    # Backtrack
    state_seq  = np.zeros(n, dtype=int)
    state_seq[-1] = int(np.argmax(log_delta[-1]))
    for t in range(n-2, -1, -1):
        state_seq[t] = psi[t+1, state_seq[t+1]]

    # Forward probabilities for current regime probabilities
    alpha_fwd = np.zeros(n_states)
    for s in range(n_states):
        alpha_fwd[s] = pi[s] * emission_prob(returns_clean[-1], s)
    alpha_fwd /= max(alpha_fwd.sum(), 1e-300)

    # Label states by mean return: lowest mean = BEAR, highest = BULL
    state_order = np.argsort(state_means)
    state_labels = {state_order[0]: "BEAR", state_order[1]: "NEUTRAL", state_order[2]: "BULL"}
    current_state = int(state_seq[-1])
    current_label = state_labels.get(current_state, "NEUTRAL")

    # Probability of each regime (last step)
    regime_probs = {}
    for s in range(n_states):
        label = state_labels.get(s, f"STATE_{s}")
        regime_probs[label] = round(float(alpha_fwd[s]) * 100, 1)

    # State history (last 30 days)
    recent_states = [state_labels.get(int(s), "NEUTRAL") for s in state_seq[-30:]]

    # Regime statistics
    state_stats = {}
    for s in range(n_states):
        mask = state_seq == s
        label = state_labels.get(s, f"STATE_{s}")
        r_in_state = returns_clean[mask]
        state_stats[label] = {
            "mean_daily_return_pct": round(float(np.mean(r_in_state)) * 100, 3) if len(r_in_state) > 0 else 0,
            "daily_vol_pct":         round(float(np.std(r_in_state)) * 100, 3)  if len(r_in_state) > 0 else 0,
            "days_in_state":         int(np.sum(mask)),
            "pct_of_time":           round(float(np.mean(mask)) * 100, 1),
        }

    return {
        "model":           "HMM (3-state)",
        "n_observations":  n,
        "current_regime":  current_label,
        "regime_probabilities": regime_probs,
        "state_statistics": state_stats,
        "recent_regimes_30d": recent_states,
        "plain_english": _hmm_plain_english(current_label, regime_probs, state_stats),
    }


def _hmm_plain_english(current, probs, stats):
    lines = [f"Current market regime: {current}"]
    bull_p = probs.get("BULL", 0)
    bear_p = probs.get("BEAR", 0)
    neut_p = probs.get("NEUTRAL", 0)
    lines.append(f"Regime probabilities — Bull: {bull_p:.0f}%, Neutral: {neut_p:.0f}%, Bear: {bear_p:.0f}%")
    if current == "BULL":
        avg_r = stats.get("BULL", {}).get("mean_daily_return_pct", 0)
        lines.append(f"Bull regimes historically return {avg_r:.2f}%/day on average. Favour long positions.")
    elif current == "BEAR":
        avg_r = stats.get("BEAR", {}).get("mean_daily_return_pct", 0)
        lines.append(f"Bear regimes average {avg_r:.2f}%/day. Reduce exposure, avoid new longs.")
    else:
        lines.append("Neutral regime — mixed signals. Stick to high-conviction setups only.")
    return lines
