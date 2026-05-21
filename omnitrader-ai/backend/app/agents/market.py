"""
market.py
=========
MarketAgent — understands current market conditions.
Distinct from MacroAgent (economic indicators).
Focuses on market internals: breadth, volatility regime, sector rotation.

Score 0–100 (100 = ideal market conditions to trade, 50 = neutral):
  1. VIX regime       — fear gauge level
  2. Market breadth   — % stocks above 200 SMA (pre-computed in stock_technicals)
  3. Sector rotation  — momentum of sector ETFs (from macro_data sector proxies)
  4. Volatility trend — is VIX rising or falling? (VIX direction matters more than level)
  5. Index trend      — SPX or NSEI above/below their own 50/200 SMA

Returns {"score": int, "thesis": list[str], "market_regime": str}
"""
import logging
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import text

logger = logging.getLogger("omnitrader.agent.market")


class MarketAgent:
    def __init__(self, db: AsyncSession, ticker: str):
        self.db = db
        self.ticker = ticker  # used to determine India vs US market context

    async def analyze(self) -> dict:
        score = 50
        thesis = []
        market_regime = "Unknown"

        is_india = ".NS" in self.ticker or ".BO" in self.ticker

        # ── Dimension 1: VIX regime ──────────────────────────────────────────
        try:
            vix_res = await self.db.execute(text("""
                SELECT value, time FROM macro_data
                WHERE indicator = 'VIX' ORDER BY time DESC LIMIT 5
            """))
            vix_rows = vix_res.fetchall()
            if vix_rows:
                v = float(vix_rows[0].value)
                if v < 15:
                    score += 15
                    thesis.append(f"Low volatility regime (VIX {v:.1f}) — ideal trading conditions.")
                elif v <= 20:
                    score += 8
                    thesis.append(f"Moderate volatility (VIX {v:.1f}) — healthy market.")
                elif v <= 30:
                    score -= 5
                    thesis.append(f"Elevated volatility (VIX {v:.1f}) — proceed with caution.")
                else:
                    score -= 18
                    thesis.append(f"High fear regime (VIX {v:.1f}) — significant market stress.")
                    if v > 40:
                        score -= 7  # extra delta to reach -25 total vs base -18
                        market_regime = "Extreme Fear"

                # VIX direction (latest vs oldest of the 5 rows)
                if len(vix_rows) >= 2:
                    v_old = float(vix_rows[-1].value)
                    vix_delta = v - v_old
                    if vix_delta > 3:
                        score -= 8
                        thesis.append("VIX rising — fear accelerating.")
                    elif vix_delta < -3:
                        score += 6
                        thesis.append("VIX falling — fear subsiding.")
        except Exception as e:
            logger.debug("VIX query failed: %s", e)

        # ── Dimension 2: Market breadth ──────────────────────────────────────
        try:
            breadth_res = await self.db.execute(text("""
                SELECT
                    COUNT(*) FILTER (WHERE sma_200 IS NOT NULL AND close > sma_200)::float /
                    NULLIF(COUNT(*) FILTER (WHERE sma_200 IS NOT NULL), 0) AS pct_above_200
                FROM stock_technicals st
                JOIN (
                    SELECT DISTINCT ON (ticker) ticker, close FROM stock_prices ORDER BY ticker, time DESC
                ) sp ON sp.ticker = st.ticker
                WHERE st.date = (SELECT MAX(date) FROM stock_technicals)
            """))
            breadth_row = breadth_res.fetchone()
            if breadth_row and breadth_row.pct_above_200 is not None:
                pct = float(breadth_row.pct_above_200)
                if pct > 0.70:
                    score += 15
                    thesis.append(f"Strong breadth: {pct:.0%} of stocks above 200 SMA.")
                elif pct > 0.55:
                    score += 8
                    thesis.append(f"Good breadth: {pct:.0%} above 200 SMA.")
                elif pct < 0.35:
                    score -= 15
                    thesis.append(f"Weak breadth: only {pct:.0%} above 200 SMA — broad market decline.")
                elif pct < 0.45:
                    score -= 8
                    thesis.append(f"Narrowing breadth: {pct:.0%} above 200 SMA.")

                # Set market_regime based on breadth (only overwrite if not already "Extreme Fear")
                if market_regime != "Extreme Fear":
                    if pct > 0.65:
                        market_regime = "Bull Market"
                    elif pct > 0.45:
                        market_regime = "Mixed"
                    else:
                        market_regime = "Bear Market"
        except Exception as e:
            logger.debug("Market breadth query failed: %s", e)

        # ── Dimension 3: Index trend ─────────────────────────────────────────
        try:
            index_ticker = "^NSEI" if is_india else "^GSPC"
            tech_res = await self.db.execute(text("""
                SELECT sma_50, sma_200, date FROM stock_technicals
                WHERE ticker = :index_ticker ORDER BY date DESC LIMIT 1
            """), {"index_ticker": index_ticker})
            tech_row = tech_res.fetchone()

            # Fallback to SPY for US if ^GSPC not found
            if tech_row is None and not is_india:
                tech_res = await self.db.execute(text("""
                    SELECT sma_50, sma_200, date FROM stock_technicals
                    WHERE ticker = 'SPY' ORDER BY date DESC LIMIT 1
                """))
                tech_row = tech_res.fetchone()
                index_ticker = "SPY"

            if tech_row:
                price_res = await self.db.execute(text("""
                    SELECT close FROM stock_prices WHERE ticker = :index_ticker ORDER BY time DESC LIMIT 1
                """), {"index_ticker": index_ticker})
                price_row = price_res.fetchone()

                if price_row and tech_row.sma_50 and tech_row.sma_200:
                    price = float(price_row.close)
                    sma50 = float(tech_row.sma_50)
                    sma200 = float(tech_row.sma_200)

                    if price > sma50 and sma50 > sma200:
                        score += 12
                        thesis.append("Index in bull trend (Golden Cross active).")
                    elif price > sma200:
                        score += 6
                        thesis.append("Index above 200 SMA — long-term trend positive.")
                    elif price < sma50 and sma50 < sma200:
                        score -= 15
                        thesis.append("Index Death Cross — broad market bearish.")
                    else:
                        score -= 10
                        thesis.append("Index below 200 SMA — broad market in downtrend.")
        except Exception as e:
            logger.debug("Index trend query failed: %s", e)

        # ── Dimension 4: Sector rotation (bonus) ────────────────────────────
        try:
            sector_res = await self.db.execute(text("""
                SELECT indicator, value, time FROM macro_data
                WHERE indicator IN ('XLK_PRICE', 'XLF_PRICE', 'XLE_PRICE', 'NIFTY_IT', 'NIFTY_BANK')
                  AND time > NOW() - INTERVAL '7 days'
                ORDER BY indicator, time DESC
            """))
            sector_rows = sector_res.fetchall()
            if sector_rows:
                # Group by indicator — get latest 2 values per indicator
                from collections import defaultdict
                sector_vals: dict = defaultdict(list)
                for row in sector_rows:
                    sector_vals[row.indicator].append(float(row.value))

                up_count = 0
                checked = 0
                for indicator, vals in sector_vals.items():
                    if len(vals) >= 2:
                        checked += 1
                        if vals[0] > vals[1]:  # latest > previous
                            up_count += 1

                if checked > 0:
                    if up_count > 2:
                        score += 5
                        thesis.append("Broad sector participation — healthy rotation.")
                    elif up_count < 1:
                        score -= 5
                        thesis.append("Narrow sector leadership — weak rotation.")
        except Exception as e:
            logger.debug("Sector rotation query skipped: %s", e)

        # Cap score at 0–100
        score = max(0, min(100, score))

        return {"score": score, "thesis": thesis, "market_regime": market_regime}
