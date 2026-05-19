import logging
import pandas as pd
from sqlalchemy.orm import Session
from sqlalchemy import select, text
from app.models.market_data import StockPrice

logger = logging.getLogger("omnitrader.agent.technical")


class TechnicalAgent:
    def __init__(self, db: Session, ticker: str):
        self.db = db
        self.ticker = ticker

    async def analyze(self) -> dict:
        """
        Technical Score (0–100) across 6 dimensions:
          1. Trend structure     — price vs SMA20/50/200, golden/death cross
          2. MACD                — signal line crossover (bullish/bearish)
          3. RSI                 — overbought / oversold / momentum
          4. Volume surge        — 5-day avg vs 20-day avg ratio
          5. Relative strength   — stock returns vs SPY/Nifty over 63 days
          6. Breakout proximity  — price within 5% of 52-week high

        Returns: {"score": int, "thesis": list[str]}
        """
        stmt = select(StockPrice).where(
            StockPrice.ticker == self.ticker
        ).order_by(StockPrice.time.desc()).limit(300)

        result = await self.db.execute(stmt)
        prices = result.scalars().all()

        if not prices or len(prices) < 50:
            return {
                "score": 0,
                "thesis": ["Insufficient price history (need 50+ days) for technical analysis."]
            }

        df = pd.DataFrame([{
            "time":   p.time,
            "close":  p.close,
            "high":   p.high,
            "low":    p.low,
            "volume": p.volume,
        } for p in prices]).sort_values("time").reset_index(drop=True)

        # Moving averages
        df["SMA_20"]  = df["close"].rolling(20).mean()
        df["SMA_50"]  = df["close"].rolling(50).mean()
        df["SMA_200"] = df["close"].rolling(200).mean() if len(df) >= 200 else pd.Series([None] * len(df))

        # RSI (14-period)
        delta = df["close"].diff()
        gain  = delta.where(delta > 0, 0.0).rolling(14).mean()
        loss  = (-delta.where(delta < 0, 0.0)).rolling(14).mean()
        rs    = gain / loss.replace(0, float("nan"))
        df["RSI"] = 100 - (100 / (1 + rs))

        # MACD (12, 26, 9)
        ema12     = df["close"].ewm(span=12, adjust=False).mean()
        ema26     = df["close"].ewm(span=26, adjust=False).mean()
        df["MACD"]        = ema12 - ema26
        df["MACD_signal"] = df["MACD"].ewm(span=9, adjust=False).mean()
        df["MACD_hist"]   = df["MACD"] - df["MACD_signal"]

        latest  = df.iloc[-1]
        prev    = df.iloc[-2] if len(df) > 1 else latest

        score  = 50
        thesis = []

        price      = latest["close"]
        sma_20     = latest["SMA_20"]
        sma_50     = latest["SMA_50"]
        sma_200    = latest["SMA_200"]
        rsi        = latest["RSI"]

        # ── 1. Trend Structure ────────────────────────────────────────────────
        if pd.notna(sma_200):
            if price > sma_200:
                score += 18
                thesis.append("Long-term uptrend intact (price > 200-day SMA).")
            else:
                score -= 18
                thesis.append("Below 200-day SMA — stock in long-term downtrend.")

            if pd.notna(sma_50):
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
        else:
            # < 200 days — use SMA_50 only
            if pd.notna(sma_50):
                if price > sma_50:
                    score += 15
                    thesis.append("Price above 50-day SMA (insufficient history for 200 SMA).")
                else:
                    score -= 10
                    thesis.append("Price below 50-day SMA.")

        # Short-term pulse: price vs 20 SMA
        if pd.notna(sma_20):
            if price > sma_20:
                score += 4
                thesis.append("Short-term pulse positive (price > 20-day SMA).")
            else:
                score -= 3
                thesis.append("Short-term pulse negative (price < 20-day SMA).")

        # ── 2. MACD Signal ────────────────────────────────────────────────────
        macd_now  = latest["MACD"]
        macd_sig  = latest["MACD_signal"]
        macd_prev = prev["MACD"]
        macd_sp   = prev["MACD_signal"]

        if pd.notna(macd_now) and pd.notna(macd_sig):
            bullish_cross = (macd_now > macd_sig) and (macd_prev <= macd_sp)
            bearish_cross = (macd_now < macd_sig) and (macd_prev >= macd_sp)

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
                thesis.append(f"MACD neutral (MACD={macd_now:.3f}, signal={macd_sig:.3f}).")

        # ── 3. RSI ────────────────────────────────────────────────────────────
        if pd.notna(rsi):
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

        # ── 4. Volume Surge ───────────────────────────────────────────────────
        vols = df["volume"].dropna()
        if len(vols) >= 20:
            vol_5d  = vols.iloc[-5:].mean()
            vol_20d = vols.iloc[-20:].mean()
            if vol_20d > 0:
                vol_ratio = vol_5d / vol_20d
                if vol_ratio > 2.5:
                    score += 12
                    thesis.append(f"Volume explosion: {vol_ratio:.1f}× 20-day avg — strong institutional accumulation signal.")
                elif vol_ratio > 1.5:
                    score += 6
                    thesis.append(f"Above-average volume: {vol_ratio:.1f}× 20-day avg — demand confirmation.")
                elif vol_ratio < 0.5:
                    score -= 5
                    thesis.append(f"Volume drought: {vol_ratio:.1f}× 20-day avg — lack of conviction in the move.")
                else:
                    thesis.append(f"Volume normal: {vol_ratio:.1f}× 20-day avg.")

        # ── 5. Relative Strength vs Index (63-day / ~3 months) ────────────────
        # Fetch index price for comparison (SPY for US, ^NSEI proxy in macro_data)
        try:
            index_ticker = "^NSEI" if (".NS" in self.ticker or ".BO" in self.ticker) else "SPY"
            idx_rows = await self.db.execute(text("""
                SELECT close FROM stock_prices
                WHERE ticker = :t AND close IS NOT NULL
                ORDER BY time DESC LIMIT 64
            """), {"t": index_ticker})
            idx_prices = [r.close for r in idx_rows.fetchall()]

            if len(idx_prices) >= 63 and len(df) >= 63:
                # 63-day return
                stock_ret = (df["close"].iloc[-1] - df["close"].iloc[-63]) / df["close"].iloc[-63]
                idx_ret   = (idx_prices[0] - idx_prices[62]) / idx_prices[62]
                rs_delta  = stock_ret - idx_ret

                if rs_delta > 0.10:
                    score += 12
                    thesis.append(f"Strong relative strength: outperforming index by +{rs_delta*100:.1f}% over 3 months.")
                elif rs_delta > 0.03:
                    score += 5
                    thesis.append(f"Mild relative outperformance vs index (+{rs_delta*100:.1f}% over 3 months).")
                elif rs_delta < -0.10:
                    score -= 10
                    thesis.append(f"Underperforming index by {rs_delta*100:.1f}% over 3 months — weak RS.")
                elif rs_delta < -0.03:
                    score -= 4
                    thesis.append(f"Slight underperformance vs index ({rs_delta*100:.1f}% over 3 months).")
        except Exception:
            pass  # Index data unavailable — skip RS check silently

        # ── 6. Breakout Proximity (52-week high) ───────────────────────────────
        closes_52w = df["close"].iloc[-252:] if len(df) >= 252 else df["close"]
        high_52w   = closes_52w.max()
        if high_52w > 0:
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

        score = max(0, min(100, score))
        logger.info("TechnicalAgent %s: score=%d price=%.2f RSI=%.1f",
                    self.ticker, score, price, rsi if pd.notna(rsi) else -1)

        return {"score": score, "thesis": thesis}
