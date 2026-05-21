"""
ingestion/core/economic_calendar.py
====================================
Economic Calendar — tracks high-impact macro events.

Sources:
1. Hardcoded 2025-2026 FOMC meeting dates (from federalreserve.gov)
2. Dynamically computed NFP (first Friday of each month)
3. Dynamically computed CPI release (2nd Tuesday of each month)
"""
import logging
from datetime import datetime, timezone, timedelta
from typing import Optional

logger = logging.getLogger("omnitrader.econ_calendar")

# FOMC 2025-2026 meeting dates (from federalreserve.gov)
FOMC_DATES_2025_2026 = [
    "2025-01-29", "2025-03-19", "2025-05-07", "2025-06-18",
    "2025-07-30", "2025-09-17", "2025-10-29", "2025-12-10",
    "2026-01-28", "2026-03-18", "2026-04-29", "2026-06-17",
    "2026-07-29", "2026-09-16", "2026-10-28", "2026-12-09",
]

# Typical monthly release windows (approximate — exact dates vary)
MONTHLY_EVENTS = {
    "CPI":          "Typically released 2nd week of each month (BLS)",
    "PPI":          "Typically released 2nd-3rd week of each month (BLS)",
    "NFP":          "First Friday of each month (BLS)",
    "PCE":          "Last Friday of each month (BEA)",
    "FOMC_MINUTES": "3 weeks after each FOMC meeting",
}


class EconomicCalendarService:
    """Provides upcoming high-impact economic events and blackout-period detection."""

    def get_upcoming_events(self, days_ahead: int = 30) -> list[dict]:
        """
        Return upcoming high-impact economic events within days_ahead days.

        Each event dict contains:
            date:            str (ISO date)
            event:           str
            impact:          "HIGH" | "MEDIUM"
            country:         "US" | "IN" | "GLOBAL"
            days_until:      int
            description:     str
            trading_advice:  str
        """
        now    = datetime.now(timezone.utc)
        cutoff = now + timedelta(days=days_ahead)
        events: list[dict] = []

        # ── 1. FOMC meetings ───────────────────────────────────────────────────
        for date_str in FOMC_DATES_2025_2026:
            dt = datetime.fromisoformat(date_str).replace(
                hour=18, minute=0, second=0, microsecond=0, tzinfo=timezone.utc
            )
            if now <= dt <= cutoff:
                days_until = (dt - now).days
                events.append({
                    "date":           date_str,
                    "event":          "FOMC Meeting Decision",
                    "impact":         "HIGH",
                    "country":        "US",
                    "days_until":     days_until,
                    "description":    (
                        "Federal Reserve interest rate decision. "
                        "High volatility expected across equities, bonds, and forex."
                    ),
                    "trading_advice": (
                        "Avoid new positions 24h before. "
                        "Consider reducing size until decision passes."
                    ),
                })

        # ── 2. Non-Farm Payrolls — first Friday of each month at 13:30 UTC ────
        for month_offset in range(3):
            base      = now + timedelta(days=month_offset * 30)
            first_day = base.replace(
                day=1, hour=13, minute=30, second=0, microsecond=0
            )
            # Find first Friday (weekday 4)
            days_to_friday = (4 - first_day.weekday()) % 7
            nfp_date = first_day + timedelta(days=days_to_friday)
            if now <= nfp_date <= cutoff:
                events.append({
                    "date":           nfp_date.date().isoformat(),
                    "event":          "Non-Farm Payrolls (NFP)",
                    "impact":         "HIGH",
                    "country":        "US",
                    "days_until":     (nfp_date - now).days,
                    "description":    (
                        "US jobs report. High volatility in indices, USD, and bonds. "
                        "Surprise moves often exceed 1% on SPX."
                    ),
                    "trading_advice": (
                        "Avoid trades 2h before release. "
                        "Markets often gap on surprise. "
                        "Widen stops on open positions."
                    ),
                })

        # ── 3. US CPI — 2nd Tuesday of each month at 13:30 UTC ───────────────
        for month_offset in range(3):
            base      = now + timedelta(days=month_offset * 30)
            first_day = base.replace(
                day=1, hour=13, minute=30, second=0, microsecond=0
            )
            # Find first Tuesday (weekday 1)
            days_to_tue = (1 - first_day.weekday()) % 7
            first_tue   = first_day + timedelta(days=days_to_tue)
            cpi_date    = first_tue + timedelta(days=7)  # second Tuesday
            if now <= cpi_date <= cutoff:
                events.append({
                    "date":           cpi_date.date().isoformat(),
                    "event":          "US CPI Inflation Report",
                    "impact":         "HIGH",
                    "country":        "US",
                    "days_until":     (cpi_date - now).days,
                    "description":    (
                        "Consumer Price Index. Drives Federal Reserve rate expectations. "
                        "High-beta tech stocks most sensitive."
                    ),
                    "trading_advice": (
                        "Monitor high-beta positions. "
                        "Hot CPI prints can spike bond yields and compress equity multiples."
                    ),
                })

        # Sort by date ascending
        events.sort(key=lambda x: x["days_until"])
        return events

    def is_blackout_period(self, hours_ahead: int = 24) -> bool:
        """
        Returns True if a HIGH-impact event falls within hours_ahead hours.
        Automated order submission should check this before trading.
        """
        events = self.get_upcoming_events(days_ahead=2)
        for evt in events:
            if evt["impact"] == "HIGH" and evt["days_until"] * 24 <= hours_ahead:
                return True
        return False

    def get_next_event(self) -> Optional[dict]:
        """Return the single nearest upcoming HIGH-impact event."""
        events = self.get_upcoming_events(days_ahead=60)
        high_impact = [e for e in events if e["impact"] == "HIGH"]
        return high_impact[0] if high_impact else None
