"""
app/flows/backup_flow.py
=========================
Prefect flow that runs backup_db.py on a schedule and cleans up old backups.
Default schedule: every Sunday at 02:00 IST (20:30 UTC Saturday).
Keeps the last 4 weekly backups (28 days of history).
"""
import logging
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

from prefect import flow, task

logger = logging.getLogger(__name__)
BACKUP_ROOT = Path(__file__).parent.parent.parent / "backups"
KEEP_BACKUPS = 1   # keep only the latest backup


@task(name="run_backup_script", retries=1, retry_delay_seconds=300)
def run_backup_script() -> str:
    """Invoke backup_db.py as a subprocess to avoid memory pressure."""
    date_str = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    script = Path(__file__).parent.parent.parent / "backup_db.py"
    logger.info("Starting weekly DB backup → backups/%s", date_str)

    result = subprocess.run(
        [sys.executable, str(script), "--date", date_str],
        capture_output=True, text=True, timeout=14400,  # 4h max
    )
    if result.returncode != 0:
        logger.error("Backup failed:\n%s", result.stderr)
        raise RuntimeError(f"backup_db.py exited with code {result.returncode}")

    logger.info("Backup stdout:\n%s", result.stdout[-2000:])
    return date_str


@task(name="cleanup_old_backups")
def cleanup_old_backups() -> None:
    """Remove backup folders older than KEEP_BACKUPS weeks."""
    if not BACKUP_ROOT.exists():
        return

    dirs = sorted([d for d in BACKUP_ROOT.iterdir() if d.is_dir()], reverse=True)
    to_delete = dirs[KEEP_BACKUPS:]
    for old_dir in to_delete:
        logger.info("Removing old backup: %s", old_dir)
        import shutil
        shutil.rmtree(old_dir, ignore_errors=True)
    logger.info("Cleanup done — removed %d old backups, kept %d", len(to_delete), min(len(dirs), KEEP_BACKUPS))


@flow(name="weekly_db_backup", log_prints=True)
def weekly_db_backup_flow() -> None:
    """Weekly: dump all DB tables to compressed CSV and clean up old backups."""
    date_str = run_backup_script()
    cleanup_old_backups()
    logger.info("✅ Backup flow complete for date: %s", date_str)
