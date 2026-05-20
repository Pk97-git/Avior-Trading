"""
risk.py
=======
RiskAgent — prevents bad trades by scoring trade risk across 5 dimensions:
  1. Volatility risk  — ATR/price ratio; high volatility = risky
  2. Drawdown risk    — price vs 52-week high; deep correction = catch-a-falling-knife risk
  3. Leverage risk    — debt/equity from company_financials
  4. Liquidity risk   — volume_ratio; thinly traded = hard to exit
  5. Portfolio risk   — concentration vs existing positions; correlation penalty

Returns {"score": int, "thesis": list[str], "risk_flags": list[str]}
"""
import logging
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import text

logger = logging.getLogger("omnitrader.agent.risk")


class RiskAgent:
    def __init__(self, db: AsyncSession, ticker: str):
        self.db = db
        self.ticker = ticker

    async def analyze(self) -> dict:
        score = 60  # neutral baseline (not 50 — risk is usually manageable)
        thesis = []
        risk_flags = []

        # ── 1. Volatility risk ────────────────────────────────────────────────
        try:
            tech_row = await self.db.execute(
                text("""
                    SELECT atr_14, week_52_high, week_52_low, price_zscore_20d
                    FROM stock_technicals
                    WHERE ticker = :t
                    ORDER BY date DESC
                    LIMIT 1
                """),
                {"t": self.ticker},
            )
            tech = tech_row.fetchone()

            price_row = await self.db.execute(
                text("""
                    SELECT close
                    FROM stock_prices
                    WHERE ticker = :t
                    ORDER BY date DESC
                    LIMIT 1
                """),
                {"t": self.ticker},
            )
            price_rec = price_row.fetchone()
            latest_price = float(price_rec.close) if price_rec and price_rec.close else None

            if tech and latest_price and latest_price > 0 and tech.atr_14:
                atr = float(tech.atr_14)
                atr_ratio = atr / latest_price

                if atr_ratio > 0.05:
                    score -= 20
                    risk_flags.append("HIGH_VOLATILITY")
                    thesis.append(f"High volatility: ATR/price ratio {atr_ratio:.1%} exceeds 5% threshold.")
                elif atr_ratio > 0.03:
                    score -= 10
                    thesis.append(f"Elevated volatility: ATR/price ratio {atr_ratio:.1%}.")
                elif atr_ratio < 0.015:
                    score += 12
                    thesis.append(f"Low volatility: ATR/price ratio {atr_ratio:.1%} — stable price action.")

            if tech and tech.price_zscore_20d is not None:
                z = float(tech.price_zscore_20d)
                if z > 2.5:
                    score -= 8
                    thesis.append(f"Price overextended: 20d z-score = {z:.2f} (overbought risk).")
                elif z < -2.5:
                    score -= 5
                    thesis.append(f"Price in freefall: 20d z-score = {z:.2f} (falling knife risk).")

        except Exception as e:
            logger.warning("RiskAgent %s: volatility fetch failed: %s", self.ticker, e)

        # ── 2. Drawdown risk ──────────────────────────────────────────────────
        try:
            if tech and latest_price and tech.week_52_high:
                high_52w = float(tech.week_52_high)
                if high_52w > 0:
                    ratio = latest_price / high_52w

                    if ratio < 0.60:
                        score -= 15
                        risk_flags.append("DEEP_DRAWDOWN")
                        thesis.append(
                            f"Deep drawdown: price is {ratio:.0%} of 52-week high — catch-a-falling-knife risk."
                        )
                    elif ratio < 0.75:
                        score -= 8
                        thesis.append(f"Moderate drawdown: price at {ratio:.0%} of 52-week high.")
                    elif ratio > 0.95:
                        score += 8
                        thesis.append(f"Near 52-week highs ({ratio:.0%}): confirmed strength.")
        except Exception as e:
            logger.warning("RiskAgent %s: drawdown calc failed: %s", self.ticker, e)

        # ── 3. Leverage risk ──────────────────────────────────────────────────
        try:
            fin_row = await self.db.execute(
                text("""
                    SELECT debt_to_equity, free_cash_flow
                    FROM company_financials
                    WHERE ticker = :t
                    ORDER BY fiscal_date DESC
                    LIMIT 1
                """),
                {"t": self.ticker},
            )
            fin = fin_row.fetchone()

            if fin and fin.debt_to_equity is not None:
                de = float(fin.debt_to_equity)

                if de > 3.0:
                    score -= 18
                    risk_flags.append("EXCESSIVE_LEVERAGE")
                    thesis.append(f"Excessive leverage: D/E ratio = {de:.1f}x.")
                elif de > 2.0:
                    score -= 10
                    risk_flags.append("HIGH_LEVERAGE")
                    thesis.append(f"High leverage: D/E ratio = {de:.1f}x.")
                elif de < 0.5:
                    score += 10
                    thesis.append(f"Conservative balance sheet: D/E ratio = {de:.1f}x.")

                # Extra penalty: negative FCF + elevated leverage
                fcf = float(fin.free_cash_flow) if fin.free_cash_flow is not None else None
                if fcf is not None and fcf < 0 and de > 1.5:
                    score -= 8
                    risk_flags.append("CASH_BURN_RISK")
                    thesis.append(f"Cash burn risk: negative FCF with D/E = {de:.1f}x.")

        except Exception as e:
            logger.warning("RiskAgent %s: leverage fetch failed: %s", self.ticker, e)

        # ── 4. Liquidity risk ─────────────────────────────────────────────────
        try:
            liq_row = await self.db.execute(
                text("""
                    SELECT vol_ratio
                    FROM stock_technicals
                    WHERE ticker = :t
                    ORDER BY date DESC
                    LIMIT 1
                """),
                {"t": self.ticker},
            )
            liq = liq_row.fetchone()

            if liq and liq.vol_ratio is not None:
                vr = float(liq.vol_ratio)

                if vr < 0.3:
                    score -= 15
                    risk_flags.append("LOW_LIQUIDITY")
                    thesis.append(f"Low liquidity: volume ratio = {vr:.2f} — difficult to exit position.")
                elif vr < 0.6:
                    score -= 5
                    thesis.append(f"Below-average liquidity: volume ratio = {vr:.2f}.")
                elif vr > 1.5:
                    score += 5
                    thesis.append(f"High liquidity: volume ratio = {vr:.2f} — easy entry/exit.")

        except Exception as e:
            logger.warning("RiskAgent %s: liquidity fetch failed: %s", self.ticker, e)

        # ── 5. Portfolio concentration risk ───────────────────────────────────
        try:
            pos_rows = await self.db.execute(
                text("""
                    SELECT ticker, current_value, sector
                    FROM portfolio_positions
                    WHERE status = 'OPEN'
                    ORDER BY current_value DESC
                """),
            )
            positions = pos_rows.fetchall()

            if positions:
                total_portfolio_value = sum(
                    float(p.current_value) for p in positions if p.current_value
                )
                ticker_positions = [p for p in positions if p.ticker == self.ticker]
                ticker_value = sum(float(p.current_value) for p in ticker_positions if p.current_value)

                # Concentration in this ticker
                if total_portfolio_value > 0 and ticker_value / total_portfolio_value > 0.10:
                    score -= 15
                    risk_flags.append("CONCENTRATION_RISK")
                    conc_pct = ticker_value / total_portfolio_value * 100
                    thesis.append(
                        f"Concentration risk: {self.ticker} already represents {conc_pct:.0f}% of portfolio."
                    )

                # Sector concentration check
                ticker_sector_row = await self.db.execute(
                    text("SELECT sector FROM stocks WHERE ticker = :t"),
                    {"t": self.ticker},
                )
                ticker_sector_rec = ticker_sector_row.fetchone()
                ticker_sector = ticker_sector_rec.sector if ticker_sector_rec else None

                if ticker_sector and total_portfolio_value > 0:
                    sector_value = sum(
                        float(p.current_value)
                        for p in positions
                        if p.sector == ticker_sector and p.current_value
                    )
                    sector_pct = sector_value / total_portfolio_value
                    if sector_pct > 0.30:
                        score -= 8
                        thesis.append(
                            f"Sector concentration: {ticker_sector} already {sector_pct:.0%} of portfolio."
                        )

                # Over-diversification penalty
                if len(positions) > 20:
                    score -= 5
                    thesis.append(
                        f"Portfolio has {len(positions)} open positions — diluted alpha risk."
                    )

                # No existing position is a positive signal
                if not ticker_positions:
                    score += 5
                    thesis.append(f"Fresh allocation opportunity — {self.ticker} not currently held.")
            else:
                # Empty portfolio — no concentration risk
                score += 5
                thesis.append("No existing portfolio positions — fresh allocation opportunity.")

        except Exception as e:
            logger.warning("RiskAgent %s: portfolio fetch failed: %s", self.ticker, e)

        # Cap score to 0–100
        score = max(0, min(100, score))

        logger.info(
            "RiskAgent %s: score=%d flags=%s",
            self.ticker, score, risk_flags,
        )

        return {
            "score": score,
            "thesis": thesis,
            "risk_flags": risk_flags,
        }
