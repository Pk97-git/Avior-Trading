"""
services/llm_service.py
=======================
Centralized LLM service — single shared AsyncAnthropic client with:

  • Prompt caching (cache_control: ephemeral) on system prompts and tools
  • Model routing: Haiku → fast/cheap, Sonnet → balanced, Opus → deep reasoning
  • Token usage tracking with cost estimation
  • Retry logic (3 attempts, exponential backoff) on rate-limit errors
  • Three task-oriented methods: explain(), summarize(), reason()

Model routing
-------------
  HAIKU  (claude-haiku-4-5-20251001) — quick summaries, simple Q&A, extraction
  SONNET (claude-sonnet-4-6)         — analysis, research, copilot, tool use
  OPUS   (claude-opus-4-7)           — deep reasoning, complex strategy decisions

Cost rates (per million tokens, May 2025)
-----------------------------------------
  Haiku  input  $0.80  output $4.00  cache_write $0.10  cache_read $0.08
  Sonnet input  $3.00  output $15.00 cache_write $3.75  cache_read $0.30
  Opus   input  $15.00 output $75.00 cache_write $18.75 cache_read $1.50
"""
from __future__ import annotations

import asyncio
import logging
import os
import time
from dataclasses import dataclass, field
from typing import Optional

from anthropic import AsyncAnthropic, APIStatusError

logger = logging.getLogger(__name__)

_MODEL_COSTS: dict[str, dict[str, float]] = {
    "claude-haiku-4-5-20251001": {
        "input":        0.80,
        "output":       4.00,
        "cache_write":  0.10,
        "cache_read":   0.08,
    },
    "claude-sonnet-4-6": {
        "input":        3.00,
        "output":       15.00,
        "cache_write":  3.75,
        "cache_read":   0.30,
    },
    "claude-opus-4-7": {
        "input":        15.00,
        "output":       75.00,
        "cache_write":  18.75,
        "cache_read":   1.50,
    },
}

MODEL_HAIKU  = "claude-haiku-4-5-20251001"
MODEL_SONNET = "claude-sonnet-4-6"
MODEL_OPUS   = "claude-opus-4-7"


@dataclass
class _UsageStats:
    total_requests:       int   = 0
    total_input_tokens:   int   = 0
    total_output_tokens:  int   = 0
    total_cache_write:    int   = 0
    total_cache_read:     int   = 0
    total_cost_usd:       float = 0.0
    requests_by_model:    dict  = field(default_factory=dict)
    cost_by_model:        dict  = field(default_factory=dict)
    errors:               int   = 0


class LLMService:
    """
    Singleton LLM service. Use the module-level `llm` instance.

    Usage:
        from app.services.llm_service import llm
        result = await llm.summarize(text="...", style="bullet")
        result = await llm.explain(ticker="RELIANCE.NS", context={...})
        result = await llm.reason(question="...", data={...})
    """

    def __init__(self) -> None:
        self._client: Optional[AsyncAnthropic] = None
        self._stats = _UsageStats()
        self._lock = asyncio.Lock()

    @property
    def client(self) -> AsyncAnthropic:
        if self._client is None:
            api_key = os.getenv("ANTHROPIC_API_KEY")
            if not api_key:
                raise EnvironmentError("ANTHROPIC_API_KEY not set")
            self._client = AsyncAnthropic(api_key=api_key)
        return self._client

    def _make_cached_system(self, text: str) -> list[dict]:
        return [{"type": "text", "text": text, "cache_control": {"type": "ephemeral"}}]

    def _compute_cost(self, model: str, usage) -> float:
        rates = _MODEL_COSTS.get(model, _MODEL_COSTS[MODEL_SONNET])
        input_tokens  = getattr(usage, "input_tokens", 0)
        output_tokens = getattr(usage, "output_tokens", 0)
        cache_write   = getattr(usage, "cache_creation_input_tokens", 0)
        cache_read    = getattr(usage, "cache_read_input_tokens", 0)
        cost = (
            input_tokens  * rates["input"]       / 1_000_000 +
            output_tokens * rates["output"]      / 1_000_000 +
            cache_write   * rates["cache_write"] / 1_000_000 +
            cache_read    * rates["cache_read"]  / 1_000_000
        )
        return cost

    def _record_usage(self, model: str, usage, cost: float) -> None:
        self._stats.total_requests += 1
        self._stats.total_input_tokens  += getattr(usage, "input_tokens", 0)
        self._stats.total_output_tokens += getattr(usage, "output_tokens", 0)
        self._stats.total_cache_write   += getattr(usage, "cache_creation_input_tokens", 0)
        self._stats.total_cache_read    += getattr(usage, "cache_read_input_tokens", 0)
        self._stats.total_cost_usd      += cost
        self._stats.requests_by_model[model] = self._stats.requests_by_model.get(model, 0) + 1
        self._stats.cost_by_model[model]     = round(self._stats.cost_by_model.get(model, 0.0) + cost, 6)

    async def _call(self, model: str, system_text: str, user_content: str,
                    max_tokens: int = 1024, tools=None, tool_choice=None) -> tuple[str, object]:
        system = self._make_cached_system(system_text)
        messages = [{"role": "user", "content": user_content}]

        kwargs = dict(
            model=model,
            max_tokens=max_tokens,
            system=system,
            messages=messages,
        )
        if tools:
            kwargs["tools"] = tools
        if tool_choice:
            kwargs["tool_choice"] = tool_choice

        last_exc = None
        for attempt in range(3):
            try:
                resp = await self.client.messages.create(**kwargs)
                text = ""
                for block in resp.content:
                    if hasattr(block, "text"):
                        text += block.text
                cost = self._compute_cost(model, resp.usage)
                self._record_usage(model, resp.usage, cost)
                return text, resp.usage
            except APIStatusError as exc:
                if exc.status_code == 429:  # rate limit
                    wait = 2 ** attempt * 2
                    logger.warning("[LLMService] Rate limit hit, retrying in %ds (attempt %d/3)", wait, attempt + 1)
                    await asyncio.sleep(wait)
                    last_exc = exc
                else:
                    self._stats.errors += 1
                    raise
            except Exception as exc:
                self._stats.errors += 1
                raise

        self._stats.errors += 1
        raise last_exc

    async def explain(self, ticker: str, context: dict, question: str = "") -> dict:
        """
        Explain a stock signal, trade setup, or market situation in plain English.

        Args:
            ticker:   stock ticker
            context:  dict with keys like signal, score, rsi, macd, pe_ratio, etc.
            question: optional specific question (default: explain the signal)

        Returns:
            {explanation: str, key_factors: list[str], risk_note: str, model: str, cost_usd: float}
        """
        system = """You are OmniTrader AI — a concise financial analyst.
Explain trading signals and market situations in plain English.
Be specific, data-driven, and actionable. No disclaimers.
Format: 2-3 sentences explanation, then a brief risk note."""

        # Build context string
        ctx_lines = []
        for k, v in context.items():
            ctx_lines.append(f"  {k}: {v}")
        ctx_str = "\n".join(ctx_lines)

        q = question or f"Why does {ticker} have this signal? What does it mean for a trader?"

        prompt = f"""Stock: {ticker}
Current context:
{ctx_str}

Question: {q}

Respond with:
EXPLANATION: <2-3 sentences explaining the signal/situation in plain English>
KEY FACTORS: <3 bullet points — most important factors driving this>
RISK NOTE: <1 sentence on the main risk>"""

        text, usage = await self._call(MODEL_SONNET, system, prompt, max_tokens=512)
        cost = self._compute_cost(MODEL_SONNET, usage)

        # Parse structured response
        lines = text.strip().split("\n")
        explanation = ""
        key_factors = []
        risk_note = ""

        section = None
        for line in lines:
            line = line.strip()
            if line.startswith("EXPLANATION:"):
                explanation = line[12:].strip()
                section = "explanation"
            elif line.startswith("KEY FACTORS:"):
                section = "factors"
            elif line.startswith("RISK NOTE:"):
                risk_note = line[10:].strip()
                section = None
            elif section == "explanation" and line:
                explanation += " " + line
            elif section == "factors" and line.lstrip("-• "):
                key_factors.append(line.lstrip("-• ").strip())

        return {
            "ticker":      ticker,
            "explanation": explanation or text,
            "key_factors": key_factors[:3],
            "risk_note":   risk_note,
            "model":       MODEL_SONNET,
            "cost_usd":    round(cost, 6),
        }

    async def summarize(self, text: str, style: str = "paragraph",
                        max_length: int = 200, context: str = "") -> dict:
        """
        Summarize news, earnings calls, research reports, or any text.

        Args:
            text:       content to summarize
            style:      'paragraph' | 'bullet' | 'headline' | 'tweet'
            max_length: approximate word count for output
            context:    optional context (e.g. 'Q3 2024 earnings call for INFY')

        Returns:
            {summary: str, sentiment: str, key_points: list[str], model: str, cost_usd: float}
        """
        system = """You are a financial news analyst. Summarize content concisely and accurately.
Focus on: price impacts, earnings beats/misses, guidance changes, strategic announcements.
Extract market-moving information. Be specific with numbers."""

        style_instructions = {
            "paragraph": f"Write a {max_length}-word paragraph summary.",
            "bullet": f"Write {min(5, max_length//40)} bullet points covering key facts.",
            "headline": "Write a single punchy headline (max 15 words).",
            "tweet": "Write a tweet-length summary (max 280 chars) with key data point.",
        }

        instruction = style_instructions.get(style, style_instructions["paragraph"])
        ctx_line = f"\nContext: {context}" if context else ""

        # Truncate very long text to avoid huge token bills
        truncated = text[:6000] if len(text) > 6000 else text

        prompt = f"""{ctx_line}
Content to summarize:
---
{truncated}
---

{instruction}

Then on a new line, add:
SENTIMENT: <POSITIVE|NEGATIVE|NEUTRAL|MIXED>
KEY POINTS: <3 short bullet points of most important facts>"""

        text_out, usage = await self._call(MODEL_HAIKU, system, prompt, max_tokens=400)
        cost = self._compute_cost(MODEL_HAIKU, usage)

        # Parse
        lines = text_out.strip().split("\n")
        summary_lines = []
        sentiment = "NEUTRAL"
        key_points = []
        section = "summary"

        for line in lines:
            line = line.strip()
            if line.startswith("SENTIMENT:"):
                sentiment = line[10:].strip().upper()
                section = None
            elif line.startswith("KEY POINTS:"):
                section = "points"
            elif section == "summary" and line:
                summary_lines.append(line)
            elif section == "points" and line.lstrip("-• "):
                key_points.append(line.lstrip("-• ").strip())

        summary = " ".join(summary_lines).strip() or text_out

        return {
            "summary":    summary,
            "sentiment":  sentiment,
            "key_points": key_points[:3],
            "style":      style,
            "model":      MODEL_HAIKU,
            "cost_usd":   round(cost, 6),
        }

    async def reason(self, question: str, data: dict, depth: str = "standard") -> dict:
        """
        Chain-of-thought reasoning for complex financial decisions.

        Args:
            question: the decision or analysis question
            data:     relevant data (prices, signals, portfolio, macro, etc.)
            depth:    'quick' (Haiku) | 'standard' (Sonnet) | 'deep' (Opus)

        Returns:
            {reasoning: str, conclusion: str, confidence: int, action: str, model: str, cost_usd: float}
        """
        model_map = {"quick": MODEL_HAIKU, "standard": MODEL_SONNET, "deep": MODEL_OPUS}
        model = model_map.get(depth, MODEL_SONNET)

        system = """You are a professional quantitative analyst and portfolio manager.
Reason step-by-step through financial decisions.
Be rigorous, consider multiple scenarios, quantify uncertainty.
Always give a clear conclusion with a confidence level (0-100)."""

        data_str = "\n".join(f"  {k}: {v}" for k, v in data.items())

        prompt = f"""Question: {question}

Available data:
{data_str}

Think step by step:
1. What are the key factors relevant to this question?
2. What does each data point suggest?
3. What are the risks and uncertainties?
4. What is the most likely scenario?
5. What should be done?

Format your response as:
REASONING: <step-by-step analysis>
CONCLUSION: <clear one-sentence conclusion>
CONFIDENCE: <0-100 confidence in this conclusion>
ACTION: <specific actionable recommendation>"""

        text_out, usage = await self._call(model, system, prompt, max_tokens=1024)
        cost = self._compute_cost(model, usage)

        # Parse
        reasoning = ""
        conclusion = ""
        confidence = 50
        action = ""

        lines = text_out.strip().split("\n")
        section = None
        reasoning_lines = []

        for line in lines:
            line_stripped = line.strip()
            if line_stripped.startswith("REASONING:"):
                section = "reasoning"
                reasoning_lines.append(line_stripped[10:].strip())
            elif line_stripped.startswith("CONCLUSION:"):
                section = None
                conclusion = line_stripped[11:].strip()
            elif line_stripped.startswith("CONFIDENCE:"):
                section = None
                try:
                    confidence = int("".join(c for c in line_stripped[11:] if c.isdigit())[:3])
                    confidence = max(0, min(100, confidence))
                except:
                    confidence = 50
            elif line_stripped.startswith("ACTION:"):
                section = None
                action = line_stripped[7:].strip()
            elif section == "reasoning" and line_stripped:
                reasoning_lines.append(line_stripped)

        return {
            "question":   question,
            "reasoning":  "\n".join(reasoning_lines) or text_out,
            "conclusion": conclusion,
            "confidence": confidence,
            "action":     action,
            "depth":      depth,
            "model":      model,
            "cost_usd":   round(cost, 6),
        }

    def get_usage_stats(self) -> dict:
        s = self._stats
        return {
            "total_requests":        s.total_requests,
            "total_input_tokens":    s.total_input_tokens,
            "total_output_tokens":   s.total_output_tokens,
            "cache_write_tokens":    s.total_cache_write,
            "cache_read_tokens":     s.total_cache_read,
            "total_cost_usd":        round(s.total_cost_usd, 4),
            "requests_by_model":     s.requests_by_model,
            "cost_by_model":         s.cost_by_model,
            "errors":                s.errors,
            "cache_hit_rate_pct":    round(
                s.total_cache_read / max(s.total_input_tokens, 1) * 100, 2
            ),
        }


# ── Module-level singleton ─────────────────────────────────────────────────────
llm = LLMService()
