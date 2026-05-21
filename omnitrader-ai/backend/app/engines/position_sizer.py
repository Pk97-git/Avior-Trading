"""
engines/position_sizer.py
==========================
Kelly Criterion + Fixed Fractional position sizing.

Given a trade setup (entry, stop, target, win_rate, portfolio_value),
returns the optimal position size in shares/units AND in currency.

Also computes:
  - Full Kelly (theoretically optimal but volatile — never use raw)
  - Half Kelly (safer, used by most professionals)
  - Fixed 1% risk (conservative: never risk more than 1% of portfolio)
  - Fixed 2% risk (standard professional risk per trade)
  - Recommended: min(Half Kelly, 2% risk rule)
"""
import math
from dataclasses import dataclass
from typing import Optional


@dataclass
class SizingResult:
    recommended_shares: int
    recommended_capital: float          # in currency
    recommended_pct_portfolio: float    # 0-100

    full_kelly_shares: int
    full_kelly_capital: float
    full_kelly_pct: float

    half_kelly_shares: int
    half_kelly_capital: float
    half_kelly_pct: float

    fixed_1pct_shares: int
    fixed_1pct_capital: float

    fixed_2pct_shares: int
    fixed_2pct_capital: float

    risk_per_share: float               # entry - stop (the $ risk per share)
    reward_per_share: float             # target - entry
    risk_reward_ratio: float
    expected_value: float               # EV per ₹1 risked
    max_loss_if_stopped: float          # recommended_shares * risk_per_share
    max_gain_if_target: float           # recommended_shares * reward_per_share
    method_used: str
    notes: list


def compute_position_size(
    portfolio_value: float,     # total capital in ₹ or $
    entry_price: float,
    stop_loss: float,
    take_profit: float,
    win_rate: float,            # 0.0 to 1.0 (e.g. 0.55 for 55%)
    max_risk_pct: float = 2.0,  # max % of portfolio to risk per trade
    country: str = "IN",
) -> SizingResult:
    """
    Compute optimal position size using Kelly Criterion + fixed risk rules.

    Returns recommended position as the MINIMUM of half_kelly and 2% risk,
    which is the institutional standard (never over-bet, protect capital).
    """
    notes = []

    # Basic validation
    if entry_price <= 0 or stop_loss <= 0 or take_profit <= 0:
        raise ValueError("Prices must be positive")
    if stop_loss >= entry_price:
        raise ValueError("Stop loss must be below entry price for long trades")
    if take_profit <= entry_price:
        raise ValueError("Take profit must be above entry price for long trades")
    if not 0 < win_rate < 1:
        raise ValueError("Win rate must be between 0 and 1")

    # Risk/reward per share
    risk_per_share   = entry_price - stop_loss
    reward_per_share = take_profit - entry_price
    rr_ratio         = reward_per_share / risk_per_share

    # Kelly formula: f* = W - (1-W)/R  where W=win_rate, R=reward/risk
    b = rr_ratio          # odds of winning relative to losing
    p = win_rate
    q = 1 - win_rate
    kelly_fraction = (p * b - q) / b   # = p - q/b

    if kelly_fraction <= 0:
        notes.append("Negative Kelly — this trade has negative expected value. Do not trade.")
        kelly_fraction = 0.0

    # Expected value per ₹1 risked
    ev = p * rr_ratio - q

    # Full Kelly: % of portfolio to put IN (not to risk — convert)
    # Kelly tells us fraction of portfolio to BET, but in stock trading
    # we translate it as: capital_at_risk = kelly_fraction * portfolio
    # shares = capital_at_risk / risk_per_share

    full_kelly_risk_capital  = kelly_fraction * portfolio_value
    full_kelly_shares        = max(0, int(full_kelly_risk_capital / risk_per_share))
    full_kelly_capital       = full_kelly_shares * entry_price
    full_kelly_pct           = (full_kelly_capital / portfolio_value) * 100 if portfolio_value > 0 else 0

    half_kelly_risk_capital  = (kelly_fraction / 2) * portfolio_value
    half_kelly_shares        = max(0, int(half_kelly_risk_capital / risk_per_share))
    half_kelly_capital       = half_kelly_shares * entry_price
    half_kelly_pct           = (half_kelly_capital / portfolio_value) * 100 if portfolio_value > 0 else 0

    # Fixed % risk rules
    fixed_1pct_risk_capital  = portfolio_value * 0.01
    fixed_1pct_shares        = max(0, int(fixed_1pct_risk_capital / risk_per_share))
    fixed_1pct_capital       = fixed_1pct_shares * entry_price

    fixed_2pct_risk_capital  = portfolio_value * (max_risk_pct / 100)
    fixed_2pct_shares        = max(0, int(fixed_2pct_risk_capital / risk_per_share))
    fixed_2pct_capital       = fixed_2pct_shares * entry_price

    # Recommended = min(half_kelly, 2% fixed risk)
    # This is the professional approach: Kelly for upside, fixed risk for downside protection
    rec_shares  = min(half_kelly_shares, fixed_2pct_shares)
    rec_capital = rec_shares * entry_price
    rec_pct     = (rec_capital / portfolio_value) * 100 if portfolio_value > 0 else 0

    # Determine which rule was binding
    if half_kelly_shares <= fixed_2pct_shares:
        method_used = "Half Kelly (Kelly was the binding constraint)"
        notes.append(f"Kelly fraction: {kelly_fraction:.1%} → Half Kelly: {kelly_fraction/2:.1%} of capital at risk")
    else:
        method_used = f"Fixed {max_risk_pct}% risk rule (Kelly was more aggressive but capped)"
        notes.append(f"Kelly suggested more but was capped at {max_risk_pct}% portfolio risk per trade")

    if ev < 0.2:
        notes.append(f"Low expected value ({ev:.2f}x per ₹1 risked). Consider skipping or reducing size.")
    elif ev >= 0.5:
        notes.append(f"Strong expected value ({ev:.2f}x per ₹1 risked). Setup has good mathematical edge.")

    if rr_ratio < 1.5:
        notes.append("R/R ratio below 1.5:1 — professionals typically require minimum 2:1.")

    max_loss = rec_shares * risk_per_share
    max_gain = rec_shares * reward_per_share

    return SizingResult(
        recommended_shares=rec_shares,
        recommended_capital=round(rec_capital, 2),
        recommended_pct_portfolio=round(rec_pct, 2),
        full_kelly_shares=full_kelly_shares,
        full_kelly_capital=round(full_kelly_capital, 2),
        full_kelly_pct=round(full_kelly_pct, 2),
        half_kelly_shares=half_kelly_shares,
        half_kelly_capital=round(half_kelly_capital, 2),
        half_kelly_pct=round(half_kelly_pct, 2),
        fixed_1pct_shares=fixed_1pct_shares,
        fixed_1pct_capital=round(fixed_1pct_capital, 2),
        fixed_2pct_shares=fixed_2pct_shares,
        fixed_2pct_capital=round(fixed_2pct_capital, 2),
        risk_per_share=round(risk_per_share, 4),
        reward_per_share=round(reward_per_share, 4),
        risk_reward_ratio=round(rr_ratio, 3),
        expected_value=round(ev, 4),
        max_loss_if_stopped=round(max_loss, 2),
        max_gain_if_target=round(max_gain, 2),
        method_used=method_used,
        notes=notes,
    )
