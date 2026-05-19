import logging
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import text

logger = logging.getLogger("omnitrader.agent.technical")


class TechnicalAgent:
    def __init__(self, db: AsyncSession, ticker: str):
        self.db = db
        self.ticker = ticker

    async def analyze(self) -> dict:
        """
        Technical Score (0–100) across 6 dimensions:
          1. Trend structure     — price vs SMA20/50/200, golden/death cross
          2. MACD                — signal line crossover (bullish/bearish)
          3. RSI                 — overbought / oversold / momentum
          4. Volume surge        — vol_ratio vs 20-day avg (pre-computed)
          5. Relative strength   — rs_vs_spx or rs_vs_nsei (pre-computed, 63-day)
          6. Breakout proximity  — price vs week_52_high (pre-computed)

        Reads from stock_technicals (pre-computed) + 1 price row.
        Returns: {"score": int, "thesis": list[str], "atr_14": float|None}
        """
        # Fetch latest 2 rows from stock_technicals for crossover detection
        tech_result = await self.db.execute(text("""
            SELECT date, sma_20, sma_50, sma_200,
                   rsi_14, macd, macd_signal, macd_hist,
                   atr_14, bb_upper, bb_lower,
                   vol_ratio, week_52_high, week_52_low,
                   rs_vs_spx, rs_vs_nsei
            FROM stock_technicals
            WHERE ticker = :ticker
            ORDER BY date DESC
            LIMIT 2
        """), {"ticker": self.ticker})
        rows = tech_result.fetchall()

        if not rows:
            return {
                "score": 50,
                "thesis": ["Technical indicators not yet computed for this ticker."],
                "atr_14": None,
            }

        latest = rows[0]
        prev   = rows[1] if len(rows) > 1 else rows[0]

        # Fetch current price (one row)
        price_result = await self.db.execute(text("""
            SELECT close FROM stock_prices
            WHERE ticker = :ticker AND close IS NOT NULL
            ORDER BY time DESC LIMIT 1
        """), {"ticker": self.ticker})
        price_row = price_result.fetchone()

        if not price_row:
            return {
                "score": 50,
                "thesis": ["No price data available."],
                "atr_14": latest.atr_14,
            }

        price   = price_row.close
        score   = 50
        thesis  = []

        sma_20  = latest.sma_20
        sma_50  = latest.sma_50
        sma_200 = latest.sma_200
        rsi     = latest.rsi_14

        # ── 1. Trend Structure ────────────────────────────────────────────────
        if sma_200 is not None:
            if price > sma_200:
                score += 18
                thesis.append("Long-term uptrend intact (price > 200-day SMA).")
            else:
                score -= 18
                thesis.append("Below 200-day SMA — stock in long-term downtrend.")

            if sma_50 is not None:
                if price > sma_50:
                    score += 12
                    if sma_50 > sma_200:
                        score += 8
                        thesis.append("Golden Cross active (50 SMA > 200 SMA) + price above both MAs.")
                    else:
                        thesis.append("Price above 50 SMA — medium-term momentum positive.")
                else:
                    score -= 10
                    if sma_50 < sma_200:
                        score -= 5
                        thesis.append("Death Cross (50 SMA < 200 SMA) — confirmed downtrend.")
                    else:
                        thesis.append("Price below 50 SMA — medium-term momentum negative.")
        elif sma_50 is not None:
            if price > sma_50:
                score += 15
                thesis.append("Price above 50-day SMA (insufficient history for 200 SMA).")
            else:
                score -= 10
                thesis.append("Price below 50-day SMA.")

        if sma_20 is not None:
            if price > sma_20:
                score += 4
                thesis.append("Short-term pulse positive (price > 20-day SMA).")
            else:
                score -= 3
                thesis.append("Short-term pulse negative (price < 20-day SMA).")

        # ── 2. MACD Signal ────────────────────────────────────────────────────
        macd_now = latest.macd
        macd_sig = latest.macd_signal
        macd_prev_val = prev.macd
        macd_prev_sig = prev.macd_signal

        if macd_now is not None and macd_sig is not None:
            bullish_cross = (macd_now > macd_sig) and (macd_prev_val is not None) and (macd_prev_val <= (macd_prev_sig or macd_sig))
            bearish_cross = (macd_now < macd_sig) and (macd_prev_val is not None) and (macd_prev_val >= (macd_prev_sig or macd_sig))

            if bullish_cross:
                score += 12
                thesis.append("MACD bullish crossover — fresh buy signal.")
            elif bearish_cross:
                score -= 12
                thesis.append("MACD bearish crossover — fresh sell signal.")
            elif macd_now > macd_sig and macd_now > 0:
                score += 6
                thesis.append("MACD above signal line in positive territory — bullish momentum.")
            elif macd_now < macd_sig and macd_now < 0:
                score -= 6
                thesis.append("MACD below signal line in negative territory — bearish momentum.")
            else:
                thesis.append(f"MACD neutral ({macd_now:.3f} vs signal {macd_sig:.3f}).")

        # ── 3. RSI ────────────────────────────────────────────────────────────
        if rsi is not None:
            if rsi > 75:
                score -= 12
                thesis.append(f"RSI {rsi:.0f} — severely overbought. High reversal risk.")
            elif rsi > 65:
                score -= 5
                thesis.append(f"RSI {rsi:.0f} — approaching overbought. Take partial profit zone.")
            elif rsi < 25:
                score += 15
                thesis.append(f"RSI {rsi:.0f} — deeply oversold. High-probability bounce setup.")
            elif rsi < 35:
                score += 8
                thesis.append(f"RSI {rsi:.0f} — oversold. Potential mean-reversion entry.")
            elif 45 <= rsi <= 60:
                score += 4
                thesis.append(f"RSI {rsi:.0f} — healthy momentum range (no extremes).")
            else:
                thesis.append(f"RSI {rsi:.0f} — neutral.")

        # ── 4. Volume Surge (pre-computed ratio) ──────────────────────────────
        vol_ratio = latest.vol_ratio
        if vol_ratio is not None:
            if vol_ratio > 2.5:
                score += 12
                thesis.append(f"Volume explosion: {vol_ratio:.1f}× 20-day avg — strong institutional accumulation signal.")
            elif vol_ratio > 1.5:
                score += 6
                thesis.append(f"Above-average volume: {vol_ratio:.1f}× 20-day avg — demand confirmation.")
            elif vol_ratio < 0.5:
                score -= 5
                thesis.append(f"Volume drought: {vol_ratio:.1f}× 20-day avg — lack of conviction.")
            else:
                thesis.append(f"Volume normal: {vol_ratio:.1f}× 20-day avg.")

        # ── 5. Relative Strength (pre-computed, 63-day) ───────────────────────
        is_india = ".NS" in self.ticker or ".BO" in self.ticker
        rs = latest.rs_vs_nsei if is_india else latest.rs_vs_spx
        if rs is not None:
            rs_delta_pct = (rs - 1.0) * 100  # convert ratio to % outperformance
            if rs_delta_pct > 10:
                score += 12
                thesis.append(f"Strong relative strength: outperforming index by +{rs_delta_pct:.1f}% over 3 months.")
            elif rs_delta_pct > 3:
                score += 5
                thesis.append(f"Mild relative outperformance vs index (+{rs_delta_pct:.1f}% over 3 months).")
            elif rs_delta_pct < -10:
                score -= 10
                thesis.append(f"Underperforming index by {rs_delta_pct:.1f}% over 3 months — weak RS.")
            elif rs_delta_pct < -3:
                score -= 4
                thesis.append(f"Slight underperformance vs index ({rs_delta_pct:.1f}% over 3 months).")

        # ── 6. Breakout Proximity (52-week high, pre-computed) ────────────────
        high_52w = latest.week_52_high
        if high_52w and high_52w > 0:
            proximity = price / high_52w
            if proximity >= 0.98:
                score += 10
                thesis.append(f"Near 52-week high ({proximity*100:.0f}%) — momentum breakout zone.")
            elif proximity >= 0.90:
                score += 4
                thesis.append(f"Within 10% of 52-week high ({proximity*100:.0f}%) — strong setup.")
            elif proximity <= 0.60:
                score -= 6
                thesis.append(f"Far from 52-week high ({proximity*100:.0f}%) — stock in deep correction.")

        # Bollinger Band context (informational)
        if latest.bb_upper is not None and latest.bb_lower is not None:
            bb_range = latest.bb_upper - latest.bb_lower
            if bb_range > 0:
                bb_pos = (price - latest.bb_lower) / bb_range
                if bb_pos > 0.95:
                    score -= 3
                    thesis.append("Price at upper Bollinger Band — potential short-term resistance.")
                elif bb_pos < 0.05:
                    score += 3
                    thesis.append("Price at lower Bollinger Band — potential mean-reversion opportunity.")

        score = max(0, min(100, score))
        logger.info("TechnicalAgent %s: score=%d price=%.2f RSI=%s",
                    self.ticker, score, price,
                    f"{rsi:.1f}" if rsi is not None else "n/a")

        return {"score": score, "thesis": thesis, "atr_14": latest.atr_14}
