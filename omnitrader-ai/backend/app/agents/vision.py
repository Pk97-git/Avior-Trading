from typing import Optional, List, Dict, Tuple
"""
agents/vision.py
================
VisionAgent — analyses mplfinance chart images using Claude's vision API
to identify chart patterns, trend direction, support/resistance levels,
and volume signals.

Returns:
    {
        "score":   int (0–100),
        "thesis":  list[str],
        "pattern": str,          # short label, e.g. "Ascending Triangle"
    }

Fallback behaviour:
  • If no ChartSnapshot exists for the ticker → score 50, neutral thesis.
  • If the image file is missing or unreadable → same fallback.
  • If the Anthropic API call fails → same fallback.

Required env var:
  ANTHROPIC_API_KEY — set in .env alongside DATABASE_URL etc.
"""
import base64
import logging
import os
from pathlib import Path

from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import text

logger = logging.getLogger(__name__)

# Lazy import to avoid crashing at startup if anthropic is not yet installed
try:
    import anthropic as _anthropic_module
    _ANTHROPIC_AVAILABLE = True
except ImportError:
    _ANTHROPIC_AVAILABLE = False
    logger.warning("VisionAgent: 'anthropic' package not installed. Run: pip install anthropic>=0.34.0")


_VISION_PROMPT = """You are an expert technical analyst reviewing a stock price chart.

Analyse the chart image and provide:
1. The primary chart pattern (e.g. Ascending Triangle, Head & Shoulders, Cup and Handle, Flag, Range-bound, etc.)
2. The current trend direction (Uptrend / Downtrend / Sideways)
3. Key support and resistance levels visible
4. Volume signal (Accumulation / Distribution / Neutral)
5. An overall bullish/bearish score from 0 to 100 where:
   - 0–30 = strongly bearish
   - 31–45 = mildly bearish
   - 46–54 = neutral
   - 55–70 = mildly bullish
   - 71–100 = strongly bullish

Respond in this exact JSON format (no markdown, no explanation outside JSON):
{
  "pattern": "<pattern name>",
  "trend": "<Uptrend|Downtrend|Sideways>",
  "support": "<price level or description>",
  "resistance": "<price level or description>",
  "volume_signal": "<Accumulation|Distribution|Neutral>",
  "score": <integer 0-100>,
  "thesis": [
    "<key observation 1>",
    "<key observation 2>",
    "<key observation 3>"
  ]
}"""


class VisionAgent:
    """
    Analyses chart images for a single ticker using Claude's vision capability.
    """

    MODEL = "claude-sonnet-4-6"

    def __init__(self, db: AsyncSession, ticker: str):
        self.db     = db
        self.ticker = ticker.upper()

    async def analyze(self) -> dict:
        """
        Fetch the latest chart snapshot, call Claude vision, return scored result.
        Gracefully falls back to neutral if anything fails.
        """
        if not _ANTHROPIC_AVAILABLE:
            return self._fallback("anthropic package not installed")

        api_key = os.getenv("ANTHROPIC_API_KEY")
        if not api_key:
            return self._fallback("ANTHROPIC_API_KEY not set")

        # ── Fetch latest chart snapshot path ─────────────────────────────────
        try:
            row = await self._latest_chart_path()
        except Exception as e:
            logger.warning("VisionAgent: DB error for %s: %s", self.ticker, e)
            return self._fallback("DB error fetching chart snapshot")

        if not row:
            return self._fallback("No chart snapshot available")

        image_path = row["image_path"]
        if not image_path or not Path(image_path).exists():
            return self._fallback(f"Chart image not found: {image_path}")

        # ── Encode image ──────────────────────────────────────────────────────
        try:
            with open(image_path, "rb") as f:
                image_data = base64.standard_b64encode(f.read()).decode("utf-8")
            media_type = "image/png" if image_path.endswith(".png") else "image/jpeg"
        except Exception as e:
            logger.warning("VisionAgent: Failed to read image %s: %s", image_path, e)
            return self._fallback("Failed to read chart image")

        # ── Call Claude vision ────────────────────────────────────────────────
        try:
            client = _anthropic_module.Anthropic(api_key=api_key)
            message = client.messages.create(
                model=self.MODEL,
                max_tokens=512,
                messages=[
                    {
                        "role": "user",
                        "content": [
                            {
                                "type":       "image",
                                "source": {
                                    "type":       "base64",
                                    "media_type": media_type,
                                    "data":       image_data,
                                },
                            },
                            {
                                "type": "text",
                                "text": _VISION_PROMPT,
                            },
                        ],
                    }
                ],
            )

            raw = message.content[0].text.strip()
            return self._parse_response(raw)

        except Exception as e:
            logger.error("VisionAgent: Claude API call failed for %s: %s", self.ticker, e)
            return self._fallback(f"Vision API error: {type(e).__name__}")

    # ── Helpers ───────────────────────────────────────────────────────────────

    async def _latest_chart_path(self) -> Optional[dict]:
        """Fetch the most recent chart snapshot row for this ticker."""
        query = text("""
            SELECT image_path
            FROM chart_snapshots
            WHERE ticker = :ticker
              AND image_path IS NOT NULL
            ORDER BY generated_at DESC
            LIMIT 1
        """)
        result = await self.db.execute(query, {"ticker": self.ticker})
        row = result.fetchone()
        return {"image_path": row.image_path} if row else None

    def _parse_response(self, raw: str) -> dict:
        """Parse JSON response from Claude. Falls back to neutral on parse error."""
        import json
        try:
            # Strip markdown code fences if present
            if raw.startswith("```"):
                raw = raw.split("\n", 1)[1].rsplit("```", 1)[0].strip()
            parsed = json.loads(raw)
            score   = int(parsed.get("score",  50))
            score   = max(0, min(100, score))
            pattern = parsed.get("pattern",      "Unknown")
            trend   = parsed.get("trend",         "Sideways")
            vol_sig = parsed.get("volume_signal", "Neutral")
            thesis  = parsed.get("thesis",        [])

            # Prepend pattern + trend line if thesis is short
            if len(thesis) < 3:
                thesis = [
                    f"Pattern: {pattern} ({trend} trend)",
                    f"Volume signal: {vol_sig}",
                ] + thesis

            return {
                "score":   score,
                "pattern": pattern,
                "thesis":  thesis[:5],
            }
        except Exception as e:
            logger.warning("VisionAgent: Failed to parse Claude response: %s | raw=%s", e, raw[:200])
            return self._fallback("Failed to parse vision response")

    @staticmethod
    def _fallback(reason: str) -> dict:
        return {
            "score":   50,
            "pattern": "Unknown",
            "thesis":  [f"Vision analysis unavailable: {reason}"],
        }
