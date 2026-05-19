from typing import Optional, List, Dict, Tuple
"""
agents/execution.py
====================
Execution Cost Model
Estimates realistic transaction costs before committing a position size.
Adjusts the sizing engine's kelly_fraction downward when net costs are too high.

Models:
  - Slippage:       0.1% × ATR_ratio (scales with volatility)
  - Market impact:  sqrt(position_size_usd / avg_30d_volume_usd) × 0.1
  - Commission:     Configurable (default 0 for commission-free brokers)
  - Spread cost:    Estimated from bid-ask as 0.05% for liquid, 0.2% for illiquid

Returns:
    {
        "net_cost_pct":       float,   # total estimated round-trip cost %
        "adjusted_kelly":     float,   # kelly_fraction after cost adjustment
        "is_tradeable":       bool,    # False if costs > 1% of position
        "execution_note":     str,
    }
"""
import logging
import math
from datetime import datetime, timedelta, timezone

from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import text

logger = logging.getLogger(__name__)

COMMISSION_PER_SIDE = 0.0    # 0% for commission-free (Zerodha equity, IBKR lite)
ILLIQUID_THRESHOLD_USD = 500_000   # avg daily volume below this = illiquid


class ExecutionModel:
    def __init__(self, db: AsyncSession, ticker: str):
        self.db = db
        self.ticker = ticker.upper()

    async def adjust(
        self,
        kelly_fraction: float,
        portfolio_value_usd: float = 100_000,  # default portfolio size
    ) -> dict:
        try:
            avg_volume    = await self._avg_daily_volume_usd()
            latest_price  = await self._latest_close()
            atr_ratio     = await self._atr_ratio()

            position_size_usd = kelly_fraction * portfolio_value_usd

            # ── Slippage ────────────────────────────────────────────────────────
            slippage = 0.001 * (atr_ratio / 0.02)   # scales with volatility
            slippage = min(slippage, 0.005)           # cap at 0.5%

            # ── Market Impact ────────────────────────────────────────────────────
            if avg_volume and avg_volume > 0:
                impact = math.sqrt(position_size_usd / avg_volume) * 0.10
                impact = min(impact, 0.01)            # cap at 1%
            else:
                impact = 0.002                        # assume 0.2% for unknown

            # ── Spread ──────────────────────────────────────────────────────────
            spread = 0.0005 if (avg_volume and avg_volume > ILLIQUID_THRESHOLD_USD) else 0.002

            # Round-trip (2 sides)
            net_cost = (slippage + impact + spread + COMMISSION_PER_SIDE) * 2

            # Adjust Kelly if costs eat >0.5% (round-trip)
            is_tradeable = net_cost < 0.01   # < 1% round-trip cost
            if net_cost > 0.005:
                # Scale down kelly proportionally
                cost_penalty = 1 - min(0.8, net_cost * 10)
                adjusted_kelly = kelly_fraction * cost_penalty
            else:
                adjusted_kelly = kelly_fraction

            adjusted_kelly = round(max(0.0, adjusted_kelly), 4)

            note = (
                f"Est. round-trip cost: {net_cost*100:.2f}% "
                f"(slippage={slippage*100:.2f}% impact={impact*100:.2f}% spread={spread*100:.2f}%). "
                f"Kelly adjusted from {kelly_fraction:.1%} → {adjusted_kelly:.1%}."
            )
            if not is_tradeable:
                note += " ⚠️ High transaction cost — position size was significantly reduced."

            return {
                "net_cost_pct":   round(net_cost * 100, 3),
                "adjusted_kelly": adjusted_kelly,
                "is_tradeable":   is_tradeable,
                "execution_note": note,
            }

        except Exception as e:
            logger.error("ExecutionModel failed for %s: %s", self.ticker, e)
            return {
                "net_cost_pct":   0.0,
                "adjusted_kelly": kelly_fraction,
                "is_tradeable":   True,
                "execution_note": "Cost model unavailable; using unadjusted sizing.",
            }

    async def _avg_daily_volume_usd(self) -> Optional[float]:
        since = datetime.now(timezone.utc) - timedelta(days=30)
        res = await self.db.execute(text("""
            SELECT AVG(volume * close) as avg_vol_usd
            FROM stock_prices
            WHERE ticker = :t AND time >= :since
              AND volume IS NOT NULL AND close IS NOT NULL
        """), {"t": self.ticker, "since": since})
        row = res.fetchone()
        return row.avg_vol_usd if row else None

    async def _latest_close(self) -> Optional[float]:
        res = await self.db.execute(text(
            "SELECT close FROM stock_prices WHERE ticker = :t ORDER BY time DESC LIMIT 1"
        ), {"t": self.ticker})
        row = res.fetchone()
        return row.close if row else None

    async def _atr_ratio(self) -> float:
        """ATR as % of price."""
        since = datetime.now(timezone.utc) - timedelta(days=20)
        res = await self.db.execute(text("""
            SELECT high, low, close FROM stock_prices
            WHERE ticker = :t AND time >= :since
            ORDER BY time ASC
        """), {"t": self.ticker, "since": since})
        rows = res.fetchall()
        if len(rows) < 5:
            return 0.02
        trs = [max(r.high - r.low, 0) for r in rows if r.high and r.low]
        atr = sum(trs[-14:]) / min(14, len(trs))
        last_close = rows[-1].close or 1.0
        return atr / last_close if last_close > 0 else 0.02
