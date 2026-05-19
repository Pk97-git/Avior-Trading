#!/usr/bin/env python3
"""
reset_db.py
============
Truncates ALL tables. Clean slate.

Run:
    source venv/bin/activate
    python reset_db.py
"""
import asyncio
import sys

sys.path.insert(0, ".")
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy import text
from app.core.config import settings

engine = create_async_engine(settings.SQLALCHEMY_DATABASE_URI, echo=False)
Session = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

TABLES = [
    "market_snapshots",
    "news_sentiment",
    "promoter_holdings",
    "institutional_flows",
    "macro_economic_data",
    "company_financials",
    "stock_prices",
    "stocks",
]

async def main():
    print("\n🗑️  Wiping all tables...")
    async with Session() as session:
        for table in TABLES:
            try:
                await session.execute(text(f"TRUNCATE TABLE {table} CASCADE"))
                print(f"  ✓ {table}")
            except Exception as e:
                print(f"  ⚠ {table}: {e}")
        await session.commit()
    print("\n✅ Database is now empty and clean.\n")

if __name__ == "__main__":
    asyncio.run(main())
