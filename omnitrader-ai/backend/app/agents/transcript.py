"""
TranscriptAgent: reads from earnings_transcripts, scores management tone + guidance.
"""
import logging
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import text

logger = logging.getLogger("omnitrader.agent.transcript")


class TranscriptAgent:
    def __init__(self, db: AsyncSession, ticker: str):
        self.db = db
        self.ticker = ticker

    async def analyze(self) -> dict:
        """
        Returns {"score": int, "thesis": list[str], "summary": str|None}

        Score (0–100, baseline 50):
          - guidance RAISE  + POSITIVE tone  → +20
          - guidance RAISE  + NEUTRAL tone   → +12
          - guidance LOWER  + NEGATIVE tone  → -20
          - guidance LOWER  + NEUTRAL tone   → -12
          - sentiment_score >  0.3           → +8
          - sentiment_score < -0.3           → -8
          - MAINTAIN guidance                → ±0
        """
        result = await self.db.execute(
            text("""
                SELECT ai_summary,
                       sentiment_score,
                       management_tone,
                       guidance_change,
                       earnings_date,
                       fiscal_period
                FROM earnings_transcripts
                WHERE ticker = :t
                ORDER BY earnings_date DESC
                LIMIT 1
            """),
            {"t": self.ticker},
        )
        row = result.fetchone()

        if not row:
            return {
                "score": 50,
                "thesis": ["No earnings transcript data available."],
                "summary": None,
            }

        summary = row.ai_summary
        sentiment_score = row.sentiment_score or 0.0
        management_tone = (row.management_tone or "NEUTRAL").upper()
        guidance_direction = (row.guidance_change or "NA").upper()
        earnings_date = row.earnings_date
        fiscal_period = row.fiscal_period

        # ── Scoring logic ──────────────────────────────────────────────────────
        score = 50
        thesis: list[str] = []

        # Guidance + tone combinations
        if guidance_direction == "RAISE":
            if management_tone == "POSITIVE":
                score += 20
                thesis.append(
                    "Management raised guidance with a positive tone — strong bullish signal."
                )
            elif management_tone == "NEUTRAL":
                score += 12
                thesis.append(
                    "Management raised guidance with a neutral tone — moderately bullish."
                )
            else:
                # RAISE + NEGATIVE (rare but possible)
                score += 5
                thesis.append(
                    "Management raised guidance despite cautious language — mildly bullish."
                )
        elif guidance_direction == "LOWER":
            if management_tone == "NEGATIVE":
                score -= 20
                thesis.append(
                    "Management lowered guidance with a negative tone — strong bearish signal."
                )
            elif management_tone == "NEUTRAL":
                score -= 12
                thesis.append(
                    "Management lowered guidance with a neutral tone — moderately bearish."
                )
            else:
                # LOWER + POSITIVE (damage control)
                score -= 5
                thesis.append(
                    "Management lowered guidance despite positive spin — mildly bearish."
                )
        elif guidance_direction == "MAINTAIN":
            # No score adjustment for maintain
            thesis.append(
                f"Guidance maintained — management tone was {management_tone.lower()}."
            )
        else:
            # NA or unknown guidance
            if management_tone == "POSITIVE":
                thesis.append("Management tone was positive; no explicit guidance change.")
            elif management_tone == "NEGATIVE":
                thesis.append("Management tone was negative; no explicit guidance change.")
            else:
                thesis.append("No guidance change and neutral management tone.")

        # Sentiment score adjustment
        if sentiment_score > 0.3:
            score += 8
            thesis.append(
                f"Earnings release sentiment strongly positive (score: {sentiment_score:.2f})."
            )
        elif sentiment_score < -0.3:
            score -= 8
            thesis.append(
                f"Earnings release sentiment strongly negative (score: {sentiment_score:.2f})."
            )
        else:
            thesis.append(
                f"Earnings sentiment score neutral at {sentiment_score:.2f}."
            )

        # Add date context
        date_label = fiscal_period or (earnings_date.isoformat() if earnings_date else "unknown")
        thesis.append(f"Based on earnings transcript from {date_label}.")

        # Clamp score to [0, 100]
        score = max(0, min(100, score))

        logger.info(
            "TranscriptAgent %s: score=%d guidance=%s tone=%s sentiment=%.2f",
            self.ticker,
            score,
            guidance_direction,
            management_tone,
            sentiment_score,
        )

        return {
            "score": score,
            "thesis": thesis,
            "summary": summary,
        }
