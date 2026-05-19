"""
run_catchup_backfill.py
=======================
A targeted script to identify stocks that have historical data
but are missing recent days (e.g. they are "Stale").
It queries the DB for the last ingested date and only downloads
the missing date range up to today for those specific stocks.
"""
import asyncio
import time
from datetime import datetime, timezone, timedelta
from sqlalchemy import text
from app.db.session import engine, AsyncSessionLocal
from app.ingestion.core.prices import DataIngestionService
from app.ingestion.infra.rate_limiter import RateLimiterRegistry

BATCH_SIZE = 50
DELAY_BETWEEN_TICKERS = 1.0  # seconds between each ticker (safe: ~60/min for small date ranges)


async def get_stale_tickers():
    """Get tickers with data but missing recent days (date gaps)."""
    print("  Scanning DB for stale tickers...", flush=True)
    async with engine.connect() as conn:
        res = await conn.execute(text("""
            SELECT ticker, MAX(time)::date as last_date
            FROM stock_prices
            GROUP BY ticker
            HAVING NOW() - MAX(time) > INTERVAL '1 days'
            ORDER BY MAX(time) ASC
        """))
        stale = [(r.ticker, str(r.last_date)) for r in res.fetchall()]
        print(f"  Found {len(stale):,} stocks needing catch-up.", flush=True)
        return stale


async def ingest_gap(ticker: str, start: str, end: str):
    """Ingest one ticker for a specific date range with rate limiting."""
    try:
        await RateLimiterRegistry.acquire("yfinance")
        async with AsyncSessionLocal() as session:
            svc = DataIngestionService(session)
            await svc.fetch_history(ticker, start=start, end=end)
            return True
    except Exception as e:
        err = str(e)
        if "delisted" in err.lower() or "404" in err or "not found" in err.lower() or "invalid" in err.lower():
            return -1  # Bad ticker
        print(f"  [ERROR] {ticker}: {e}")
        return False


async def main():
    print("OmniTrader AI — Automated Catch-up Backfill")
    print("Identifies missing date gaps for all stocks and brings them up to today.\n")

    stale = await get_stale_tickers()

    if not stale:
        print("\n✅ ALL STOCKS ARE CURRENT! Nothing left to do.")
        return

    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    total_gaps_filled = 0
    bad_tickers = []

    print(f"\n{'='*60}")
    print(f"  Processing {len(stale):,} stale stocks up to {today}")
    print(f"  Started: {time.strftime('%H:%M:%S IST')}")
    print(f"{'='*60}\n")

    for i, (ticker, last_date) in enumerate(stale):
        # We need to fetch from the day after the last_date
        last_date_obj = datetime.strptime(last_date, "%Y-%m-%d").date()
        fetch_start_date = (last_date_obj + timedelta(days=1)).strftime("%Y-%m-%d")

        # Skip if fetch_start_date is today or in the future
        if fetch_start_date >= today:
             continue
        
        success = await ingest_gap(ticker, start=fetch_start_date, end=today)
        
        if success == -1:
            bad_tickers.append(ticker)
            print(f"  [SKIP] {ticker} — invalid/delisted, marking for removal")
        elif success:
            total_gaps_filled += 1
            print(f"  [{i+1}/{len(stale)}] ✓ {ticker}: Filled gap from {fetch_start_date} to today")
        
        await asyncio.sleep(DELAY_BETWEEN_TICKERS)

    # ── Remove confirmed bad tickers from DB ──────────────────────────
    if bad_tickers:
        async with engine.begin() as conn:
            await conn.execute(
                text("DELETE FROM stocks WHERE ticker = ANY(:tickers)"),
                {"tickers": bad_tickers}
            )
        print(f"\n  Removed {len(bad_tickers)} invalid tickers from universe.")

    print(f"\n✅ Catch-up complete. Successfully updated {total_gaps_filled} stocks to today.")


if __name__ == "__main__":
    asyncio.run(main())
