"""
api/notification_prefs.py
==========================
Manage morning-brief notification preferences.

Endpoints
---------
GET  /api/v1/notifications/preferences          — read current prefs
PUT  /api/v1/notifications/preferences          — save prefs
POST /api/v1/notifications/test                 — send a test brief right now
GET  /api/v1/notifications/preview              — preview without sending
"""
from __future__ import annotations

import logging
import os
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, EmailStr, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import get_db

logger = logging.getLogger(__name__)
router = APIRouter()

# ── in-memory prefs store (persisted via env; for multi-user extend to DB) ────
_prefs: dict = {}


class NotificationPrefs(BaseModel):
    email_enabled:   bool = False
    email_address:   Optional[str] = None
    telegram_enabled:     bool = False
    telegram_bot_token:   Optional[str] = None
    telegram_chat_id:     Optional[str] = None
    min_score:       int  = Field(default=65, ge=0, le=100)
    send_time_utc:   str  = Field(default="01:00", description="HH:MM in UTC (7:00 AM IST = 01:30)")
    enabled:         bool = True


class PrefsResponse(BaseModel):
    prefs:          NotificationPrefs
    smtp_configured: bool
    next_send_utc:   Optional[str] = None


# ── helpers ───────────────────────────────────────────────────────────────────

def _get_prefs() -> NotificationPrefs:
    return NotificationPrefs(
        email_enabled=_prefs.get("email_enabled", False),
        email_address=_prefs.get("email_address", os.getenv("ALERT_EMAIL_TO")),
        telegram_enabled=_prefs.get("telegram_enabled", bool(os.getenv("TELEGRAM_BOT_TOKEN"))),
        telegram_bot_token=_prefs.get("telegram_bot_token", os.getenv("TELEGRAM_BOT_TOKEN")),
        telegram_chat_id=_prefs.get("telegram_chat_id", os.getenv("TELEGRAM_CHAT_ID")),
        min_score=_prefs.get("min_score", 65),
        send_time_utc=_prefs.get("send_time_utc", "01:30"),
        enabled=_prefs.get("enabled", True),
    )


def _smtp_configured() -> bool:
    return bool(
        os.getenv("SMTP_USER") and
        os.getenv("SMTP_PASS") and
        os.getenv("SMTP_HOST", "smtp.gmail.com")
    )


# ── routes ────────────────────────────────────────────────────────────────────

@router.get("/preferences", response_model=PrefsResponse)
async def get_preferences():
    """Return current notification preferences."""
    prefs = _get_prefs()
    # Mask secrets in response
    masked = prefs.model_copy()
    if masked.telegram_bot_token:
        masked.telegram_bot_token = masked.telegram_bot_token[:6] + "…"
    return PrefsResponse(
        prefs=masked,
        smtp_configured=_smtp_configured(),
        next_send_utc=prefs.send_time_utc + " UTC daily",
    )


@router.put("/preferences", response_model=PrefsResponse)
async def save_preferences(body: NotificationPrefs):
    """Save notification preferences (stored in memory; restart-persistent via .env)."""
    global _prefs
    _prefs = body.model_dump()
    logger.info("[NotificationPrefs] Updated: email=%s tg=%s score>=%d",
                body.email_enabled, body.telegram_enabled, body.min_score)

    masked = body.model_copy()
    if masked.telegram_bot_token:
        masked.telegram_bot_token = masked.telegram_bot_token[:6] + "…"
    return PrefsResponse(
        prefs=masked,
        smtp_configured=_smtp_configured(),
        next_send_utc=body.send_time_utc + " UTC daily",
    )


@router.post("/test")
async def send_test_brief(db: AsyncSession = Depends(get_db)):
    """
    Send the morning brief right now using current preferences.

    Useful to verify Email + Telegram are configured correctly before
    the next scheduled delivery.
    """
    from app.services.notifications import NotificationService

    prefs = _get_prefs()
    if not prefs.enabled:
        raise HTTPException(400, "Notifications are disabled. Enable them first.")

    if not prefs.email_enabled and not prefs.telegram_enabled:
        raise HTTPException(400, "No channels enabled. Enable Email or Telegram first.")

    svc = NotificationService()

    result = await svc.send_morning_brief(
        db=db,
        override_email=prefs.email_address if prefs.email_enabled else None,
        override_telegram_token=prefs.telegram_bot_token if prefs.telegram_enabled else None,
        override_telegram_chat_id=prefs.telegram_chat_id if prefs.telegram_enabled else None,
    )

    if result.get("status") == "no_opportunity":
        raise HTTPException(404, "No qualifying trade found in the last 24 hours. Run the trade scan first.")

    if result.get("status") == "no_channels":
        raise HTTPException(400, "Delivery failed — check SMTP / Telegram credentials.")

    return result


@router.get("/preview")
async def preview_brief(db: AsyncSession = Depends(get_db)):
    """
    Preview today's morning brief content without sending.

    Returns the formatted Telegram text + email subject so you can
    see exactly what would be delivered.
    """
    from app.engines.morning_brief_composer import (
        compose_morning_brief, format_telegram, format_email_html, format_email_plain,
    )

    brief = await compose_morning_brief(db)
    if not brief:
        raise HTTPException(404, "No qualifying trade found for today.")

    subject, _ = format_email_html(brief)
    telegram_text = format_telegram(brief)
    plain = format_email_plain(brief)

    return {
        "brief":          brief,
        "email_subject":  subject,
        "telegram_text":  telegram_text,
        "plain_text":     plain,
    }
