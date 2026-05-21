"""
api/ai.py
=========
AI inference endpoints — explain, summarize, reason.

POST /ai/explain    — explain a signal or market situation in plain English
POST /ai/summarize  — summarize news, earnings, or report text
POST /ai/reason     — chain-of-thought reasoning for complex decisions
GET  /ai/usage      — token usage and cost tracking stats
"""
import logging
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import get_db
from app.services.llm_service import llm

router = APIRouter()
logger = logging.getLogger(__name__)


class ExplainRequest(BaseModel):
    ticker:   str         = Field(..., description="Stock ticker, e.g. RELIANCE.NS or AAPL")
    question: str         = Field("", description="Specific question (optional — defaults to explaining the signal)")
    context:  dict        = Field(default_factory=dict, description="Any relevant data: signal, score, rsi, pe, etc.")


class SummarizeRequest(BaseModel):
    text:       str  = Field(..., min_length=10, description="Text to summarize")
    style:      str  = Field("paragraph", description="paragraph | bullet | headline | tweet")
    max_length: int  = Field(200, ge=50, le=500, description="Target word count")
    context:    str  = Field("", description="Optional context (e.g. 'Q3 2024 earnings call for INFY')")


class ReasonRequest(BaseModel):
    question: str  = Field(..., description="The decision or analysis question")
    data:     dict = Field(default_factory=dict, description="Relevant data for reasoning")
    depth:    str  = Field("standard", description="quick | standard | deep")


@router.post("/explain")
async def explain_signal(
    req: ExplainRequest,
    db: AsyncSession = Depends(get_db),
):
    """
    Explain a stock signal or market situation in plain English.

    If context is not provided, auto-fetches the latest AI analysis from DB.
    Returns a plain-English explanation, 3 key factors, and a risk note.

    Example:
        {"ticker": "RELIANCE.NS", "question": "Why is this a buy?"}
    """
    context = dict(req.context)

    # Auto-fetch context from DB if not provided
    if not context:
        try:
            result = await db.execute(text("""
                SELECT signal, final_score, entry_price, stop_loss, take_profit,
                       atr_14, regime, analysis_date::date as signal_date
                FROM ai_analysis
                WHERE ticker = :ticker
                ORDER BY analysis_date DESC LIMIT 1
            """), {"ticker": req.ticker.upper()})
            row = result.fetchone()
            if row:
                context = {
                    "signal":      row.signal,
                    "ai_score":    row.final_score,
                    "entry_price": row.entry_price,
                    "stop_loss":   row.stop_loss,
                    "take_profit": row.take_profit,
                    "regime":      row.regime,
                    "signal_date": str(row.signal_date) if row.signal_date else None,
                }
        except Exception as e:
            logger.warning("[AI] Failed to auto-fetch context for %s: %s", req.ticker, e)

    if not context:
        context = {"note": "No analysis data available yet"}

    try:
        result = await llm.explain(
            ticker=req.ticker.upper(),
            context=context,
            question=req.question,
        )
        return result
    except EnvironmentError as exc:
        raise HTTPException(status_code=503, detail=f"LLM service not available: {exc}")
    except Exception as exc:
        logger.exception("[AI] explain failed: %s", exc)
        raise HTTPException(status_code=500, detail=str(exc))


@router.post("/summarize")
async def summarize_text(req: SummarizeRequest):
    """
    Summarize financial text: news articles, earnings call excerpts, research reports.

    Styles:
    - paragraph: flowing 200-word summary
    - bullet: 5 key bullet points
    - headline: single punchy headline
    - tweet: 280-char tweet

    Uses Claude Haiku for speed and cost efficiency.
    """
    valid_styles = {"paragraph", "bullet", "headline", "tweet"}
    if req.style not in valid_styles:
        raise HTTPException(422, f"style must be one of: {sorted(valid_styles)}")

    try:
        result = await llm.summarize(
            text=req.text,
            style=req.style,
            max_length=req.max_length,
            context=req.context,
        )
        return result
    except EnvironmentError as exc:
        raise HTTPException(status_code=503, detail=f"LLM service not available: {exc}")
    except Exception as exc:
        logger.exception("[AI] summarize failed: %s", exc)
        raise HTTPException(status_code=500, detail=str(exc))


@router.post("/reason")
async def reason_through(req: ReasonRequest):
    """
    Chain-of-thought reasoning for complex financial decisions.

    Depth:
    - quick: Haiku — fast, rough reasoning (~$0.001)
    - standard: Sonnet — balanced analysis (~$0.01)
    - deep: Opus — thorough multi-scenario analysis (~$0.05)

    Examples:
      {"question": "Should I rebalance my portfolio given current market conditions?",
       "data": {"portfolio_drift": "15%", "regime": "Risk-Off", "cash": "20%"}}

      {"question": "Is TATAMOTORS a good long-term hold at current valuations?",
       "data": {"pe": 12, "debt_equity": 1.2, "ev_growth": "18%", "sector_trend": "EV tailwind"},
       "depth": "deep"}
    """
    valid_depths = {"quick", "standard", "deep"}
    if req.depth not in valid_depths:
        raise HTTPException(422, f"depth must be one of: {sorted(valid_depths)}")

    try:
        result = await llm.reason(
            question=req.question,
            data=req.data,
            depth=req.depth,
        )
        return result
    except EnvironmentError as exc:
        raise HTTPException(status_code=503, detail=f"LLM service not available: {exc}")
    except Exception as exc:
        logger.exception("[AI] reason failed: %s", exc)
        raise HTTPException(status_code=500, detail=str(exc))


@router.get("/usage")
async def get_usage():
    """
    Token usage and cost tracking for all LLM API calls this session.
    Resets when the server restarts (in-memory only).
    """
    stats = llm.get_usage_stats()
    # Add human-readable cost breakdown
    stats["estimated_monthly_usd"] = round(stats["total_cost_usd"] * 720, 2)  # if this rate holds for a month
    return stats
