from typing import Optional, List, Dict, Tuple
"""
agents/sizing.py
================
Volatility-Based Position Sizing with Half-Kelly Criterion

Inputs:
  - calibrated_prob:  win probability from CalibrationEngine
  - final_score:      raw conviction score (0-100)
  - ticker:           to compute ATR-based volatility from stock_prices

Kelly formula (Half-Kelly for safety):
  edge  = calibrated_prob - (1 - calibrated_prob)     # expected edge
  odds  = upside / downside (from technical agent targets; defaults to 1.5)
  f     = (edge * odds - loss_prob) / odds
  half_f = f * 0.5
  max_position = min(half_f, 0.20)  # hard cap at 20% of portfolio

Returns:
    {
        "kelly_fraction":    float,   # 0.0–0.20
        "max_position_pct":  float,   # as percentage (e.g. 5.2)
        "atr_14":            float,   # 14-day ATR in price units
        "volatility_note":   str,
    }
"""
import logging
from datetime import datetime, timedelta, timezone

from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import text

logger = logging.getLogger(__name__)

MAX_KELLY = 0.20   # Never size > 20% of portfolio in a single position


def _compute_atr(highs: list[float], lows: list[float], closes: list[float], period: int = 14) -> Optional[float]:
    if len(closes) < period + 1:
        return None
    trs = []
    for i in range(1, len(closes)):
        tr = max(
            highs[i] - lows[i],
            abs(highs[i] - closes[i-1]),
            abs(lows[i]  - closes[i-1]),
        )
        trs.append(tr)
    return sum(trs[-period:]) / period


class SizingEngine:
    def __init__(self, db: AsyncSession, ticker: str):
        self.db = db
        self.ticker = ticker.upper()

    async def compute(
        self,
        calibrated_prob: float,
        final_score: int,
        upside_downside_ratio: float = 1.5,  # default if no technical targets
    ) -> dict:
        try:
            atr = await self._compute_atr_from_db()
            current_price = await self._latest_close()

            # ATR as fraction of price (normalised volatility)
            atr_ratio = (atr / current_price) if (atr and current_price and current_price > 0) else 0.02

            # Half-Kelly
            p   = max(0.01, min(0.99, calibrated_prob))
            q   = 1 - p
            r   = max(1.0, upside_downside_ratio)
            kelly = (p * r - q) / r
            half_kelly = kelly * 0.5

            # Volatility dampening: high ATR (volatile stock) → smaller position
            # ATR > 3% of price → halve Kelly
            vol_dampener = 1.0
            if atr_ratio > 0.04:
                vol_dampener = 0.5
            elif atr_ratio > 0.02:
                vol_dampener = 0.75

            final_fraction = max(0.0, min(MAX_KELLY, half_kelly * vol_dampener))

            # Score-based sanity gate: don't size at all if score < 55
            if final_score < 55:
                final_fraction = 0.0

            volatility_note = (
                f"14d ATR = {atr:.2f} ({atr_ratio*100:.1f}% of price). "
                f"Kelly={kelly:.1%} → Half-Kelly={half_kelly:.1%} → "
                f"Vol-adjusted={final_fraction:.1%}"
            )

            # ATR-based trade levels (2×ATR stop, 6×ATR target = 3:1 R:R)
            stop_loss   = round(current_price - 2 * atr, 4) if (atr and current_price) else None
            take_profit = round(current_price + 6 * atr, 4) if (atr and current_price) else None

            return {
                "kelly_fraction":   round(final_fraction, 4),
                "max_position_pct": round(final_fraction * 100, 2),
                "atr_14":           round(atr, 4) if atr else None,
                "entry_price":      round(current_price, 4) if current_price else None,
                "stop_loss":        stop_loss,
                "take_profit":      take_profit,
                "volatility_note":  volatility_note,
            }

        except Exception as e:
            logger.error("SizingEngine failed for %s: %s", self.ticker, e)
            return {
                "kelly_fraction":   0.0,
                "max_position_pct": 0.0,
                "atr_14":           None,
                "entry_price":      None,
                "stop_loss":        None,
                "take_profit":      None,
                "volatility_note":  "Sizing unavailable.",
            }

    async def _compute_atr_from_db(self) -> Optional[float]:
        since = datetime.now(timezone.utc) - timedelta(days=30)
        res = await self.db.execute(text("""
            SELECT high, low, close FROM stock_prices
            WHERE ticker = :t AND time >= :since
              AND high IS NOT NULL AND low IS NOT NULL AND close IS NOT NULL
            ORDER BY time ASC
        """), {"t": self.ticker, "since": since})
        rows = res.fetchall()
        if not rows:
            return None
        return _compute_atr(
            [r.high for r in rows],
            [r.low  for r in rows],
            [r.close for r in rows],
        )

    async def _latest_close(self) -> Optional[float]:
        res = await self.db.execute(text("""
            SELECT close FROM stock_prices WHERE ticker = :t
            ORDER BY time DESC LIMIT 1
        """), {"t": self.ticker})
        row = res.fetchone()
        return row.close if row else None
