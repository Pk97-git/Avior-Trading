"""
services/notifications.py
==========================
NotificationService — fires when new alerts are created.

Supports:
  • Slack webhooks  (SLACK_WEBHOOK_URL)
  • Email via SMTP  (SMTP_HOST / SMTP_PORT / SMTP_USER / SMTP_PASS / ALERT_EMAIL_TO)

Both channels are optional — if the env var is absent, that channel is skipped.
Errors are logged and swallowed so a notification failure never blocks the
main analysis pipeline.
"""
from __future__ import annotations

import asyncio
import logging
import os
import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from typing import List, Optional

logger = logging.getLogger(__name__)

# Emoji map keyed by signal name
_SIGNAL_EMOJI = {
    "STRONG_BUY":     "🟢",
    "ACCUMULATE":     "🔵",
    "PROACTIVE_SWING": "🟣",
    "AVOID":          "🟡",
    "DISTRIBUTION":   "🔴",
}


class NotificationService:
    def __init__(self) -> None:
        self.slack_webhook: Optional[str] = os.getenv("SLACK_WEBHOOK_URL")
        self.email_to: Optional[str] = os.getenv("ALERT_EMAIL_TO")
        self.smtp_host: str = os.getenv("SMTP_HOST", "smtp.gmail.com")
        self.smtp_port: int = int(os.getenv("SMTP_PORT", "587"))
        self.smtp_user: Optional[str] = os.getenv("SMTP_USER")
        self.smtp_pass: Optional[str] = os.getenv("SMTP_PASS")

    # ──────────────────────────────────────────────────────────────────────────
    # Public entry point
    # ──────────────────────────────────────────────────────────────────────────

    async def send_alert(
        self,
        ticker: str,
        signal: str,
        prev_signal: Optional[str],
        final_score: int,
        thesis_bullets: List[str],
    ) -> None:
        """Fire Slack + email notifications concurrently. Never raises."""
        tasks = []
        if self.slack_webhook:
            tasks.append(self._send_slack(ticker, signal, prev_signal, final_score, thesis_bullets))
        if self.email_to and self.smtp_user and self.smtp_pass:
            tasks.append(self._send_email(ticker, signal, prev_signal, final_score, thesis_bullets))

        if not tasks:
            logger.debug("[Notifications] No channels configured — skipping.")
            return

        results = await asyncio.gather(*tasks, return_exceptions=True)
        for r in results:
            if isinstance(r, Exception):
                logger.warning("[Notifications] Channel error: %s", r)

    # ──────────────────────────────────────────────────────────────────────────
    # Slack
    # ──────────────────────────────────────────────────────────────────────────

    async def _send_slack(
        self,
        ticker: str,
        signal: str,
        prev_signal: Optional[str],
        final_score: int,
        thesis_bullets: List[str],
    ) -> None:
        """POST a formatted message to the Slack incoming webhook."""
        emoji = _SIGNAL_EMOJI.get(signal, "⚪")
        signal_label = signal.replace("_", " ").title()

        if prev_signal and prev_signal != signal:
            prev_label = prev_signal.replace("_", " ").title()
            change_line = f"{prev_label} → *{signal_label}*"
        else:
            change_line = f"*{signal_label}*"

        bullets_text = "\n".join(
            f"• {b}" for b in (thesis_bullets or [])[:3]
        )

        text = (
            f"{emoji} *{ticker}* — {change_line}\n"
            f"Score: *{final_score}/100*\n"
            f"{bullets_text}"
        )

        payload = {
            "text": text,
            "blocks": [
                {
                    "type": "section",
                    "text": {"type": "mrkdwn", "text": text},
                }
            ],
        }

        loop = asyncio.get_event_loop()
        await loop.run_in_executor(None, self._post_slack, payload)
        logger.info("[Notifications] Slack sent for %s (%s)", ticker, signal)

    def _post_slack(self, payload: dict) -> None:
        """Synchronous requests call — runs in a thread executor."""
        import requests  # local import to avoid top-level dependency issues

        resp = requests.post(
            self.slack_webhook,  # type: ignore[arg-type]
            json=payload,
            timeout=10,
        )
        resp.raise_for_status()

    # ──────────────────────────────────────────────────────────────────────────
    # Email
    # ──────────────────────────────────────────────────────────────────────────

    async def _send_email(
        self,
        ticker: str,
        signal: str,
        prev_signal: Optional[str],
        final_score: int,
        thesis_bullets: List[str],
    ) -> None:
        """Send plain-text + HTML email via SMTP (runs smtplib in executor)."""
        subject = f"[OmniTrader] {ticker}: {signal.replace('_', ' ').title()} (score {final_score})"
        plain, html = self._build_email_body(ticker, signal, prev_signal, final_score, thesis_bullets)

        loop = asyncio.get_event_loop()
        await loop.run_in_executor(
            None,
            self._smtp_send,
            subject,
            plain,
            html,
        )
        logger.info("[Notifications] Email sent for %s (%s) → %s", ticker, signal, self.email_to)

    def _build_email_body(
        self,
        ticker: str,
        signal: str,
        prev_signal: Optional[str],
        final_score: int,
        thesis_bullets: List[str],
    ) -> tuple[str, str]:
        signal_label = signal.replace("_", " ").title()
        emoji = _SIGNAL_EMOJI.get(signal, "")

        if prev_signal and prev_signal != signal:
            prev_label = prev_signal.replace("_", " ").title()
            change_line = f"{prev_label} → {signal_label}"
        else:
            change_line = signal_label

        top3 = (thesis_bullets or [])[:3]
        bullets_plain = "\n".join(f"  • {b}" for b in top3)
        bullets_html = "".join(f"<li>{b}</li>" for b in top3)

        plain = (
            f"OmniTrader AI — {ticker} Alert\n"
            f"{'=' * 40}\n\n"
            f"Signal : {change_line}\n"
            f"Score  : {final_score}/100\n\n"
            f"Thesis:\n{bullets_plain}\n\n"
            f"{'—' * 40}\n"
            f"This is an automated message from OmniTrader AI.\n"
        )

        html = f"""<!DOCTYPE html>
<html>
<head><meta charset="utf-8"></head>
<body style="font-family:sans-serif;background:#0f1117;color:#e2e8f0;padding:24px;margin:0;">
  <div style="max-width:560px;margin:auto;background:#1a1f2e;border-radius:12px;padding:24px;border:1px solid #2d3748;">
    <h2 style="margin:0 0 4px 0;font-size:18px;">
      {emoji} <span style="color:#7dd3fc;">{ticker}</span> — {signal_label}
    </h2>
    <p style="margin:0 0 16px 0;color:#94a3b8;font-size:13px;">Signal: {change_line}</p>

    <div style="display:flex;align-items:center;gap:12px;margin-bottom:20px;">
      <div style="background:#0ea5e9;color:#fff;border-radius:8px;padding:8px 16px;font-size:24px;font-weight:700;">
        {final_score}
      </div>
      <span style="color:#94a3b8;font-size:13px;">out of 100</span>
    </div>

    <h3 style="font-size:13px;color:#94a3b8;margin:0 0 8px 0;text-transform:uppercase;letter-spacing:.05em;">
      Key Thesis
    </h3>
    <ul style="margin:0 0 20px 0;padding-left:20px;color:#cbd5e1;font-size:14px;line-height:1.7;">
      {bullets_html}
    </ul>

    <p style="font-size:11px;color:#475569;margin:0;border-top:1px solid #2d3748;padding-top:12px;">
      This is an automated alert from OmniTrader AI.
    </p>
  </div>
</body>
</html>"""

        return plain, html

    def _smtp_send(self, subject: str, plain: str, html: str) -> None:
        """Synchronous SMTP send — runs in a thread executor."""
        msg = MIMEMultipart("alternative")
        msg["Subject"] = subject
        msg["From"] = self.smtp_user  # type: ignore[assignment]
        msg["To"] = self.email_to  # type: ignore[assignment]
        msg.attach(MIMEText(plain, "plain"))
        msg.attach(MIMEText(html, "html"))

        with smtplib.SMTP(self.smtp_host, self.smtp_port) as server:
            server.ehlo()
            server.starttls()
            server.login(self.smtp_user, self.smtp_pass)  # type: ignore[arg-type]
            server.sendmail(self.smtp_user, self.email_to, msg.as_string())  # type: ignore[arg-type]

    # ──────────────────────────────────────────────────────────────────────────
    # Health alerts
    # ──────────────────────────────────────────────────────────────────────────

    async def send_health_alert(self, warnings: List[str]) -> None:
        """
        Fire a system-health notification to all configured channels.

        Formats a structured message listing data-freshness warnings from
        HealthMonitor. Never raises — errors are logged and swallowed.
        """
        if not warnings:
            return

        tasks = []
        if self.slack_webhook:
            tasks.append(self._send_health_slack(warnings))
        if self.email_to and self.smtp_user and self.smtp_pass:
            tasks.append(self._send_health_email(warnings))

        if not tasks:
            logger.debug("[Notifications] No channels configured — skipping health alert.")
            return

        results = await asyncio.gather(*tasks, return_exceptions=True)
        for r in results:
            if isinstance(r, Exception):
                logger.warning("[Notifications] Health alert channel error: %s", r)

    async def _send_health_slack(self, warnings: List[str]) -> None:
        """POST a formatted health-alert message to the Slack webhook."""
        bullets = "\n".join(f"• {w}" for w in warnings)
        text = (
            f"⚠️ *OmniTrader Health Alert*\n"
            f"The following data freshness issues were detected:\n"
            f"{bullets}"
        )
        payload = {
            "text": text,
            "blocks": [
                {
                    "type": "section",
                    "text": {"type": "mrkdwn", "text": text},
                }
            ],
        }

        loop = asyncio.get_event_loop()
        await loop.run_in_executor(None, self._post_slack, payload)
        logger.info("[Notifications] Health alert sent to Slack (%d warnings)", len(warnings))

    async def _send_health_email(self, warnings: List[str]) -> None:
        """Send a health-alert email via SMTP."""
        subject = f"[OmniTrader] System Health Alert — {len(warnings)} warning(s)"
        plain, html = self._build_health_email_body(warnings)

        loop = asyncio.get_event_loop()
        await loop.run_in_executor(None, self._smtp_send, subject, plain, html)
        logger.info("[Notifications] Health alert email sent → %s", self.email_to)

    def _build_health_email_body(self, warnings: List[str]) -> tuple[str, str]:
        """Build plain-text and HTML bodies for a health-alert email."""
        bullets_plain = "\n".join(f"  • {w}" for w in warnings)
        bullets_html  = "".join(f"<li>{w}</li>" for w in warnings)

        plain = (
            f"OmniTrader AI — System Health Alert\n"
            f"{'=' * 40}\n\n"
            f"The following data freshness issues were detected:\n\n"
            f"{bullets_plain}\n\n"
            f"Please investigate promptly to ensure signal quality.\n\n"
            f"{'—' * 40}\n"
            f"This is an automated message from OmniTrader AI.\n"
        )

        html = f"""<!DOCTYPE html>
<html>
<head><meta charset="utf-8"></head>
<body style="font-family:sans-serif;background:#0f1117;color:#e2e8f0;padding:24px;margin:0;">
  <div style="max-width:560px;margin:auto;background:#1a1f2e;border-radius:12px;padding:24px;border:1px solid #2d3748;">
    <h2 style="margin:0 0 8px 0;font-size:18px;color:#fbbf24;">
      ⚠️ OmniTrader Health Alert
    </h2>
    <p style="margin:0 0 16px 0;color:#94a3b8;font-size:13px;">
      The following data freshness issues were detected and require attention.
    </p>

    <h3 style="font-size:13px;color:#94a3b8;margin:0 0 8px 0;text-transform:uppercase;letter-spacing:.05em;">
      Warnings
    </h3>
    <ul style="margin:0 0 20px 0;padding-left:20px;color:#fcd34d;font-size:14px;line-height:1.7;">
      {bullets_html}
    </ul>

    <p style="font-size:11px;color:#475569;margin:0;border-top:1px solid #2d3748;padding-top:12px;">
      This is an automated health report from OmniTrader AI.
    </p>
  </div>
</body>
</html>"""

        return plain, html
