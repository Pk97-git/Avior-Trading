"""
engines/pattern_backtest.py
============================
PatternBacktestEngine — tests how well a specific candlestick pattern
has performed historically on a given ticker.

For each detected occurrence of the pattern in the historical data:
  Entry  : open of candle N+1 (next day after detection)
  Stop   : pattern low - 0.5×ATR (for bullish) or pattern high + 0.5×ATR (bearish)
  Target : entry + 2×risk (2:1 risk/reward)
  Timeout: exit at close of day +10 if neither stop nor target hit

Metrics computed:
  win_rate           : % of trades that hit target before stop
  avg_return_pct     : mean % return across all trades
  avg_win_pct        : mean return on winning trades
  avg_loss_pct       : mean return on losing trades
  profit_factor      : gross wins / gross losses
  max_drawdown_pct   : max portfolio drawdown during test
  sharpe_ratio       : annualised (√252 × mean_daily / std_daily)
  total_trades       : number of pattern occurrences found
  equity_curve       : list of {date, value} for charting
  trade_list         : list of individual trades with entry/exit/pnl
"""
from __future__ import annotations

import asyncio
import logging
import math
from collections import defaultdict
from datetime import datetime
from typing import Optional

import pandas as pd

logger = logging.getLogger(__name__)

# ── Transaction cost constants ─────────────────────────────────────────────────

INDIA_STT_PCT          = 0.001       # 0.10% buy-side only (delivery)
INDIA_BROKERAGE_PCT    = 0.0003      # 0.03% per leg
INDIA_BROKERAGE_CAP    = 20.0        # ₹20 cap per order
INDIA_EXCHANGE_PCT     = 0.0000345   # NSE transaction charge per leg
INDIA_GST_ON_BROKERAGE = 0.18        # 18% GST on brokerage
INDIA_STAMP_DUTY_PCT   = 0.00015     # 0.015% buy-side
INDIA_SEBI_PCT         = 0.000001    # SEBI charge per leg

US_SEC_FEE_PCT         = 0.0000278   # on sells only

# ── Trade timeout window ───────────────────────────────────────────────────────

TRADE_TIMEOUT_DAYS = 10
INITIAL_PORTFOLIO  = 100_000.0


def _compute_trade_cost(value: float, side: str, country: str) -> float:
    """
    Return total transaction cost in currency units for a trade.
    value = trade_value (price × shares)
    side  = "BUY" or "SELL"
    """
    if country == "IN":
        brokerage = min(value * INDIA_BROKERAGE_PCT, INDIA_BROKERAGE_CAP)
        gst       = brokerage * INDIA_GST_ON_BROKERAGE
        exchange  = value * INDIA_EXCHANGE_PCT
        sebi      = value * INDIA_SEBI_PCT
        stt       = value * INDIA_STT_PCT if side == "BUY" else 0.0
        stamp     = value * INDIA_STAMP_DUTY_PCT if side == "BUY" else 0.0
        return brokerage + gst + exchange + sebi + stt + stamp
    else:  # US
        sec_fee = value * US_SEC_FEE_PCT if side == "SELL" else 0.0
        return sec_fee


def _compute_atr14(df: pd.DataFrame) -> pd.Series:
    """
    Compute ATR-14 using EWM of True Range.
    TR = max(high-low, |high-prev_close|, |low-prev_close|)
    Returns a Series aligned to df.index.
    """
    high  = df["High"] if "High" in df.columns else df["high"]
    low   = df["Low"]  if "Low"  in df.columns else df["low"]
    close = df["Close"] if "Close" in df.columns else df["close"]

    prev_close = close.shift(1)
    tr1 = high - low
    tr2 = (high - prev_close).abs()
    tr3 = (low  - prev_close).abs()
    true_range = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)
    atr = true_range.ewm(span=14, adjust=False).mean()
    return atr


def _sharpe(trade_returns: list[float]) -> float:
    """Annualised Sharpe from a list of trade-level returns (not daily)."""
    if len(trade_returns) < 3:
        return 0.0
    n = len(trade_returns)
    mean = sum(trade_returns) / n
    var = sum((r - mean) ** 2 for r in trade_returns) / max(n - 1, 1)
    std = math.sqrt(var)
    # Scale to daily approximation: assume average hold ~5 days
    daily_mean = mean / 5.0
    daily_std  = std  / math.sqrt(5.0)
    return (daily_mean / daily_std) * math.sqrt(252) if daily_std > 0 else 0.0


def _max_drawdown(equity: list[float]) -> float:
    """Return max drawdown as a negative percentage (e.g. -20.5)."""
    if len(equity) < 2:
        return 0.0
    peak   = equity[0]
    max_dd = 0.0
    for v in equity:
        if v > peak:
            peak = v
        dd = (v - peak) / peak if peak > 0 else 0.0
        if dd < max_dd:
            max_dd = dd
    return max_dd * 100.0


class PatternBacktestEngine:
    """
    Backtest a single candlestick pattern code on a historical OHLCV DataFrame.

    Parameters
    ----------
    df           : OHLCV DataFrame with a datetime index.  Columns may be
                   title-cased (Open/High/Low/Close/Volume) or lower-cased.
    pattern_code : e.g. "BULLISH_ENGULFING"
    country      : "IN" or "US" for transaction cost model
    ticker       : optional ticker symbol for the result dict
    """

    def __init__(
        self,
        df: pd.DataFrame,
        pattern_code: str,
        country: str = "IN",
        ticker: str = "",
    ):
        self.df           = df.copy()
        self.pattern_code = pattern_code.upper()
        self.country      = country.upper()
        self.ticker       = ticker

        # Normalise column names to title-case so the rest of the code is uniform
        rename_map = {c: c.title() for c in self.df.columns if c.lower() in
                      ("open", "high", "low", "close", "volume", "adj close")}
        self.df.rename(columns=rename_map, inplace=True)

        # Flatten multi-level columns (yfinance >= 0.2 quirk)
        if isinstance(self.df.columns, pd.MultiIndex):
            self.df.columns = self.df.columns.get_level_values(0)

        # Ensure datetime index
        if not isinstance(self.df.index, pd.DatetimeIndex):
            self.df.index = pd.to_datetime(self.df.index)

        self.df.sort_index(inplace=True)

    # ── Helpers ────────────────────────────────────────────────────────────────

    def _normalise_df_for_engine(self) -> pd.DataFrame:
        """Return a lowercase-column copy for CandlestickPatternEngine."""
        col_map = {
            "Open":  "open",
            "High":  "high",
            "Low":   "low",
            "Close": "close",
            "Volume": "volume",
        }
        out = self.df.rename(columns=col_map)
        return out

    # ── Main ───────────────────────────────────────────────────────────────────

    async def run(self) -> dict:
        """
        1. Import CandlestickPatternEngine from app.engines.candlestick_patterns
        2. Run detect_all(lookback=len(df)) to get all historical pattern matches
        3. For each match, simulate a trade with ATR-based stop/target
        4. Compute all metrics
        5. Return result dict
        """
        # Lazy import to avoid circular dependencies
        from app.engines.candlestick_patterns import (
            CandlestickPatternEngine,
            PatternBias,
        )

        if len(self.df) < 30:
            return self._empty_result("Insufficient data (need at least 30 candles)")

        # ── Detect all historical occurrences ─────────────────────────────────
        engine_df = self._normalise_df_for_engine()
        pattern_engine = CandlestickPatternEngine(engine_df)

        loop = asyncio.get_event_loop()
        all_matches = await loop.run_in_executor(
            None, lambda: pattern_engine.detect_all(lookback=len(self.df))
        )

        # Filter to the requested pattern code
        pattern_matches = [
            m for m in all_matches
            if m.get("code", "").upper() == self.pattern_code
        ]

        if not pattern_matches:
            return self._empty_result(f"No occurrences of {self.pattern_code} found")

        # Determine expected bias from pattern code prefix
        is_bullish = self.pattern_code.startswith("BULLISH") or any(
            kw in self.pattern_code
            for kw in ("HAMMER", "MORNING", "SOLDIER", "BOTTOM", "INVERSE", "INVERTED")
        )
        is_bearish = self.pattern_code.startswith("BEARISH") or any(
            kw in self.pattern_code
            for kw in ("HANGING", "SHOOTING", "EVENING", "CROW", "TOP")
        )

        # Use bias field from the match if available
        atr_series = _compute_atr14(self.df)
        df_index   = self.df.index
        n_rows     = len(self.df)

        trade_list: list[dict]   = []
        equity_curve: list[dict] = []
        portfolio_value          = INITIAL_PORTFOLIO
        portfolio_peak           = INITIAL_PORTFOLIO

        # ── Simulate each trade ────────────────────────────────────────────────
        for match in pattern_matches:
            # candle_index = 0 means the most-recent candle in detect_all's context.
            # We need the absolute position in self.df.
            # detect_all should return either candle_index (0 = most recent) or
            # an absolute index.  We handle both cases.
            raw_ci = match.get("candle_index", 0)

            # Convert "0 = most recent" convention to absolute position
            abs_idx = n_rows - 1 - raw_ci

            # We need at least one candle after detection for entry
            if abs_idx < 0 or abs_idx >= n_rows - 1:
                continue

            entry_abs_idx = abs_idx + 1  # next candle

            try:
                pattern_candle_row = self.df.iloc[abs_idx]
                entry_candle_row   = self.df.iloc[entry_abs_idx]
                entry_date_ts      = df_index[entry_abs_idx]
                entry_price        = float(entry_candle_row["Open"])
                pattern_low        = float(pattern_candle_row["Low"])
                pattern_high       = float(pattern_candle_row["High"])
                atr_val            = float(atr_series.iloc[abs_idx])
            except (KeyError, IndexError, TypeError, ValueError) as exc:
                logger.debug("Pattern backtest: skipping match %s — %s", match, exc)
                continue

            if entry_price <= 0 or atr_val <= 0 or math.isnan(atr_val):
                continue

            # ── Determine trade direction from match bias ──────────────────────
            match_bias = match.get("bias", "").upper()
            if match_bias in ("BULLISH",):
                trade_is_bullish = True
            elif match_bias in ("BEARISH",):
                trade_is_bullish = False
            else:
                trade_is_bullish = is_bullish

            # ── Stop / target ──────────────────────────────────────────────────
            if trade_is_bullish:
                stop_price   = pattern_low  - 0.5 * atr_val
                risk         = entry_price - stop_price
                target_price = entry_price + 2.0 * risk
            else:
                stop_price   = pattern_high + 0.5 * atr_val
                risk         = stop_price   - entry_price
                target_price = entry_price  - 2.0 * risk

            if risk <= 0:
                continue

            # ── Simulate day by day ────────────────────────────────────────────
            result_label = "TIMEOUT"
            exit_abs_idx = min(entry_abs_idx + TRADE_TIMEOUT_DAYS, n_rows - 1)
            exit_price   = float(self.df.iloc[exit_abs_idx]["Close"])

            for day_idx in range(entry_abs_idx, exit_abs_idx + 1):
                try:
                    day_row   = self.df.iloc[day_idx]
                    day_high  = float(day_row["High"])
                    day_low   = float(day_row["Low"])
                    day_close = float(day_row["Close"])
                except (KeyError, IndexError, TypeError, ValueError):
                    continue

                if trade_is_bullish:
                    if day_low <= stop_price:
                        result_label = "LOSS"
                        exit_price   = stop_price
                        exit_abs_idx = day_idx
                        break
                    if day_high >= target_price:
                        result_label = "WIN"
                        exit_price   = target_price
                        exit_abs_idx = day_idx
                        break
                else:
                    if day_high >= stop_price:
                        result_label = "LOSS"
                        exit_price   = stop_price
                        exit_abs_idx = day_idx
                        break
                    if day_low <= target_price:
                        result_label = "WIN"
                        exit_price   = target_price
                        exit_abs_idx = day_idx
                        break
                exit_price = day_close  # carry forward close in case of timeout

            # ── Apply transaction costs ────────────────────────────────────────
            trade_value_entry = entry_price * 1.0   # normalised per unit
            trade_value_exit  = exit_price  * 1.0

            cost_entry = _compute_trade_cost(trade_value_entry, "BUY",  self.country)
            cost_exit  = _compute_trade_cost(trade_value_exit,  "SELL", self.country)
            total_cost_pct = (cost_entry + cost_exit) / entry_price if entry_price > 0 else 0.0

            if trade_is_bullish:
                raw_pnl_pct = (exit_price - entry_price) / entry_price * 100.0
            else:
                raw_pnl_pct = (entry_price - exit_price) / entry_price * 100.0

            pnl_pct = raw_pnl_pct - total_cost_pct * 100.0

            exit_date_ts = df_index[exit_abs_idx]

            trade_list.append({
                "entry_date":   entry_date_ts.strftime("%Y-%m-%d"),
                "exit_date":    exit_date_ts.strftime("%Y-%m-%d"),
                "entry_price":  round(entry_price,  4),
                "exit_price":   round(exit_price,   4),
                "stop_price":   round(stop_price,   4),
                "target_price": round(target_price, 4),
                "pnl_pct":      round(pnl_pct,      4),
                "result":       result_label,
                "candle_index": raw_ci,
            })

            # ── Update equity curve (one entry per trade close) ────────────────
            portfolio_value = portfolio_value * (1.0 + pnl_pct / 100.0)
            if portfolio_value > portfolio_peak:
                portfolio_peak = portfolio_value
            equity_curve.append({
                "date":  exit_date_ts.strftime("%Y-%m-%d"),
                "value": round(portfolio_value, 2),
            })

        # ── Sort trade list chronologically ───────────────────────────────────
        trade_list.sort(key=lambda t: t["entry_date"])
        equity_curve.sort(key=lambda e: e["date"])

        if not trade_list:
            return self._empty_result(f"No simulatable trades for {self.pattern_code}")

        # ── Compute metrics ────────────────────────────────────────────────────
        total_trades = len(trade_list)
        wins   = [t for t in trade_list if t["result"] == "WIN"]
        losses = [t for t in trade_list if t["result"] != "WIN"]

        win_rate     = len(wins) / total_trades if total_trades > 0 else 0.0
        all_returns  = [t["pnl_pct"] for t in trade_list]
        win_returns  = [t["pnl_pct"] for t in wins]
        loss_returns = [t["pnl_pct"] for t in losses]

        avg_return_pct = sum(all_returns)  / len(all_returns)  if all_returns  else 0.0
        avg_win_pct    = sum(win_returns)  / len(win_returns)  if win_returns  else 0.0
        avg_loss_pct   = sum(loss_returns) / len(loss_returns) if loss_returns else 0.0

        gross_wins   = sum(r for r in all_returns if r > 0)
        gross_losses = abs(sum(r for r in all_returns if r <= 0))
        profit_factor = (
            round(gross_wins / gross_losses, 4)
            if gross_losses > 0
            else (float("inf") if gross_wins > 0 else 0.0)
        )

        equity_values    = [INITIAL_PORTFOLIO] + [e["value"] for e in equity_curve]
        max_drawdown_pct = _max_drawdown(equity_values)
        sharpe_ratio     = _sharpe(all_returns)
        expectancy_pct   = win_rate * avg_win_pct + (1.0 - win_rate) * avg_loss_pct

        # ── Monthly returns ────────────────────────────────────────────────────
        monthly_returns: dict[str, float] = {}
        monthly_groups: dict[str, list[float]] = defaultdict(list)

        for trade in trade_list:
            ym = trade["exit_date"][:7]   # "YYYY-MM"
            monthly_groups[ym].append(trade["pnl_pct"])

        for ym, returns in monthly_groups.items():
            monthly_returns[ym] = round(sum(returns) / len(returns), 4)

        # ── Date range ────────────────────────────────────────────────────────
        date_start = self.df.index[0].strftime("%Y-%m-%d")
        date_end   = self.df.index[-1].strftime("%Y-%m-%d")

        # ── Pattern metadata ──────────────────────────────────────────────────
        pattern_name = self.pattern_code.replace("_", " ").title()
        # Try to get the human name from the match list
        if pattern_matches:
            meta_name = pattern_matches[0].get("name") or pattern_name
        else:
            meta_name = pattern_name

        return {
            "pattern_code":      self.pattern_code,
            "pattern_name":      meta_name,
            "ticker":            self.ticker,
            "date_range":        {"start": date_start, "end": date_end},
            "total_trades":      total_trades,
            "win_rate":          round(win_rate, 4),
            "avg_return_pct":    round(avg_return_pct, 4),
            "avg_win_pct":       round(avg_win_pct, 4),
            "avg_loss_pct":      round(avg_loss_pct, 4),
            "profit_factor":     profit_factor,
            "max_drawdown_pct":  round(max_drawdown_pct, 4),
            "sharpe_ratio":      round(sharpe_ratio, 4),
            "expectancy_pct":    round(expectancy_pct, 4),
            "equity_curve":      equity_curve,
            "trade_list":        trade_list,
            "monthly_returns":   monthly_returns,
        }

    # ── Fallback ───────────────────────────────────────────────────────────────

    def _empty_result(self, reason: str = "") -> dict:
        date_start = self.df.index[0].strftime("%Y-%m-%d")  if len(self.df) > 0 else ""
        date_end   = self.df.index[-1].strftime("%Y-%m-%d") if len(self.df) > 0 else ""

        logger.info(
            "[PatternBacktest] %s / %s — empty result: %s",
            self.ticker, self.pattern_code, reason,
        )

        return {
            "pattern_code":     self.pattern_code,
            "pattern_name":     self.pattern_code.replace("_", " ").title(),
            "ticker":           self.ticker,
            "date_range":       {"start": date_start, "end": date_end},
            "total_trades":     0,
            "win_rate":         0.0,
            "avg_return_pct":   0.0,
            "avg_win_pct":      0.0,
            "avg_loss_pct":     0.0,
            "profit_factor":    0.0,
            "max_drawdown_pct": 0.0,
            "sharpe_ratio":     0.0,
            "expectancy_pct":   0.0,
            "equity_curve":     [],
            "trade_list":       [],
            "monthly_returns":  {},
            "note":             reason,
        }
