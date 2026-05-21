"""
execution_agent.py
==================
ExecutionAgent — the final gate before order placement.
Answers: "Should we execute this trade right now? And at what size?"

Distinct from ExecutionModel (execution.py) which only models transaction costs.
ExecutionAgent is an AI agent in the pipeline with a score, thesis, and action.

Score 0–100 (100 = perfect execution conditions):
  1. Market hours check — is the relevant exchange open?
  2. Spread/cost assessment — is execution cost acceptable vs expected return?
  3. Liquidity window — is this a high-volume period (open/close) or thin mid-session?
  4. Signal strength — is the final score high enough to justify execution costs?
  5. Circuit breaker — are system-level halts in effect?

Returns {"score": int, "thesis": list[str], "should_execute": bool, "execution_notes": str}
"""
import logging
from datetime import datetime, timezone, time as dtime
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import text

logger = logging.getLogger("omnitrader.agent.execution")


class ExecutionAgent:
    def __init__(self, db: AsyncSession, ticker: str):
        self.db = db
        self.ticker = ticker

    async def analyze(self, final_score: int = 50) -> dict:
        score = 50
        thesis = []
        should_execute = True

        now_utc = datetime.now(timezone.utc)
        hour = now_utc.hour
        minute = now_utc.minute
        is_india = ".NS" in self.ticker or ".BO" in self.ticker

        # ── 1. Market hours check ────────────────────────────────────────────
        if is_india:
            # NSE: 03:45–10:00 UTC (Mon-Fri)
            market_open = dtime(3, 45) <= dtime(hour, minute) <= dtime(10, 0)
            session_name = "NSE"
        else:
            # NYSE/NASDAQ: 13:30–20:00 UTC (Mon-Fri)
            market_open = dtime(13, 30) <= dtime(hour, minute) <= dtime(20, 0)
            session_name = "NYSE"

        is_weekday = now_utc.weekday() < 5

        if not is_weekday:
            score -= 20
            thesis.append("Weekend — order execution deferred to Monday open.")
        elif market_open:
            score += 20
            thesis.append(f"Market open — {session_name} live session.")
        else:
            score -= 10
            thesis.append("Market closed — order will queue for next session open.")

        # ── 2. Liquidity window ──────────────────────────────────────────────
        if is_weekday and market_open:
            if is_india:
                open_hour, open_min = 3, 45
                close_hour, close_min = 10, 0
            else:
                open_hour, open_min = 13, 30
                close_hour, close_min = 20, 0

            open_minutes = open_hour * 60 + open_min
            close_minutes = close_hour * 60 + close_min
            current_minutes = hour * 60 + minute

            mins_from_open = current_minutes - open_minutes
            mins_to_close = close_minutes - current_minutes

            if mins_from_open <= 30 or mins_to_close <= 30:
                score += 10
                thesis.append("High-liquidity window — optimal execution timing.")
            elif mins_from_open >= 120 and mins_to_close >= 120:
                score -= 5
                thesis.append("Mid-session — spread may be wider.")

        # ── 3. Signal strength gate ──────────────────────────────────────────
        if final_score >= 70:
            score += 15
            thesis.append("High-conviction signal — execution cost justified.")
        elif final_score >= 60:
            score += 8
            thesis.append("Good signal strength.")
        elif final_score < 35:
            score -= 25
            should_execute = False
            thesis.append("Signal too weak — do not execute.")
        elif final_score < 45:
            score -= 15
            thesis.append("Weak signal — execution cost may outweigh edge.")

        # ── 4. Transaction cost check (ATR ratio) ────────────────────────────
        try:
            atr_res = await self.db.execute(text("""
                SELECT atr_14 FROM stock_technicals WHERE ticker = :t ORDER BY date DESC LIMIT 1
            """), {"t": self.ticker})
            atr_row = atr_res.fetchone()

            price_res = await self.db.execute(text("""
                SELECT close FROM stock_prices WHERE ticker = :t ORDER BY time DESC LIMIT 1
            """), {"t": self.ticker})
            price_row = price_res.fetchone()

            if atr_row and price_row and atr_row.atr_14 and price_row.close:
                atr = float(atr_row.atr_14)
                close = float(price_row.close)
                if close > 0:
                    atr_ratio = atr / close
                    if atr_ratio > 0.04:
                        score -= 10
                        thesis.append("High ATR — execution costs elevated as % of move.")
                    elif atr_ratio < 0.01:
                        score += 5
                        thesis.append("Low volatility — tight spreads expected.")
        except Exception as e:
            logger.debug("ATR cost check failed for %s: %s", self.ticker, e)

        # ── 5. should_execute determination ─────────────────────────────────
        should_execute = should_execute and score >= 40 and final_score >= 35

        # Cap score at 0–100
        score = max(0, min(100, score))

        return {
            "score": score,
            "thesis": thesis,
            "should_execute": should_execute,
            "execution_notes": "; ".join(thesis[:2]),
        }
