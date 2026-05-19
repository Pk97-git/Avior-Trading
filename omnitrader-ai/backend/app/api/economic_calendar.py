"""
api/economic_calendar.py
========================
Economic calendar endpoints.

GET /events           — upcoming high-impact macro events
GET /events/blackout  — whether we are in a trading blackout window
"""
import logging
from typing import Optional

from fastapi import APIRouter, Query

from app.ingestion.core.economic_calendar import EconomicCalendarService

router  = APIRouter()
logger  = logging.getLogger(__name__)

_svc = EconomicCalendarService()


# ── GET /events ────────────────────────────────────────────────────────────────

@router.get("/events")
async def get_upcoming_events(
    days_ahead: int = Query(30, ge=1, le=90, description="How many days ahead to scan"),
):
    """
    Return all upcoming high-impact economic events within days_ahead days.
    Includes FOMC meetings, NFP, and CPI release dates.
    """
    events = _svc.get_upcoming_events(days_ahead=days_ahead)
    return events


# ── GET /events/blackout ───────────────────────────────────────────────────────

@router.get("/events/blackout")
async def get_blackout_status():
    """
    Returns whether the current time is within a trading blackout window
    (i.e., a HIGH-impact macro event is scheduled within the next 24 hours).

    Circuit breakers and order-submission endpoints should poll this endpoint
    before placing trades.

    Returns:
        is_blackout: bool
        reason:      str | None   — human-readable description of the event
        next_event:  dict | None  — the nearest upcoming HIGH-impact event
    """
    is_blackout = _svc.is_blackout_period(hours_ahead=24)
    next_event  = _svc.get_next_event()

    reason: Optional[str] = None
    if is_blackout and next_event:
        reason = (
            f"{next_event['event']} on {next_event['date']} "
            f"({next_event['days_until']}d away). {next_event['trading_advice']}"
        )

    return {
        "is_blackout": is_blackout,
        "reason":      reason,
        "next_event":  next_event,
    }
