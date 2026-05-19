"""
run_continuous_backfill.py
===========================
Continuous backfill that reads DIRECTLY from the database.
Queries the `stocks` table for ALL tickers missing price history, 
processes them in safe batches, and loops until complete.

Key fix: Bypasses the UniverseManager file cache entirely.
Uses the same rate limits (40 req/min) to avoid Yahoo Finance bans.
"""
import asyncio
import time
from sqlalchemy import text
from app.db.session import engine, AsyncSessionLocal
from app.ingestion.core.prices import DataIngestionService
from app.ingestion.infra.rate_limiter import RateLimiterRegistry

BATCH_SIZE = 50  # Process 50 tickers at a time
DELAY_BETWEEN_TICKERS = 1.5  # seconds between each ticker (safe: ~40/min)


async def get_missing_tickers():
    """Get all tickers in the `stocks` table that have NO rows in `stock_prices`."""
    print("  Scanning DB for missing tickers...", flush=True)
    async with engine.connect() as conn:
        # NOT EXISTS is much faster than LEFT JOIN on large tables
        res = await conn.execute(text("""
            SELECT ticker FROM stocks
            WHERE NOT EXISTS (
                SELECT 1 FROM stock_prices sp WHERE sp.ticker = stocks.ticker
            )
            AND (data_unavailable IS NULL OR data_unavailable = FALSE)
            ORDER BY ticker
        """))
        tickers = [r.ticker for r in res.fetchall()]
        print(f"  Found {len(tickers):,} stocks with no price data.", flush=True)
        return tickers


async def get_stale_tickers():
    """Get tickers with data but missing more than 5 days (date gaps)."""
    async with engine.connect() as conn:
        res = await conn.execute(text("""
            SELECT ticker, MAX(time)::date as last_date
            FROM stock_prices
            GROUP BY ticker
            HAVING NOW() - MAX(time) > INTERVAL '5 days'
            ORDER BY MAX(time) ASC
        """))
        return [(r.ticker, str(r.last_date)) for r in res.fetchall()]


async def ingest_ticker(ticker: str, period: str = "max", start: str = None, end: str = None):
    """Ingest one ticker with rate limiting. Returns True on success, False on skip."""
    try:
        await RateLimiterRegistry.acquire("yfinance")
        async with AsyncSessionLocal() as session:
            svc = DataIngestionService(session)
            if start and end:
                await svc.fetch_history(ticker, start=start, end=end)
            else:
                await svc.fetch_history(ticker, period=period)
            return True  # fetch_history returns None; success = no exception
    except Exception as e:
        err = str(e)
        if "delisted" in err.lower() or "404" in err or "not found" in err.lower() or "invalid" in err.lower():
            return -1  # Bad ticker, remove from universe
        print(f"  [ERROR] {ticker}: {e}")
        return False


async def main():
    run = 0
    total_new = 0

    print("OmniTrader AI — DB-Direct Continuous Backfill")
    print("Reads missing stocks directly from the database, bypassing cache.\n")

    while True:
        missing = await get_missing_tickers()
        stale = await get_stale_tickers()

        if not missing and not stale:
            print("\n✅ ALL STOCKS FULLY INGESTED! Nothing left to do.")
            break

        run += 1
        print(f"\n{'='*60}")
        print(f"  Pass #{run} | {len(missing):,} fully missing | {len(stale):,} with gaps")
        print(f"  Started: {time.strftime('%H:%M:%S IST')}")
        print(f"{'='*60}\n")

        # ── Phase 1: Fetch stocks with no data at all ─────────────────────
        bad_tickers = []
        batch_done = 0

        for i, ticker in enumerate(missing):
            rows = await ingest_ticker(ticker, period="max")
            if rows == -1:
                bad_tickers.append(ticker)
                print(f"  [SKIP] {ticker} — invalid/delisted, marking for removal")
            elif rows > 0:
                batch_done += 1
                total_new += 1
                print(f"  [{i+1}/{len(missing)}] ✓ {ticker}: {rows:,} rows")
            else:
                print(f"  [{i+1}/{len(missing)}] ~ {ticker}: 0 rows (no data available)")
            
            await asyncio.sleep(DELAY_BETWEEN_TICKERS)

        # ── Phase 2: Fill date gaps ────────────────────────────────────────
        from datetime import datetime, timezone
        today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        for ticker, last_date in stale[:100]:  # Cap at 100 gap fills per pass
            rows = await ingest_ticker(ticker, start=last_date, end=today)
            if rows > 0:
                print(f"  [GAP] ✓ {ticker}: +{rows:,} rows from {last_date}")
            await asyncio.sleep(DELAY_BETWEEN_TICKERS)

        # ── Remove confirmed bad tickers from DB ──────────────────────────
        if bad_tickers:
            async with engine.begin() as conn:
                await conn.execute(
                    text("DELETE FROM stocks WHERE ticker = ANY(:tickers)"),
                    {"tickers": bad_tickers}
                )
            print(f"\n  Removed {len(bad_tickers)} invalid tickers from universe.")

        print(f"\n  ✓ Pass #{run} complete. {batch_done} new stocks ingested. {total_new} total so far.")

        # If we still have more missing, loop immediately
        remaining_after = await get_missing_tickers()
        if remaining_after:
            print(f"  {len(remaining_after):,} stocks still remaining — continuing...\n")
        else:
            print("\n✅ ALL STOCKS FULLY INGESTED!")
            break


if __name__ == "__main__":
    print("Starting DB-direct continuous backfill — press Ctrl+C to stop cleanly.\n")
    asyncio.run(main())
