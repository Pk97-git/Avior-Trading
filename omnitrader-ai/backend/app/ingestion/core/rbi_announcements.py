"""
ingestion/core/rbi_announcements.py
=====================================
RbiAnnouncementsService — scrapes RBI press releases and monetary policy decisions.

Sources:
  1. RBI RSS feed: https://www.rbi.org.in/Scripts/rss.aspx?id=2 (press releases)
  2. RBI Monetary Policy: https://www.rbi.org.in/Scripts/BS_PressReleaseDisplay.aspx (policy decisions)

Sentiment scoring:
  - Hawkish language (rate hike, inflation concerns, tightening) → negative score
  - Dovish language (accommodation, growth support, rate cut) → positive score
  - is_policy_rate=True when announcement contains repo rate change
"""
import logging
import re
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from typing import Optional

import httpx
import xml.etree.ElementTree as ET
from sqlalchemy.dialects.postgresql import insert as pg_insert

from app.db.session import AsyncSessionLocal
from app.models.market_data import RbiAnnouncement

logger = logging.getLogger(__name__)

RBI_RSS_FEEDS = [
    ("https://www.rbi.org.in/Scripts/rss.aspx?id=2",  "Press Release"),
    ("https://www.rbi.org.in/Scripts/rss.aspx?id=4",  "Monetary Policy"),
    ("https://www.rbi.org.in/Scripts/rss.aspx?id=27", "Data Release"),
]

RBI_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
    "Accept":     "application/rss+xml, application/xml, text/xml, */*",
}

HAWKISH_WORDS = [
    "rate hike", "hike", "tighten", "inflation concern", "withdraw accommodation",
    "stance: withdrawal", "stance changed to withdrawal", "increase repo",
]
DOVISH_WORDS = [
    "rate cut", "cut", "accommodative", "growth support", "ease",
    "reduce repo", "supportive", "stimulus",
]


def _score_sentiment(title: str, summary: str) -> float:
    text = (title + " " + (summary or "")).lower()
    hawks = sum(1 for w in HAWKISH_WORDS if w in text)
    doves = sum(1 for w in DOVISH_WORDS if w in text)
    if hawks == 0 and doves == 0:
        return 0.0
    # Normalize to -1..+1 (dovish = positive for markets)
    return round((doves - hawks) / max(hawks + doves, 1), 2)


def _is_policy_rate(title: str, summary: str) -> bool:
    text = (title + " " + (summary or "")).lower()
    return any(kw in text for kw in [
        "repo rate", "monetary policy", "policy rates", "bi-monthly",
        "policy committee", "mpc", "repurchase rate",
    ])


def _parse_rss_item(item_elem: ET.Element, category: str) -> Optional[dict]:
    """Parse a single <item> from an RSS feed."""
    try:
        title   = (item_elem.findtext("title") or "").strip()
        link    = (item_elem.findtext("link")  or "").strip()
        pub_str = (item_elem.findtext("pubDate") or "").strip()
        desc    = (item_elem.findtext("description") or "").strip()
        # Strip HTML tags from description
        desc = re.sub(r"<[^>]+>", " ", desc).strip()[:500]

        if not title or not link:
            return None

        try:
            pub_date = parsedate_to_datetime(pub_str)
            if pub_date.tzinfo is None:
                pub_date = pub_date.replace(tzinfo=timezone.utc)
        except Exception:
            pub_date = datetime.now(timezone.utc)

        sentiment = _score_sentiment(title, desc)
        policy    = _is_policy_rate(title, desc)

        return {
            "published_date":  pub_date,
            "title":           title[:500],
            "category":        category,
            "url":             link,
            "summary":         desc or None,
            "sentiment_score": sentiment,
            "is_policy_rate":  policy,
        }
    except Exception as e:
        logger.debug("RBI RSS item parse error: %s", e)
        return None


class RbiAnnouncementsService:
    async def fetch_and_store(self) -> dict:
        """Fetch all configured RBI RSS feeds and upsert into DB."""
        total_new = 0
        errors = []

        async with httpx.AsyncClient(headers=RBI_HEADERS, timeout=30.0, follow_redirects=True) as client:
            for feed_url, category in RBI_RSS_FEEDS:
                try:
                    items = await self._fetch_feed(client, feed_url, category)
                    stored = await self._upsert(items)
                    total_new += stored
                    logger.info("[RBI] %s: %d items stored", category, stored)
                except Exception as e:
                    logger.warning("[RBI] Feed %s failed: %s", feed_url, e)
                    errors.append(str(e))

        return {"stored": total_new, "errors": errors}

    async def _fetch_feed(self, client: httpx.AsyncClient, url: str, category: str) -> list[dict]:
        resp = await client.get(url)
        resp.raise_for_status()

        root = ET.fromstring(resp.text)
        channel = root.find("channel")
        if channel is None:
            return []

        items = []
        for item in channel.findall("item"):
            parsed = _parse_rss_item(item, category)
            if parsed:
                items.append(parsed)

        return items

    async def _upsert(self, records: list[dict]) -> int:
        if not records:
            return 0
        async with AsyncSessionLocal() as db:
            stmt = pg_insert(RbiAnnouncement).values(records)
            stmt = stmt.on_conflict_do_update(
                constraint="uq_rbi_url",
                set_={
                    "title":           stmt.excluded.title,
                    "summary":         stmt.excluded.summary,
                    "sentiment_score": stmt.excluded.sentiment_score,
                    "is_policy_rate":  stmt.excluded.is_policy_rate,
                },
            )
            await db.execute(stmt)
            await db.commit()
        return len(records)
