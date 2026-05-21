"""
services/health_monitor.py
==========================
HealthMonitor — checks data freshness and system health.
Designed to be called from the scheduler.

Fires a NotificationService.send_health_alert() if any data source
is critically stale.
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import List, Optional

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger(__name__)

# (table_name, timestamp_column, warn_after_hours)
_FRESHNESS_CHECKS = [
    ("stock_prices",  "time",          26),
    ("ai_analysis",   "analysis_date", 28),
    ("macro_data",    "time",          36),
]


class HealthMonitor:
    """
    Checks data freshness and system health. Designed to be called from the scheduler.
    Fires notifications if critical data is stale.
    """

    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    # ──────────────────────────────────────────────────────────────────────────
    # Public entry point
    # ──────────────────────────────────────────────────────────────────────────

    async def run_checks(self) -> dict:
        """
        Runs all data-freshness and operational checks.

        Checks performed:
          1. stock_prices  — WARN if latest timestamp > 26 h old
          2. ai_analysis   — WARN if latest analysis_date > 28 h old
          3. macro_data    — WARN if latest time > 36 h old
          4. alerts count  — INFO: number of alerts in last 24 h

        If any WARN exists, fires NotificationService.send_health_alert().

        Returns:
        {
            "status":   "OK" | "WARN",
            "checks":   [{ "table": str, "last_update": str | None,
                           "hours_stale": float, "status": "OK"|"WARN"|"EMPTY" }],
            "warnings": [str],
        }
        """
        checks: list[dict]  = []
        warnings: list[str] = []

        # ── Freshness checks ──────────────────────────────────────────────────
        for table, ts_col, warn_hours in _FRESHNESS_CHECKS:
            result = await self._check_table_freshness(table, ts_col, warn_hours)
            checks.append(result)
            if result["status"] == "WARN":
                hours = result["hours_stale"]
                last  = result["last_update"] or "never"
                warnings.append(
                    f"{table}: last update {last} — {hours:.1f}h ago "
                    f"(threshold {warn_hours}h)"
                )
            elif result["status"] == "EMPTY":
                warnings.append(f"{table}: table is empty — no data found")

        # ── Alert count (INFO only) ───────────────────────────────────────────
        alert_count: Optional[int] = None
        try:
            res = await self.db.execute(
                text("""
                    SELECT COUNT(*) FROM alerts
                    WHERE generated_at >= NOW() - INTERVAL '24 hours'
                """)
            )
            alert_count = int(res.scalar() or 0)
        except Exception as exc:
            logger.warning("[HealthMonitor] Could not query alerts count: %s", exc)

        checks.append({
            "table":       "alerts",
            "last_update": None,
            "hours_stale": 0.0,
            "status":      "INFO",
            "count_24h":   alert_count,
        })

        overall_status = "WARN" if warnings else "OK"

        # ── Fire notification if any warnings ────────────────────────────────
        if warnings:
            try:
                from app.services.notifications import NotificationService
                notif = NotificationService()
                await notif.send_health_alert(warnings)
            except Exception as exc:
                logger.warning("[HealthMonitor] Failed to send health alert: %s", exc)

        logger.info(
            "[HealthMonitor] status=%s  warnings=%d  alert_count_24h=%s",
            overall_status,
            len(warnings),
            alert_count,
        )

        return {
            "status":   overall_status,
            "checks":   checks,
            "warnings": warnings,
        }

    # ──────────────────────────────────────────────────────────────────────────
    # Private helpers
    # ──────────────────────────────────────────────────────────────────────────

    async def _check_table_freshness(
        self,
        table: str,
        ts_col: str,
        warn_hours: int,
    ) -> dict:
        """
        Query the latest timestamp from `table`.`ts_col` and assess staleness.

        Returns:
        {
            "table":       str,
            "last_update": str | None,        # ISO-8601 or None if empty
            "hours_stale": float,             # 0.0 if table is empty / error
            "status":      "OK" | "WARN" | "EMPTY",
        }
        """
        try:
            result = await self.db.execute(
                text(f"SELECT MAX({ts_col}) AS last_ts FROM {table}")  # noqa: S608
            )
            row = result.fetchone()
        except Exception as exc:
            logger.warning(
                "[HealthMonitor] Cannot query %s.%s: %s", table, ts_col, exc
            )
            return {
                "table":       table,
                "last_update": None,
                "hours_stale": 0.0,
                "status":      "EMPTY",
            }

        last_ts: Optional[datetime] = row.last_ts if row else None

        if last_ts is None:
            return {
                "table":       table,
                "last_update": None,
                "hours_stale": 0.0,
                "status":      "EMPTY",
            }

        # Normalise to UTC-aware datetime
        if last_ts.tzinfo is None:
            last_ts = last_ts.replace(tzinfo=timezone.utc)

        now        = datetime.now(timezone.utc)
        hours_stale = (now - last_ts).total_seconds() / 3600

        status = "WARN" if hours_stale > warn_hours else "OK"

        return {
            "table":       table,
            "last_update": last_ts.isoformat(),
            "hours_stale": round(hours_stale, 2),
            "status":      status,
        }
