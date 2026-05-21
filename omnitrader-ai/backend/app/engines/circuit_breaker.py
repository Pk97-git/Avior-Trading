"""
engines/circuit_breaker.py
==========================
CircuitBreakerEngine — checks market conditions and portfolio state
before allowing new positions to be opened.

Rules (all evaluated simultaneously; multiple can trigger):
  1. VIX > 35                          → HALT: extreme volatility
  2. VIX > 25                          → CAUTION: elevated volatility
  3. Portfolio daily P&L < -2%         → HALT: daily loss limit breached
  4. Portfolio drawdown from peak > 10% → CAUTION: drawdown warning
  5. Yield curve deeply inverted
     (US10Y - US2Y < -0.8%)            → CAUTION: recession signal
"""
from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from typing import List, Optional

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger(__name__)


class CircuitBreakerEngine:
    """
    Checks market conditions and portfolio state before allowing new positions.

    Rules (all checked; multiple can trigger simultaneously):
      1. VIX > 35                           → HALT: extreme volatility
      2. VIX > 25                           → CAUTION: elevated volatility
      3. Portfolio daily P&L < -2%          → HALT: daily loss limit breached
      4. Portfolio drawdown from peak > 10% → CAUTION: drawdown warning
      5. Yield curve deeply inverted
         (US10Y - US2Y < -0.8%)             → CAUTION: recession signal
    """

    VIX_HALT_THRESHOLD    = 35.0
    VIX_CAUTION_THRESHOLD = 25.0
    DAILY_PNL_HALT_PCT    = -2.0   # percent
    DRAWDOWN_CAUTION_PCT  = -10.0  # percent (negative = loss from peak)
    YIELD_CURVE_CAUTION   = -0.8   # percent (US10Y - US2Y)

    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    # ──────────────────────────────────────────────────────────────────────────
    # Public API
    # ──────────────────────────────────────────────────────────────────────────

    async def check(self) -> dict:
        """
        Evaluate all circuit-breaker rules and return a status dict.

        Returns:
        {
            "trading_allowed": bool,       # False = HALT all new positions
            "caution":         bool,       # True = reduce sizing by 50%
            "status":          str,        # "CLEAR" | "CAUTION" | "HALT"
            "reasons":         list[str],  # human-readable explanations
            "vix":             float | None,
            "daily_pnl_pct":   float | None,
            "drawdown_pct":    float | None,
        }
        """
        halt_reasons: List[str]    = []
        caution_reasons: List[str] = []

        vix:           Optional[float] = None
        daily_pnl_pct: Optional[float] = None
        drawdown_pct:  Optional[float] = None

        # ── Rule 1 & 2: VIX ──────────────────────────────────────────────────
        try:
            vix = await self._latest_macro_value("VIX")
            if vix is not None:
                if vix > self.VIX_HALT_THRESHOLD:
                    halt_reasons.append(
                        f"VIX at {vix:.1f} exceeds halt threshold of {self.VIX_HALT_THRESHOLD} — extreme volatility"
                    )
                elif vix > self.VIX_CAUTION_THRESHOLD:
                    caution_reasons.append(
                        f"VIX at {vix:.1f} exceeds caution threshold of {self.VIX_CAUTION_THRESHOLD} — elevated volatility"
                    )
        except Exception as exc:
            logger.warning("[CircuitBreaker] VIX check failed: %s", exc)

        # ── Rules 3 & 4: Portfolio P&L / drawdown ────────────────────────────
        try:
            pnl_result = await self._portfolio_pnl()
            daily_pnl_pct = pnl_result.get("daily_pnl_pct")
            drawdown_pct  = pnl_result.get("drawdown_pct")

            if daily_pnl_pct is not None and daily_pnl_pct < self.DAILY_PNL_HALT_PCT:
                halt_reasons.append(
                    f"Daily P&L at {daily_pnl_pct:.2f}% breaches {self.DAILY_PNL_HALT_PCT}% loss limit"
                )

            if drawdown_pct is not None and drawdown_pct < self.DRAWDOWN_CAUTION_PCT:
                caution_reasons.append(
                    f"Portfolio drawdown from peak at {drawdown_pct:.2f}% exceeds {abs(self.DRAWDOWN_CAUTION_PCT)}% warning threshold"
                )
        except Exception as exc:
            logger.warning("[CircuitBreaker] Portfolio P&L check failed: %s", exc)

        # ── Rule 5: Yield curve ───────────────────────────────────────────────
        try:
            us10y = await self._latest_macro_value("US10Y")
            us2y  = await self._latest_macro_value("US2Y")
            if us10y is not None and us2y is not None:
                spread = us10y - us2y
                if spread < self.YIELD_CURVE_CAUTION:
                    caution_reasons.append(
                        f"Yield curve deeply inverted: US10Y–US2Y = {spread:.2f}% "
                        f"(threshold {self.YIELD_CURVE_CAUTION}%) — recession signal"
                    )
        except Exception as exc:
            logger.warning("[CircuitBreaker] Yield curve check failed: %s", exc)

        # ── Determine overall status ──────────────────────────────────────────
        all_reasons = halt_reasons + caution_reasons

        if halt_reasons:
            status          = "HALT"
            trading_allowed = False
            caution         = False
        elif caution_reasons:
            status          = "CAUTION"
            trading_allowed = True
            caution         = True
        else:
            status          = "CLEAR"
            trading_allowed = True
            caution         = False

        return {
            "trading_allowed": trading_allowed,
            "caution":         caution,
            "status":          status,
            "reasons":         all_reasons,
            "vix":             vix,
            "daily_pnl_pct":   daily_pnl_pct,
            "drawdown_pct":    drawdown_pct,
        }

    # ──────────────────────────────────────────────────────────────────────────
    # Private helpers
    # ──────────────────────────────────────────────────────────────────────────

    async def _latest_macro_value(self, indicator: str) -> Optional[float]:
        """Return the latest value for a macro indicator, or None if not found."""
        result = await self.db.execute(
            text("""
                SELECT value FROM macro_data
                WHERE indicator = :indicator
                ORDER BY time DESC
                LIMIT 1
            """),
            {"indicator": indicator},
        )
        row = result.fetchone()
        return float(row.value) if row and row.value is not None else None

    async def _portfolio_pnl(self) -> dict:
        """
        Compute daily P&L and drawdown from peak for open positions.

        Queries portfolio_positions for held positions and stock_prices for
        current market values. Falls back gracefully if the table doesn't exist.

        Returns:
            {
                "daily_pnl_pct": float | None,
                "drawdown_pct":  float | None,
            }
        """
        # Check if portfolio_positions table exists
        try:
            exists_check = await self.db.execute(
                text("""
                    SELECT 1 FROM information_schema.tables
                    WHERE table_name = 'portfolio_positions'
                    LIMIT 1
                """)
            )
            if not exists_check.fetchone():
                logger.debug("[CircuitBreaker] portfolio_positions table not found — skipping P&L check")
                return {"daily_pnl_pct": None, "drawdown_pct": None}
        except Exception as exc:
            logger.warning("[CircuitBreaker] Table existence check failed: %s", exc)
            return {"daily_pnl_pct": None, "drawdown_pct": None}

        # Fetch open positions with entry data
        try:
            positions_result = await self.db.execute(
                text("""
                    SELECT ticker, quantity, entry_price, cost_basis
                    FROM portfolio_positions
                    WHERE status = 'OPEN'
                      AND quantity > 0
                """)
            )
            positions = positions_result.fetchall()
        except Exception as exc:
            logger.warning("[CircuitBreaker] Failed to fetch portfolio positions: %s", exc)
            return {"daily_pnl_pct": None, "drawdown_pct": None}

        if not positions:
            return {"daily_pnl_pct": None, "drawdown_pct": None}

        tickers = [row.ticker for row in positions]

        # Fetch current prices
        try:
            price_result = await self.db.execute(
                text("""
                    SELECT DISTINCT ON (ticker) ticker, close, time
                    FROM stock_prices
                    WHERE ticker = ANY(:tickers)
                    ORDER BY ticker, time DESC
                """),
                {"tickers": tickers},
            )
            current_prices = {row.ticker: float(row.close) for row in price_result.fetchall()}
        except Exception as exc:
            logger.warning("[CircuitBreaker] Failed to fetch current prices: %s", exc)
            return {"daily_pnl_pct": None, "drawdown_pct": None}

        # Fetch yesterday's prices for daily P&L
        yesterday = datetime.now(timezone.utc) - timedelta(days=1)
        try:
            prev_price_result = await self.db.execute(
                text("""
                    SELECT DISTINCT ON (ticker) ticker, close
                    FROM stock_prices
                    WHERE ticker = ANY(:tickers)
                      AND time <= :yesterday
                    ORDER BY ticker, time DESC
                """),
                {"tickers": tickers, "yesterday": yesterday},
            )
            prev_prices = {row.ticker: float(row.close) for row in prev_price_result.fetchall()}
        except Exception as exc:
            logger.warning("[CircuitBreaker] Failed to fetch previous prices: %s", exc)
            prev_prices = {}

        # Compute portfolio-level totals
        total_cost        = 0.0
        total_current_val = 0.0
        total_prev_val    = 0.0

        for pos in positions:
            ticker   = pos.ticker
            qty      = float(pos.quantity)
            entry_px = float(pos.entry_price) if pos.entry_price else None
            cost_b   = float(pos.cost_basis)  if pos.cost_basis  else None

            current_px = current_prices.get(ticker)
            prev_px    = prev_prices.get(ticker)

            if current_px is None:
                continue

            # Cost basis for this position
            if cost_b is not None:
                pos_cost = cost_b
            elif entry_px is not None:
                pos_cost = entry_px * qty
            else:
                continue

            total_cost        += pos_cost
            total_current_val += current_px * qty
            if prev_px is not None:
                total_prev_val += prev_px * qty

        if total_cost <= 0:
            return {"daily_pnl_pct": None, "drawdown_pct": None}

        # Drawdown from peak (using cost basis as proxy for peak entry value)
        drawdown_pct = ((total_current_val - total_cost) / total_cost) * 100

        # Daily P&L
        daily_pnl_pct: Optional[float] = None
        if total_prev_val > 0:
            daily_pnl_pct = ((total_current_val - total_prev_val) / total_prev_val) * 100

        return {
            "daily_pnl_pct": round(daily_pnl_pct, 4) if daily_pnl_pct is not None else None,
            "drawdown_pct":  round(drawdown_pct, 4),
        }
