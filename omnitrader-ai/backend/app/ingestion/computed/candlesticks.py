"""
ingestion/computed/candlesticks.py
====================================
CandlestickPatternService — detects 15 classic candlestick patterns from OHLC data.

Patterns detected (bullish/bearish):
  Reversal:     Doji, Hammer, Hanging Man, Shooting Star, Inverted Hammer
  Continuation: Bullish/Bearish Engulfing, Bullish/Bearish Harami
  Multi-candle: Morning Star, Evening Star, Three White Soldiers, Three Black Crows
  Special:      Tweezer Top, Tweezer Bottom

Each pattern returns {name, direction, strength} where:
  direction: "BULLISH" or "BEARISH"
  strength:  "STRONG" or "MODERATE"
"""
import logging
import math
from datetime import date, timedelta
from typing import Optional

import pandas as pd
from sqlalchemy import text
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import AsyncSessionLocal
from app.models.market_data import CandlestickPattern

logger = logging.getLogger(__name__)


def _body(o, c): return abs(c - o)
def _upper_shadow(o, c, h): return h - max(o, c)
def _lower_shadow(o, c, l): return min(o, c) - l
def _range(h, l): return h - l if h > l else float("nan")


def _detect_patterns(df: pd.DataFrame) -> list[dict]:
    """
    Detect candlestick patterns on the last 10 rows of OHLCV data.
    df must have columns: date, open, high, low, close, volume (sorted ascending).
    Returns list of {name, direction, strength} for the most recent candle.
    """
    if len(df) < 3:
        return []

    df = df.tail(10).reset_index(drop=True)
    patterns = []

    n = len(df) - 1  # index of the most recent candle
    o = df.loc[n, "open"];  h = df.loc[n, "high"]
    l = df.loc[n, "low"];   c = df.loc[n, "close"]
    body    = _body(o, c)
    rng     = _range(h, l)
    up_shad = _upper_shadow(o, c, h)
    lo_shad = _lower_shadow(o, c, l)
    is_bull = c > o

    if rng == 0 or math.isnan(rng):
        return []

    body_pct    = body / rng
    up_shad_pct = up_shad / rng
    lo_shad_pct = lo_shad / rng

    # Previous candles
    if n >= 1:
        o1 = df.loc[n-1, "open"]; c1 = df.loc[n-1, "close"]
        h1 = df.loc[n-1, "high"]; l1 = df.loc[n-1, "low"]
        body1 = _body(o1, c1)
    if n >= 2:
        o2 = df.loc[n-2, "open"]; c2 = df.loc[n-2, "close"]
        c_bull1 = c1 > o1  # prev candle bullish?

    # ── 1. Doji ───────────────────────────────────────────────────────────────
    if body_pct < 0.05 and rng > 0:
        patterns.append({"name": "Doji", "direction": "NEUTRAL", "strength": "MODERATE"})

    # ── 2. Hammer (bullish reversal at bottom) ────────────────────────────────
    if (lo_shad_pct > 0.60 and body_pct < 0.25 and up_shad_pct < 0.10
            and c > l + rng * 0.30):
        patterns.append({"name": "Hammer", "direction": "BULLISH", "strength": "STRONG"})

    # ── 3. Inverted Hammer ────────────────────────────────────────────────────
    if (up_shad_pct > 0.60 and body_pct < 0.25 and lo_shad_pct < 0.10):
        patterns.append({"name": "Inverted Hammer", "direction": "BULLISH", "strength": "MODERATE"})

    # ── 4. Hanging Man (bearish reversal at top) ──────────────────────────────
    if (lo_shad_pct > 0.60 and body_pct < 0.25 and up_shad_pct < 0.10
            and not is_bull):
        patterns.append({"name": "Hanging Man", "direction": "BEARISH", "strength": "STRONG"})

    # ── 5. Shooting Star ──────────────────────────────────────────────────────
    if (up_shad_pct > 0.60 and body_pct < 0.25 and lo_shad_pct < 0.10
            and not is_bull):
        patterns.append({"name": "Shooting Star", "direction": "BEARISH", "strength": "STRONG"})

    # ── 6. Bullish Engulfing ──────────────────────────────────────────────────
    if (n >= 1 and is_bull and not (c1 > o1)
            and c > o1 and o < c1):
        strength = "STRONG" if body > body1 * 1.5 else "MODERATE"
        patterns.append({"name": "Bullish Engulfing", "direction": "BULLISH", "strength": strength})

    # ── 7. Bearish Engulfing ──────────────────────────────────────────────────
    if (n >= 1 and not is_bull and c1 > o1
            and o > c1 and c < o1):
        strength = "STRONG" if body > body1 * 1.5 else "MODERATE"
        patterns.append({"name": "Bearish Engulfing", "direction": "BEARISH", "strength": strength})

    # ── 8. Bullish Harami ─────────────────────────────────────────────────────
    if (n >= 1 and is_bull and not (c1 > o1)
            and o > min(o1, c1) and c < max(o1, c1)
            and body < body1 * 0.5):
        patterns.append({"name": "Bullish Harami", "direction": "BULLISH", "strength": "MODERATE"})

    # ── 9. Bearish Harami ─────────────────────────────────────────────────────
    if (n >= 1 and not is_bull and c1 > o1
            and o < max(o1, c1) and c > min(o1, c1)
            and body < body1 * 0.5):
        patterns.append({"name": "Bearish Harami", "direction": "BEARISH", "strength": "MODERATE"})

    # ── 10. Morning Star (3-candle bullish reversal) ──────────────────────────
    if n >= 2:
        if (not (c2 > o2) and _body(o2, c2) / _range(h1, l1) > 1.5  # first: big bear
                and _body(o1, c1) < _body(o2, c2) * 0.4            # second: small body
                and is_bull and c > (o2 + c2) / 2):                  # third: bull closes above midpoint
            patterns.append({"name": "Morning Star", "direction": "BULLISH", "strength": "STRONG"})

    # ── 11. Evening Star (3-candle bearish reversal) ──────────────────────────
    if n >= 2:
        if ((c2 > o2) and _body(o2, c2) / max(_range(h1, l1), 0.001) > 1.5
                and _body(o1, c1) < _body(o2, c2) * 0.4
                and not is_bull and c < (o2 + c2) / 2):
            patterns.append({"name": "Evening Star", "direction": "BEARISH", "strength": "STRONG"})

    # ── 12. Three White Soldiers ──────────────────────────────────────────────
    if n >= 2:
        bulls = all(df.loc[i, "close"] > df.loc[i, "open"] for i in [n-2, n-1, n])
        rising = df.loc[n-1, "close"] > df.loc[n-2, "close"] and c > df.loc[n-1, "close"]
        if bulls and rising and body_pct > 0.5:
            patterns.append({"name": "Three White Soldiers", "direction": "BULLISH", "strength": "STRONG"})

    # ── 13. Three Black Crows ─────────────────────────────────────────────────
    if n >= 2:
        bears = all(df.loc[i, "close"] < df.loc[i, "open"] for i in [n-2, n-1, n])
        falling = df.loc[n-1, "close"] < df.loc[n-2, "close"] and c < df.loc[n-1, "close"]
        if bears and falling and body_pct > 0.5:
            patterns.append({"name": "Three Black Crows", "direction": "BEARISH", "strength": "STRONG"})

    # ── 14. Tweezer Bottom ────────────────────────────────────────────────────
    if n >= 1 and abs(l - l1) / max(rng, 0.001) < 0.02 and is_bull and not (c1 > o1):
        patterns.append({"name": "Tweezer Bottom", "direction": "BULLISH", "strength": "MODERATE"})

    # ── 15. Tweezer Top ───────────────────────────────────────────────────────
    if n >= 1 and abs(h - h1) / max(rng, 0.001) < 0.02 and not is_bull and c1 > o1:
        patterns.append({"name": "Tweezer Top", "direction": "BEARISH", "strength": "MODERATE"})

    return patterns


def _dominant_signal(patterns: list[dict]) -> tuple[str, str]:
    """Return (dominant_name, signal) from pattern list."""
    if not patterns:
        return None, "NEUTRAL"

    bull = [p for p in patterns if p["direction"] == "BULLISH"]
    bear = [p for p in patterns if p["direction"] == "BEARISH"]
    strong_bull = [p for p in bull if p["strength"] == "STRONG"]
    strong_bear = [p for p in bear if p["strength"] == "STRONG"]

    if strong_bull and not strong_bear:
        signal = "REVERSAL_UP" if any(p["name"] in ("Morning Star", "Bullish Engulfing", "Hammer") for p in strong_bull) else "BULLISH"
        return strong_bull[0]["name"], signal
    if strong_bear and not strong_bull:
        signal = "REVERSAL_DOWN" if any(p["name"] in ("Evening Star", "Bearish Engulfing", "Shooting Star") for p in strong_bear) else "BEARISH"
        return strong_bear[0]["name"], signal
    if bull and not bear:
        return bull[0]["name"], "BULLISH"
    if bear and not bull:
        return bear[0]["name"], "BEARISH"
    return patterns[0]["name"], "NEUTRAL"


class CandlestickPatternService:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def run_batch(self, tickers: list[str], start_date: date = None) -> dict:
        total = 0
        failed = []
        for ticker in tickers:
            try:
                n = await self._process_ticker(ticker, start_date)
                total += n
            except Exception as e:
                logger.warning("[Candles] %s: %s", ticker, e)
                failed.append(ticker)
        return {"rows": total, "failed": len(failed)}

    async def _process_ticker(self, ticker: str, start_date: date = None) -> int:
        lookback = (start_date - timedelta(days=30)) if start_date else None
        query = "SELECT time::date AS date, open, high, low, close, volume FROM stock_prices WHERE ticker = :t"
        params = {"t": ticker}
        if lookback:
            query += " AND time >= :lb"
            params["lb"] = lookback
        query += " ORDER BY time ASC"
        result = await self.db.execute(text(query), params)
        rows = result.fetchall()
        if len(rows) < 3:
            return 0

        df = pd.DataFrame(rows, columns=["date", "open", "high", "low", "close", "volume"])
        records = []

        if start_date:
            dates_to_process = [d for d in df["date"].tolist() if d >= start_date]
        else:
            dates_to_process = df["date"].tolist()

        for d in dates_to_process:
            idx = df[df["date"] == d].index
            if len(idx) == 0:
                continue
            i = idx[0]
            window = df.iloc[max(0, i-9):i+1]
            patterns = _detect_patterns(window)
            dominant, signal = _dominant_signal(patterns)
            records.append({
                "ticker":        ticker,
                "date":          d,
                "patterns":      patterns,
                "dominant":      dominant,
                "signal":        signal,
                "pattern_count": len(patterns),
            })

        if not records:
            return 0

        stmt = pg_insert(CandlestickPattern).values(records)
        stmt = stmt.on_conflict_do_update(
            constraint="uq_candle_ticker_date",
            set_={
                "patterns":      stmt.excluded.patterns,
                "dominant":      stmt.excluded.dominant,
                "signal":        stmt.excluded.signal,
                "pattern_count": stmt.excluded.pattern_count,
            },
        )
        await self.db.execute(stmt)
        await self.db.commit()
        return len(records)
