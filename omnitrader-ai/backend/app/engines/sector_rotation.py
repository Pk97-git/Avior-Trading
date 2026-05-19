from typing import Optional, List, Dict, Tuple, Any
"""
engines/sector_rotation.py
==========================
SectorRotationEngine — reads stock_prices for the 11 SPDR sector ETFs
and calculates 4-week and 12-week relative performance.

Returns a ranked list of sectors so the MacroAgent and MarketAnalysis
view can identify which sectors have momentum.
"""
import logging
from datetime import datetime, timedelta, timezone
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import text

logger = logging.getLogger(__name__)

# SPDR sector ETFs — available in stock_prices if sector ETF ingestion ran
SECTOR_ETFS = {
    "Technology":         "XLK",
    "Financials":         "XLF",
    "Healthcare":         "XLV",
    "Energy":             "XLE",
    "Consumer Disc":      "XLY",
    "Consumer Staples":   "XLP",
    "Industrials":        "XLI",
    "Materials":          "XLB",
    "Utilities":          "XLU",
    "Real Estate":        "XLRE",
    "Communication":      "XLC",
}


class SectorRotationEngine:
    """Ranks sectors by short-term (4W) and medium-term (12W) price momentum."""

    def __init__(self, db: AsyncSession):
        self.db = db

    async def _fetch_etf_prices(self, ticker: str, since: datetime) -> list[dict]:
        query = text("""
            SELECT time, close FROM stock_prices
            WHERE ticker = :ticker AND time >= :since AND close IS NOT NULL
            ORDER BY time ASC
        """)
        result = await self.db.execute(query, {"ticker": ticker, "since": since})
        return [{"time": r.time, "close": r.close} for r in result.fetchall()]

    def _pct_change(self, rows: list[dict], weeks: int) -> Optional[float]:
        """Return % change over last `weeks` weeks. None if insufficient data."""
        if not rows:
            return None
        cutoff = datetime.now(timezone.utc) - timedelta(weeks=weeks)
        old_rows = [r for r in rows if r["time"] <= cutoff]
        if not old_rows:
            return None
        old_price = old_rows[-1]["close"]
        new_price = rows[-1]["close"]
        if old_price == 0:
            return None
        return round(((new_price - old_price) / old_price) * 100, 2)

    async def calculate(self) -> list[dict]:
        """
        Calculate 4W and 12W returns for all 11 sectors.

        Returns a list sorted by 4W performance (best first):
            [
                {
                    "sector": "Technology",
                    "etf": "XLK",
                    "change_4w": 3.2,
                    "change_12w": 8.1,
                    "rank_4w": 1,
                },
                ...
            ]
        """
        since = datetime.now(timezone.utc) - timedelta(weeks=13)
        results = []

        for sector, etf in SECTOR_ETFS.items():
            try:
                rows = await self._fetch_etf_prices(etf, since)
                c4  = self._pct_change(rows, weeks=4)
                c12 = self._pct_change(rows, weeks=12)
                results.append({
                    "sector": sector,
                    "etf": etf,
                    "change_4w": c4,
                    "change_12w": c12,
                    "current_price": rows[-1]["close"] if rows else None,
                })
            except Exception as e:
                logger.warning("Sector ETF %s (%s): %s", etf, sector, e)
                results.append({
                    "sector": sector,
                    "etf": etf,
                    "change_4w": None,
                    "change_12w": None,
                    "current_price": None,
                })

        # Sort by 4W change — None values go to end
        results.sort(key=lambda x: x["change_4w"] if x["change_4w"] is not None else -999,
                     reverse=True)

        for i, r in enumerate(results):
            r["rank_4w"] = i + 1

        return results
