"""
event_extractor.py
==================
Classifies news headlines into structured event types using Claude.
Updates news_sentiment.event_type for unclassified recent headlines.
"""
import asyncio
import json
import logging
import re
from datetime import datetime, timedelta
from typing import Optional

from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import text

from app.db.session import async_session_factory
from anthropic import AsyncAnthropic

logger = logging.getLogger("omnitrader.ingestion.event_extractor")

# Valid event type labels
VALID_EVENT_TYPES = {
    "EARNINGS_BEAT",
    "EARNINGS_MISS",
    "EARNINGS_IN_LINE",
    "GUIDANCE_RAISE",
    "GUIDANCE_LOWER",
    "MERGER_ACQUISITION",
    "LEADERSHIP_CHANGE",
    "REGULATORY_ACTION",
    "PRODUCT_LAUNCH",
    "LEGAL_ACTION",
    "DIVIDEND_CHANGE",
    "SHARE_BUYBACK",
    "ANALYST_UPGRADE",
    "ANALYST_DOWNGRADE",
    "OTHER",
}

EVENT_TYPE_LIST = ", ".join(sorted(VALID_EVENT_TYPES))


async def _classify_batch_with_claude(
    headlines: list[dict],
) -> list[dict]:
    """
    Send a batch of headlines to Claude Haiku for event type classification.

    Each item in headlines: {"time": ..., "ticker": ..., "headline": ...}
    Returns list of {"time": ..., "ticker": ..., "event_type": ...}
    """
    client = AsyncAnthropic()

    # Build numbered list for the prompt
    numbered = "\n".join(
        f"{i + 1}. [{item['ticker']}] {item['headline']}"
        for i, item in enumerate(headlines)
    )

    prompt = f"""Classify each news headline below into exactly one event type from this list:
{EVENT_TYPE_LIST}

Return a JSON array where each element has:
- "index": the 1-based number of the headline
- "event_type": one of the event types above (use OTHER if none fits)

Headlines:
{numbered}

Respond with a valid JSON array only. Example format:
[{{"index": 1, "event_type": "EARNINGS_BEAT"}}, {{"index": 2, "event_type": "ANALYST_UPGRADE"}}]"""

    try:
        message = await client.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=2048,
            messages=[{"role": "user", "content": prompt}],
        )
        raw = message.content[0].text.strip()

        # Parse JSON array from response
        json_match = re.search(r"\[.*\]", raw, re.DOTALL)
        if json_match:
            parsed = json.loads(json_match.group())
        else:
            parsed = json.loads(raw)

        # Map index → event_type
        index_map: dict[int, str] = {}
        for item in parsed:
            idx = int(item.get("index", 0))
            etype = str(item.get("event_type", "OTHER")).upper()
            if etype not in VALID_EVENT_TYPES:
                etype = "OTHER"
            index_map[idx] = etype

        # Build results aligned with input headlines
        results = []
        for i, headline_item in enumerate(headlines):
            event_type = index_map.get(i + 1, "OTHER")
            results.append(
                {
                    "time": headline_item["time"],
                    "ticker": headline_item["ticker"],
                    "event_type": event_type,
                }
            )
        return results

    except Exception as exc:
        logger.warning("Claude event classification failed: %s", exc)
        # Fall back: mark all as OTHER
        return [
            {
                "time": item["time"],
                "ticker": item["ticker"],
                "event_type": "OTHER",
            }
            for item in headlines
        ]


class EventExtractorService:
    """
    Classifies unclassified news_sentiment rows using Claude and
    writes the event_type back to the database.
    """

    async def run_batch(
        self,
        days_back: int = 7,
        batch_size: int = 50,
    ) -> dict:
        """
        1. Query news_sentiment WHERE event_type IS NULL AND published_at > now() - interval
        2. Process in batches of batch_size
        3. For each batch, send all headlines to Claude
        4. UPDATE news_sentiment SET event_type = ? WHERE time = ? AND ticker = ?
        5. Rate limit: 1s between batches
        """
        results = {"classified": 0, "batches": 0, "errors": 0}

        cutoff = datetime.utcnow() - timedelta(days=days_back)

        async with async_session_factory() as db:
            try:
                # Fetch all unclassified recent rows
                fetch_result = await db.execute(
                    text("""
                        SELECT time, ticker, headline
                        FROM news_sentiment
                        WHERE event_type IS NULL
                          AND time > :cutoff
                          AND headline IS NOT NULL
                        ORDER BY time DESC
                    """),
                    {"cutoff": cutoff},
                )
                rows = fetch_result.fetchall()
            except Exception as exc:
                logger.error("Failed to fetch unclassified headlines: %s", exc)
                return results

        if not rows:
            logger.info("No unclassified headlines found in the last %d days", days_back)
            return results

        headlines = [
            {"time": row.time, "ticker": row.ticker, "headline": row.headline}
            for row in rows
        ]

        logger.info(
            "Found %d unclassified headlines — processing in batches of %d",
            len(headlines),
            batch_size,
        )

        # Process in batches
        for batch_start in range(0, len(headlines), batch_size):
            batch = headlines[batch_start : batch_start + batch_size]

            try:
                classified = await _classify_batch_with_claude(batch)
            except Exception as exc:
                logger.error("Batch classification error: %s", exc)
                results["errors"] += 1
                await asyncio.sleep(1)
                continue

            # Write results back to DB
            async with async_session_factory() as db:
                try:
                    for item in classified:
                        await db.execute(
                            text("""
                                UPDATE news_sentiment
                                SET event_type = :event_type
                                WHERE time = :t AND ticker = :ticker
                            """),
                            {
                                "event_type": item["event_type"],
                                "t": item["time"],
                                "ticker": item["ticker"],
                            },
                        )
                    await db.commit()
                    results["classified"] += len(classified)
                    results["batches"] += 1
                    logger.info(
                        "Classified batch %d/%d (%d headlines)",
                        results["batches"],
                        -(-len(headlines) // batch_size),
                        len(classified),
                    )
                except Exception as exc:
                    logger.error("DB write failed for batch: %s", exc)
                    await db.rollback()
                    results["errors"] += 1

            # Rate limit between batches
            await asyncio.sleep(1)

        return results
