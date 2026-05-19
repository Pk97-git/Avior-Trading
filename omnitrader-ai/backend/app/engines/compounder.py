from typing import Optional, List, Dict, Tuple, Any
"""
engines/compounder.py
=====================
CompoundersEngine — screens MEDIUM-tier equities for long-term quality
using financial statement data already ingested.

Classification:
  COMPOUNDER        — high-quality business worth holding for years
  ACCUMULATION_ZONE — quality business but needs a better entry point
  OVERVALUED_WAIT   — good business but currently expensive
  INSUFFICIENT_DATA — not enough history to classify

Criteria for COMPOUNDER:
  • 5-period revenue CAGR > 12%   (uses available fiscal periods)
  • Latest ROIC > 15%
  • Latest D/E < 1.0
"""
import logging
import math
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import text

logger = logging.getLogger(__name__)

COMPOUNDER        = "COMPOUNDER"
ACCUMULATION_ZONE = "ACCUMULATION_ZONE"
OVERVALUED_WAIT   = "OVERVALUED_WAIT"
INSUFFICIENT_DATA = "INSUFFICIENT_DATA"


class CompoundersEngine:
    """Screens tickers for long-term compounding quality."""

    def __init__(self, db: AsyncSession):
        self.db = db

    def _cagr(self, start: float, end: float, periods: int) -> Optional[float]:
        """Annualised CAGR over `periods` fiscal periods (assumed ~1yr each)."""
        if not start or not end or start <= 0 or periods < 2:
            return None
        return (math.pow(end / start, 1.0 / periods) - 1) * 100

    async def classify_ticker(self, ticker: str) -> dict:
        """
        Classify a single ticker.

        Returns:
            {
                "ticker": str,
                "classification": str,
                "revenue_cagr_pct": Optional[float],
                "roic": Optional[float],
                "debt_to_equity": Optional[float],
                "periods_available": int,
                "reason": str,
            }
        """
        query = text("""
            SELECT fiscal_date, revenue, roic, debt_to_equity, pe_ratio
            FROM company_financials
            WHERE ticker = :ticker
            ORDER BY fiscal_date ASC
        """)
        result = await self.db.execute(query, {"ticker": ticker})
        rows = result.fetchall()

        if len(rows) < 2:
            return {
                "ticker": ticker,
                "classification": INSUFFICIENT_DATA,
                "revenue_cagr_pct": None,
                "roic": None,
                "debt_to_equity": None,
                "periods_available": len(rows),
                "reason": "Need at least 2 fiscal periods.",
            }

        first = rows[0]
        last  = rows[-1]
        n     = len(rows)

        # Use up to 5 most recent periods for CAGR calculation
        cagr_start = rows[max(0, n - 6)]
        cagr_periods = min(n - 1, 5)
        rev_cagr = self._cagr(cagr_start.revenue, last.revenue, cagr_periods)

        roic = last.roic
        de   = last.debt_to_equity
        pe   = last.pe_ratio

        # Classify
        quality_score = 0
        if rev_cagr is not None and rev_cagr > 12:
            quality_score += 1
        if roic is not None and roic > 15:
            quality_score += 1
        if de is not None and de < 1.0:
            quality_score += 1

        if quality_score == 3:
            classification = COMPOUNDER
            reason = f"Revenue CAGR {rev_cagr:.1f}%, ROIC {roic:.1f}%, D/E {de:.2f} — all criteria met."
        elif quality_score == 2:
            # Good business — check valuation via P/E
            if pe is not None and pe > 40:
                classification = OVERVALUED_WAIT
                reason = f"Quality business (score {quality_score}/3) but P/E={pe:.0f} is elevated."
            else:
                classification = ACCUMULATION_ZONE
                reason = f"Quality business (score {quality_score}/3). Reasonable valuation."
        else:
            classification = ACCUMULATION_ZONE
            reason = f"Moderate quality (score {quality_score}/3). Monitor for improvement."

        return {
            "ticker": ticker,
            "classification": classification,
            "revenue_cagr_pct": round(rev_cagr, 1) if rev_cagr is not None else None,
            "roic": round(roic, 1) if roic is not None else None,
            "debt_to_equity": round(de, 2) if de is not None else None,
            "pe_ratio": round(pe, 1) if pe is not None else None,
            "periods_available": n,
            "reason": reason,
        }

    async def screen(self, tickers: list[str]) -> list[dict]:
        """
        Screen a list of tickers and return classifications, sorted by quality.
        """
        results = []
        for ticker in tickers:
            try:
                r = await self.classify_ticker(ticker)
                results.append(r)
            except Exception as e:
                logger.warning("Compounder screen failed for %s: %s", ticker, e)

        # Sort: COMPOUNDER first, then ACCUMULATION_ZONE, then others
        order = {COMPOUNDER: 0, ACCUMULATION_ZONE: 1, OVERVALUED_WAIT: 2, INSUFFICIENT_DATA: 3}
        results.sort(key=lambda x: order.get(x["classification"], 9))
        return results
