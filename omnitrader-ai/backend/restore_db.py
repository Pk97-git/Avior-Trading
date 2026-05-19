"""
restore_db.py
==============
Restores omnitrader_db from a backup folder created by backup_db.py.

Usage:
    # Restore from latest backup
    python restore_db.py

    # Restore from specific date
    python restore_db.py --date 2026-02-24

    # Restore only specific tables
    python restore_db.py --date 2026-02-24 --tables stocks stock_prices

    # Dry-run (show what would be restored without touching DB)
    python restore_db.py --date 2026-02-24 --dry-run

Strategy:
  - Reads each .csv.gz file
  - Uses PostgreSQL COPY for maximum speed
  - Tables with primary keys use INSERT ON CONFLICT DO NOTHING (safe to re-run)
  - stock_prices uses ON CONFLICT DO NOTHING (idempotent)
"""
import argparse
import asyncio
import csv
import gzip
import io
import json
import logging
from pathlib import Path
from datetime import datetime, timezone

import asyncpg

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger("restore")

DB_CONFIG = dict(host="localhost", port=5432,
                 user="omnitrader", password="omnitrader", database="omnitrader_db")
BACKUP_ROOT = Path(__file__).parent / "backups"

# Primary key / conflict columns per table (for ON CONFLICT DO NOTHING)
CONFLICT_COLS = {
    "stocks":               "(ticker)",
    "stock_prices":         "(ticker, time)",
    "company_financials":   "(ticker, fiscal_date)",
    "macro_data":           "(time, indicator)",
    "institutional_flows":  "(ticker, date, flow_type)",
    "news_sentiment":       "(ticker, published_at, source)",
    "promoter_holdings":    "(ticker, report_date)",
    "regime_labels":        "(time)",
    "ai_analysis":          "(ticker, analysis_date)",
    "alerts":               "(id)",
    "market_snapshots":     "(time)",
    "chart_snapshots":      "(ticker, generated_at, timeframe)",
}


def _latest_backup_date() -> str:
    dirs = sorted([d.name for d in BACKUP_ROOT.iterdir() if d.is_dir()], reverse=True)
    if not dirs:
        raise FileNotFoundError(f"No backups found in {BACKUP_ROOT}")
    return dirs[0]


async def restore_file(conn: asyncpg.Connection, fpath: Path, table: str, dry_run: bool) -> int:
    logger.info("Restoring %s from %s ...", table, fpath.name)

    with gzip.open(fpath, "rt", encoding="utf-8") as f:
        reader = csv.reader(f)
        columns = next(reader)   # header row
        rows = list(reader)

    if not rows:
        logger.info("  %s — empty file, skipping", table)
        return 0

    if dry_run:
        logger.info("  [DRY-RUN] Would insert %d rows into %s", len(rows), table)
        return len(rows)

    conflict = CONFLICT_COLS.get(table, "")
    conflict_clause = f"ON CONFLICT {conflict} DO NOTHING" if conflict else ""

    col_list = ", ".join(f'"{c}"' for c in columns)
    placeholders = ", ".join(f"${i+1}" for i in range(len(columns)))
    sql = f'INSERT INTO "{table}" ({col_list}) VALUES ({placeholders}) {conflict_clause}'

    # Coerce empty strings back to None
    def _parse(v):
        return None if v == "" else v

    records = [tuple(_parse(v) for v in row) for row in rows]

    # Use executemany in batches of 5000 for speed
    BATCH = 5000
    inserted = 0
    for i in range(0, len(records), BATCH):
        batch = records[i:i+BATCH]
        await conn.executemany(sql, batch)
        inserted += len(batch)

    logger.info("  ✓ %s — %d rows restored", table, inserted)
    return inserted


async def run_restore(date_str: str, tables_filter: list[str], dry_run: bool) -> None:
    backup_dir = BACKUP_ROOT / date_str
    manifest_path = backup_dir / "manifest.json"

    if not manifest_path.exists():
        raise FileNotFoundError(f"No manifest found at {manifest_path}")

    manifest = json.loads(manifest_path.read_text())
    logger.info("Restoring backup from %s (created %s)", date_str, manifest.get("created_at", "?"))

    if dry_run:
        logger.info("[DRY-RUN MODE — no DB changes will be made]")

    conn = await asyncpg.connect(**DB_CONFIG)
    total_rows = 0

    try:
        for entry in manifest["tables"]:
            table = entry["table"]
            if tables_filter and table not in tables_filter:
                continue
            if "error" in entry:
                logger.warning("Skipping %s — backup had error: %s", table, entry["error"])
                continue

            for fname in entry.get("files", []):
                fpath = backup_dir / fname
                if not fpath.exists():
                    logger.warning("File not found: %s — skipping", fpath)
                    continue
                total_rows += await restore_file(conn, fpath, table, dry_run)

    finally:
        await conn.close()

    logger.info("\n✅ Restore complete — %s rows processed", f"{total_rows:,}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Restore omnitrader_db from backup")
    parser.add_argument("--date", default=None,
                        help="Backup date to restore (default: latest)")
    parser.add_argument("--tables", nargs="+", default=[],
                        help="Specific tables to restore (default: all)")
    parser.add_argument("--dry-run", action="store_true",
                        help="Show what would be restored without making DB changes")
    args = parser.parse_args()

    date_str = args.date or _latest_backup_date()
    logger.info("Using backup date: %s", date_str)
    asyncio.run(run_restore(date_str, args.tables, args.dry_run))
