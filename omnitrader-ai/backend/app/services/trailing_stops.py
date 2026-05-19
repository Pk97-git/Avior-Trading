"""
TrailingStopService — automatically ratchets stop-losses upward as positions move in favour.

Strategy:
  - For each open long position:
    1. Get current price (latest StockPrice.close for the ticker)
    2. Compute ATR-14 from last 14 trading days (True Range avg)
    3. Trailing stop level = current_price - (ATR_multiplier * ATR14)
    4. Only update stop_loss if new_stop > current stop_loss (never move stop down)
    5. If current_price <= current stop_loss → flag for exit (return in needs_exit list)

  ATR_multiplier defaults:
    - STRONG_BUY signal: 2.0× ATR (give room to breathe)
    - ACCUMULATE: 2.5× ATR
    - PROACTIVE_SWING: 1.5× ATR (tighter, swing trade)
    - default: 2.0× ATR

Returns:
  {
    updated: [{ position_id, ticker, old_stop, new_stop, current_price }],
    needs_exit: [{ position_id, ticker, current_price, stop_loss, entry_price }],
    skipped: int  (positions with insufficient price history)
  }
"""

import logging
from datetime import datetime, timezone, timedelta
import numpy as np
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, text
from app.models.market_data import PortfolioPosition, StockPrice

logger = logging.getLogger("omnitrader.trailing_stops")

ATR_MULTIPLIER = {
    "STRONG_BUY": 2.0,
    "ACCUMULATE": 2.5,
    "PROACTIVE_SWING": 1.5,
}
DEFAULT_MULTIPLIER = 2.0


class TrailingStopService:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def run(self) -> dict:
        """Main entry: update all open positions' trailing stops."""
        # Fetch all open positions
        stmt = select(PortfolioPosition).where(
            PortfolioPosition.is_open == True  # noqa: E712
        )
        result = await self.db.execute(stmt)
        positions = result.scalars().all()

        updated = []
        needs_exit = []
        skipped = 0

        for pos in positions:
            current_price = await self._get_current_price(pos.ticker)
            if current_price is None:
                logger.debug("No current price for %s — skipping.", pos.ticker)
                skipped += 1
                continue

            # Check if price has already breached the existing stop loss
            if pos.stop_loss is not None and current_price <= pos.stop_loss:
                needs_exit.append({
                    "position_id": pos.id,
                    "ticker":      pos.ticker,
                    "current_price": round(current_price, 4),
                    "stop_loss":   round(pos.stop_loss, 4),
                    "entry_price": round(pos.entry_price, 4) if pos.entry_price else None,
                })
                logger.warning(
                    "Position %d (%s) breached stop: price=%.4f stop=%.4f",
                    pos.id, pos.ticker, current_price, pos.stop_loss,
                )
                continue

            atr14 = await self._compute_atr14(pos.ticker)
            if atr14 is None:
                logger.debug("Insufficient ATR history for %s — skipping.", pos.ticker)
                skipped += 1
                continue

            multiplier = ATR_MULTIPLIER.get(pos.signal or "", DEFAULT_MULTIPLIER)
            new_stop = current_price - (multiplier * atr14)

            old_stop = pos.stop_loss

            # Only ratchet upward — never lower the stop
            if old_stop is None or new_stop > old_stop:
                pos.stop_loss = round(new_stop, 4)
                updated.append({
                    "position_id":   pos.id,
                    "ticker":        pos.ticker,
                    "old_stop":      round(old_stop, 4) if old_stop is not None else None,
                    "new_stop":      round(new_stop, 4),
                    "current_price": round(current_price, 4),
                })
                logger.info(
                    "Updated trailing stop for %s (id=%d): %.4f → %.4f (price=%.4f, ATR=%.4f, mult=%.1f)",
                    pos.ticker, pos.id, old_stop or 0.0, new_stop, current_price, atr14, multiplier,
                )

        if updated:
            await self.db.commit()

        return {
            "updated":    updated,
            "needs_exit": needs_exit,
            "skipped":    skipped,
        }

    async def _compute_atr14(self, ticker: str) -> float | None:
        """
        Compute 14-day ATR from stock_prices.
        True Range = max(high-low, abs(high-prev_close), abs(low-prev_close))
        Returns None if < 15 rows available.
        """
        # Fetch last 20 rows (DESC) so we have enough to compute 14 TR values
        stmt = (
            select(StockPrice.high, StockPrice.low, StockPrice.close)
            .where(StockPrice.ticker == ticker)
            .order_by(StockPrice.time.desc())
            .limit(20)
        )
        result = await self.db.execute(stmt)
        rows = result.fetchall()

        # Need at least 15 rows to compute 14 True Range values (each needs a prev close)
        if len(rows) < 15:
            return None

        # Rows are newest-first; reverse so index 0 is oldest
        rows = list(reversed(rows))

        true_ranges = []
        for i in range(1, len(rows)):
            high      = rows[i].high
            low       = rows[i].low
            prev_close = rows[i - 1].close

            if high is None or low is None or prev_close is None:
                continue

            tr = max(
                high - low,
                abs(high - prev_close),
                abs(low  - prev_close),
            )
            true_ranges.append(tr)

        if len(true_ranges) < 14:
            return None

        # Use the last 14 TR values for ATR-14
        atr14 = float(np.mean(true_ranges[-14:]))
        return atr14

    async def _get_current_price(self, ticker: str) -> float | None:
        """Latest close from stock_prices."""
        stmt = (
            select(StockPrice.close)
            .where(StockPrice.ticker == ticker)
            .order_by(StockPrice.time.desc())
            .limit(1)
        )
        result = await self.db.execute(stmt)
        row = result.scalar()
        return float(row) if row is not None else None

    async def update_single_position(self, position_id: int) -> dict:
        """Update trailing stop for one position. Returns result dict."""
        result = await self.db.execute(
            select(PortfolioPosition).where(
                PortfolioPosition.id == position_id,
                PortfolioPosition.is_open == True,  # noqa: E712
            )
        )
        pos = result.scalars().first()
        if not pos:
            return {"error": f"Open position {position_id} not found."}

        current_price = await self._get_current_price(pos.ticker)
        if current_price is None:
            return {
                "position_id": position_id,
                "ticker":      pos.ticker,
                "status":      "skipped",
                "reason":      "no_price_data",
            }

        # Check breach first
        if pos.stop_loss is not None and current_price <= pos.stop_loss:
            return {
                "position_id":   position_id,
                "ticker":        pos.ticker,
                "status":        "needs_exit",
                "current_price": round(current_price, 4),
                "stop_loss":     round(pos.stop_loss, 4),
                "entry_price":   round(pos.entry_price, 4) if pos.entry_price else None,
            }

        atr14 = await self._compute_atr14(pos.ticker)
        if atr14 is None:
            return {
                "position_id": position_id,
                "ticker":      pos.ticker,
                "status":      "skipped",
                "reason":      "insufficient_atr_history",
            }

        multiplier = ATR_MULTIPLIER.get(pos.signal or "", DEFAULT_MULTIPLIER)
        new_stop   = current_price - (multiplier * atr14)
        old_stop   = pos.stop_loss

        if old_stop is None or new_stop > old_stop:
            pos.stop_loss = round(new_stop, 4)
            await self.db.commit()
            return {
                "position_id":   position_id,
                "ticker":        pos.ticker,
                "status":        "updated",
                "old_stop":      round(old_stop, 4) if old_stop is not None else None,
                "new_stop":      round(new_stop, 4),
                "current_price": round(current_price, 4),
                "atr14":         round(atr14, 4),
                "multiplier":    multiplier,
            }

        return {
            "position_id":   position_id,
            "ticker":        pos.ticker,
            "status":        "no_change",
            "current_stop":  round(old_stop, 4) if old_stop is not None else None,
            "computed_stop": round(new_stop, 4),
            "current_price": round(current_price, 4),
            "atr14":         round(atr14, 4),
            "multiplier":    multiplier,
        }
