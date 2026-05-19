#!/usr/bin/env python3
"""
populate_universe.py
=====================
Fetches the real stock universe and populates ONLY the `stocks` metadata table.
No price history. No fundamentals. Just the list of tradable stocks.

Sources:
  US  → S&P 500 + Nasdaq 100 (Wikipedia)
  IN  → Nifty 500 + Nifty Midcap 100 (NSE API)
  +   → Crypto (BTC, ETH...) and Major Indices (^GSPC, ^NSEI...)

Run:
    source venv/bin/activate
    python populate_universe.py
"""
import asyncio
import sys
import time

sys.path.insert(0, ".")
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.dialects.postgresql import insert as pg_insert
from app.core.config import settings
from app.models.market_data import Stock
from app.ingestion.infra.universe import (
    fetch_sp500, fetch_nasdaq100,
    fetch_nifty500, fetch_nifty_midcap,
    CRYPTO_UNIVERSE, INDEX_UNIVERSE, MACRO_UNIVERSE,
)

engine = create_async_engine(settings.SQLALCHEMY_DATABASE_URI, echo=False)
Session = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)


def build_records() -> list[dict]:
    """Fetch all tickers and return dicts ready for DB insertion."""
    records = []
    seen = set()

    def add(ticker, country, sector, industry):
        if ticker not in seen:
            seen.add(ticker)
            records.append({
                "ticker": ticker,
                "country": country,
                "sector": sector,
                "industry": industry,
                "name": ticker,   # name will be enriched later during price ingestion
                "meta_data": {},
            })

    print("📡 Fetching universe...")

    sp500 = fetch_sp500()
    print(f"  S&P 500       : {len(sp500):>5} tickers")
    for t in sp500:
        add(t, "US", None, None)

    nasdaq = fetch_nasdaq100()
    print(f"  Nasdaq 100    : {len(nasdaq):>5} tickers")
    for t in nasdaq:
        add(t, "US", None, None)

    nifty500 = fetch_nifty500()
    print(f"  Nifty 500     : {len(nifty500):>5} tickers")
    for t in nifty500:
        add(t, "IN", None, None)

    midcap = fetch_nifty_midcap()
    print(f"  Nifty Midcap  : {len(midcap):>5} tickers")
    for t in midcap:
        add(t, "IN", None, None)

    for t in CRYPTO_UNIVERSE:
        add(t, "Other", "Crypto", "Cryptocurrency")
    for t in INDEX_UNIVERSE:
        add(t, "Other", "Index", "Market Index")
    for t in MACRO_UNIVERSE:
        add(t, "Other", "Macro", "Commodity/FX")

    print(f"\n  US   : {sum(1 for r in records if r['country'] == 'US'):>5}")
    print(f"  IN   : {sum(1 for r in records if r['country'] == 'IN'):>5}")
    print(f"  Other: {sum(1 for r in records if r['country'] == 'Other'):>5}")
    print(f"  TOTAL: {len(records):>5}\n")
    return records


async def insert_records(session: AsyncSession, records: list[dict]):
    CHUNK = 500
    inserted = 0
    for i in range(0, len(records), CHUNK):
        chunk = records[i:i + CHUNK]
        stmt = pg_insert(Stock).values(chunk)
        stmt = stmt.on_conflict_do_update(
            index_elements=["ticker"],
            set_={
                "country": stmt.excluded.country,
                "sector": stmt.excluded.sector,
                "industry": stmt.excluded.industry,
            }
        )
        await session.execute(stmt)
        await session.commit()
        inserted += len(chunk)
        print(f"  Inserted {inserted}/{len(records)}...", end="\r")
    print(f"  ✅ {len(records)} stocks inserted into `stocks` table.   ")


async def main():
    t0 = time.time()
    print("=" * 50)
    print("  OmniTrader AI — Universe Population")
    print("=" * 50)

    records = build_records()

    print("📥 Writing to database...")
    async with Session() as session:
        await insert_records(session, records)

    print(f"\n✅ Done in {time.time() - t0:.1f}s")
    print("   Next: run price ingestion via POST /ingestion/trigger-now/initial_load\n")


if __name__ == "__main__":
    asyncio.run(main())
