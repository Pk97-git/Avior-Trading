"""
fo_ban.py
=========
Fetches the NSE F&O ban list daily and updates the is_fo_banned flag
on the stocks table for India equities.

Stocks enter the ban when their open interest exceeds 95% of the
Market Wide Position Limit (MWPL). They exit when OI drops below 80%.
New positions (buy/sell) in F&O are not allowed during the ban period.
"""
import logging

import httpx
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import text

logger = logging.getLogger(__name__)

_NSE_BAN_URL = "https://archives.nseindia.com/content/fo/fo_secban.csv"
_NSE_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Referer": "https://www.nseindia.com/",
}


class FoBanService:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def fetch_ban_list(self) -> list[str]:
        """Returns list of NSE symbols currently in F&O ban."""
        try:
            async with httpx.AsyncClient(timeout=15, follow_redirects=True) as client:
                resp = await client.get(_NSE_BAN_URL, headers=_NSE_HEADERS)
                if resp.status_code != 200:
                    logger.warning("NSE F&O ban list returned %d", resp.status_code)
                    return []
                symbols = []
                for line in resp.text.strip().splitlines():
                    s = line.strip()
                    if s and not s.lower().startswith("symbol"):
                        symbols.append(s.upper())
                return symbols
        except Exception as e:
            logger.error("FoBanService fetch failed: %s", e)
            return []

    async def update_ban_flags(self) -> dict:
        """Reset all India stock ban flags, then set banned ones."""
        banned_symbols = await self.fetch_ban_list()

        # Reset all India equities
        await self.db.execute(text("""
            UPDATE stocks
            SET is_fo_banned = FALSE, fo_ban_updated = NOW()
            WHERE ticker LIKE '%.NS' OR ticker LIKE '%.BO'
        """))

        # Set currently banned tickers
        for symbol in banned_symbols:
            ns_ticker = f"{symbol}.NS"
            await self.db.execute(text("""
                UPDATE stocks
                SET is_fo_banned = TRUE, fo_ban_updated = NOW()
                WHERE ticker = :t
            """), {"t": ns_ticker})

        await self.db.commit()
        logger.info("FoBanService: %d symbols in F&O ban", len(banned_symbols))
        return {"banned_count": len(banned_symbols), "symbols": banned_symbols}
