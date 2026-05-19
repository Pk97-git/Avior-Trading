"""
technicals.py
=============
Computes and stores pre-calculated technical indicators for all tickers
in the HIGH + MEDIUM equity universe, derived from stored stock_prices data.

Indicators computed per ticker per day:
  Trend:      SMA 20/50/200, EMA 9/21
  Momentum:   RSI 14, MACD (12/26/9 — line, signal, histogram)
  Volatility: ATR 14, Bollinger Bands (20, 2σ)
  Volume:     Volume ratio vs 20-day average
  Levels:     52-week high/low
  RS:         3-month return relative to SPX and Nifty

Only the LATEST date (or date range) is written per incremental run.
The initial load backfills all available dates from stored price history.
"""
import logging
import math
from datetime import date, timedelta
from typing import Optional

import pandas as pd
from sqlalchemy import select, text
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.market_data import StockTechnicals, StockPrice

logger = logging.getLogger(__name__)


def _ema(series: pd.Series, span: int) -> pd.Series:
    return series.ewm(span=span, adjust=False).mean()


def _rsi(close: pd.Series, period: int = 14) -> pd.Series:
    delta = close.diff()
    gain = delta.clip(lower=0)
    loss = -delta.clip(upper=0)
    avg_gain = gain.ewm(com=period - 1, adjust=False).mean()
    avg_loss = loss.ewm(com=period - 1, adjust=False).mean()
    rs = avg_gain / avg_loss.replace(0, float("nan"))
    return 100 - (100 / (1 + rs))


def _atr(high: pd.Series, low: pd.Series, close: pd.Series, period: int = 14) -> pd.Series:
    prev_close = close.shift(1)
    tr = pd.concat([
        high - low,
        (high - prev_close).abs(),
        (low - prev_close).abs(),
    ], axis=1).max(axis=1)
    return tr.ewm(com=period - 1, adjust=False).mean()


def _compute_technicals(df: pd.DataFrame) -> pd.DataFrame:
    """
    Given a DataFrame with columns [date, open, high, low, close, volume],
    sorted ascending by date, returns a DataFrame with all technical columns.
    """
    df = df.sort_values("date").reset_index(drop=True)
    c = df["close"]
    h = df["high"]
    l = df["low"]
    v = df["volume"].fillna(0)

    # ── Trend ──────────────────────────────────────────────────────────────────
    df["sma_20"]  = c.rolling(20).mean()
    df["sma_50"]  = c.rolling(50).mean()
    df["sma_200"] = c.rolling(200).mean()
    df["ema_9"]   = _ema(c, 9)
    df["ema_21"]  = _ema(c, 21)

    # ── Momentum ────────────────────────────────────────────────────────────────
    df["rsi_14"]     = _rsi(c, 14)
    ema12            = _ema(c, 12)
    ema26            = _ema(c, 26)
    df["macd"]       = ema12 - ema26
    df["macd_signal"] = _ema(df["macd"], 9)
    df["macd_hist"]  = df["macd"] - df["macd_signal"]

    # ── Volatility ──────────────────────────────────────────────────────────────
    df["atr_14"]  = _atr(h, l, c, 14)
    df["bb_mid"]  = c.rolling(20).mean()
    bb_std        = c.rolling(20).std()
    df["bb_upper"] = df["bb_mid"] + 2 * bb_std
    df["bb_lower"] = df["bb_mid"] - 2 * bb_std

    # ── Volume ──────────────────────────────────────────────────────────────────
    vol_20 = v.rolling(20).mean()
    df["vol_ratio"] = v / vol_20.replace(0, float("nan"))

    # ── Key levels ──────────────────────────────────────────────────────────────
    df["week_52_high"] = c.rolling(252).max()
    df["week_52_low"]  = c.rolling(252).min()

    # ── Mean Reversion Signals ──────────────────────────────────────────────
    # Price z-score vs 20-day mean
    rolling_std_20 = c.rolling(20).std()
    df["price_zscore_20d"] = (c - df["sma_20"]) / rolling_std_20.replace(0, float("nan"))

    # Bollinger Bandwidth (volatility measure, percent)
    df["bb_bandwidth"] = ((df["bb_upper"] - df["bb_lower"]) / df["bb_mid"].replace(0, float("nan"))) * 100

    # Bollinger Squeeze: bandwidth < 10th percentile of trailing 126 days
    bw_10th = df["bb_bandwidth"].rolling(126).quantile(0.10)
    df["bb_squeeze"] = df["bb_bandwidth"] < bw_10th

    # ── Fibonacci Levels (50-day swing high/low) ──────────────────────────
    df["fib_high_50d"] = c.rolling(50).max()
    df["fib_low_50d"]  = c.rolling(50).min()
    fib_range = df["fib_high_50d"] - df["fib_low_50d"]
    fib_range_safe = fib_range.replace(0, float("nan"))
    df["fib_236"] = df["fib_low_50d"] + 0.236 * fib_range
    df["fib_382"] = df["fib_low_50d"] + 0.382 * fib_range
    df["fib_500"] = df["fib_low_50d"] + 0.500 * fib_range
    df["fib_618"] = df["fib_low_50d"] + 0.618 * fib_range
    df["fib_pct_pos"] = (c - df["fib_low_50d"]) / fib_range_safe  # 0=at low, 1=at high

    return df


class TechnicalIndicatorService:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def _load_prices(self, ticker: str, start_date: Optional[date] = None) -> pd.DataFrame:
        """Load OHLCV from stock_prices for a single ticker."""
        query = """
            SELECT time::date AS date, open, high, low, close, volume
            FROM stock_prices
            WHERE ticker = :ticker
        """
        params = {"ticker": ticker}
        if start_date:
            # Need 252 rows of lookback before start_date for indicators to warm up
            lookback = start_date - timedelta(days=400)
            query += " AND time >= :lookback"
            params["lookback"] = lookback
        query += " ORDER BY time ASC"
        result = await self.db.execute(text(query), params)
        rows = result.fetchall()
        if not rows:
            return pd.DataFrame()
        return pd.DataFrame(rows, columns=["date", "open", "high", "low", "close", "volume"])

    async def _load_benchmark(self, ticker: str) -> pd.Series:
        """Load close prices for a benchmark index as a Series indexed by date."""
        result = await self.db.execute(
            text("SELECT time::date AS date, close FROM stock_prices WHERE ticker = :t ORDER BY time ASC"),
            {"t": ticker},
        )
        rows = result.fetchall()
        if not rows:
            return pd.Series(dtype=float)
        df = pd.DataFrame(rows, columns=["date", "close"])
        return df.set_index("date")["close"]

    async def _load_intraday_vwap(self, ticker: str, start_date: date = None) -> pd.Series:
        """Compute daily VWAP for ticker from intraday_prices. Returns Series indexed by date."""
        query = """
            SELECT time::date AS dt,
                   SUM(close * COALESCE(volume, 0)) / NULLIF(SUM(COALESCE(volume, 0)), 0) AS vwap
            FROM intraday_prices
            WHERE ticker = :ticker AND close IS NOT NULL
        """
        params = {"ticker": ticker}
        if start_date:
            lookback = start_date - timedelta(days=10)
            query += " AND time >= :lb"
            params["lb"] = lookback
        query += " GROUP BY dt ORDER BY dt ASC"
        result = await self.db.execute(text(query), params)
        rows = result.fetchall()
        if not rows:
            return pd.Series(dtype=float)
        df = pd.DataFrame(rows, columns=["dt", "vwap"])
        return df.set_index("dt")["vwap"]

    async def compute_and_store(
        self,
        ticker: str,
        start_date: Optional[date] = None,
        spx_closes: Optional[pd.Series] = None,
        nsei_closes: Optional[pd.Series] = None,
    ) -> int:
        """
        Compute technical indicators for a ticker and upsert into stock_technicals.
        Returns number of rows written.
        """
        prices = await self._load_prices(ticker, start_date)
        if len(prices) < 30:
            return 0

        df = _compute_technicals(prices)

        # If start_date supplied, filter to only write rows >= start_date
        if start_date:
            df = df[df["date"] >= start_date]

        if df.empty:
            return 0

        # ── Relative Strength ─────────────────────────────────────────────────
        is_india = ticker.endswith(".NS") or ticker.endswith(".BO")
        benchmark = nsei_closes if is_india else spx_closes
        bench_col = "rs_vs_nsei" if is_india else "rs_vs_spx"

        def _rs(row_date, close_val, bench: pd.Series) -> Optional[float]:
            if bench is None or bench.empty:
                return None
            try:
                d = row_date
                d_ago = d - timedelta(days=90)
                if d not in bench.index or d_ago not in bench.index:
                    # Find nearest
                    bench_sorted = bench.index.tolist()
                    idx_now = min(range(len(bench_sorted)), key=lambda i: abs((bench_sorted[i] - d).days))
                    idx_ago = min(range(len(bench_sorted)), key=lambda i: abs((bench_sorted[i] - d_ago).days))
                    b_now = bench.iloc[idx_now]
                    b_ago = bench.iloc[idx_ago]
                else:
                    b_now = bench[d]
                    b_ago = bench[d_ago]
                if b_ago == 0:
                    return None
                bench_ret = (b_now - b_ago) / b_ago
                if bench_ret == 0:
                    return None
                stock_ret = (close_val - prices.set_index("date").loc[
                    min(prices["date"].tolist(), key=lambda x: abs((x - d_ago).days)), "close"
                ]) / prices.set_index("date").loc[
                    min(prices["date"].tolist(), key=lambda x: abs((x - d_ago).days)), "close"
                ]
                return float(stock_ret / bench_ret)
            except Exception:
                return None

        # Build records
        records = []
        price_indexed = prices.set_index("date")["close"]
        for _, row in df.iterrows():
            def _f(v):
                if v is None or (isinstance(v, float) and math.isnan(v)):
                    return None
                return float(v)

            # Simple RS: 63-day (≈3-month) return ratio
            rs_val = None
            if benchmark is not None and not benchmark.empty:
                try:
                    d = row["date"]
                    d_ago = d - timedelta(days=63)
                    # find closest dates
                    p_dates = sorted(price_indexed.index.tolist())
                    b_dates = sorted(benchmark.index.tolist())

                    def closest(dates_list, target):
                        return min(dates_list, key=lambda x: abs((x - target).days), default=None)

                    p_now_date = closest(p_dates, d)
                    p_ago_date = closest(p_dates, d_ago)
                    b_now_date = closest(b_dates, d)
                    b_ago_date = closest(b_dates, d_ago)

                    if all(x is not None for x in [p_now_date, p_ago_date, b_now_date, b_ago_date]):
                        p_ret = (price_indexed[p_now_date] - price_indexed[p_ago_date]) / price_indexed[p_ago_date]
                        b_ret = (benchmark[b_now_date] - benchmark[b_ago_date]) / benchmark[b_ago_date]
                        if b_ret != 0:
                            rs_val = float(p_ret / b_ret)
                except Exception:
                    pass

            rec = {
                "ticker":       ticker,
                "date":         row["date"],
                "sma_20":       _f(row.get("sma_20")),
                "sma_50":       _f(row.get("sma_50")),
                "sma_200":      _f(row.get("sma_200")),
                "ema_9":        _f(row.get("ema_9")),
                "ema_21":       _f(row.get("ema_21")),
                "rsi_14":       _f(row.get("rsi_14")),
                "macd":         _f(row.get("macd")),
                "macd_signal":  _f(row.get("macd_signal")),
                "macd_hist":    _f(row.get("macd_hist")),
                "atr_14":       _f(row.get("atr_14")),
                "bb_upper":     _f(row.get("bb_upper")),
                "bb_lower":     _f(row.get("bb_lower")),
                "bb_mid":       _f(row.get("bb_mid")),
                "vol_ratio":    _f(row.get("vol_ratio")),
                "week_52_high": _f(row.get("week_52_high")),
                "week_52_low":  _f(row.get("week_52_low")),
                "rs_vs_spx":         rs_val if not is_india else None,
                "rs_vs_nsei":        rs_val if is_india else None,
                "vwap":              None,  # populated separately via _load_intraday_vwap
                "bb_bandwidth":      _f(row.get("bb_bandwidth")),
                "bb_squeeze":        bool(row.get("bb_squeeze")) if row.get("bb_squeeze") is not None and not (isinstance(row.get("bb_squeeze"), float) and math.isnan(row.get("bb_squeeze"))) else None,
                "price_zscore_20d":  _f(row.get("price_zscore_20d")),
                "fib_high_50d":      _f(row.get("fib_high_50d")),
                "fib_low_50d":       _f(row.get("fib_low_50d")),
                "fib_236":           _f(row.get("fib_236")),
                "fib_382":           _f(row.get("fib_382")),
                "fib_500":           _f(row.get("fib_500")),
                "fib_618":           _f(row.get("fib_618")),
                "fib_pct_pos":       _f(row.get("fib_pct_pos")),
            }
            records.append(rec)

        if not records:
            return 0

        # Batch upsert
        stmt = pg_insert(StockTechnicals).values(records)
        stmt = stmt.on_conflict_do_update(
            constraint="uq_stock_technicals_ticker_date",
            set_={c: stmt.excluded[c] for c in records[0] if c not in ("ticker", "date")},
        )
        await self.db.execute(stmt)
        await self.db.commit()

        # Populate VWAP from intraday data (separate pass — data may not exist yet)
        try:
            vwap_series = await self._load_intraday_vwap(ticker, start_date)
            if not vwap_series.empty:
                for rec in records:
                    d = rec["date"]
                    if d in vwap_series.index:
                        rec["vwap"] = float(vwap_series[d])
                # Re-upsert only rows that got VWAP data
                vwap_records = [r for r in records if r.get("vwap") is not None]
                if vwap_records:
                    stmt2 = pg_insert(StockTechnicals).values(vwap_records)
                    stmt2 = stmt2.on_conflict_do_update(
                        constraint="uq_stock_technicals_ticker_date",
                        set_={"vwap": stmt2.excluded.vwap},
                    )
                    await self.db.execute(stmt2)
                    await self.db.commit()
        except Exception as e:
            logger.debug("[Technicals] VWAP update for %s: %s", ticker, e)

        return len(records)

    async def run_batch(
        self,
        tickers: list[str],
        start_date: Optional[date] = None,
    ) -> dict:
        """
        Run compute_and_store for a list of tickers.
        Loads SPX and Nifty benchmarks once and passes to each ticker.
        """
        # Load benchmarks once
        spx_closes = await self._load_benchmark("^GSPC")
        nsei_closes = await self._load_benchmark("^NSEI")

        total_rows = 0
        failed = []
        for ticker in tickers:
            try:
                n = await self.compute_and_store(
                    ticker,
                    start_date=start_date,
                    spx_closes=spx_closes,
                    nsei_closes=nsei_closes,
                )
                total_rows += n
            except Exception as e:
                logger.error("[Technicals] %s: %s", ticker, e)
                failed.append(ticker)

        return {"tickers": len(tickers), "rows_written": total_rows, "failed": len(failed)}
