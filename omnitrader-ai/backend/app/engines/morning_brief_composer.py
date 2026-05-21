"""
engines/morning_brief_composer.py
===================================
Composes the daily morning brief — one focused trade idea with full reasoning.

Picks the highest-scored trade_opportunity from the last 24 h, enriches it
with the matching intelligence signal, and returns structured content ready
for Email, Telegram, or any other notification channel.
"""
from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from typing import Optional

from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger(__name__)

# ── helpers ────────────────────────────────────────────────────────────────────

def _fmt_pct(val: float, sign: bool = True) -> str:
    s = f"{val:+.1f}%" if sign else f"{val:.1f}%"
    return s

def _signal_emoji(signal: str) -> str:
    return {
        "STRONG_BUY": "🟢", "ACCUMULATE": "🟢", "PROACTIVE_SWING": "🟣",
        "HOLD": "🔵", "REDUCE": "🟡", "AVOID": "🔴",
        "DISTRIBUTION": "🔴", "SELL": "🔴",
    }.get(signal, "⚪")

def _rr_label(rr: float) -> str:
    if rr >= 3:   return "Excellent (3:1+)"
    if rr >= 2:   return "Good (2:1+)"
    if rr >= 1.5: return "Fair (1.5:1)"
    return f"Low ({rr:.1f}:1)"

# ── main composer ─────────────────────────────────────────────────────────────

async def compose_morning_brief(db: AsyncSession) -> Optional[dict]:
    """
    Returns a dict with all fields needed to build Email / Telegram messages,
    or None if no actionable opportunity exists.
    """
    cutoff = datetime.now(timezone.utc) - timedelta(hours=28)

    # 1. Fetch best opportunity in the last 28 hours
    try:
        row = await db.execute(
            text("""
                SELECT t.ticker, t.signal, t.final_score, t.entry_price,
                       t.stop_loss, t.target_price, t.time_horizon,
                       t.risk_reward, t.position_size_pct, t.thesis_bullets,
                       t.risk_factors, t.conviction,
                       s.name as company_name, s.sector, s.country
                FROM   trade_opportunities t
                LEFT JOIN stocks s ON s.ticker = t.ticker
                WHERE  t.created_at >= :cutoff
                  AND  t.signal IN ('STRONG_BUY','ACCUMULATE','PROACTIVE_SWING')
                  AND  t.final_score >= 65
                ORDER  BY t.final_score DESC, t.conviction DESC
                LIMIT  1
            """),
            {"cutoff": cutoff},
        )
        opp = row.fetchone()
    except Exception as e:
        logger.warning("[MorningBrief] DB query failed: %s", e)
        return None

    if not opp:
        logger.info("[MorningBrief] No qualifying opportunity found.")
        return None

    ticker       = opp.ticker
    signal       = opp.signal or "ACCUMULATE"
    score        = int(opp.final_score or 0)
    entry        = float(opp.entry_price or 0)
    stop         = float(opp.stop_loss or 0)
    target       = float(opp.target_price or 0)
    horizon      = opp.time_horizon or "10–15 days"
    rr           = float(opp.risk_reward or 0)
    pos_size     = float(opp.position_size_pct or 3)
    bullets      = opp.thesis_bullets or []
    risks        = opp.risk_factors or []
    company      = opp.company_name or ticker
    sector       = opp.sector or "—"
    country      = opp.country or "IN"

    currency     = "₹" if country == "IN" else "$"

    # Derived metrics
    stop_pct  = ((stop - entry) / entry * 100) if entry else 0
    tgt_pct   = ((target - entry) / entry * 100) if entry else 0

    top_bullets = bullets[:4] if isinstance(bullets, list) else []
    top_risks   = risks[:2] if isinstance(risks, list) else []

    return {
        "ticker":       ticker,
        "company":      company,
        "sector":       sector,
        "country":      country,
        "signal":       signal,
        "score":        score,
        "entry":        entry,
        "stop":         stop,
        "target":       target,
        "stop_pct":     stop_pct,
        "target_pct":   tgt_pct,
        "rr":           rr,
        "rr_label":     _rr_label(rr),
        "pos_size":     pos_size,
        "horizon":      horizon,
        "bullets":      top_bullets,
        "risks":        top_risks,
        "currency":     currency,
        "emoji":        _signal_emoji(signal),
        "generated_at": datetime.now(timezone.utc).strftime("%d %b %Y, %H:%M UTC"),
    }


# ── formatters ────────────────────────────────────────────────────────────────

def format_telegram(brief: dict) -> str:
    """Plain-text + Markdown for Telegram (MarkdownV2 escaping avoided — use HTML parse mode)."""
    bullets_text = "\n".join(f"  • {b}" for b in brief["bullets"]) or "  • No thesis available"
    risks_text   = "\n".join(f"  ⚠️ {r}" for r in brief["risks"])   or "  ⚠️ Sector/market risk"

    c = brief["currency"]
    entry_str = f"{c}{brief['entry']:,.2f}" if brief["entry"] else "—"
    stop_str  = f"{c}{brief['stop']:,.2f} ({brief['stop_pct']:+.1f}%)" if brief["stop"] else "—"
    tgt_str   = f"{c}{brief['target']:,.2f} ({brief['target_pct']:+.1f}%)" if brief["target"] else "—"

    return (
        f"{brief['emoji']} <b>TOP TRADE TODAY — {brief['ticker']}</b>\n"
        f"<i>{brief['company']} | {brief['sector']}</i>\n"
        f"━━━━━━━━━━━━━━━━━━━━━━━━━\n"
        f"📈 <b>BUY</b>  at  <b>{entry_str}</b>\n"
        f"🛑 Stop:    <b>{stop_str}</b>\n"
        f"🎯 Target:  <b>{tgt_str}</b>\n"
        f"⚖️  R/R: <b>{brief['rr_label']}</b> | Score: <b>{brief['score']}/100</b>\n\n"
        f"<b>WHY THIS TRADE:</b>\n"
        f"{bullets_text}\n\n"
        f"<b>KEY RISKS:</b>\n"
        f"{risks_text}\n\n"
        f"⏱ Horizon: <b>{brief['horizon']}</b> | Position: <b>{brief['pos_size']:.0f}%</b> of portfolio\n"
        f"<i>Generated {brief['generated_at']}</i>"
    )


def format_email_html(brief: dict) -> tuple[str, str]:
    """Returns (subject, html_body)."""
    c = brief["currency"]
    entry_str = f"{c}{brief['entry']:,.2f}" if brief["entry"] else "—"
    stop_str  = f"{c}{brief['stop']:,.2f}" if brief["stop"] else "—"
    tgt_str   = f"{c}{brief['target']:,.2f}" if brief["target"] else "—"

    subject = (
        f"[OmniTrader] {brief['ticker']} — Score {brief['score']}/100 | "
        f"Entry {entry_str} → Target {tgt_str}"
    )

    bullet_rows = "".join(
        f"<tr><td style='padding:4px 0;color:#94a3b8;font-size:14px;line-height:1.6;'>• {b}</td></tr>"
        for b in brief["bullets"]
    ) or "<tr><td style='color:#94a3b8;font-size:14px;'>No thesis bullets available.</td></tr>"

    risk_rows = "".join(
        f"<tr><td style='padding:3px 0;color:#fcd34d;font-size:13px;'>⚠️ {r}</td></tr>"
        for r in brief["risks"]
    ) or "<tr><td style='color:#fcd34d;font-size:13px;'>⚠️ Sector/market risk</td></tr>"

    stop_pct_str = f"{brief['stop_pct']:+.1f}%"
    tgt_pct_str  = f"{brief['target_pct']:+.1f}%"

    html = f"""<!DOCTYPE html>
<html>
<head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"></head>
<body style="margin:0;padding:0;background:#0f1117;font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',sans-serif;">
<div style="max-width:580px;margin:24px auto;background:#1a1f2e;border-radius:16px;overflow:hidden;border:1px solid #2d3748;">

  <!-- Header -->
  <div style="background:linear-gradient(135deg,#1e3a5f,#0f2744);padding:24px 28px;">
    <div style="font-size:11px;color:#64748b;text-transform:uppercase;letter-spacing:.1em;margin-bottom:6px;">
      OmniTrader AI · Morning Brief · {brief['generated_at']}
    </div>
    <div style="font-size:22px;font-weight:700;color:#f1f5f9;">
      {brief['emoji']} {brief['ticker']}
      <span style="font-size:13px;font-weight:400;color:#94a3b8;margin-left:8px;">
        {brief['company']}
      </span>
    </div>
    <div style="font-size:12px;color:#64748b;margin-top:4px;">{brief['sector']} · {brief['country']}</div>
  </div>

  <!-- Score bar -->
  <div style="background:#111827;padding:16px 28px;display:flex;align-items:center;gap:16px;">
    <div style="text-align:center;min-width:64px;">
      <div style="font-size:36px;font-weight:800;color:#22d3ee;line-height:1;">{brief['score']}</div>
      <div style="font-size:10px;color:#64748b;text-transform:uppercase;">/ 100</div>
    </div>
    <div style="flex:1;">
      <div style="background:#1f2937;border-radius:4px;height:8px;">
        <div style="background:linear-gradient(90deg,#0ea5e9,#22d3ee);height:8px;border-radius:4px;width:{brief['score']}%;"></div>
      </div>
      <div style="font-size:12px;color:#94a3b8;margin-top:6px;">
        {brief['signal'].replace('_',' ').title()} · R/R {brief['rr_label']}
      </div>
    </div>
  </div>

  <!-- Trade levels -->
  <div style="padding:20px 28px;">
    <table style="width:100%;border-collapse:collapse;">
      <tr>
        <td style="padding:8px 12px;background:#0f2744;border-radius:8px 8px 0 0;width:33%;">
          <div style="font-size:10px;color:#64748b;text-transform:uppercase;letter-spacing:.05em;">Entry Zone</div>
          <div style="font-size:18px;font-weight:700;color:#22d3ee;margin-top:2px;">{entry_str}</div>
        </td>
        <td style="padding:8px 12px;background:#2d1515;border-radius:8px 8px 0 0;width:33%;margin-left:4px;">
          <div style="font-size:10px;color:#64748b;text-transform:uppercase;letter-spacing:.05em;">Stop Loss</div>
          <div style="font-size:18px;font-weight:700;color:#f87171;margin-top:2px;">{stop_str}</div>
          <div style="font-size:11px;color:#f87171;">{stop_pct_str}</div>
        </td>
        <td style="padding:8px 12px;background:#0d2d1a;border-radius:8px 8px 0 0;width:33%;margin-left:4px;">
          <div style="font-size:10px;color:#64748b;text-transform:uppercase;letter-spacing:.05em;">Target</div>
          <div style="font-size:18px;font-weight:700;color:#4ade80;margin-top:2px;">{tgt_str}</div>
          <div style="font-size:11px;color:#4ade80;">{tgt_pct_str}</div>
        </td>
      </tr>
    </table>
    <div style="margin-top:8px;font-size:12px;color:#64748b;">
      Position size: <strong style="color:#94a3b8;">{brief['pos_size']:.0f}%</strong> of portfolio ·
      Horizon: <strong style="color:#94a3b8;">{brief['horizon']}</strong>
    </div>
  </div>

  <!-- Why -->
  <div style="padding:0 28px 20px;">
    <div style="font-size:11px;color:#64748b;text-transform:uppercase;letter-spacing:.1em;margin-bottom:10px;">
      Why This Trade
    </div>
    <table style="width:100%;border-collapse:collapse;">
      {bullet_rows}
    </table>
  </div>

  <!-- Risks -->
  <div style="padding:0 28px 24px;">
    <div style="font-size:11px;color:#64748b;text-transform:uppercase;letter-spacing:.1em;margin-bottom:10px;">
      Key Risks
    </div>
    <table style="width:100%;border-collapse:collapse;">
      {risk_rows}
    </table>
  </div>

  <!-- Footer -->
  <div style="background:#111827;padding:16px 28px;text-align:center;border-top:1px solid #1f2937;">
    <p style="font-size:12px;color:#475569;margin:0;">
      This is an automated morning brief from OmniTrader AI.<br>
      Past performance is not indicative of future results. Always use stop losses.
    </p>
  </div>
</div>
</body>
</html>"""

    return subject, html


def format_email_plain(brief: dict) -> str:
    c = brief["currency"]
    entry_str = f"{c}{brief['entry']:,.2f}" if brief["entry"] else "—"
    stop_str  = f"{c}{brief['stop']:,.2f} ({brief['stop_pct']:+.1f}%)" if brief["stop"] else "—"
    tgt_str   = f"{c}{brief['target']:,.2f} ({brief['target_pct']:+.1f}%)" if brief["target"] else "—"

    bullets_text = "\n".join(f"  • {b}" for b in brief["bullets"]) or "  • No thesis available"
    risks_text   = "\n".join(f"  ⚠ {r}" for r in brief["risks"])  or "  ⚠ Sector/market risk"

    return (
        f"OmniTrader AI — Morning Brief\n"
        f"{'=' * 44}\n\n"
        f"TOP TRADE: {brief['ticker']} ({brief['company']})\n"
        f"Signal: {brief['signal']} | Score: {brief['score']}/100\n\n"
        f"TRADE LEVELS\n"
        f"  Entry:     {entry_str}\n"
        f"  Stop Loss: {stop_str}\n"
        f"  Target:    {tgt_str}\n"
        f"  R/R:       {brief['rr_label']}\n"
        f"  Position:  {brief['pos_size']:.0f}% of portfolio\n"
        f"  Horizon:   {brief['horizon']}\n\n"
        f"WHY THIS TRADE:\n{bullets_text}\n\n"
        f"KEY RISKS:\n{risks_text}\n\n"
        f"{'—' * 44}\n"
        f"Generated {brief['generated_at']}\n"
        f"OmniTrader AI — Past performance is not indicative of future results.\n"
    )
