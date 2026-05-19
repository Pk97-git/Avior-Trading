"""
short_interest.py
=================
Fetches short interest data (short ratio, % of float shorted) via yfinance.
Stored in short_interest table; refreshed weekly for HIGH-tier US equities.
"""
import logging
from datetime import date

from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.market_data import ShortInterest

logger = logging.getLogger(__name__)


class ShortInterestService:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def fetch_for_ticker(self, ticker: str) -> dict | None:
        try:
            import yfinance as yf
            info = yf.Ticker(ticker).info
            return {
                "short_ratio":     info.get("shortRatio"),
                "short_pct_float": info.get("shortPercentOfFloat"),
                "shares_short":    info.get("sharesShort"),
            }
        except Exception as e:
            logger.debug("ShortInterest fetch failed for %s: %s", ticker, e)
            return None

    async def upsert(self, ticker: str, data: dict) -> bool:
        record = {
            "ticker":          ticker,
            "date":            date.today(),
            "short_ratio":     data.get("short_ratio"),
            "short_pct_float": data.get("short_pct_float"),
            "shares_short":    data.get("shares_short"),
        }
        stmt = pg_insert(ShortInterest).values([record])
        stmt = stmt.on_conflict_do_update(
            constraint="uq_short_interest_ticker_date",
            set_={c: stmt.excluded[c] for c in record if c not in ("ticker", "date")},
        )
        await self.db.execute(stmt)
        await self.db.commit()
        return True

    async def run_batch(self, tickers: list[str]) -> dict:
        success, failed = 0, []
        for ticker in tickers:
            try:
                data = await self.fetch_for_ticker(ticker)
                if data and any(v is not None for v in data.values()):
                    await self.upsert(ticker, data)
                    success += 1
            except Exception as e:
                logger.error("ShortInterest batch error %s: %s", ticker, e)
                failed.append(ticker)
        return {"success": success, "failed": len(failed)}
