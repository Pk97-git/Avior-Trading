"""
dividends.py
============
Fetches dividend history and forward yield via yfinance.
Stored in dividends table; refreshed weekly for MEDIUM-tier equities.
"""
import logging

import pandas as pd
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.market_data import Dividend

logger = logging.getLogger(__name__)


class DividendService:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def fetch_and_store(self, ticker: str) -> int:
        try:
            import yfinance as yf
            t = yf.Ticker(ticker)
            divs = t.dividends
            if divs is None or len(divs) == 0:
                return 0

            # Forward yield from info
            yield_fwd = None
            try:
                info = t.info
                raw_yield = info.get("dividendYield")
                if raw_yield:
                    yield_fwd = float(raw_yield) * 100
            except Exception:
                pass

            # 5-year dividend CAGR
            div_cagr_5y = None
            try:
                divs_sorted = divs.sort_index()
                cutoff = pd.Timestamp.now(tz="UTC") - pd.DateOffset(years=5)
                recent_annual = divs_sorted.last("365D").sum()
                old_window = divs_sorted[
                    (divs_sorted.index >= cutoff) &
                    (divs_sorted.index < cutoff + pd.DateOffset(years=1))
                ].sum()
                if old_window > 0 and recent_annual > 0:
                    div_cagr_5y = round(((recent_annual / old_window) ** (1 / 5) - 1) * 100, 2)
            except Exception:
                pass

            records = []
            for dt, amount in divs.items():
                ex_date = dt.date() if hasattr(dt, "date") else dt
                records.append({
                    "ticker":      ticker,
                    "ex_date":     ex_date,
                    "amount":      float(amount),
                    "yield_fwd":   yield_fwd,
                    "div_cagr_5y": div_cagr_5y,
                })

            if not records:
                return 0

            stmt = pg_insert(Dividend).values(records)
            stmt = stmt.on_conflict_do_update(
                constraint="uq_dividend_ticker_exdate",
                set_={c: stmt.excluded[c] for c in records[0] if c not in ("ticker", "ex_date")},
            )
            await self.db.execute(stmt)
            await self.db.commit()
            return len(records)
        except Exception as e:
            logger.error("DividendService %s: %s", ticker, e)
            return 0

    async def run_batch(self, tickers: list[str]) -> dict:
        total, failed = 0, 0
        for ticker in tickers:
            try:
                n = await self.fetch_and_store(ticker)
                total += n
            except Exception:
                failed += 1
        return {"rows": total, "failed": failed}
