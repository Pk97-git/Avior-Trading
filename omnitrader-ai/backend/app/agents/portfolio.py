from typing import Optional, List, Dict, Tuple
"""
agents/portfolio.py
====================
Portfolio Exposure & Correlation Control

For the current STRONG_BUY + ACCUMULATE universe, this module:
  1. Computes sector concentration (Herfindahl index)
  2. Checks pairwise correlation for the top-50 signals
  3. Flags if adding a new ticker would break diversification rules

Rules:
  - Max single-sector weight: 30% of signal count
  - Max pairwise correlation: 0.70 (over 90 days)
  - If either rule is breached, score is penalised

Returns:
    {
        "diversification_score": int (0-100),
        "sector_concentration":  float (0-1, 0=perfectly diversified),
        "max_correlation":       Optional[float],
        "correlated_peer":       Optional[str],  # ticker most correlated with this one
        "thesis":                list[str],
    }
"""
import logging
from datetime import datetime, timedelta, timezone

from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import text

logger = logging.getLogger(__name__)

MAX_SECTOR_WEIGHT = 0.30
MAX_PAIR_CORRELATION = 0.70
LOOKBACK_DAYS = 90
TOP_N_PEERS = 20   # only check correlations vs top N signals (performance)


def _pearson(x: list[float], y: list[float]) -> Optional[float]:
    n = min(len(x), len(y))
    if n < 15:
        return None
    x, y = x[-n:], y[-n:]
    mx, my = sum(x)/n, sum(y)/n
    num   = sum((xi-mx)*(yi-my) for xi, yi in zip(x, y))
    den_x = sum((xi-mx)**2 for xi in x) ** 0.5
    den_y = sum((yi-my)**2 for yi in y) ** 0.5
    if den_x == 0 or den_y == 0:
        return None
    return round(num / (den_x * den_y), 3)


def _pct_returns(closes: list[float]) -> list[float]:
    return [(closes[i]-closes[i-1])/closes[i-1] for i in range(1, len(closes)) if closes[i-1] != 0]


class PortfolioAgent:
    def __init__(self, db: AsyncSession, ticker: str):
        self.db = db
        self.ticker = ticker.upper()

    async def analyze(self) -> dict:
        try:
            # Step 1: Get current STRONG_BUY/ACCUMULATE universe
            res = await self.db.execute(text("""
                SELECT DISTINCT ON (a.ticker) a.ticker, s.sector
                FROM ai_analysis a
                LEFT JOIN stocks s ON s.ticker = a.ticker
                WHERE a.signal IN ('STRONG_BUY', 'ACCUMULATE')
                  AND a.analysis_date >= NOW() - INTERVAL '7 days'
                ORDER BY a.ticker, a.analysis_date DESC
                LIMIT 200
            """))
            signals = res.fetchall()

            if not signals:
                return {
                    "diversification_score": 70,
                    "sector_concentration": 0.0,
                    "max_correlation": None,
                    "correlated_peer": None,
                    "thesis": ["No active signals to compare against."],
                }

            # Step 2: Sector concentration (Herfindahl index)
            sector_counts: dict[str, int] = {}
            for row in signals:
                sector = row.sector or "Unknown"
                sector_counts[sector] = sector_counts.get(sector, 0) + 1

            n = len(signals)
            sector_weights = {s: c/n for s, c in sector_counts.items()}
            hhi = sum(w**2 for w in sector_weights.values())  # 0 = diversified, 1 = concentrated

            # Get this ticker's sector
            this_sector_res = await self.db.execute(
                text("SELECT sector FROM stocks WHERE ticker = :t"), {"t": self.ticker}
            )
            this_sector_row = this_sector_res.fetchone()
            this_sector = this_sector_row.sector if this_sector_row else "Unknown"
            this_sector_weight = sector_weights.get(this_sector, 0.0)

            # Step 3: Pairwise correlation vs top peers
            peers = [r.ticker for r in signals if r.ticker != self.ticker][:TOP_N_PEERS]
            since = datetime.now(timezone.utc) - timedelta(days=LOOKBACK_DAYS + 5)

            this_closes = await self._get_closes(self.ticker, since)
            this_rets = _pct_returns(this_closes) if len(this_closes) > 10 else []

            max_corr = None
            max_peer = None

            if this_rets:
                for peer in peers:
                    peer_closes = await self._get_closes(peer, since)
                    peer_rets = _pct_returns(peer_closes) if len(peer_closes) > 10 else []
                    corr = _pearson(this_rets, peer_rets)
                    if corr is not None and (max_corr is None or abs(corr) > abs(max_corr)):
                        max_corr = corr
                        max_peer = peer

            # Step 4: Score
            sector_penalty = max(0, (this_sector_weight - MAX_SECTOR_WEIGHT) * 200)
            corr_penalty   = max(0, ((max_corr or 0) - MAX_PAIR_CORRELATION) * 100) if max_corr else 0
            div_score = int(max(20, min(100, 80 - sector_penalty - corr_penalty)))

            thesis = []
            if this_sector_weight > MAX_SECTOR_WEIGHT:
                thesis.append(f"⚠️ Sector '{this_sector}' is {this_sector_weight:.0%} of active signals (limit 30%).")
            else:
                thesis.append(f"Sector '{this_sector}' weight: {this_sector_weight:.0%} — within diversification limits.")

            if max_corr is not None and max_corr > MAX_PAIR_CORRELATION:
                thesis.append(f"⚠️ High correlation with {max_peer} (ρ={max_corr:.2f}) — reduces diversification value.")
            elif max_corr is not None:
                thesis.append(f"Max peer correlation: ρ={max_corr:.2f} vs {max_peer} — acceptable.")

            return {
                "diversification_score": div_score,
                "sector_concentration":  round(hhi, 4),
                "max_correlation":       max_corr,
                "correlated_peer":       max_peer,
                "thesis":                thesis,
            }

        except Exception as e:
            logger.error("PortfolioAgent failed for %s: %s", self.ticker, e)
            return {
                "diversification_score": 60,
                "sector_concentration": 0.0,
                "max_correlation": None,
                "correlated_peer": None,
                "thesis": ["Portfolio analysis unavailable."],
            }

    async def _get_closes(self, ticker: str, since: str) -> list[float]:
        res = await self.db.execute(text("""
            SELECT close FROM stock_prices
            WHERE ticker = :t AND time >= :since AND close IS NOT NULL
            ORDER BY time ASC
        """), {"t": ticker, "since": since})
        return [r.close for r in res.fetchall()]
