"""
engines/backtest.py
===================
Core BacktestEngine — simulates historical trading performance using
signals stored in `ai_analysis` and OHLCV data from `stock_prices`.

Entry  : next available close price after signal date
Exit   : stop-loss / take-profit / max-hold / new SELL|REDUCE signal
Sizing : half-Kelly (capped at 20%) or equal-weight fallback
Output : equity curve, trade log, monthly returns, portfolio metrics
"""
from __future__ import annotations

import logging
import math
from collections import defaultdict
from datetime import date, datetime, timedelta, timezone
from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger(__name__)

# ── Constants ──────────────────────────────────────────────────────────────────

EXIT_STOP   = "STOP"
EXIT_TARGET = "TARGET"
EXIT_TIME   = "TIME"
EXIT_SIGNAL = "SIGNAL"

NEGATIVE_SIGNALS = {"SELL", "REDUCE"}

# ── Helpers ────────────────────────────────────────────────────────────────────


def _annualized_return(total_return: float, days: int) -> float:
    """CAGR from a total return fraction and calendar-day count."""
    if days <= 0:
        return 0.0
    years = days / 365.25
    if years < 1e-9:
        return 0.0
    try:
        return (1.0 + total_return) ** (1.0 / years) - 1.0
    except (ValueError, OverflowError):
        return 0.0


def _sharpe(daily_returns: list[float], risk_free_daily: float = 0.0) -> float:
    if len(daily_returns) < 2:
        return 0.0
    n = len(daily_returns)
    mean = sum(daily_returns) / n
    excess = [r - risk_free_daily for r in daily_returns]
    mean_excess = sum(excess) / n
    variance = sum((r - mean_excess) ** 2 for r in excess) / (n - 1)
    std = math.sqrt(variance) if variance > 0 else 0.0
    return (mean_excess / std) * math.sqrt(252) if std > 0 else 0.0


def _sortino(daily_returns: list[float], risk_free_daily: float = 0.0) -> float:
    if len(daily_returns) < 2:
        return 0.0
    n = len(daily_returns)
    mean_excess = sum(r - risk_free_daily for r in daily_returns) / n
    downside = [min(r - risk_free_daily, 0.0) ** 2 for r in daily_returns]
    downside_var = sum(downside) / max(len([x for x in downside if x > 0]), 1)
    downside_std = math.sqrt(downside_var) if downside_var > 0 else 0.0
    return (mean_excess / downside_std) * math.sqrt(252) if downside_std > 0 else 0.0


def _max_drawdown(equity_values: list[float]) -> float:
    if len(equity_values) < 2:
        return 0.0
    peak = equity_values[0]
    max_dd = 0.0
    for v in equity_values:
        if v > peak:
            peak = v
        dd = (v - peak) / peak if peak > 0 else 0.0
        if dd < max_dd:
            max_dd = dd
    return max_dd * 100.0  # as percentage


# ── Main Engine ────────────────────────────────────────────────────────────────


class BacktestEngine:
    """
    Parameters
    ----------
    db              : async SQLAlchemy session
    start_date      : first date of backtest window
    end_date        : last date of backtest window
    initial_capital : starting cash (default 100 000)
    signal_filter   : which signals trigger entry (default BUY)
    max_positions   : concurrent open position limit (default 10)
    use_kelly       : use half-Kelly sizing when available (default True)
    max_kelly_pct   : cap on Kelly-sized position as fraction of portfolio (default 0.20)
    max_hold_days   : force-exit after this many calendar days (default 30)
    country         : optional "US" or "IN" country filter
    """

    def __init__(
        self,
        db: AsyncSession,
        start_date: date,
        end_date: date,
        initial_capital: float = 100_000.0,
        signal_filter: list[str] | None = None,
        max_positions: int = 10,
        use_kelly: bool = True,
        max_kelly_pct: float = 0.20,
        max_hold_days: int = 30,
        country: str | None = None,
    ):
        self.db = db
        self.start_date = start_date
        self.end_date = end_date
        self.initial_capital = initial_capital
        self.signal_filter = [s.upper() for s in (signal_filter or ["BUY"])]
        self.max_positions = max_positions
        self.use_kelly = use_kelly
        self.max_kelly_pct = max_kelly_pct
        self.max_hold_days = max_hold_days
        self.country = country.upper() if country else None

    # ── Data Loading ───────────────────────────────────────────────────────────

    async def _load_signals(self) -> list[dict]:
        """
        Fetch all ai_analysis rows in the date range that match signal_filter.
        Also loads SELL/REDUCE signals for the same period so we can
        detect adverse signal flips on open positions.
        """
        params: dict[str, Any] = {
            "start": datetime.combine(self.start_date, datetime.min.time()),
            "end":   datetime.combine(self.end_date,   datetime.max.time()),
            "signals": self.signal_filter,
        }

        country_clause = ""
        if self.country:
            country_clause = "AND s.country = :country"
            params["country"] = self.country

        sql = text(f"""
            SELECT
                a.ticker,
                a.analysis_date::date          AS signal_date,
                a.signal,
                a.final_score,
                a.entry_price,
                a.stop_loss,
                a.take_profit,
                a.atr_14,
                a.kelly_fraction,
                a.regime
            FROM ai_analysis a
            JOIN stocks s ON s.ticker = a.ticker
            WHERE a.analysis_date >= :start
              AND a.analysis_date <= :end
              AND a.signal = ANY(:signals)
              {country_clause}
            ORDER BY a.analysis_date ASC, a.ticker ASC
        """)
        result = await self.db.execute(sql, params)
        rows = result.fetchall()

        signals = []
        for r in rows:
            signals.append({
                "ticker":        r.ticker,
                "signal_date":   r.signal_date,
                "signal":        r.signal,
                "final_score":   r.final_score,
                "entry_price":   r.entry_price,
                "stop_loss":     r.stop_loss,
                "take_profit":   r.take_profit,
                "atr_14":        r.atr_14,
                "kelly_fraction": r.kelly_fraction,
                "regime":        r.regime,
            })
        return signals

    async def _load_adverse_signals(self) -> dict[str, set[date]]:
        """
        Load SELL/REDUCE signal dates per ticker so we can detect
        adverse flips while a position is open.
        """
        params: dict[str, Any] = {
            "start": datetime.combine(self.start_date, datetime.min.time()),
            "end":   datetime.combine(self.end_date,   datetime.max.time()),
        }

        country_clause = ""
        if self.country:
            country_clause = "AND s.country = :country"
            params["country"] = self.country

        sql = text(f"""
            SELECT a.ticker, a.analysis_date::date AS signal_date
            FROM ai_analysis a
            JOIN stocks s ON s.ticker = a.ticker
            WHERE a.analysis_date >= :start
              AND a.analysis_date <= :end
              AND a.signal = ANY(ARRAY['SELL','REDUCE'])
              {country_clause}
        """)
        result = await self.db.execute(sql, params)
        adverse: dict[str, set[date]] = defaultdict(set)
        for r in result.fetchall():
            adverse[r.ticker].add(r.signal_date)
        return adverse

    async def _load_prices(self, tickers: list[str]) -> dict[str, dict[date, dict]]:
        """
        Load all OHLCV rows for the given tickers across the full backtest
        window (plus max_hold_days buffer). Returns:
            {ticker: {date: {open, high, low, close, volume}}}
        """
        if not tickers:
            return {}

        # Extend end by max_hold_days so we can exit positions that opened near end_date
        extended_end = self.end_date + timedelta(days=self.max_hold_days + 10)

        params: dict[str, Any] = {
            "tickers": tickers,
            "start":   datetime.combine(self.start_date, datetime.min.time()),
            "end":     datetime.combine(extended_end,    datetime.max.time()),
        }

        sql = text("""
            SELECT
                ticker,
                time::date AS price_date,
                open, high, low, close, volume
            FROM stock_prices
            WHERE ticker = ANY(:tickers)
              AND time >= :start
              AND time <= :end
            ORDER BY ticker, time ASC
        """)
        result = await self.db.execute(sql, params)
        rows = result.fetchall()

        prices: dict[str, dict[date, dict]] = defaultdict(dict)
        for r in rows:
            prices[r.ticker][r.price_date] = {
                "open":   r.open,
                "high":   r.high,
                "low":    r.low,
                "close":  r.close,
                "volume": r.volume,
            }
        return prices

    # ── Position Sizing ────────────────────────────────────────────────────────

    def _position_size(
        self,
        portfolio_value: float,
        cash: float,
        kelly_fraction: float | None,
        open_positions: int,
    ) -> float:
        """Return dollar value to invest in one new position."""
        if self.use_kelly and kelly_fraction and kelly_fraction > 0:
            # Half-Kelly, capped at max_kelly_pct
            size = min(kelly_fraction * 0.5 * portfolio_value, self.max_kelly_pct * portfolio_value)
        else:
            # Equal-weight across max_positions slots
            size = portfolio_value / max(self.max_positions, 1)

        # Never invest more than available cash
        return min(size, cash)

    # ── Main Run ───────────────────────────────────────────────────────────────

    async def run(self) -> dict:
        """Execute the backtest and return the full result dict."""

        # ── 1. Load all data upfront ──────────────────────────────────────────
        signals = await self._load_signals()
        if not signals:
            logger.warning("Backtest: no signals found for given parameters.")

        adverse_signals = await self._load_adverse_signals()

        all_tickers = list({s["ticker"] for s in signals})
        prices = await self._load_prices(all_tickers)

        # ── 2. Build sorted trading-day calendar ──────────────────────────────
        # Collect every unique date that appears in price data across all tickers
        all_dates: set[date] = set()
        for ticker_prices in prices.values():
            all_dates.update(ticker_prices.keys())

        trading_days = sorted(d for d in all_dates
                              if self.start_date <= d <= self.end_date + timedelta(days=self.max_hold_days + 10))

        # ── 3. Index signals by date ──────────────────────────────────────────
        # signal_date → list of signal dicts
        signals_by_date: dict[date, list[dict]] = defaultdict(list)
        for sig in signals:
            signals_by_date[sig["signal_date"]].append(sig)

        # ── 4. Portfolio state ────────────────────────────────────────────────
        cash: float = self.initial_capital
        # {ticker: {entry_price, stop, target, entry_date, shares, cost, signal, regime, atr_14}}
        open_positions: dict[str, dict] = {}

        equity_curve: list[dict] = []
        closed_trades: list[dict] = []
        daily_returns: list[float] = []
        portfolio_value = self.initial_capital
        peak_value = self.initial_capital

        # ── 5. Day-by-day simulation ──────────────────────────────────────────
        for current_date in trading_days:

            # ── 5a. Check exits for open positions ────────────────────────────
            tickers_to_close: list[tuple[str, float, str]] = []  # (ticker, exit_price, reason)

            for ticker, pos in list(open_positions.items()):
                day_prices = prices.get(ticker, {}).get(current_date)
                if not day_prices:
                    continue  # no data — hold

                hold_days = (current_date - pos["entry_date"]).days

                # Rule 1: Stop-loss
                if day_prices["low"] <= pos["stop"]:
                    tickers_to_close.append((ticker, pos["stop"], EXIT_STOP))
                    continue

                # Rule 2: Take-profit
                if day_prices["high"] >= pos["target"]:
                    tickers_to_close.append((ticker, pos["target"], EXIT_TARGET))
                    continue

                # Rule 3: Max hold days
                if hold_days >= self.max_hold_days:
                    tickers_to_close.append((ticker, day_prices["close"], EXIT_TIME))
                    continue

                # Rule 4: Adverse signal flip
                if current_date in adverse_signals.get(ticker, set()):
                    tickers_to_close.append((ticker, day_prices["close"], EXIT_SIGNAL))
                    continue

            for ticker, exit_price, reason in tickers_to_close:
                pos = open_positions.pop(ticker)
                shares = pos["shares"]
                proceeds = shares * exit_price
                pnl = proceeds - pos["cost"]
                return_pct = pnl / pos["cost"] * 100.0 if pos["cost"] > 0 else 0.0

                cash += proceeds
                closed_trades.append({
                    "ticker":      ticker,
                    "entry_date":  pos["entry_date"].isoformat(),
                    "exit_date":   current_date.isoformat(),
                    "entry_price": round(pos["entry_price"], 4),
                    "exit_price":  round(exit_price, 4),
                    "shares":      round(shares, 4),
                    "return_pct":  round(return_pct, 4),
                    "pnl":         round(pnl, 4),
                    "exit_reason": reason,
                    "hold_days":   (current_date - pos["entry_date"]).days,
                    "regime":      pos.get("regime"),
                    "signal":      pos.get("signal"),
                })

            # ── 5b. Open new positions on today's signals ─────────────────────
            # Only consider signals whose date is *before* current_date
            # (enter on next day's close after signal date)
            for sig in signals_by_date.get(current_date - timedelta(days=1), []):
                ticker = sig["ticker"]

                # Skip if already in a position for this ticker
                if ticker in open_positions:
                    continue

                # Skip if at max capacity
                if len(open_positions) >= self.max_positions:
                    break

                # Find entry price: today's close (first available day after signal_date)
                entry_prices_day = prices.get(ticker, {}).get(current_date)
                if not entry_prices_day:
                    # Try to find next available day within a window
                    found = False
                    for offset in range(1, 6):
                        try_date = current_date + timedelta(days=offset)
                        if try_date in prices.get(ticker, {}):
                            entry_prices_day = prices[ticker][try_date]
                            found = True
                            break
                    if not found:
                        logger.debug("Backtest: no entry price for %s near %s — skipping", ticker, current_date)
                        continue

                entry_price = entry_prices_day["close"]
                if not entry_price or entry_price <= 0:
                    continue

                # Determine stop / target with ATR fallback
                atr = sig.get("atr_14") or 0.0
                stop = sig.get("stop_loss")
                target = sig.get("take_profit")

                if not stop or stop <= 0:
                    stop = entry_price - 2.0 * atr if atr > 0 else entry_price * 0.93
                if not target or target <= 0:
                    target = entry_price + 6.0 * atr if atr > 0 else entry_price * 1.18

                # Ensure stop is below and target above entry price
                if stop >= entry_price:
                    stop = entry_price * 0.93
                if target <= entry_price:
                    target = entry_price * 1.18

                # Mark-to-market portfolio value before sizing
                mtm = cash + sum(
                    p["shares"] * (prices.get(t, {}).get(current_date, {}).get("close") or p["entry_price"])
                    for t, p in open_positions.items()
                )

                invest = self._position_size(
                    portfolio_value=mtm,
                    cash=cash,
                    kelly_fraction=sig.get("kelly_fraction"),
                    open_positions=len(open_positions),
                )

                if invest < 1.0:
                    continue  # can't afford even one unit

                shares = invest / entry_price
                cost = shares * entry_price
                cash -= cost

                open_positions[ticker] = {
                    "entry_price": entry_price,
                    "stop":        stop,
                    "target":      target,
                    "entry_date":  current_date,
                    "shares":      shares,
                    "cost":        cost,
                    "signal":      sig["signal"],
                    "regime":      sig.get("regime"),
                    "atr_14":      atr,
                }

            # ── 5c. Mark-to-market end of day ─────────────────────────────────
            holdings_value = 0.0
            for ticker, pos in open_positions.items():
                day_close = (prices.get(ticker, {}).get(current_date) or {}).get("close")
                if day_close:
                    holdings_value += pos["shares"] * day_close
                else:
                    holdings_value += pos["cost"]  # use cost basis as fallback

            prev_portfolio_value = portfolio_value
            portfolio_value = cash + holdings_value

            # Only record equity curve within the actual backtest window
            if self.start_date <= current_date <= self.end_date:
                if prev_portfolio_value > 0:
                    daily_ret = (portfolio_value - prev_portfolio_value) / prev_portfolio_value
                    daily_returns.append(daily_ret)

                if portfolio_value > peak_value:
                    peak_value = portfolio_value
                drawdown_pct = ((portfolio_value - peak_value) / peak_value * 100.0
                                if peak_value > 0 else 0.0)

                equity_curve.append({
                    "date":         current_date.isoformat(),
                    "value":        round(portfolio_value, 2),
                    "drawdown_pct": round(drawdown_pct, 4),
                })

        # ── 6. Force-close any remaining open positions at last available price ──
        final_date = self.end_date
        for ticker, pos in list(open_positions.items()):
            # Find the last known price at or before end_date
            ticker_prices = prices.get(ticker, {})
            available_dates = [d for d in ticker_prices if d <= final_date + timedelta(days=5)]
            if not available_dates:
                exit_price = pos["entry_price"]
                exit_date = final_date
            else:
                exit_date = max(available_dates)
                exit_price = ticker_prices[exit_date]["close"] or pos["entry_price"]

            shares = pos["shares"]
            proceeds = shares * exit_price
            pnl = proceeds - pos["cost"]
            return_pct = pnl / pos["cost"] * 100.0 if pos["cost"] > 0 else 0.0
            cash += proceeds

            closed_trades.append({
                "ticker":      ticker,
                "entry_date":  pos["entry_date"].isoformat(),
                "exit_date":   exit_date.isoformat(),
                "entry_price": round(pos["entry_price"], 4),
                "exit_price":  round(exit_price, 4),
                "shares":      round(shares, 4),
                "return_pct":  round(return_pct, 4),
                "pnl":         round(pnl, 4),
                "exit_reason": EXIT_TIME,
                "hold_days":   (exit_date - pos["entry_date"]).days,
                "regime":      pos.get("regime"),
                "signal":      pos.get("signal"),
            })

        # ── 7. Compute metrics ────────────────────────────────────────────────
        final_value = cash  # all positions closed
        total_return = (final_value - self.initial_capital) / self.initial_capital

        backtest_days = (self.end_date - self.start_date).days
        cagr = _annualized_return(total_return, backtest_days)

        sharpe = _sharpe(daily_returns)
        sortino = _sortino(daily_returns)
        max_dd = _max_drawdown([e["value"] for e in equity_curve]) if equity_curve else 0.0

        # Trade stats
        total_trades = len(closed_trades)
        winning = [t for t in closed_trades if t["pnl"] > 0]
        losing  = [t for t in closed_trades if t["pnl"] <= 0]
        winning_trades = len(winning)
        losing_trades  = len(losing)

        win_rate = (winning_trades / total_trades * 100.0) if total_trades > 0 else 0.0

        gross_profit = sum(t["pnl"] for t in winning)
        gross_loss   = abs(sum(t["pnl"] for t in losing))
        profit_factor = gross_profit / gross_loss if gross_loss > 0 else (
            float("inf") if gross_profit > 0 else 0.0
        )

        avg_hold = (sum(t["hold_days"] for t in closed_trades) / total_trades
                    if total_trades > 0 else 0.0)

        # Return by regime
        regime_returns: dict[str, list[float]] = defaultdict(list)
        for t in closed_trades:
            if t.get("regime"):
                regime_returns[t["regime"]].append(t["return_pct"])

        return_by_regime = {
            regime: round(sum(rets) / len(rets), 4)
            for regime, rets in regime_returns.items()
        }

        # Monthly returns
        monthly_returns: dict[str, float] = {}
        monthly_start: dict[str, float] = {}
        for entry in equity_curve:
            month_key = entry["date"][:7]  # "YYYY-MM"
            if month_key not in monthly_start:
                monthly_start[month_key] = entry["value"]
            monthly_end_value = entry["value"]
            if monthly_start[month_key] > 0:
                monthly_returns[month_key] = round(
                    (monthly_end_value - monthly_start[month_key]) / monthly_start[month_key] * 100.0, 4
                )

        metrics = {
            "total_return_pct":  round(total_return * 100.0, 4),
            "cagr_pct":          round(cagr * 100.0, 4),
            "sharpe_ratio":      round(sharpe, 4),
            "sortino_ratio":     round(sortino, 4),
            "max_drawdown_pct":  round(max_dd, 4),
            "win_rate_pct":      round(win_rate, 4),
            "profit_factor":     round(profit_factor, 4) if math.isfinite(profit_factor) else None,
            "avg_hold_days":     round(avg_hold, 2),
            "total_trades":      total_trades,
            "winning_trades":    winning_trades,
            "losing_trades":     losing_trades,
            "gross_profit":      round(gross_profit, 2),
            "gross_loss":        round(gross_loss, 2),
            "final_value":       round(final_value, 2),
            "return_by_regime":  return_by_regime,
        }

        config = {
            "start_date":       self.start_date.isoformat(),
            "end_date":         self.end_date.isoformat(),
            "initial_capital":  self.initial_capital,
            "signal_filter":    self.signal_filter,
            "max_positions":    self.max_positions,
            "use_kelly":        self.use_kelly,
            "max_kelly_pct":    self.max_kelly_pct,
            "max_hold_days":    self.max_hold_days,
            "country":          self.country,
        }

        return {
            "config":          config,
            "metrics":         metrics,
            "equity_curve":    equity_curve,
            "trades":          closed_trades,
            "monthly_returns": monthly_returns,
        }
