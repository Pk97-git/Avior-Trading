"""
earnings_surprise.py
====================
Fetches analyst consensus EPS estimates and computes earnings surprise %
from yfinance quarterly_earnings data.

Updates eps_estimate and eps_surprise_pct columns in company_financials.
"""
import logging

from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import text

logger = logging.getLogger(__name__)


class EarningsSurpriseService:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def update_for_ticker(self, ticker: str) -> int:
        try:
            import yfinance as yf
            t = yf.Ticker(ticker)
            qe = t.quarterly_earnings
            if qe is None or qe.empty:
                return 0

            count = 0
            for dt_idx, row in qe.iterrows():
                actual   = row.get("Earnings")
                estimate = row.get("Estimate")
                if actual is None or estimate is None or estimate == 0:
                    continue
                surprise_pct = float((actual - estimate) / abs(estimate) * 100)
                fiscal_date  = dt_idx.date() if hasattr(dt_idx, "date") else dt_idx

                result = await self.db.execute(text("""
                    UPDATE company_financials
                    SET eps_estimate = :est, eps_surprise_pct = :surp
                    WHERE ticker = :ticker
                      AND fiscal_date::date BETWEEN :fd - INTERVAL '45 days'
                                                AND :fd + INTERVAL '45 days'
                """), {
                    "ticker": ticker,
                    "est":    float(estimate),
                    "surp":   surprise_pct,
                    "fd":     fiscal_date,
                })
                count += result.rowcount

            await self.db.commit()
            return count
        except Exception as e:
            logger.debug("EarningsSurprise %s: %s", ticker, e)
            return 0

    async def run_batch(self, tickers: list[str]) -> dict:
        total, failed = 0, 0
        for ticker in tickers:
            try:
                n = await self.update_for_ticker(ticker)
                total += n
            except Exception:
                failed += 1
        return {"updated": total, "failed": failed}
