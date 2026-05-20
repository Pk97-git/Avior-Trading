"""
news.py
=======
NewsAgent — analyzes breaking news (last 48 hours) for a ticker.
Distinct from SentimentAgent (30-day rolling aggregates).

Scores based on:
  1. Recent event types (EARNINGS_BEAT, GUIDANCE_RAISE vs EARNINGS_MISS, LEGAL_ACTION)
  2. Sentiment velocity (is sentiment improving or worsening?)
  3. Volume of coverage (many articles = high attention)
  4. High-impact events (M&A, leadership change)

Returns {"score": int, "thesis": list[str], "breaking_event": str|None}
"""
import logging
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import text

logger = logging.getLogger("omnitrader.agent.news")

# Event type score contributions
EVENT_SCORES = {
    "EARNINGS_BEAT":     +20,
    "GUIDANCE_RAISE":    +18,
    "ANALYST_UPGRADE":   +12,
    "SHARE_BUYBACK":     +8,
    "MERGER_ACQUISITION": +10,  # positive for target; acquirer handled separately
    "DIVIDEND_CHANGE":   +8,
    "EARNINGS_MISS":     -20,
    "GUIDANCE_LOWER":    -18,
    "ANALYST_DOWNGRADE": -12,
    "REGULATORY_ACTION": -15,
    "LEGAL_ACTION":      -12,
    "LEADERSHIP_CHANGE": -8,
}

# Acquirer penalty override (execution risk)
ACQUIRER_PENALTY = -5

# Priority ordering for breaking_event selection (higher index = higher impact)
EVENT_IMPACT_RANK = [
    "LEADERSHIP_CHANGE",
    "ANALYST_UPGRADE",
    "ANALYST_DOWNGRADE",
    "SHARE_BUYBACK",
    "DIVIDEND_CHANGE",
    "GUIDANCE_RAISE",
    "GUIDANCE_LOWER",
    "LEGAL_ACTION",
    "REGULATORY_ACTION",
    "MERGER_ACQUISITION",
    "EARNINGS_BEAT",
    "EARNINGS_MISS",
]


class NewsAgent:
    def __init__(self, db: AsyncSession, ticker: str):
        self.db = db
        self.ticker = ticker

    async def analyze(self) -> dict:
        """
        Returns:
            {"score": int, "thesis": list[str], "breaking_event": str|None}
        """
        # ── Query 1: last 48h headlines ───────────────────────────────────────
        try:
            recent_rows = await self.db.execute(
                text("""
                    SELECT title, sentiment_score, event_type, published_at, source
                    FROM news_sentiment
                    WHERE ticker = :t AND published_at > NOW() - INTERVAL '48 hours'
                    ORDER BY published_at DESC
                    LIMIT 20
                """),
                {"t": self.ticker},
            )
            recent_articles = recent_rows.fetchall()
        except Exception as e:
            logger.warning("NewsAgent %s: recent fetch failed: %s", self.ticker, e)
            return {
                "score": 50,
                "thesis": ["News data unavailable. Using neutral score."],
                "breaking_event": None,
            }

        if not recent_articles:
            return {
                "score": 50,
                "thesis": ["No recent news coverage."],
                "breaking_event": None,
            }

        # ── Query 2: 7-day rolling avg for velocity comparison ────────────────
        avg_7d = None
        try:
            avg_row = await self.db.execute(
                text("""
                    SELECT AVG(sentiment_score) as avg_7d
                    FROM news_sentiment
                    WHERE ticker = :t
                      AND published_at BETWEEN NOW() - INTERVAL '7 days' AND NOW() - INTERVAL '48 hours'
                """),
                {"t": self.ticker},
            )
            avg_rec = avg_row.fetchone()
            if avg_rec and avg_rec.avg_7d is not None:
                avg_7d = float(avg_rec.avg_7d)
        except Exception as e:
            logger.warning("NewsAgent %s: 7d avg fetch failed: %s", self.ticker, e)

        score = 50  # baseline
        thesis = []
        breaking_event = None

        # ── Event type scoring ────────────────────────────────────────────────
        event_contribution = 0
        seen_event_types = []

        for article in recent_articles:
            etype = article.event_type
            if not etype:
                continue

            seen_event_types.append(etype)

            if etype in EVENT_SCORES:
                event_contribution += EVENT_SCORES[etype]

        # Cap event contribution at ±30
        event_contribution = max(-30, min(30, event_contribution))
        score += event_contribution

        if event_contribution > 0:
            thesis.append(f"Positive event signals in last 48h (net event score: +{event_contribution}).")
        elif event_contribution < 0:
            thesis.append(f"Negative event signals in last 48h (net event score: {event_contribution}).")

        # ── Sentiment velocity ────────────────────────────────────────────────
        recent_sentiments = [
            float(a.sentiment_score)
            for a in recent_articles
            if a.sentiment_score is not None
        ]
        if recent_sentiments and avg_7d is not None:
            recent_avg = sum(recent_sentiments) / len(recent_sentiments)
            velocity = recent_avg - avg_7d

            if velocity >= 0.15:
                score += 10
                thesis.append(
                    f"Sentiment accelerating: 48h avg {recent_avg:+.2f} vs 7d avg {avg_7d:+.2f} "
                    f"(+{velocity:.2f} velocity)."
                )
            elif velocity <= -0.15:
                score -= 10
                thesis.append(
                    f"Sentiment deteriorating: 48h avg {recent_avg:+.2f} vs 7d avg {avg_7d:+.2f} "
                    f"({velocity:.2f} velocity)."
                )

        # ── Coverage volume ───────────────────────────────────────────────────
        article_count = len(recent_articles)
        if article_count >= 10:
            score += 5
            thesis.append(f"High coverage: {article_count} articles in last 48h — elevated attention.")
        else:
            thesis.append(f"{article_count} article(s) in last 48h.")

        # ── Breaking event: highest-impact event_type from last 48h ──────────
        if seen_event_types:
            best_rank = -1
            for etype in seen_event_types:
                rank = EVENT_IMPACT_RANK.index(etype) if etype in EVENT_IMPACT_RANK else -1
                if rank > best_rank:
                    best_rank = rank
                    breaking_event = etype

        # Cap score to 0–100
        score = max(0, min(100, score))

        logger.info(
            "NewsAgent %s: score=%d articles=%d breaking_event=%s",
            self.ticker, score, article_count, breaking_event,
        )

        return {
            "score": score,
            "thesis": thesis,
            "breaking_event": breaking_event,
        }
