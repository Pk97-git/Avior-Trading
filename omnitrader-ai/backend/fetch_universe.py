"""
fetch_universe.py
===================
Fetches the complete universe of tradable tickers for US (NYSE, NASDAQ) and India (NSE).
Updates the metadata in the `stocks` table.

Usage:
    source venv/bin/activate && python fetch_universe.py
"""

import asyncio
import io
import json
import urllib.request
import pandas as pd
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert

from app.core.config import settings
from app.models.market_data import Stock

engine = create_async_engine(settings.SQLALCHEMY_DATABASE_URI, echo=False)
Session = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

async def fetch_nse_universe(session: AsyncSession):
    print("Fetching NSE Equity universe...")
    url = "https://archives.nseindia.com/content/equities/EQUITY_L.csv"
    try:
        # NSE often blocks simple requests, use a User-Agent
        req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
        with urllib.request.urlopen(req) as response:
            csv_data = response.read()
        
        df = pd.read_csv(io.BytesIO(csv_data))
        # Keep only main equities (Series EQ)
        df = df[df[' SERIES'] == 'EQ']
        
        records = []
        for _, row in df.iterrows():
            ticker = f"{row['SYMBOL']}.NS"
            records.append({
                "ticker": ticker,
                "name": row['NAME OF COMPANY'],
                "sector": "Unknown",  # To be enriched later
                "industry": "Unknown",
                "country": "IN",
                "meta_data": {"isin": row.get(' ISIN NUMBER', '')}
            })
            
        print(f"Found {len(records)} NSE equities.")
        await upsert_batch(session, records)
        return len(records)
    except Exception as e:
        print(f"Failed to fetch NSE universe: {e}")
        return 0

async def fetch_us_universe(session: AsyncSession):
    print("Fetching US Equity universe...")
    # Using SEC company tickers JSON as a reliable primary source for US tickers
    url = "https://www.sec.gov/files/company_tickers.json"
    try:
        req = urllib.request.Request(url, headers={
            'User-Agent': 'OmniTrader-AI Admin admin@omnitrader.ai',
            'Accept-Encoding': 'gzip, deflate'
        })
        with urllib.request.urlopen(req) as response:
            import gzip
            if response.info().get('Content-Encoding') == 'gzip':
                f = gzip.GzipFile(fileobj=response)
                data = json.loads(f.read())
            else:
                data = json.loads(response.read())
        
        records = []
        for key, info in data.items():
            records.append({
                "ticker": info['ticker'],
                "name": info['title'],
                "sector": "Unknown",  # To be enriched later
                "industry": "Unknown",
                "country": "US",
                "meta_data": {"cik": str(info['cik_str']).zfill(10)}
            })
            
        print(f"Found {len(records)} US equities.")
        await upsert_batch(session, records)
        return len(records)
    except Exception as e:
        print(f"Failed to fetch US universe: {e}")
        return 0

async def upsert_batch(session: AsyncSession, records: list):
    if not records:
        return
        
    CHUNK_SIZE = 2000
    try:
        for i in range(0, len(records), CHUNK_SIZE):
            chunk = records[i:i+CHUNK_SIZE]
            stmt = pg_insert(Stock).values(chunk)
            
            # On conflict: update the name and metadata but keep existing sector/industry if known
            stmt = stmt.on_conflict_do_update(
                index_elements=["ticker"],
                set_={
                    "name": stmt.excluded.name,
                    "meta_data": stmt.excluded.meta_data,
                    "country": stmt.excluded.country
                }
            )
            await session.execute(stmt)
        await session.commit()
    except Exception as e:
        print(f"DB Upsert failed: {e}")
        await session.rollback()

async def main():
    async with Session() as session:
        nse_count = await fetch_nse_universe(session)
        us_count = await fetch_us_universe(session)
        print(f"\n==========================================")
        print(f"Successfully populated universe:")
        print(f"  NSE (India): {nse_count}")
        print(f"  SEC (US):    {us_count}")
        print(f"  Total:       {nse_count + us_count}")
        print(f"==========================================")
        
if __name__ == "__main__":
    asyncio.run(main())
