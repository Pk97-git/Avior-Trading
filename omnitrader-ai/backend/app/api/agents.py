"""
api/agents.py
=============
Agent endpoints — trigger analysis and retrieve per-ticker results.

GET  /agents/analysis/{ticker}  — latest stored analysis for a ticker
POST /agents/analyze/{ticker}   — run fresh analysis right now
"""
import logging
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from app.db.session import get_db
from app.models.market_data import AIAnalysis
from app.agents.runner import run_all_agents

router = APIRouter()
logger = logging.getLogger(__name__)


def _serialise(a: AIAnalysis) -> dict:
    return {
        "ticker":               a.ticker,
        "analysis_date":        a.analysis_date,
        # Individual agent scores
        "fundamental_score":    a.fundamental_score,
        "technical_score":      a.technical_score,
        "macro_score":          a.macro_score,
        "institutional_score":  a.institutional_score,
        "sentiment_score":      a.sentiment_score,
        "memory_confidence":    a.memory_confidence,
        # Executive Trader output
        "final_score":          a.final_score,
        "signal":               a.signal,
        "regime":               a.regime,
        # Per-agent theses
        "fundamental_thesis":   a.fundamental_thesis,
        "technical_thesis":     a.technical_thesis,
        "macro_thesis":         a.macro_thesis,
        "institutional_thesis": a.institutional_thesis,
        "sentiment_thesis":     a.sentiment_thesis,
        "memory_thesis":        a.memory_thesis,
        "vision_score":         a.vision_score,
        "vision_thesis":        a.vision_thesis,
        "signal_thesis":        a.signal_thesis,
    }


@router.get("/analysis/{ticker}")
async def get_analysis(ticker: str, db: AsyncSession = Depends(get_db)):
    """Fetch the latest stored AI analysis for a ticker. Triggers a fresh run if none exists."""
    ticker = ticker.upper()

    stmt = (
        select(AIAnalysis)
        .where(AIAnalysis.ticker == ticker)
        .order_by(AIAnalysis.analysis_date.desc())
        .limit(1)
    )
    result = await db.execute(stmt)
    analysis = result.scalars().first()

    if not analysis:
        logger.info("No stored analysis for %s — running agents now.", ticker)
        return await trigger_analysis(ticker, db)

    return _serialise(analysis)


@router.post("/analyze/{ticker}")
async def trigger_analysis(ticker: str, db: AsyncSession = Depends(get_db)):
    """Force a fresh analysis for the given ticker. Stores result and fires alerts."""
    ticker = ticker.upper()
    logger.info("Triggering full agent run for %s", ticker)

    try:
        result = await run_all_agents(db, ticker)
        return {"status": "success", **result}
    except Exception as e:
        logger.error("Agent run failed for %s: %s", ticker, e)
        raise HTTPException(status_code=500, detail=str(e))
