"""
research.py — REST API for AI research queries
"""
import os
import logging

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import get_async_db
from app.services.research_query import ResearchQueryService

router = APIRouter(prefix="/api/v1/research", tags=["research"])
logger = logging.getLogger("omnitrader.api.research")


class ResearchRequest(BaseModel):
    query: str


class ResearchResponse(BaseModel):
    answer: str
    tools_used: list[str]
    ticker: str | None = None


@router.post("/ask", response_model=ResearchResponse)
async def ask_research_question(
    request: ResearchRequest,
    db: AsyncSession = Depends(get_async_db),
):
    """
    Submit a natural language research question about a stock or market condition.
    Claude uses tool-use to gather relevant data and synthesize a research report.

    - Returns 400 if query exceeds 500 characters.
    - Returns 503 if the Anthropic API key is not configured.
    """
    # Validate query length
    if len(request.query) > 500:
        raise HTTPException(
            status_code=400,
            detail=f"Query too long ({len(request.query)} chars). Maximum is 500 characters.",
        )

    # Check for API key
    if not os.environ.get("ANTHROPIC_API_KEY"):
        raise HTTPException(
            status_code=503,
            detail="Anthropic API key not configured. Set ANTHROPIC_API_KEY environment variable.",
        )

    try:
        service = ResearchQueryService(db=db)
        result = await service.ask(request.query)
        return ResearchResponse(
            answer=result["answer"],
            tools_used=result["tools_used"],
            ticker=result.get("ticker"),
        )
    except HTTPException:
        raise
    except Exception as exc:
        logger.error("Research query failed: %s", exc, exc_info=True)
        raise HTTPException(
            status_code=500,
            detail=f"Research query failed: {str(exc)}",
        )
