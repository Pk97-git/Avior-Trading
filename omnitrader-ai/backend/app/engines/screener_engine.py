"""
engines/screener_engine.py
===========================
ScreenerEngine — filters the stock universe based on user-defined conditions.

Each condition = {"field": str, "operator": str, "value": any}

Supported fields (pulled from DB + computed):
  Technical:
    rsi_14, rsi_7, macd_hist, bb_position (0=at lower band, 1=at upper band),
    atr_pct (ATR as % of price), vol_ratio_20d (volume vs 20d avg),
    sma20_pct (% above/below SMA20), sma50_pct, sma200_pct,
    week52_high_pct (% below 52-week high), week52_low_pct (% above 52-week low),
    price_change_1d, price_change_5d, price_change_20d

  AI/Signal:
    ai_score (0-100), signal (STRONG_BUY/ACCUMULATE/HOLD/AVOID/DISTRIBUTION/SELL)

  Fundamental:
    pe_ratio, market_cap_cr (in crores for India), revenue_growth_pct,
    roe, roic, operating_margin, debt_to_equity, eps_surprise_pct

  Universe:
    sector, country (IN/US), name (text search)

Supported operators:
  Numeric: ">", "<", ">=", "<=", "=", "between" (value is [min, max])
  String:  "=", "in" (value is list), "contains" (for name/sector search)
"""
import logging
import math
from typing import Any

import numpy as np
import pandas as pd
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger(__name__)

# ── RSI helper ─────────────────────────────────────────────────────────────────

def _compute_rsi(series: pd.Series, period: int) -> float:
    """Compute RSI for a price series using EWM (Wilder smoothing)."""
    if len(series) < period + 1:
        return float("nan")
    delta = series.diff().dropna()
    gain = delta.clip(lower=0)
    loss = (-delta).clip(lower=0)
    avg_gain = gain.ewm(alpha=1 / period, adjust=False).mean().iloc[-1]
    avg_loss = loss.ewm(alpha=1 / period, adjust=False).mean().iloc[-1]
    if avg_loss == 0:
        return 100.0
    rs = avg_gain / avg_loss
    return round(100 - (100 / (1 + rs)), 2)


def _compute_macd_hist(series: pd.Series) -> float:
    """MACD histogram = MACD line - signal line (12/26/9)."""
    if len(series) < 26:
        return float("nan")
    ema12 = series.ewm(span=12, adjust=False).mean()
    ema26 = series.ewm(span=26, adjust=False).mean()
    macd_line = ema12 - ema26
    signal_line = macd_line.ewm(span=9, adjust=False).mean()
    hist = (macd_line - signal_line).iloc[-1]
    return round(float(hist), 4) if not math.isnan(float(hist)) else float("nan")


def _sma_pct(series: pd.Series, period: int) -> float:
    """% price is above/below its SMA."""
    if len(series) < period:
        return float("nan")
    sma = series.tail(period).mean()
    last = series.iloc[-1]
    if sma == 0:
        return float("nan")
    return round((last - sma) / sma * 100, 2)


class ScreenerEngine:
    """Filter the stock universe based on user-defined conditions."""

    def __init__(self, db: AsyncSession):
        self.db = db

    # ── Public entry point ────────────────────────────────────────────────────

    async def run(self, conditions: list[dict], limit: int = 50) -> dict:
        """
        Execute screening.

        1. Build base query joining stocks + latest ai_analysis + latest company_financials
        2. Compute technical fields from recent stock_prices (one bulk query)
        3. Apply each condition as a filter
        4. Return enriched results sorted by ai_score DESC
        """
        import time
        t0 = time.time()

        # Step 1 – base data from DB
        df = await self._get_base_data()
        total_scanned = len(df)

        if df.empty:
            return {
                "total_scanned": 0,
                "matches": 0,
                "results": [],
                "conditions_applied": len(conditions),
                "elapsed_ms": round((time.time() - t0) * 1000, 1),
            }

        # Step 2 – price-based technicals
        df = await self._add_price_technicals(df)

        # Step 3 – apply conditions
        df = self._apply_conditions(df, conditions)

        # Step 4 – sort by ai_score, limit, serialise
        df = df.sort_values("ai_score", ascending=False, na_position="last")
        df = df.head(limit)

        results = []
        for _, row in df.iterrows():
            record = {}
            for col in df.columns:
                val = row[col]
                if pd.isna(val) if not isinstance(val, str) else False:
                    record[col] = None
                else:
                    record[col] = val
            results.append(record)

        elapsed = round((time.time() - t0) * 1000, 1)
        return {
            "total_scanned": total_scanned,
            "matches": len(results),
            "results": results,
            "conditions_applied": len(conditions),
            "elapsed_ms": elapsed,
        }

    # ── Base data query ───────────────────────────────────────────────────────

    async def _get_base_data(self) -> pd.DataFrame:
        """
        Single query joining stocks + latest ai_analysis + latest company_financials.
        """
        query = text("""
            SELECT
                s.ticker,
                s.name,
                s.sector,
                s.country,
                a.final_score          AS ai_score,
                a.signal,
                a.technicals,
                f.pe_ratio,
                f.roe,
                f.roic,
                f.operating_margin,
                f.debt_to_equity,
                f.eps_surprise_pct,
                f.revenue,
                f.net_income,
                f.market_cap
            FROM stocks s
            LEFT JOIN LATERAL (
                SELECT *
                FROM ai_analysis
                WHERE ticker = s.ticker
                ORDER BY created_at DESC
                LIMIT 1
            ) a ON true
            LEFT JOIN LATERAL (
                SELECT *
                FROM company_financials
                WHERE ticker = s.ticker
                ORDER BY fiscal_date DESC
                LIMIT 1
            ) f ON true
        """)
        result = await self.db.execute(query)
        rows = result.fetchall()

        if not rows:
            return pd.DataFrame()

        records = []
        for row in rows:
            r = dict(row._mapping)

            # Flatten JSONB technicals if present
            tech = r.pop("technicals", None) or {}
            if isinstance(tech, dict):
                # Pull commonly stored technicals from JSONB
                for k in ("rsi_14", "rsi_7", "macd_hist", "bb_position",
                          "atr_pct", "vol_ratio_20d"):
                    if k not in r and k in tech:
                        r[k] = tech.get(k)

            # market_cap → market_cap_cr (INR crores, or raw USD millions)
            mc = r.pop("market_cap", None)
            if mc is not None:
                r["market_cap_cr"] = round(float(mc), 2)
            else:
                r["market_cap_cr"] = None

            # revenue_growth_pct placeholder (computed if historical data available)
            r.setdefault("revenue_growth_pct", None)

            records.append(r)

        df = pd.DataFrame(records)
        return df

    # ── Price technicals ──────────────────────────────────────────────────────

    async def _add_price_technicals(self, df: pd.DataFrame) -> pd.DataFrame:
        """
        Fetch all recent price data in ONE query, compute per-ticker using
        pandas groupby. This is the performance-critical path.
        """
        tickers = df["ticker"].tolist()
        if not tickers:
            return df

        price_query = text("""
            SELECT ticker, time, close, open, high, low, volume
            FROM stock_prices
            WHERE time >= NOW() - INTERVAL '260 days'
              AND ticker = ANY(:tickers)
            ORDER BY ticker, time ASC
        """)
        price_result = await self.db.execute(price_query, {"tickers": tickers})
        price_rows = price_result.fetchall()

        if not price_rows:
            logger.warning("No price data found for %d tickers", len(tickers))
            return df

        prices_df = pd.DataFrame(
            [dict(r._mapping) for r in price_rows],
            columns=["ticker", "time", "close", "open", "high", "low", "volume"],
        )
        prices_df["close"] = pd.to_numeric(prices_df["close"], errors="coerce")
        prices_df["high"]  = pd.to_numeric(prices_df["high"],  errors="coerce")
        prices_df["low"]   = pd.to_numeric(prices_df["low"],   errors="coerce")
        prices_df["volume"] = pd.to_numeric(prices_df["volume"], errors="coerce")
        prices_df = prices_df.dropna(subset=["close"])
        prices_df = prices_df.sort_values(["ticker", "time"])

        tech_records: dict[str, dict] = {}

        for ticker, grp in prices_df.groupby("ticker", sort=False):
            grp = grp.reset_index(drop=True)
            closes = grp["close"]
            highs  = grp["high"]
            lows   = grp["low"]
            vols   = grp["volume"]

            n = len(closes)
            last_price = float(closes.iloc[-1])

            rec: dict[str, Any] = {}

            # ── RSI ──────────────────────────────────────────────────────────
            rec["rsi_14"] = _compute_rsi(closes, 14)
            rec["rsi_7"]  = _compute_rsi(closes, 7)

            # ── MACD histogram ───────────────────────────────────────────────
            rec["macd_hist"] = _compute_macd_hist(closes)

            # ── SMA % ────────────────────────────────────────────────────────
            rec["sma20_pct"]  = _sma_pct(closes, 20)
            rec["sma50_pct"]  = _sma_pct(closes, 50)
            rec["sma200_pct"] = _sma_pct(closes, 200)

            # ── Price changes ────────────────────────────────────────────────
            if n >= 2:
                rec["price_change_1d"] = round((closes.iloc[-1] / closes.iloc[-2] - 1) * 100, 2)
            else:
                rec["price_change_1d"] = float("nan")

            if n >= 6:
                rec["price_change_5d"] = round((closes.iloc[-1] / closes.iloc[-6] - 1) * 100, 2)
            else:
                rec["price_change_5d"] = float("nan")

            if n >= 21:
                rec["price_change_20d"] = round((closes.iloc[-1] / closes.iloc[-21] - 1) * 100, 2)
            else:
                rec["price_change_20d"] = float("nan")

            # ── 52-week high/low ─────────────────────────────────────────────
            week52 = closes.tail(252)
            if len(week52) > 0:
                high52 = float(week52.max())
                low52  = float(week52.min())
                rec["week52_high_pct"] = round((last_price - high52) / high52 * 100, 2) if high52 else float("nan")
                rec["week52_low_pct"]  = round((last_price - low52)  / low52  * 100, 2) if low52  else float("nan")
            else:
                rec["week52_high_pct"] = float("nan")
                rec["week52_low_pct"]  = float("nan")

            # ── Volume ratio (vs 20-day avg) ─────────────────────────────────
            if len(vols) >= 21 and vols.iloc[-1] > 0:
                avg_vol_20 = float(vols.iloc[-21:-1].mean())
                rec["vol_ratio_20d"] = round(float(vols.iloc[-1]) / avg_vol_20, 2) if avg_vol_20 > 0 else float("nan")
            else:
                rec["vol_ratio_20d"] = float("nan")

            # ── ATR % ────────────────────────────────────────────────────────
            if len(highs) >= 15 and len(lows) >= 15:
                prev_closes = closes.shift(1)
                tr = pd.concat([
                    highs - lows,
                    (highs - prev_closes).abs(),
                    (lows  - prev_closes).abs(),
                ], axis=1).max(axis=1)
                atr = float(tr.tail(14).mean())
                rec["atr_pct"] = round(atr / last_price * 100, 2) if last_price else float("nan")
            else:
                rec["atr_pct"] = float("nan")

            # ── Bollinger band position ───────────────────────────────────────
            if n >= 20:
                sma20 = float(closes.tail(20).mean())
                std20 = float(closes.tail(20).std())
                upper = sma20 + 2 * std20
                lower = sma20 - 2 * std20
                band_range = upper - lower
                if band_range > 0:
                    rec["bb_position"] = round((last_price - lower) / band_range, 4)
                else:
                    rec["bb_position"] = float("nan")
            else:
                rec["bb_position"] = float("nan")

            tech_records[ticker] = rec

        # ── Merge technicals back into main df ───────────────────────────────
        tech_cols = [
            "rsi_14", "rsi_7", "macd_hist",
            "sma20_pct", "sma50_pct", "sma200_pct",
            "price_change_1d", "price_change_5d", "price_change_20d",
            "week52_high_pct", "week52_low_pct",
            "vol_ratio_20d", "atr_pct", "bb_position",
        ]

        for col in tech_cols:
            # Only override if not already populated from JSONB technicals
            if col not in df.columns:
                df[col] = float("nan")

        for col in tech_cols:
            df[col] = df["ticker"].map(
                lambda t, c=col: tech_records.get(t, {}).get(c, float("nan"))
            )

        return df

    # ── Condition application ──────────────────────────────────────────────────

    def _apply_conditions(self, df: pd.DataFrame, conditions: list[dict]) -> pd.DataFrame:
        """Apply all conditions with AND logic. Exclude rows with NaN for the queried field."""
        mask = pd.Series([True] * len(df), index=df.index)

        for cond in conditions:
            field    = cond.get("field", "")
            operator = cond.get("operator", "")
            value    = cond.get("value")

            if field not in df.columns:
                logger.debug("Screener: unknown field '%s' — skipping condition", field)
                continue

            col = df[field]

            # Determine if this is a numeric or string field
            is_numeric = pd.api.types.is_numeric_dtype(col)

            if operator == "between":
                if not isinstance(value, (list, tuple)) or len(value) != 2:
                    continue
                lo, hi = value
                cond_mask = col.between(float(lo), float(hi)) & col.notna()

            elif operator == ">":
                cond_mask = col.notna() & (col > float(value))

            elif operator == "<":
                cond_mask = col.notna() & (col < float(value))

            elif operator == ">=":
                cond_mask = col.notna() & (col >= float(value))

            elif operator == "<=":
                cond_mask = col.notna() & (col <= float(value))

            elif operator == "=":
                if is_numeric:
                    cond_mask = col.notna() & (col == float(value))
                else:
                    cond_mask = col.str.upper() == str(value).upper()

            elif operator == "in":
                if not isinstance(value, (list, tuple)):
                    value = [value]
                values_upper = [str(v).upper() for v in value]
                cond_mask = col.str.upper().isin(values_upper)

            elif operator == "contains":
                cond_mask = col.fillna("").str.contains(str(value), case=False, na=False)

            else:
                logger.warning("Screener: unknown operator '%s' — skipping", operator)
                continue

            mask = mask & cond_mask

        return df[mask].copy()
