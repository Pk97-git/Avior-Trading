"""
run_gap_fixer.py
================
A precision script that uses SQL window functions to hunt down targeted
date gaps inside the *middle* of a stock's historical price series.
If a gap of >4 days is found (to account for weekends/holidays), it will
surgically fetch only that exact missing specific date range.
"""
import asyncio
import time
from datetime import datetime, timedelta
from sqlalchemy import text
from app.db.session import engine, AsyncSessionLocal
from app.ingestion.core.prices import DataIngestionService
from app.ingestion.infra.rate_limiter import RateLimiterRegistry

DELAY_BETWEEN_CHUNKS = 1.0


async def find_historical_gaps():
    """Uses LEAD() window function to find sequential rows separated by >4 calendar days."""
    print("  Scanning DB with Window Functions to find hidden date gaps...", flush=True)
    async with engine.connect() as conn:
        res = await conn.execute(text("""
            WITH OrderedPrices AS (
                SELECT 
                    ticker, 
                    time::date as current_date,
                    LEAD(time::date) OVER (PARTITION BY ticker ORDER BY time) as next_date
                FROM stock_prices
            )
            SELECT ticker, current_date, next_date 
            FROM OrderedPrices
            WHERE next_date - current_date > 4
            ORDER BY next_date DESC
        """))
        gaps = [(r.ticker, str(r.current_date), str(r.next_date)) for r in res.fetchall()]
        print(f"  Found {len(gaps):,} hidden date gaps requiring repair.", flush=True)
        return gaps


async def repair_gap(ticker: str, start: str, end: str):
    """Surgically ingests the exact missing date range."""
    try:
        await RateLimiterRegistry.acquire("yfinance")
        async with AsyncSessionLocal() as session:
            svc = DataIngestionService(session)
            # Add 1 day to start to fetch exactly inside the hole
            start_dt = datetime.strptime(start, "%Y-%m-%d").date() + timedelta(days=1)
            repair_start = start_dt.strftime("%Y-%m-%d")

            await svc.fetch_history(ticker, start=repair_start, end=end)
            return True
    except Exception as e:
        err = str(e)
        if "delisted" in err.lower() or "404" in err or "not found" in err.lower() or "invalid" in err.lower():
            return -1  # Bad ticker
        print(f"  [ERROR] {ticker} gap {start}->{end}: {e}")
        return False


async def main():
    print("OmniTrader AI — Historical Gap Fixer")
    print("Hunts down isolated missing days inside the middle of continuous time series.\n")

    gaps = await find_historical_gaps()

    if not gaps:
        print("\n✅ DATA IS PERFECTLY CONTINUOUS! No historical gaps found.")
        return

    print(f"\n{'='*60}")
    print(f"  Repairing {len(gaps):,} historical gaps")
    print(f"  Started: {time.strftime('%H:%M:%S IST')}")
    print(f"{'='*60}\n")

    total_repaired = 0
    bad_tickers = []

    for i, (ticker, start_date, next_date) in enumerate(gaps):
        success = await repair_gap(ticker, start_date, next_date)
        
        if success == -1:
            if ticker not in bad_tickers:
                bad_tickers.append(ticker)
                print(f"  [SKIP] {ticker} — invalid/delisted")
        elif success:
            total_repaired += 1
            print(f"  [{i+1}/{len(gaps)}] ✓ {ticker}: Surgical repair filled gap between {start_date} and {next_date}")
        
        await asyncio.sleep(DELAY_BETWEEN_CHUNKS)

    print(f"\n✅ Gap fixing complete. Successfully repaired {total_repaired} missing windows.")


if __name__ == "__main__":
    asyncio.run(main())
