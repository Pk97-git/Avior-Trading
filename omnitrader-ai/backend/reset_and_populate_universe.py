#!/usr/bin/env python3
"""
reset_and_populate_universe.py
================================
Step 1: Truncates ALL tables (clean slate)
Step 2: Fetches the real universe of stocks from:
        - S&P 500 (Wikipedia)
        - Nasdaq 100 (Wikipedia)
        - Nifty 500 (NSE India API)
        - Nifty Midcap 100 (NSE India API)
        Plus: Crypto (BTC, ETH, etc.) and Major Indices (^GSPC, ^NSEI, ...)

Only populates the `stocks` metadata table.
NO price history is fetched here.

Run:
    source venv/bin/activate
    python reset_and_populate_universe.py
"""

import asyncio
import sys
import time

from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy import text

# ── App imports ───────────────────────────────────────────────────────────────
sys.path.insert(0, ".")
from app.core.config import settings
from app.models.market_data import (
    Stock, StockPrice, CompanyFinancials, MacroEconomicData,
    InstitutionalFlow, NewsSentiment, PromoterHolding, MarketSnapshot
)
from app.ingestion.infra.universe import (
    fetch_sp500, fetch_nasdaq100, fetch_nifty500, fetch_nifty_midcap,
    CRYPTO_UNIVERSE, INDEX_UNIVERSE, MACRO_UNIVERSE
)

# ── Engine Setup ──────────────────────────────────────────────────────────────
engine = create_async_engine(settings.SQLALCHEMY_DATABASE_URI, echo=False)
Session = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

# ── Universe Definition ───────────────────────────────────────────────────────

def build_universe():
    """Fetch all ticker lists and return as a list of (ticker, country) tuples."""
    print("\n📡 Fetching universe from external sources...")
    
    us_tickers = set()
    in_tickers = set()
    special = []

    # US Equities
    sp500 = fetch_sp500()
    print(f"  ✓ S&P 500: {len(sp500)} tickers")
    us_tickers.update(sp500)

    nasdaq = fetch_nasdaq100()
    print(f"  ✓ Nasdaq 100: {len(nasdaq)} tickers")
    us_tickers.update(nasdaq)

    # Indian Equities
    nifty500 = fetch_nifty500()
    print(f"  ✓ Nifty 500: {len(nifty500)} tickers")
    in_tickers.update(nifty500)

    midcap = fetch_nifty_midcap()
    print(f"  ✓ Nifty Midcap 100: {len(midcap)} tickers")
    in_tickers.update(midcap)

    # Crypto + Indices + Macro (categorised as 'Other')
    for t in CRYPTO_UNIVERSE:
        special.append((t, "Other", "Crypto", "Cryptocurrency"))
    for t in INDEX_UNIVERSE:
        special.append((t, "Other", "Index", "Market Index"))
    for t in MACRO_UNIVERSE:
        special.append((t, "Other", "Macro", "Commodity/FX"))

    print(f"  ✓ Crypto/Indices/Macro: {len(special)} tickers")

    result = []
    for t in sorted(us_tickers):
        result.append({"ticker": t, "country": "US", "sector": None, "industry": None, "name": t})
    for t in sorted(in_tickers):
        result.append({"ticker": t, "country": "IN", "sector": None, "industry": None, "name": t})
    for t, country, sector, industry in special:
        result.append({"ticker": t, "country": country, "sector": sector, "industry": industry, "name": t})

    return result

# ── DB Operations ─────────────────────────────────────────────────────────────

TABLES_TO_TRUNCATE = [
    "market_snapshots",
    "news_sentiment",
    "promoter_holdings",
    "institutional_flows",
    "macro_economic_data",
    "company_financials",
    "stock_prices",
    "stocks",
]

async def wipe_database(session: AsyncSession):
    """Truncate all tables in the correct FK-safe order."""
    print("\n🗑️  Wiping database...")
    for table in TABLES_TO_TRUNCATE:
        try:
            await session.execute(text(f"TRUNCATE TABLE {table} CASCADE"))
            print(f"  ✓ Truncated: {table}")
        except Exception as e:
            print(f"  ⚠ Could not truncate {table}: {e}")
    await session.commit()
    print("  ✅ All tables wiped.\n")

async def populate_universe(session: AsyncSession, records: list):
    """Insert all stock records into the stocks table."""
    print(f"📥 Inserting {len(records)} stocks into `stocks` table...")
    from sqlalchemy.dialects.postgresql import insert as pg_insert

    # Deduplicate by ticker
    seen = set()
    deduped = []
    for r in records:
        if r["ticker"] not in seen:
            seen.add(r["ticker"])
            deduped.append(r)

    CHUNK = 500
    inserted = 0
    for i in range(0, len(deduped), CHUNK):
        chunk = deduped[i:i + CHUNK]
        stmt = pg_insert(Stock).values(chunk)
        stmt = stmt.on_conflict_do_update(
            index_elements=["ticker"],
            set_={
                "country": stmt.excluded.country,
                "sector": stmt.excluded.sector,
                "industry": stmt.excluded.industry,
                "name": stmt.excluded.name,
            }
        )
        await session.execute(stmt)
        await session.commit()
        inserted += len(chunk)
        print(f"  ↳ {inserted}/{len(deduped)} inserted...", end="\r")

    print(f"\n  ✅ Done. {len(deduped)} unique stocks inserted.")

# ── Main ──────────────────────────────────────────────────────────────────────

async def main():
    start = time.time()
    print("=" * 55)
    print("  OmniTrader AI — Clean DB Reset + Universe Population")
    print("=" * 55)

    # 1. Fetch universe from external sources (before opening DB connection)
    records = build_universe()
    total = len(records)
    us = sum(1 for r in records if r["country"] == "US")
    ind = sum(1 for r in records if r["country"] == "IN")
    other = total - us - ind
    print(f"\n  Universe breakdown:")
    print(f"    US Equities  : {us:>6,}")
    print(f"    IN Equities  : {ind:>6,}")
    print(f"    Crypto/Other : {other:>6,}")
    print(f"    TOTAL        : {total:>6,}")

    # 2. Wipe + insert
    async with Session() as session:
        await wipe_database(session)
        await populate_universe(session, records)

    elapsed = time.time() - start
    print(f"\n{'=' * 55}")
    print(f"  ✅ Complete in {elapsed:.1f}s")
    print(f"  Next step: run the initial price ingestion flow")
    print(f"  (The APScheduler will auto-start it at 06:05 IST,")
    print(f"   or trigger it now via POST /ingestion/trigger-now/initial_load)")
    print(f"{'=' * 55}\n")

if __name__ == "__main__":
    asyncio.run(main())
