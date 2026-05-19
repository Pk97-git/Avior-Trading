"""
backup_db.py
=============
Exports every table in omnitrader_db to compressed CSV files.

Strategy for stock_prices (38M rows):
  - Pre-2000 data  → single file  stock_prices_pre2000.csv.gz  (tiny, few tickers)
  - 2000–2009      → single file  stock_prices_2000s.csv.gz
  - 2010–2019      → single file  stock_prices_2010s.csv.gz
  - 2020+          → per-year files  stock_prices_2020.csv.gz, 2021, 2022 …

Uses PostgreSQL COPY TO STDOUT for maximum speed (10–20x faster than SELECT+fetchall).

Output structure:
  backups/
  └── 2026-02-24/
      ├── manifest.json
      ├── stocks.csv.gz
      ├── stock_prices_pre2000.csv.gz
      ├── stock_prices_2000s.csv.gz
      ├── stock_prices_2010s.csv.gz
      ├── stock_prices_2020.csv.gz
      ├── stock_prices_2021.csv.gz
      ├── ...
      ├── company_financials.csv.gz
      ├── macro_data.csv.gz
      └── ...

Run:
    python backup_db.py
    python backup_db.py --date 2026-02-01

Restore:
    python restore_db.py
    python restore_db.py --date 2026-02-24
"""
import argparse
import asyncio
import gzip
import json
import logging
import os
import io
from datetime import datetime, timezone
from pathlib import Path

import asyncpg

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger("backup")

DB_CONFIG = dict(host="localhost", port=5432,
                 user="omnitrader", password="omnitrader", database="omnitrader_db")
BACKUP_ROOT = Path(__file__).parent / "backups"
KEEP_BACKUPS = 1

# Tables exported with a simple full-table COPY
SIMPLE_TABLES = [
    "stocks",
    "company_financials",
    "macro_data",
    "institutional_flows",
    "news_sentiment",
    "promoter_holdings",
    "regime_labels",
    "ai_analysis",
    "alerts",
    "market_snapshots",
    "chart_snapshots",
]

COPY_BUFFER = 64 * 1024  # 64 KB write buffer


async def _copy_table_to_gz(conn: asyncpg.Connection, query: str, fpath: Path) -> int:
    """
    Stream a SQL query result via PostgreSQL COPY TO STDOUT directly into a .csv.gz file.
    Returns row count estimate (COPY doesn't return count, so we count newlines).
    """
    row_count = 0
    copy_query = f"COPY ({query}) TO STDOUT (FORMAT CSV, HEADER TRUE)"

    with gzip.open(fpath, "wb") as gz:
        async def sink(data: bytes) -> None:
            nonlocal row_count
            gz.write(data)
            row_count += data.count(b"\n")

        await conn.copy_from_query(query, output=gz, format="csv", header=True)

    # row_count = lines - 1 (header)
    return max(0, row_count - 1)


async def export_simple(conn: asyncpg.Connection, table: str, out_dir: Path) -> dict:
    """Export a full table via COPY."""
    fname = f"{table}.csv.gz"
    fpath = out_dir / fname
    logger.info("Exporting %s ...", table)

    # Check row count first
    n = await conn.fetchval(f"SELECT COUNT(*) FROM {table}")
    if n == 0:
        logger.info("  %s — empty", table)
        return {"table": table, "rows": 0, "files": []}

    with gzip.open(fpath, "wb") as gz:
        await conn.copy_from_query(f"SELECT * FROM {table}", output=gz, format="csv", header=True)

    size_mb = fpath.stat().st_size / 1e6
    logger.info("  ✓ %s — %d rows → %s (%.1f MB compressed)", table, n, fname, size_mb)
    return {"table": table, "rows": n, "files": [fname]}


async def export_stock_prices(conn: asyncpg.Connection, out_dir: Path) -> dict:
    """
    Export stock_prices in smart date buckets:
      pre-2000 → 1 file, 2000-2009 → 1 file, 2010-2019 → 1 file, 2020+ → per year
    """
    table = "stock_prices"
    all_files = []
    total_rows = 0

    # Get date range
    res = await conn.fetchrow("SELECT MIN(time)::date, MAX(time)::date FROM stock_prices")
    min_date, max_date = res[0], res[1]
    max_year = max_date.year if max_date else 2026
    logger.info("stock_prices date range: %s → %s", min_date, max_date)

    buckets = []

    # Pre-2000 (all in one file)
    if min_date and min_date.year < 2000:
        buckets.append(("pre2000", "time < '2000-01-01'"))

    # 2000s decade
    if max_year >= 2000:
        buckets.append(("2000s", "time >= '2000-01-01' AND time < '2010-01-01'"))

    # 2010s decade
    if max_year >= 2010:
        buckets.append(("2010s", "time >= '2010-01-01' AND time < '2020-01-01'"))

    # 2020+ per year
    for yr in range(2020, max_year + 1):
        buckets.append((str(yr), f"time >= '{yr}-01-01' AND time < '{yr+1}-01-01'"))

    for label, where_clause in buckets:
        fname = f"stock_prices_{label}.csv.gz"
        fpath = out_dir / fname
        logger.info("  Exporting stock_prices_%s ...", label)

        n = await conn.fetchval(f"SELECT COUNT(*) FROM stock_prices WHERE {where_clause}")
        if n == 0:
            logger.info("    (empty bucket — skipping)")
            continue

        with gzip.open(fpath, "wb") as gz:
            await conn.copy_from_query(
                f"SELECT * FROM stock_prices WHERE {where_clause} ORDER BY time, ticker",
                output=gz, format="csv", header=True
            )

        size_mb = fpath.stat().st_size / 1e6
        logger.info("    ✓ stock_prices_%s — %d rows → %.1f MB compressed", label, n, size_mb)
        all_files.append(fname)
        total_rows += n

    return {"table": table, "rows": total_rows, "files": all_files}


async def run_backup(date_str: str) -> None:
    out_dir = BACKUP_ROOT / date_str
    out_dir.mkdir(parents=True, exist_ok=True)
    logger.info("Starting backup → %s", out_dir)

    conn = await asyncpg.connect(**DB_CONFIG)
    manifest = {
        "backup_date": date_str,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "tables": [],
    }

    try:
        # Simple tables first
        for table in SIMPLE_TABLES:
            try:
                meta = await export_simple(conn, table, out_dir)
                manifest["tables"].append(meta)
            except Exception as e:
                logger.error("  ✗ %s failed: %s", table, e)
                manifest["tables"].append({"table": table, "error": str(e)})

        # stock_prices with smart bucketing
        try:
            meta = await export_stock_prices(conn, out_dir)
            manifest["tables"].append(meta)
        except Exception as e:
            logger.error("  ✗ stock_prices failed: %s", e)
            manifest["tables"].append({"table": "stock_prices", "error": str(e)})

    finally:
        await conn.close()

    manifest_path = out_dir / "manifest.json"
    manifest_path.write_text(json.dumps(manifest, indent=2))

    total_rows = sum(t.get("rows", 0) for t in manifest["tables"])
    total_size = sum(f.stat().st_size for f in out_dir.glob("*.csv.gz"))
    logger.info("")
    logger.info("✅ Backup complete!")
    logger.info("   Location:    %s", out_dir)
    logger.info("   Total rows:  %s", f"{total_rows:,}")
    logger.info("   Disk size:   %.1f MB (compressed)", total_size / 1e6)
    logger.info("   Files:       %d", len(list(out_dir.glob("*.csv.gz"))))


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--date", default=datetime.now(timezone.utc).strftime("%Y-%m-%d"))
    args = parser.parse_args()
    asyncio.run(run_backup(args.date))
