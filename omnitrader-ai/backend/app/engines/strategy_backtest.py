"""
engines/strategy_backtest.py
============================
StrategyBacktestEngine — simulates built-in trading strategies against
historical price data with realistic transaction costs, slippage, and
benchmark comparison.

Built-in strategies
-------------------
RSI_MEAN_REVERSION   — buy oversold (RSI<30), sell overbought (RSI>70)
MACD_CROSSOVER       — buy bullish MACD cross, sell bearish cross
MA_CROSSOVER         — 50/200-day SMA golden/death cross
MOMENTUM             — buy top 20% 3-month performers, rebalance monthly
BOLLINGER_REVERSION  — buy at lower band, sell at upper band
BUY_AND_HOLD         — always long from day 1 (use as baseline)

Transaction costs
-----------------
India (country="IN"):
  Brokerage      : 0.03% per leg (≤ ₹20 per order)
  STT            : 0.10% on buy-side only (delivery)
  Exchange (NSE) : 0.00345% per leg
  GST            : 18% on brokerage amount
  Stamp duty     : 0.015% on buy-side
  SEBI charge    : 0.0001% per leg
  Total roundtrip ≈ 0.15–0.20%

US (country="US"):
  Brokerage      : $0.00 (Alpaca/Robinhood model)
  SEC fee        : 0.00278% on sells only
  Total roundtrip ≈ 0.003%

Slippage model
--------------
  impact_pct = BASE_SLIP + (order_value / avg_daily_volume_value) * IMPACT_FACTOR
  BASE_SLIP  = 0.05%  (bid-ask half-spread for large-cap liquid stocks)
  IMPACT_FACTOR = 0.50  (1% ADV → +0.5% slippage)
  Capped at 1.5% per trade
  Buy: execution_price = price * (1 + impact/100)
  Sell: execution_price = price * (1 - impact/100)

Benchmark
---------
  India: ^NSEI (Nifty 50 index)
  US:    ^GSPC (S&P 500 index)
  Benchmark is always simulated as Buy-and-Hold with no costs.
"""
from __future__ import annotations

import asyncio
import json
import logging
import math
from collections import defaultdict
from datetime import date, datetime, timedelta
from typing import Optional

import pandas as pd
import yfinance as yf
from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger(__name__)

# ── Transaction cost constants ─────────────────────────────────────────────────

INDIA_BROKERAGE_PCT    = 0.0003      # 0.03% per leg
INDIA_BROKERAGE_CAP    = 20.0        # ₹20 cap per order
INDIA_STT_PCT          = 0.001       # 0.10% buy-side only (delivery)
INDIA_EXCHANGE_PCT     = 0.0000345   # NSE transaction charge per leg
INDIA_GST_ON_BROKERAGE = 0.18        # 18% GST on brokerage
INDIA_STAMP_DUTY_PCT   = 0.00015     # 0.015% buy-side
INDIA_SEBI_PCT         = 0.000001    # SEBI charge per leg

US_SEC_FEE_PCT         = 0.0000278   # on sells only
US_BROKERAGE           = 0.0         # free (Alpaca/Robinhood)

# ── Slippage constants ─────────────────────────────────────────────────────────

BASE_SLIP_PCT    = 0.05    # base half-spread % (large-cap liquid)
IMPACT_FACTOR    = 0.50    # per 100% ADV: +0.50% slippage
MAX_SLIP_PCT     = 1.50    # cap

# ── Strategy names ─────────────────────────────────────────────────────────────

STRATEGY_RSI          = "RSI_MEAN_REVERSION"
STRATEGY_MACD         = "MACD_CROSSOVER"
STRATEGY_MA           = "MA_CROSSOVER"
STRATEGY_MOMENTUM     = "MOMENTUM"
STRATEGY_BOLLINGER    = "BOLLINGER_REVERSION"
STRATEGY_BUY_AND_HOLD = "BUY_AND_HOLD"

ALL_STRATEGIES = [
    STRATEGY_RSI, STRATEGY_MACD, STRATEGY_MA,
    STRATEGY_MOMENTUM, STRATEGY_BOLLINGER, STRATEGY_BUY_AND_HOLD,
]

STRATEGY_DESCRIPTIONS = {
    STRATEGY_RSI: {
        "name": "RSI Mean Reversion",
        "description": "Buy when RSI drops below 30 (oversold), sell when RSI rises above 70 (overbought). Works best on range-bound stocks.",
        "best_for": "Sideways/ranging markets",
        "typical_hold": "5–20 days",
        "parameters": {"rsi_period": 14, "oversold": 30, "overbought": 70},
    },
    STRATEGY_MACD: {
        "name": "MACD Crossover",
        "description": "Buy on bullish MACD cross (MACD line crosses above signal line), sell on bearish cross. Classic momentum/trend strategy.",
        "best_for": "Trending markets",
        "typical_hold": "15–45 days",
        "parameters": {"fast": 12, "slow": 26, "signal": 9},
    },
    STRATEGY_MA: {
        "name": "MA Crossover (Golden/Death Cross)",
        "description": "Buy when 50-day SMA crosses above 200-day SMA (golden cross). Sell when 50-day crosses below 200-day (death cross).",
        "best_for": "Long-term trend following",
        "typical_hold": "2–12 months",
        "parameters": {"fast_ma": 50, "slow_ma": 200},
    },
    STRATEGY_MOMENTUM: {
        "name": "Momentum (Monthly Rebalance)",
        "description": "Every month, rank all tickers by 3-month return. Go long the top performers, exit the bottom performers.",
        "best_for": "Diversified portfolios in bull markets",
        "typical_hold": "1 month (rebalanced)",
        "parameters": {"lookback_days": 63, "rebalance_freq": "monthly", "top_pct": 0.3},
    },
    STRATEGY_BOLLINGER: {
        "name": "Bollinger Band Reversion",
        "description": "Buy when price closes below lower Bollinger Band (2σ). Sell when price closes above upper Bollinger Band.",
        "best_for": "Mean-reverting stocks with predictable ranges",
        "typical_hold": "5–15 days",
        "parameters": {"period": 20, "std": 2.0},
    },
    STRATEGY_BUY_AND_HOLD: {
        "name": "Buy and Hold",
        "description": "Buy on day 1, hold until end date. Simple baseline to beat. Equal-weight across all tickers.",
        "best_for": "Benchmark / comparison baseline",
        "typical_hold": "Full period",
        "parameters": {},
    },
}

# ── Technical indicator helpers ────────────────────────────────────────────────


def _compute_rsi(series: pd.Series, period: int = 14) -> pd.Series:
    delta = series.diff()
    gain = delta.clip(lower=0).rolling(period).mean()
    loss = (-delta.clip(upper=0)).rolling(period).mean()
    rs = gain / loss.replace(0, 1e-9)
    return 100 - (100 / (1 + rs))


def _compute_macd(series: pd.Series) -> tuple[pd.Series, pd.Series]:
    ema12 = series.ewm(span=12, adjust=False).mean()
    ema26 = series.ewm(span=26, adjust=False).mean()
    macd = ema12 - ema26
    signal = macd.ewm(span=9, adjust=False).mean()
    return macd, signal


def _compute_bollinger(
    series: pd.Series, period: int = 20, std: float = 2.0
) -> tuple[pd.Series, pd.Series, pd.Series]:
    mid = series.rolling(period).mean()
    s = series.rolling(period).std()
    return mid + std * s, mid, mid - std * s


# ── Cost / slippage helpers ────────────────────────────────────────────────────


def _compute_trade_cost(value: float, side: str, country: str) -> float:
    """
    Return total transaction cost in currency units for a trade.
    value = trade_value (price × shares)
    side  = "BUY" or "SELL"
    """
    if country == "IN":
        brokerage = min(value * INDIA_BROKERAGE_PCT, INDIA_BROKERAGE_CAP)
        gst = brokerage * INDIA_GST_ON_BROKERAGE
        exchange = value * INDIA_EXCHANGE_PCT
        sebi = value * INDIA_SEBI_PCT
        stt = value * INDIA_STT_PCT if side == "BUY" else 0.0
        stamp = value * INDIA_STAMP_DUTY_PCT if side == "BUY" else 0.0
        return brokerage + gst + exchange + sebi + stt + stamp
    else:  # US
        sec_fee = value * US_SEC_FEE_PCT if side == "SELL" else 0.0
        return US_BROKERAGE + sec_fee


def _apply_slippage(
    price: float,
    side: str,
    order_value: float,
    avg_daily_volume_value: float,
) -> float:
    """
    Return slippage-adjusted execution price.
    order_value and avg_daily_volume_value must be in same currency.
    """
    if avg_daily_volume_value <= 0:
        avg_daily_volume_value = order_value * 100  # assume tiny fraction of volume
    volume_ratio = order_value / avg_daily_volume_value
    impact_pct = BASE_SLIP_PCT + volume_ratio * IMPACT_FACTOR * 100
    impact_pct = min(impact_pct, MAX_SLIP_PCT)
    if side == "BUY":
        return price * (1 + impact_pct / 100)
    else:
        return price * (1 - impact_pct / 100)


# ── Statistics helpers ─────────────────────────────────────────────────────────


def _cagr(total_return: float, days: int) -> float:
    if days <= 0:
        return 0.0
    years = days / 365.25
    try:
        return (1.0 + total_return) ** (1.0 / years) - 1.0
    except (ValueError, OverflowError):
        return 0.0


def _sharpe(daily_returns: list[float]) -> float:
    if len(daily_returns) < 10:
        return 0.0
    n = len(daily_returns)
    mean = sum(daily_returns) / n
    var = sum((r - mean) ** 2 for r in daily_returns) / max(n - 1, 1)
    std = math.sqrt(var)
    return (mean / std) * math.sqrt(252) if std > 0 else 0.0


def _sortino(daily_returns: list[float]) -> float:
    if len(daily_returns) < 10:
        return 0.0
    n = len(daily_returns)
    mean = sum(daily_returns) / n
    downside_sq = [min(r, 0.0) ** 2 for r in daily_returns]
    downside_var = sum(downside_sq) / max(len([x for x in downside_sq if x > 0]), 1)
    downside_std = math.sqrt(downside_var)
    return (mean / downside_std) * math.sqrt(252) if downside_std > 0 else 0.0


def _max_drawdown(equity: list[float]) -> float:
    """Return max drawdown as a negative percentage (e.g. -20.5 means 20.5% drawdown)."""
    if len(equity) < 2:
        return 0.0
    peak = equity[0]
    max_dd = 0.0
    for v in equity:
        if v > peak:
            peak = v
        dd = (v - peak) / peak if peak > 0 else 0.0
        if dd < max_dd:
            max_dd = dd
    return max_dd * 100.0  # negative percentage


def _calmar(cagr_pct: float, max_dd_pct: float) -> float:
    """Calmar ratio = CAGR / |Max Drawdown|"""
    dd = abs(max_dd_pct)
    return cagr_pct / dd if dd > 0 else 0.0


def _beta_alpha(
    strategy_returns: list[float], benchmark_returns: list[float]
) -> tuple[float, float]:
    """Compute beta and annualised alpha of strategy vs benchmark."""
    if len(strategy_returns) < 10 or len(benchmark_returns) < 10:
        return 1.0, 0.0
    n = min(len(strategy_returns), len(benchmark_returns))
    sr = strategy_returns[:n]
    br = benchmark_returns[:n]
    mean_sr = sum(sr) / n
    mean_br = sum(br) / n
    cov = sum((sr[i] - mean_sr) * (br[i] - mean_br) for i in range(n)) / max(n - 1, 1)
    var_br = sum((r - mean_br) ** 2 for r in br) / max(n - 1, 1)
    beta = cov / var_br if var_br > 0 else 1.0
    alpha_daily = mean_sr - beta * mean_br
    alpha_ann = alpha_daily * 252 * 100  # annualised %
    return round(beta, 4), round(alpha_ann, 4)


# ── Signal generation functions ────────────────────────────────────────────────


def _signals_rsi(
    df: pd.DataFrame, oversold: int = 30, overbought: int = 70
) -> pd.Series:
    """Returns a Series of 'BUY'/'SELL'/'HOLD' indexed by date."""
    close = df["Close"]
    rsi = _compute_rsi(close, 14)
    signals = pd.Series("HOLD", index=df.index)
    signals[rsi < oversold] = "BUY"
    signals[rsi > overbought] = "SELL"
    return signals


def _signals_macd(df: pd.DataFrame) -> pd.Series:
    close = df["Close"]
    macd, sig = _compute_macd(close)
    signals = pd.Series("HOLD", index=df.index)
    # Bullish cross: MACD crosses above signal
    bull_cross = (macd > sig) & (macd.shift(1) <= sig.shift(1))
    # Bearish cross: MACD crosses below signal
    bear_cross = (macd < sig) & (macd.shift(1) >= sig.shift(1))
    signals[bull_cross] = "BUY"
    signals[bear_cross] = "SELL"
    return signals


def _signals_ma_crossover(df: pd.DataFrame, fast: int = 50, slow: int = 200) -> pd.Series:
    close = df["Close"]
    sma_fast = close.rolling(fast).mean()
    sma_slow = close.rolling(slow).mean()
    signals = pd.Series("HOLD", index=df.index)
    # Golden cross: fast crosses above slow
    golden = (sma_fast > sma_slow) & (sma_fast.shift(1) <= sma_slow.shift(1))
    # Death cross: fast crosses below slow
    death = (sma_fast < sma_slow) & (sma_fast.shift(1) >= sma_slow.shift(1))
    signals[golden] = "BUY"
    signals[death] = "SELL"
    return signals


def _signals_bollinger(df: pd.DataFrame) -> pd.Series:
    close = df["Close"]
    bb_up, bb_mid, bb_lo = _compute_bollinger(close, 20, 2.0)
    signals = pd.Series("HOLD", index=df.index)
    signals[close < bb_lo] = "BUY"
    signals[close > bb_up] = "SELL"
    return signals


def _signals_buy_and_hold(df: pd.DataFrame) -> pd.Series:
    signals = pd.Series("HOLD", index=df.index)
    if len(signals) > 0:
        signals.iloc[0] = "BUY"  # buy on day 1
    return signals


# ── Main Engine ────────────────────────────────────────────────────────────────


class StrategyBacktestEngine:
    """
    Simulate a named trading strategy over historical price data.

    Parameters
    ----------
    strategy_name    : one of ALL_STRATEGIES
    tickers          : list of ticker symbols to trade
    start_date       : backtest start
    end_date         : backtest end
    initial_capital  : starting cash
    country          : "IN" or "US" (affects costs + benchmark)
    max_positions    : max concurrent positions
    stop_loss_pct    : fixed stop-loss as % below entry (0 = no stop)
    take_profit_pct  : fixed take-profit as % above entry (0 = no target)
    apply_slippage   : whether to apply slippage model
    apply_costs      : whether to apply transaction costs
    """

    def __init__(
        self,
        strategy_name: str,
        tickers: list[str],
        start_date: date,
        end_date: date,
        initial_capital: float = 100_000.0,
        country: str = "IN",
        max_positions: int = 10,
        stop_loss_pct: float = 5.0,
        take_profit_pct: float = 15.0,
        apply_slippage: bool = True,
        apply_costs: bool = True,
    ):
        if strategy_name not in ALL_STRATEGIES:
            raise ValueError(
                f"Unknown strategy: {strategy_name}. Valid: {ALL_STRATEGIES}"
            )
        self.strategy_name = strategy_name
        self.tickers = tickers
        self.start_date = start_date
        self.end_date = end_date
        self.initial_capital = initial_capital
        self.country = country.upper()
        self.max_positions = max_positions
        self.stop_loss_pct = stop_loss_pct / 100.0
        self.take_profit_pct = take_profit_pct / 100.0
        self.apply_slippage = apply_slippage
        self.apply_costs = apply_costs

    # ── Private helpers ────────────────────────────────────────────────────────

    def _get_price_row(
        self, df: pd.DataFrame, current_date: date
    ) -> Optional[pd.Series]:
        """Safely get a row for the given date from a yfinance DataFrame."""
        ts = pd.Timestamp(current_date)
        try:
            if ts in df.index:
                return df.loc[ts]
        except Exception:
            pass
        return None

    def _get_avg_vol_value(
        self, df: pd.DataFrame, current_date: date, price: float
    ) -> float:
        """Return approximate 20-day average daily volume value in currency units."""
        ts = pd.Timestamp(current_date)
        try:
            idx = df.index.searchsorted(ts)
            start_idx = max(0, idx - 20)
            end_idx = max(start_idx + 1, idx)
            vol_slice = df["Volume"].iloc[start_idx:end_idx]
            avg_vol = float(vol_slice.mean()) if len(vol_slice) > 0 else 0.0
            return avg_vol * price
        except Exception:
            return 0.0

    def _close_position(
        self,
        ticker: str,
        pos: dict,
        exit_price_raw: float,
        current_date: date,
        exit_reason: str,
        df: pd.DataFrame,
        apply_costs: bool,
        apply_slippage: bool,
    ) -> tuple[dict, float, float, float]:
        """
        Close a position and return (trade_record, proceeds, cost_paid, slip_paid).
        """
        shares = pos["shares"]
        order_value = exit_price_raw * shares

        # Slippage on exit
        avg_vol_val = self._get_avg_vol_value(df, current_date, exit_price_raw)
        if apply_slippage:
            exec_price = _apply_slippage(
                exit_price_raw, "SELL", order_value, avg_vol_val
            )
        else:
            exec_price = exit_price_raw

        slip_paid = abs(exec_price - exit_price_raw) * shares

        # Transaction cost on exit
        exec_value = exec_price * shares
        cost = _compute_trade_cost(exec_value, "SELL", self.country) if apply_costs else 0.0

        proceeds = exec_value - cost
        pnl = proceeds - pos["cost_basis"]
        hold_days = (current_date - pos["entry_date"]).days

        trade = {
            "ticker":       ticker,
            "entry_date":   pos["entry_date"].isoformat(),
            "exit_date":    current_date.isoformat(),
            "entry_price":  round(pos["entry_price"], 4),
            "exit_price":   round(exec_price, 4),
            "shares":       round(shares, 6),
            "pnl":          round(pnl, 2),
            "return_pct":   round(
                pnl / pos["cost_basis"] * 100 if pos["cost_basis"] > 0 else 0.0, 4
            ),
            "exit_reason":  exit_reason,
            "hold_days":    hold_days,
            "costs_paid":   round(cost, 2),
            "slippage_paid": round(slip_paid, 2),
        }
        return trade, proceeds, cost, slip_paid

    # ── Main simulation ────────────────────────────────────────────────────────

    async def run(self) -> dict:
        """Run the full strategy backtest and return a comprehensive result dict."""

        loop = asyncio.get_event_loop()
        benchmark_ticker = "^NSEI" if self.country == "IN" else "^GSPC"

        # Fetch 6 months extra before start for indicator warmup
        fetch_start = (
            datetime.combine(self.start_date, datetime.min.time()) - timedelta(days=180)
        ).strftime("%Y-%m-%d")
        fetch_end = self.end_date.strftime("%Y-%m-%d")

        all_fetch = self.tickers + [benchmark_ticker]

        async def _fetch(ticker: str):
            return ticker, await loop.run_in_executor(
                None,
                lambda t=ticker: yf.download(
                    t,
                    start=fetch_start,
                    end=fetch_end,
                    progress=False,
                    auto_adjust=True,
                ),
            )

        results_list = await asyncio.gather(
            *[_fetch(t) for t in all_fetch], return_exceptions=True
        )

        price_data: dict[str, pd.DataFrame] = {}
        for item in results_list:
            if isinstance(item, Exception):
                logger.warning("Failed to fetch ticker: %s", item)
                continue
            ticker, df = item
            if df is not None and len(df) >= 30:
                # Flatten multi-level columns if present (yfinance >= 0.2 quirk)
                if isinstance(df.columns, pd.MultiIndex):
                    df.columns = df.columns.get_level_values(0)
                price_data[ticker] = df

        # ── Generate signals ───────────────────────────────────────────────────

        ticker_signals: dict[str, pd.Series] = {}
        for ticker in self.tickers:
            df = price_data.get(ticker)
            if df is None or len(df) < 50:
                continue
            if self.strategy_name == STRATEGY_RSI:
                ticker_signals[ticker] = _signals_rsi(df)
            elif self.strategy_name == STRATEGY_MACD:
                ticker_signals[ticker] = _signals_macd(df)
            elif self.strategy_name == STRATEGY_MA:
                ticker_signals[ticker] = _signals_ma_crossover(df)
            elif self.strategy_name == STRATEGY_BOLLINGER:
                ticker_signals[ticker] = _signals_bollinger(df)
            elif self.strategy_name == STRATEGY_BUY_AND_HOLD:
                ticker_signals[ticker] = _signals_buy_and_hold(df)
            elif self.strategy_name == STRATEGY_MOMENTUM:
                # Momentum signals are computed cross-sectionally in the simulation loop
                ticker_signals[ticker] = pd.Series("HOLD", index=df.index)

        # ── Build trading calendar ─────────────────────────────────────────────

        all_dates: set = set()
        for ticker in self.tickers:
            df = price_data.get(ticker)
            if df is not None:
                for d in df.index:
                    dt = d.date() if hasattr(d, "date") else d
                    if self.start_date <= dt <= self.end_date:
                        all_dates.add(dt)
        trading_days = sorted(all_dates)

        if not trading_days:
            logger.warning("No trading days found in backtest window.")
            return self._empty_result(benchmark_ticker)

        # ── Portfolio simulation ───────────────────────────────────────────────

        cash = self.initial_capital
        open_positions: dict[str, dict] = {}  # ticker → position dict
        closed_trades: list[dict] = []
        equity_curve: list[dict] = []
        daily_returns: list[float] = []
        total_costs_paid = 0.0
        total_slippage_paid = 0.0
        prev_portfolio_value = self.initial_capital
        portfolio_peak = self.initial_capital

        last_rebalance_month: Optional[int] = None  # for MOMENTUM

        for current_date in trading_days:

            # ── MOMENTUM: cross-sectional rebalance at month change ────────────
            if self.strategy_name == STRATEGY_MOMENTUM and (
                last_rebalance_month is None
                or current_date.month != last_rebalance_month
            ):
                scores: dict[str, float] = {}
                for t in self.tickers:
                    df = price_data.get(t)
                    if df is None:
                        continue
                    close = df["Close"]
                    ts = pd.Timestamp(current_date)
                    idx = close.index.searchsorted(ts)
                    if idx >= 63 and idx <= len(close):
                        try:
                            ret = float(close.iloc[idx - 1]) / float(close.iloc[idx - 64]) - 1
                            scores[t] = ret
                        except Exception:
                            pass

                if scores:
                    ranked = sorted(scores, key=scores.__getitem__, reverse=True)
                    top_n = max(1, int(len(ranked) * 0.30))
                    top_tickers = set(ranked[:top_n])

                    # Close positions not in top_tickers
                    for t in list(open_positions.keys()):
                        if t not in top_tickers:
                            df = price_data.get(t)
                            if df is None:
                                continue
                            ts = pd.Timestamp(current_date)
                            idx = df["Close"].index.searchsorted(ts)
                            if idx > 0 and idx <= len(df):
                                sell_price_raw = float(df["Close"].iloc[idx - 1])
                                trade, proceeds, cost, slip = self._close_position(
                                    t,
                                    open_positions[t],
                                    sell_price_raw,
                                    current_date,
                                    "MOMENTUM_REBALANCE",
                                    df,
                                    self.apply_costs,
                                    self.apply_slippage,
                                )
                                cash += proceeds
                                total_costs_paid += cost
                                total_slippage_paid += slip
                                closed_trades.append(trade)
                                open_positions.pop(t)

                    # Mark top tickers as BUY today via signal override
                    for t in top_tickers:
                        if t in ticker_signals:
                            ts = pd.Timestamp(current_date)
                            if ts in ticker_signals[t].index:
                                ticker_signals[t][ts] = "BUY"

                last_rebalance_month = current_date.month

            # ── Check exits for open positions ─────────────────────────────────
            for ticker in list(open_positions.keys()):
                pos = open_positions[ticker]
                df = price_data.get(ticker)
                if df is None:
                    continue

                row = self._get_price_row(df, current_date)
                if row is None:
                    continue

                try:
                    day_low = float(row["Low"])
                    day_high = float(row["High"])
                    day_close = float(row["Close"])
                except (KeyError, TypeError, ValueError):
                    continue

                exit_reason = None
                exit_price_raw = day_close

                # Stop-loss check (triggered if low touches stop)
                if self.stop_loss_pct > 0 and day_low <= pos["stop"]:
                    exit_reason = "STOP_LOSS"
                    exit_price_raw = pos["stop"]

                # Take-profit check (triggered if high touches target)
                elif self.take_profit_pct > 0 and day_high >= pos["target"]:
                    exit_reason = "TAKE_PROFIT"
                    exit_price_raw = pos["target"]

                # Signal-based exit
                else:
                    sig_series = ticker_signals.get(ticker)
                    if sig_series is not None:
                        ts = pd.Timestamp(current_date)
                        if ts in sig_series.index and sig_series[ts] == "SELL":
                            exit_reason = "SIGNAL"
                            exit_price_raw = day_close

                if exit_reason:
                    trade, proceeds, cost, slip = self._close_position(
                        ticker,
                        pos,
                        exit_price_raw,
                        current_date,
                        exit_reason,
                        df,
                        self.apply_costs,
                        self.apply_slippage,
                    )
                    cash += proceeds
                    total_costs_paid += cost
                    total_slippage_paid += slip
                    closed_trades.append(trade)
                    open_positions.pop(ticker)

            # ── Open new positions on BUY signals ──────────────────────────────
            for ticker, sig_series in ticker_signals.items():
                if ticker in open_positions:
                    continue
                if len(open_positions) >= self.max_positions:
                    break

                ts = pd.Timestamp(current_date)
                if ts not in sig_series.index:
                    continue
                if sig_series[ts] != "BUY":
                    continue

                df = price_data.get(ticker)
                if df is None:
                    continue

                row = self._get_price_row(df, current_date)
                if row is None:
                    continue

                try:
                    raw_price = float(row["Close"])
                except (KeyError, TypeError, ValueError):
                    continue

                if raw_price <= 0 or cash <= 0:
                    continue

                # Position sizing: equal weight across remaining capacity,
                # capped at 20% of initial capital per position
                remaining_slots = self.max_positions - len(open_positions)
                target_invest = cash / remaining_slots
                max_invest = self.initial_capital * 0.20
                invest = min(target_invest, max_invest, cash)

                if invest < 1.0:
                    continue

                # Slippage on entry
                avg_vol_val = self._get_avg_vol_value(df, current_date, raw_price)
                if self.apply_slippage:
                    exec_price = _apply_slippage(
                        raw_price, "BUY", invest, avg_vol_val
                    )
                else:
                    exec_price = raw_price

                slip_paid = abs(exec_price - raw_price) * (invest / exec_price)

                shares = invest / exec_price
                gross_value = exec_price * shares

                # Transaction cost on entry
                cost = (
                    _compute_trade_cost(gross_value, "BUY", self.country)
                    if self.apply_costs
                    else 0.0
                )

                total_deducted = gross_value + cost
                if total_deducted > cash:
                    # Adjust shares down to fit available cash
                    affordable = cash / (exec_price * (1 + (cost / gross_value if gross_value > 0 else 0)))
                    shares = affordable
                    gross_value = exec_price * shares
                    cost = (
                        _compute_trade_cost(gross_value, "BUY", self.country)
                        if self.apply_costs
                        else 0.0
                    )
                    total_deducted = gross_value + cost

                cash -= total_deducted
                total_costs_paid += cost
                total_slippage_paid += slip_paid

                stop_price = exec_price * (1 - self.stop_loss_pct) if self.stop_loss_pct > 0 else 0.0
                target_price = exec_price * (1 + self.take_profit_pct) if self.take_profit_pct > 0 else float("inf")

                open_positions[ticker] = {
                    "shares":       shares,
                    "entry_price":  raw_price,
                    "exec_price":   exec_price,
                    "stop":         stop_price,
                    "target":       target_price,
                    "entry_date":   current_date,
                    "cost_basis":   gross_value + cost,  # total capital deployed
                }

            # ── Mark-to-market end of day ──────────────────────────────────────
            holdings_value = 0.0
            for ticker, pos in open_positions.items():
                df = price_data.get(ticker)
                if df is None:
                    continue
                row = self._get_price_row(df, current_date)
                if row is not None:
                    try:
                        holdings_value += pos["shares"] * float(row["Close"])
                    except (KeyError, TypeError, ValueError):
                        holdings_value += pos["cost_basis"]  # fallback: cost basis
                else:
                    holdings_value += pos["cost_basis"]

            portfolio_value = cash + holdings_value

            # Drawdown from rolling peak
            if portfolio_value > portfolio_peak:
                portfolio_peak = portfolio_value
            drawdown_pct = (
                (portfolio_value - portfolio_peak) / portfolio_peak * 100
                if portfolio_peak > 0
                else 0.0
            )

            equity_curve.append({
                "date":             current_date.isoformat(),
                "value":            round(portfolio_value, 2),
                "drawdown_pct":     round(drawdown_pct, 4),
                "positions_count":  len(open_positions),
                "cash":             round(cash, 2),
            })

            if prev_portfolio_value > 0:
                daily_ret = (portfolio_value - prev_portfolio_value) / prev_portfolio_value
                daily_returns.append(daily_ret)
            prev_portfolio_value = portfolio_value

        # ── Force-close remaining open positions at end_date ──────────────────
        for ticker, pos in list(open_positions.items()):
            df = price_data.get(ticker)
            if df is None:
                # Return cost basis as proceeds (no gain/loss)
                cash += pos["cost_basis"]
                continue

            # Use last available close at or before end_date
            close = df["Close"]
            ts = pd.Timestamp(self.end_date)
            idx = close.index.searchsorted(ts, side="right")
            if idx > 0:
                last_price = float(close.iloc[idx - 1])
            else:
                last_price = pos["exec_price"]

            trade, proceeds, cost, slip = self._close_position(
                ticker,
                pos,
                last_price,
                self.end_date,
                "END_OF_BACKTEST",
                df,
                apply_costs=False,   # no forced-close costs
                apply_slippage=False,
            )
            cash += proceeds
            closed_trades.append(trade)
            open_positions.pop(ticker)

        # ── Benchmark simulation (buy-and-hold, no costs) ──────────────────────
        bench_df = price_data.get(benchmark_ticker)
        benchmark_equity: list[float] = []
        benchmark_returns: list[float] = []

        if bench_df is not None:
            bench_start_price: Optional[float] = None
            for d in trading_days:
                ts = pd.Timestamp(d)
                row = None
                try:
                    if ts in bench_df.index:
                        row = bench_df.loc[ts]
                except Exception:
                    pass
                if row is None:
                    # Carry forward last value
                    if benchmark_equity:
                        benchmark_equity.append(benchmark_equity[-1])
                    continue
                try:
                    price = float(row["Close"])
                except (KeyError, TypeError, ValueError):
                    if benchmark_equity:
                        benchmark_equity.append(benchmark_equity[-1])
                    continue

                if bench_start_price is None:
                    bench_start_price = price

                bench_value = self.initial_capital * (price / bench_start_price)
                benchmark_equity.append(bench_value)
                if len(benchmark_equity) > 1:
                    benchmark_returns.append(
                        (benchmark_equity[-1] - benchmark_equity[-2]) / benchmark_equity[-2]
                    )

        # ── Compute strategy metrics ───────────────────────────────────────────
        final_value = cash  # all positions now closed
        total_return = (final_value - self.initial_capital) / self.initial_capital
        backtest_days = (self.end_date - self.start_date).days

        equity_values = [e["value"] for e in equity_curve]
        max_dd = _max_drawdown(equity_values)

        strategy_metrics: dict = {
            "total_return_pct":    round(total_return * 100, 4),
            "cagr_pct":            round(_cagr(total_return, backtest_days) * 100, 4),
            "sharpe_ratio":        round(_sharpe(daily_returns), 4),
            "sortino_ratio":       round(_sortino(daily_returns), 4),
            "max_drawdown_pct":    round(max_dd, 4),
            "calmar_ratio":        0.0,
            "win_rate_pct":        0.0,
            "profit_factor":       0.0,
            "total_trades":        len(closed_trades),
            "winning_trades":      0,
            "losing_trades":       0,
            "avg_hold_days":       0.0,
            "gross_profit":        0.0,
            "gross_loss":          0.0,
            "total_costs_paid":    round(total_costs_paid, 2),
            "total_slippage_paid": round(total_slippage_paid, 2),
            "final_value":         round(final_value, 2),
        }

        wins = [t for t in closed_trades if t["pnl"] > 0]
        losses = [t for t in closed_trades if t["pnl"] <= 0]
        gp = sum(t["pnl"] for t in wins)
        gl = abs(sum(t["pnl"] for t in losses))
        nt = len(closed_trades)

        strategy_metrics["winning_trades"] = len(wins)
        strategy_metrics["losing_trades"] = len(losses)
        strategy_metrics["win_rate_pct"] = (
            round(len(wins) / nt * 100, 4) if nt > 0 else 0.0
        )
        strategy_metrics["profit_factor"] = (
            round(gp / gl, 4)
            if gl > 0
            else (float("inf") if gp > 0 else 0.0)
        )
        strategy_metrics["gross_profit"] = round(gp, 2)
        strategy_metrics["gross_loss"] = round(gl, 2)
        strategy_metrics["avg_hold_days"] = (
            round(sum(t["hold_days"] for t in closed_trades) / nt, 2) if nt > 0 else 0.0
        )
        strategy_metrics["calmar_ratio"] = _calmar(
            strategy_metrics["cagr_pct"], abs(strategy_metrics["max_drawdown_pct"])
        )

        # ── Compute benchmark metrics ──────────────────────────────────────────
        bench_return = (
            (benchmark_equity[-1] - self.initial_capital) / self.initial_capital
            if benchmark_equity
            else 0.0
        )
        bench_cagr = _cagr(bench_return, backtest_days)
        bench_sharpe = _sharpe(benchmark_returns)
        bench_max_dd = _max_drawdown(benchmark_equity) if benchmark_equity else 0.0

        beta, alpha = _beta_alpha(daily_returns, benchmark_returns)
        excess_return = strategy_metrics["total_return_pct"] - bench_return * 100

        benchmark_metrics = {
            "ticker":           benchmark_ticker,
            "total_return_pct": round(bench_return * 100, 4),
            "cagr_pct":         round(bench_cagr * 100, 4),
            "sharpe_ratio":     round(bench_sharpe, 4),
            "max_drawdown_pct": round(bench_max_dd, 4),
            "final_value":      round(
                benchmark_equity[-1] if benchmark_equity else self.initial_capital, 2
            ),
        }

        comparison = {
            "excess_return_pct":       round(excess_return, 4),
            "alpha_ann_pct":           alpha,
            "beta":                    beta,
            "strategy_wins":           strategy_metrics["total_return_pct"]
                                       > benchmark_metrics["total_return_pct"],
            "sharpe_advantage":        round(
                strategy_metrics["sharpe_ratio"] - benchmark_metrics["sharpe_ratio"], 4
            ),
            "drawdown_advantage_pct":  round(
                benchmark_metrics["max_drawdown_pct"] - strategy_metrics["max_drawdown_pct"], 4
            ),
        }

        # ── Monthly returns from equity curve ──────────────────────────────────
        monthly_returns: list[dict] = []
        monthly_groups: dict[str, list[float]] = defaultdict(list)

        for entry in equity_curve:
            ym = entry["date"][:7]  # "YYYY-MM"
            monthly_groups[ym].append(entry["value"])

        sorted_months = sorted(monthly_groups.keys())
        prev_month_end: Optional[float] = None

        for ym in sorted_months:
            values = monthly_groups[ym]
            month_end = values[-1]
            if prev_month_end is not None and prev_month_end > 0:
                m_ret = (month_end - prev_month_end) / prev_month_end * 100
            else:
                m_ret = 0.0
            year, month = ym.split("-")
            monthly_returns.append({
                "year":       int(year),
                "month":      int(month),
                "month_label": ym,
                "return_pct": round(m_ret, 4),
                "end_value":  round(month_end, 2),
            })
            prev_month_end = month_end

        # ── Benchmark curve ────────────────────────────────────────────────────
        benchmark_curve = [
            {"date": trading_days[i].isoformat(), "value": round(v, 2)}
            for i, v in enumerate(benchmark_equity)
            if i < len(trading_days)
        ]

        # ── Final result ───────────────────────────────────────────────────────
        return {
            "strategy":      self.strategy_name,
            "strategy_info": STRATEGY_DESCRIPTIONS.get(self.strategy_name, {}),
            "config": {
                "tickers":         self.tickers,
                "start_date":      self.start_date.isoformat(),
                "end_date":        self.end_date.isoformat(),
                "initial_capital": self.initial_capital,
                "country":         self.country,
                "max_positions":   self.max_positions,
                "stop_loss_pct":   self.stop_loss_pct * 100,
                "take_profit_pct": self.take_profit_pct * 100,
                "apply_slippage":  self.apply_slippage,
                "apply_costs":     self.apply_costs,
                "benchmark":       benchmark_ticker,
            },
            "metrics":          strategy_metrics,
            "benchmark":        benchmark_metrics,
            "comparison":       comparison,
            "equity_curve":     equity_curve,
            "benchmark_curve":  benchmark_curve,
            "trades":           closed_trades,
            "monthly_returns":  monthly_returns,
            "cost_breakdown": {
                "model":                   "India (STT+GST+Stamp)" if self.country == "IN" else "US (SEC fee)",
                "total_costs":             round(total_costs_paid, 2),
                "total_slippage":          round(total_slippage_paid, 2),
                "total_friction":          round(total_costs_paid + total_slippage_paid, 2),
                "friction_pct_of_capital": round(
                    (total_costs_paid + total_slippage_paid) / self.initial_capital * 100, 4
                ),
            },
        }

    # ── Fallback for empty data ────────────────────────────────────────────────

    def _empty_result(self, benchmark_ticker: str) -> dict:
        """Return a zero-filled result when no trading data is available."""
        return {
            "strategy":      self.strategy_name,
            "strategy_info": STRATEGY_DESCRIPTIONS.get(self.strategy_name, {}),
            "config": {
                "tickers":         self.tickers,
                "start_date":      self.start_date.isoformat(),
                "end_date":        self.end_date.isoformat(),
                "initial_capital": self.initial_capital,
                "country":         self.country,
                "max_positions":   self.max_positions,
                "stop_loss_pct":   self.stop_loss_pct * 100,
                "take_profit_pct": self.take_profit_pct * 100,
                "apply_slippage":  self.apply_slippage,
                "apply_costs":     self.apply_costs,
                "benchmark":       benchmark_ticker,
            },
            "metrics": {
                "total_return_pct": 0.0, "cagr_pct": 0.0, "sharpe_ratio": 0.0,
                "sortino_ratio": 0.0, "max_drawdown_pct": 0.0, "calmar_ratio": 0.0,
                "win_rate_pct": 0.0, "profit_factor": 0.0, "total_trades": 0,
                "winning_trades": 0, "losing_trades": 0, "avg_hold_days": 0.0,
                "gross_profit": 0.0, "gross_loss": 0.0,
                "total_costs_paid": 0.0, "total_slippage_paid": 0.0,
                "final_value": round(self.initial_capital, 2),
            },
            "benchmark": {
                "ticker": benchmark_ticker,
                "total_return_pct": 0.0, "cagr_pct": 0.0, "sharpe_ratio": 0.0,
                "max_drawdown_pct": 0.0, "final_value": round(self.initial_capital, 2),
            },
            "comparison": {
                "excess_return_pct": 0.0, "alpha_ann_pct": 0.0, "beta": 1.0,
                "strategy_wins": False, "sharpe_advantage": 0.0,
                "drawdown_advantage_pct": 0.0,
            },
            "equity_curve":    [],
            "benchmark_curve": [],
            "trades":          [],
            "monthly_returns": [],
            "cost_breakdown": {
                "model": "India (STT+GST+Stamp)" if self.country == "IN" else "US (SEC fee)",
                "total_costs": 0.0, "total_slippage": 0.0,
                "total_friction": 0.0, "friction_pct_of_capital": 0.0,
            },
        }
