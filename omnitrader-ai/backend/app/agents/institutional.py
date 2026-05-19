from typing import Optional, List, Dict, Tuple
"""
agents/institutional.py
=======================
InstitutionalAgent — tracks smart-money behaviour for a ticker.

India tickers (.NS / .BO):
  • FII 30-day net flow trend (institutional_flows, entity_type='FII', market='INDIA')
  • Promoter holding change from previous quarter (promoter_holdings)

US tickers:
  • Volume anomaly: 5-day avg vs 90-day avg from stock_prices

Scoring rubric (starts at 50):
  Strong FII net buying (> +500 Cr aggregate)  → +20
  Moderate FII buying                          → +10
  FII net selling                              → −15
  Promoter holding increased                   → +15
  Promoter holding decreased                   → −10
  Volume spike > 2× 90d avg (US)              → +10
  Volume drought < 0.5× 90d avg               → −5
"""
import logging
from datetime import datetime, timedelta, timezone
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import text

logger = logging.getLogger(__name__)


class InstitutionalAgent:
    def __init__(self, db: AsyncSession, ticker: str):
        self.db = db
        self.ticker = ticker

    def _is_india(self) -> bool:
        return ".NS" in self.ticker or ".BO" in self.ticker

    async def _fii_net_30d(self) -> Optional[float]:
        """Sum of FII net_value over the last 30 trading days (India only)."""
        since = datetime.now(timezone.utc) - timedelta(days=35)
        query = text("""
            SELECT COALESCE(SUM(net_value), 0) AS total_net
            FROM institutional_flows
            WHERE entity_type = 'FII'
              AND market = 'INDIA'
              AND date >= :since
        """)
        result = await self.db.execute(query, {"since": since})
        row = result.fetchone()
        return row.total_net if row else None

    async def _promoter_delta(self) -> Optional[float]:
        """
        Change in promoter holding % from previous quarter to latest (India only).
        Returns None if < 2 quarters of data.
        """
        query = text("""
            SELECT promoter_pct, quarter_end
            FROM promoter_holdings
            WHERE ticker = :ticker
            ORDER BY quarter_end DESC
            LIMIT 2
        """)
        result = await self.db.execute(query, {"ticker": self.ticker})
        rows = result.fetchall()
        if len(rows) < 2:
            return None
        return rows[0].promoter_pct - rows[1].promoter_pct

    async def _volume_anomaly(self) -> Optional[float]:
        """
        Ratio of 5-day avg volume to 90-day avg volume.
        > 2.0 = volume spike; < 0.5 = drought.
        """
        query = text("""
            SELECT AVG(volume) AS avg_vol, COUNT(*) AS n
            FROM (
                SELECT volume FROM stock_prices
                WHERE ticker = :ticker AND volume IS NOT NULL
                ORDER BY time DESC
                LIMIT 90
            ) t
        """)
        r90 = await self.db.execute(query, {"ticker": self.ticker})
        row90 = r90.fetchone()
        if not row90 or not row90.avg_vol or row90.n < 20:
            return None

        query5 = text("""
            SELECT AVG(volume) AS avg_vol FROM (
                SELECT volume FROM stock_prices
                WHERE ticker = :ticker AND volume IS NOT NULL
                ORDER BY time DESC
                LIMIT 5
            ) t
        """)
        r5 = await self.db.execute(query5, {"ticker": self.ticker})
        row5 = r5.fetchone()
        if not row5 or not row5.avg_vol:
            return None

        return row5.avg_vol / row90.avg_vol

    async def analyze(self) -> dict:
        """
        Returns:
            {"score": int, "thesis": list[str]}
        """
        score  = 50
        thesis = []

        if self._is_india():
            # ── FII net flow ──────────────────────────────────────────────────
            try:
                fii_net = await self._fii_net_30d()
                if fii_net is not None:
                    if fii_net > 5000:
                        score += 20
                        thesis.append(f"FIIs strong net buyers (+₹{fii_net:,.0f} Cr in last 30 days).")
                    elif fii_net > 500:
                        score += 10
                        thesis.append(f"FIIs net buyers (+₹{fii_net:,.0f} Cr) — positive flow.")
                    elif fii_net < -500:
                        score -= 15
                        thesis.append(f"FIIs net sellers (₹{fii_net:,.0f} Cr) — institutional exit signal.")
                    else:
                        thesis.append(f"FII flows neutral (₹{fii_net:,.0f} Cr).")
            except Exception as e:
                logger.warning("FII flow fetch for %s: %s", self.ticker, e)
                thesis.append("FII flow data unavailable.")

            # ── Promoter holdings ─────────────────────────────────────────────
            try:
                delta = await self._promoter_delta()
                if delta is not None:
                    if delta > 0.5:
                        score += 15
                        thesis.append(f"Promoter holding increased by {delta:.1f}% — strong insider confidence.")
                    elif delta < -0.5:
                        score -= 10
                        thesis.append(f"Promoter holding decreased by {abs(delta):.1f}% — insider selling.")
                    else:
                        thesis.append(f"Promoter holding stable (Δ{delta:+.1f}%).")
                else:
                    thesis.append("Insufficient promoter holding history.")
            except Exception as e:
                logger.warning("Promoter delta fetch for %s: %s", self.ticker, e)
                thesis.append("Promoter holding data unavailable.")

        else:
            # ── US: volume anomaly ────────────────────────────────────────────
            try:
                vol_ratio = await self._volume_anomaly()
                if vol_ratio is not None:
                    if vol_ratio > 2.0:
                        score += 10
                        thesis.append(f"Volume spike: {vol_ratio:.1f}× 90-day average — institutional interest.")
                    elif vol_ratio > 1.3:
                        score += 5
                        thesis.append(f"Above-average volume ({vol_ratio:.1f}×) — mild accumulation signal.")
                    elif vol_ratio < 0.5:
                        score -= 5
                        thesis.append(f"Volume drought ({vol_ratio:.1f}×) — lack of conviction.")
                    else:
                        thesis.append(f"Normal volume ({vol_ratio:.1f}× 90d avg).")
                else:
                    thesis.append("Insufficient volume history for anomaly detection.")
            except Exception as e:
                logger.warning("Volume anomaly fetch for %s: %s", self.ticker, e)
                thesis.append("Volume data unavailable.")

        score = max(0, min(100, score))
        logger.info("InstitutionalAgent %s: score=%d", self.ticker, score)
        return {"score": score, "thesis": thesis}
