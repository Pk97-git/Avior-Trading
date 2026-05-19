"""
agents/sentiment.py
===================
SentimentAgent — aggregates news_sentiment for a ticker over 30 days
and converts it into a 0–100 score.

Formula:
  base    = 50
  avg_adj = avg(sentiment_score) * 30     # sentiment_score is −1 to +1
  trend   = (last7_avg − prior23_avg) * 10
  score   = clamp(base + avg_adj + trend, 0, 100)

If no sentiment data exists → returns neutral score 50.
"""
import logging
from datetime import datetime, timedelta, timezone
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import text

logger = logging.getLogger(__name__)


class SentimentAgent:
    def __init__(self, db: AsyncSession, ticker: str):
        self.db = db
        self.ticker = ticker

    async def _fetch_scores(self, days: int = 30) -> list[dict]:
        since = datetime.now(timezone.utc) - timedelta(days=days)
        query = text("""
            SELECT time, sentiment_score
            FROM news_sentiment
            WHERE ticker = :ticker
              AND time >= :since
              AND sentiment_score IS NOT NULL
            ORDER BY time ASC
        """)
        result = await self.db.execute(query, {"ticker": self.ticker, "since": since})
        return [{"time": r.time, "score": r.sentiment_score} for r in result.fetchall()]

    async def analyze(self) -> dict:
        """
        Returns:
            {"score": int, "thesis": list[str]}
        """
        try:
            rows = await self._fetch_scores(days=30)
        except Exception as e:
            logger.warning("SentimentAgent %s: fetch failed: %s", self.ticker, e)
            return {"score": 50, "thesis": ["Sentiment data unavailable. Using neutral score."]}

        if not rows:
            return {
                "score": 50,
                "thesis": ["No news sentiment data for this ticker in the last 30 days."],
            }

        scores = [r["score"] for r in rows]
        avg_score = sum(scores) / len(scores)

        # Positive / negative breakdown
        pos = sum(1 for s in scores if s > 0.1)
        neg = sum(1 for s in scores if s < -0.1)
        total = len(scores)
        pos_pct = pos / total * 100
        neg_pct = neg / total * 100

        # 7-day trend vs prior 23 days
        cutoff = datetime.now(timezone.utc) - timedelta(days=7)
        recent = [r["score"] for r in rows if r["time"] >= cutoff]
        older  = [r["score"] for r in rows if r["time"] < cutoff]
        recent_avg = sum(recent) / len(recent) if recent else avg_score
        older_avg  = sum(older)  / len(older)  if older  else avg_score
        trend_delta = recent_avg - older_avg

        # Score formula
        base_score = 50
        avg_adj    = avg_score * 30
        trend_adj  = trend_delta * 10
        score = int(max(0, min(100, base_score + avg_adj + trend_adj)))

        # Thesis
        thesis = []
        if avg_score > 0.2:
            thesis.append(f"Predominantly positive sentiment ({pos_pct:.0f}% positive headlines over 30d).")
        elif avg_score < -0.2:
            thesis.append(f"Predominantly negative sentiment ({neg_pct:.0f}% negative headlines over 30d).")
        else:
            thesis.append(f"Mixed sentiment (pos {pos_pct:.0f}% / neg {neg_pct:.0f}%).")

        if trend_delta > 0.1:
            thesis.append(f"Sentiment improving over last 7 days (+{trend_delta:.2f} shift).")
        elif trend_delta < -0.1:
            thesis.append(f"Sentiment deteriorating over last 7 days ({trend_delta:.2f} shift).")

        thesis.append(f"Based on {total} headlines. Avg sentiment: {avg_score:.2f}.")

        logger.info("SentimentAgent %s: score=%d avg=%.2f trend=%.2f",
                    self.ticker, score, avg_score, trend_delta)
        return {"score": score, "thesis": thesis}
