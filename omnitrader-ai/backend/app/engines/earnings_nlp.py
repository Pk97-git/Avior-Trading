"""
engines/earnings_nlp.py
========================
Earnings call tone analysis using LLM.

Since full transcript APIs are expensive (Seeking Alpha, Refinitiv),
we use:
  1. Recent news headlines around earnings date (from news_sentiment DB table)
  2. yfinance earnings calendar for context
  3. Groq LLM to synthesise a tone assessment

Tone signals detected:
  - BULLISH_TONE:   Management guidance raised, strong language, confident
  - CAUTIOUS_TONE:  Hedged language, macro concerns, cautious guidance
  - BEARISH_TONE:   Guidance cut, weak demand, cost pressures flagged
  - NEUTRAL_TONE:   In-line results, no major language shifts

Output:
  - tone: str
  - confidence: float (0-1)
  - key_phrases: list[str]  (quotes that drove the assessment)
  - guidance_direction: UP | FLAT | DOWN | UNKNOWN
  - surprise_sentiment: BEAT | MISS | IN_LINE | UNKNOWN
  - analyst_reaction: UPGRADED | DOWNGRADED | NEUTRAL | UNKNOWN
  - summary: str  (plain English)
  - risk_flags: list[str]
"""
import logging
import os
from typing import Optional

logger = logging.getLogger(__name__)

TONE_PROMPT = """You are a financial analyst specialising in earnings call tone analysis.
Analyse the following news headlines and summaries about a company's recent earnings.
Identify management tone, guidance direction, and analyst reaction.

Be specific. Quote actual phrases if present. Focus on:
- Management's language (confident vs cautious vs nervous)
- Guidance direction (raised/maintained/lowered)
- Analyst reactions (upgrades/downgrades)
- Key risks mentioned
- EPS/revenue beat or miss

Company: {ticker}
Sector: {sector}
Recent earnings-related news:
{news_text}

Respond in this exact format:
TONE: [BULLISH_TONE|CAUTIOUS_TONE|BEARISH_TONE|NEUTRAL_TONE]
CONFIDENCE: [0.0-1.0]
GUIDANCE: [UP|FLAT|DOWN|UNKNOWN]
SURPRISE: [BEAT|MISS|IN_LINE|UNKNOWN]
ANALYST_REACTION: [UPGRADED|DOWNGRADED|NEUTRAL|UNKNOWN]
KEY_PHRASES: [3-5 specific phrases from the news that drove your assessment, separated by |]
RISK_FLAGS: [1-3 specific risks mentioned, separated by | or NONE]
SUMMARY: [2-3 sentences plain English summary of the earnings tone and what it means for the stock]"""


async def analyse_earnings_tone(
    ticker: str,
    sector: str = "",
    news_items: list[dict] = None,
) -> dict:
    """
    Analyse earnings tone from news headlines using Groq LLM.

    news_items: list of {headline, summary, published_at, sentiment_score}
    """
    groq_key = os.getenv("GROQ_API_KEY")

    # Build news text for LLM
    if not news_items:
        news_text = "No recent earnings news available."
        has_data = False
    else:
        has_data = True
        news_lines = []
        for item in news_items[:15]:  # Cap at 15 headlines
            headline = item.get("headline", "")
            summary  = item.get("summary", "")
            pub_date = str(item.get("published_at", ""))[:10]
            sentiment = item.get("sentiment_score", 0)
            sentiment_label = "positive" if sentiment > 0.2 else "negative" if sentiment < -0.2 else "neutral"
            text = f"[{pub_date}] ({sentiment_label}) {headline}"
            if summary and len(summary) > 20:
                text += f"\n  → {summary[:200]}"
            news_lines.append(text)
        news_text = "\n".join(news_lines)

    if not groq_key or not has_data:
        # Fallback: use sentiment scores to estimate tone
        if news_items:
            scores = [item.get("sentiment_score", 0) for item in news_items if item.get("sentiment_score") is not None]
            avg_sentiment = sum(scores) / len(scores) if scores else 0
        else:
            avg_sentiment = 0

        if avg_sentiment > 0.3:
            tone = "BULLISH_TONE"
        elif avg_sentiment < -0.3:
            tone = "BEARISH_TONE"
        elif avg_sentiment < -0.1:
            tone = "CAUTIOUS_TONE"
        else:
            tone = "NEUTRAL_TONE"

        return {
            "ticker":            ticker,
            "tone":              tone,
            "confidence":        0.4,
            "guidance_direction": "UNKNOWN",
            "surprise_sentiment": "UNKNOWN",
            "analyst_reaction":   "UNKNOWN",
            "key_phrases":       [],
            "risk_flags":        [],
            "summary":           f"Tone estimated from {len(news_items or [])} news items. Groq API key not set for deep NLP analysis.",
            "news_count":        len(news_items or []),
            "llm_used":          False,
        }

    # Use Groq for proper NLP
    try:
        from groq import Groq
        client = Groq(api_key=groq_key)
        prompt = TONE_PROMPT.format(ticker=ticker, sector=sector, news_text=news_text)

        response = client.chat.completions.create(
            model="llama-3.3-70b-versatile",
            messages=[{"role": "user", "content": prompt}],
            max_tokens=600,
            temperature=0.2,
        )
        text = response.choices[0].message.content.strip()

        # Parse structured response
        parsed = _parse_tone_response(text)
        parsed["ticker"]     = ticker
        parsed["news_count"] = len(news_items)
        parsed["llm_used"]   = True
        return parsed

    except Exception as e:
        logger.warning("Earnings NLP Groq call failed for %s: %s", ticker, e)
        return {
            "ticker":            ticker,
            "tone":              "NEUTRAL_TONE",
            "confidence":        0.3,
            "guidance_direction": "UNKNOWN",
            "surprise_sentiment": "UNKNOWN",
            "analyst_reaction":   "UNKNOWN",
            "key_phrases":       [],
            "risk_flags":        [],
            "summary":           f"LLM analysis failed: {str(e)[:100]}",
            "news_count":        len(news_items or []),
            "llm_used":          False,
        }


def _parse_tone_response(text: str) -> dict:
    """Parse the structured LLM response."""
    result = {
        "tone": "NEUTRAL_TONE",
        "confidence": 0.5,
        "guidance_direction": "UNKNOWN",
        "surprise_sentiment": "UNKNOWN",
        "analyst_reaction": "UNKNOWN",
        "key_phrases": [],
        "risk_flags": [],
        "summary": "",
    }

    for line in text.split("\n"):
        line = line.strip()
        if line.startswith("TONE:"):
            val = line[5:].strip()
            if val in ("BULLISH_TONE", "CAUTIOUS_TONE", "BEARISH_TONE", "NEUTRAL_TONE"):
                result["tone"] = val
        elif line.startswith("CONFIDENCE:"):
            try:
                result["confidence"] = float(line[11:].strip())
            except ValueError:
                pass
        elif line.startswith("GUIDANCE:"):
            val = line[9:].strip()
            if val in ("UP", "FLAT", "DOWN", "UNKNOWN"):
                result["guidance_direction"] = val
        elif line.startswith("SURPRISE:"):
            val = line[9:].strip()
            if val in ("BEAT", "MISS", "IN_LINE", "UNKNOWN"):
                result["surprise_sentiment"] = val
        elif line.startswith("ANALYST_REACTION:"):
            val = line[17:].strip()
            if val in ("UPGRADED", "DOWNGRADED", "NEUTRAL", "UNKNOWN"):
                result["analyst_reaction"] = val
        elif line.startswith("KEY_PHRASES:"):
            phrases = line[12:].strip().split("|")
            result["key_phrases"] = [p.strip() for p in phrases if p.strip() and p.strip() != "NONE"][:5]
        elif line.startswith("RISK_FLAGS:"):
            flags = line[11:].strip().split("|")
            result["risk_flags"] = [f.strip() for f in flags if f.strip() and f.strip() != "NONE"][:3]
        elif line.startswith("SUMMARY:"):
            result["summary"] = line[8:].strip()

    return result
