"""
run_fundamentals_backfill.py
==============================
Continuously ingests company fundamentals (P/E, Revenue, EPS, ROIC, D/E etc.)
for all tickers in the universe that don't yet have data.

Uses FundamentalService.fetch_financials() — same service used by the Prefect flows.
Rate limit: 40 req/min (Yahoo Finance limit).

Usage:
    source venv/bin/activate
    python run_fundamentals_backfill.py

Will run until all tickers are processed or interrupted with Ctrl+C.
"""
import asyncio
import logging
import time
from datetime import datetime, timezone

from sqlalchemy.ext.asyncio import AsyncSession
from app.db.session import AsyncSessionLocal
from app.ingestion.core.macro_fundamental import FundamentalService

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s"
)
logger = logging.getLogger("fundamentals_backfill")

RATE_LIMIT_PER_MIN = 35          # conservative (Yahoo Fi limit is ~40)
SLEEP_BETWEEN = 60 / RATE_LIMIT_PER_MIN   # ~1.7 seconds between calls
BATCH_LOG_EVERY = 25             # print summary every N tickers


async def get_missing_tickers() -> list[str]:
    """Get all tickers that have no entry in company_financials."""
    from sqlalchemy import text
    async with AsyncSessionLocal() as db:
        res = await db.execute(text("""
            SELECT ticker FROM stocks
            WHERE NOT EXISTS (
                SELECT 1 FROM company_financials cf WHERE cf.ticker = stocks.ticker
            )
            AND (data_unavailable IS NULL OR data_unavailable = FALSE)
            ORDER BY ticker
        """))
        return [r.ticker for r in res.fetchall()]


async def run_backfill():
    print("\nOmniTrader AI — Company Fundamentals Backfill")
    print("Scanning for tickers missing fundamentals data...\n")

    missing = await get_missing_tickers()
    total = len(missing)

    if total == 0:
        print("✅ All tickers already have fundamentals data!")
        return

    print(f"Found {total:,} tickers without fundamentals data.")
    print(f"Rate: {RATE_LIMIT_PER_MIN} req/min (~{total * SLEEP_BETWEEN / 60:.0f} minutes estimated)\n")
    print("=" * 60)

    success = 0
    skipped = 0
    errors  = 0
    start_time = time.time()

    for i, ticker in enumerate(missing, 1):
        try:
            async with AsyncSessionLocal() as db:
                svc = FundamentalService(db)
                await svc.fetch_financials(ticker)
                await db.commit()
                success += 1
        except Exception as e:
            err_str = str(e)
            if "No data found" in err_str or "404" in err_str or "no data" in err_str.lower():
                skipped += 1
            else:
                errors += 1
                logger.warning("[%d/%d] %s — %s", i, total, ticker, err_str[:80])

        if i % BATCH_LOG_EVERY == 0 or i == total:
            elapsed = time.time() - start_time
            rate    = i / elapsed * 60
            eta_min = (total - i) / max(rate, 1)
            pct     = i / total * 100
            print(
                f"  [{i:>6}/{total}]  {pct:4.1f}%  "
                f"✓{success} ✗{errors} ~{skipped}  "
                f"Rate:{rate:.0f}/min  ETA:{eta_min:.0f}m"
            )

        await asyncio.sleep(SLEEP_BETWEEN)

    elapsed = (time.time() - start_time) / 60
    print(f"\n{'='*60}")
    print(f"✅ Fundamentals backfill complete in {elapsed:.1f} min")
    print(f"   Ingested: {success:,}  |  No data: {skipped:,}  |  Errors: {errors:,}")


if __name__ == "__main__":
    asyncio.run(run_backfill())
