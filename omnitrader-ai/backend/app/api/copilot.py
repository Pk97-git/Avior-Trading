"""
api/copilot.py
==============
AI Copilot conversational endpoints.

POST /api/v1/copilot/chat            — send a message, get rich AI response
GET  /api/v1/copilot/sessions/{sid}  — retrieve session history
DELETE /api/v1/copilot/sessions/{sid} — clear a session

Response shape:
{
    "session_id":  str,
    "answer":      str,           # Markdown
    "charts":      list[ChartSpec],
    "citations":   list[dict],
    "actions":     list[ActionSpec],
    "follow_ups":  list[str],
    "tools_used":  list[str],
}
"""
import logging
from typing import Optional

from fastapi import APIRouter, Body, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import get_db
from app.services.copilot import CopilotService

router = APIRouter()
logger = logging.getLogger(__name__)


# ── Chat ──────────────────────────────────────────────────────────────────────

@router.post("/chat")
async def copilot_chat(
    message: str        = Body(..., description="Natural language question or instruction"),
    session_id: Optional[str] = Body(None, description="Omit to start a new session"),
    db: AsyncSession    = Depends(get_db),
):
    """
    Send a message to the AI Copilot and receive a rich response.

    Supports multi-turn conversations — pass the returned `session_id` back
    on subsequent requests to continue the same conversation.

    Example questions:
    - "Why did my portfolio fall today?"
    - "Best AI stocks under $100?"
    - "Compare Indian IT sector with US tech."
    - "Should I sell Tesla?"

    Returns:
    - **answer**: Markdown-formatted response with data citations
    - **charts**: List of chart specs (candlestick, bar, pie, line) for frontend rendering
    - **citations**: Data sources used (prices, AI scores, news, etc.)
    - **actions**: Clickable trade actions (BUY/SELL/REDUCE with endpoint + params)
    - **follow_ups**: 3 suggested next questions
    - **tools_used**: Which data tools were called
    """
    if not message.strip():
        raise HTTPException(status_code=422, detail="message cannot be empty")

    try:
        svc = CopilotService(db)
        result = await svc.chat(message=message.strip(), session_id=session_id)
        return result
    except Exception as exc:
        logger.exception("[Copilot] chat failed: %s", exc)
        raise HTTPException(status_code=500, detail=f"Copilot error: {str(exc)}")


# ── Session history ───────────────────────────────────────────────────────────

@router.get("/sessions/{session_id}")
async def get_session_history(
    session_id: str,
    db: AsyncSession = Depends(get_db),
):
    """
    Retrieve the readable message history for a session.

    Returns user and assistant text messages only (tool calls are omitted).
    """
    svc = CopilotService(db)
    history = svc.get_history(session_id)
    return {
        "session_id": session_id,
        "messages": history,
        "count": len(history),
    }


# ── Clear session ─────────────────────────────────────────────────────────────

@router.delete("/sessions/{session_id}")
async def clear_session(
    session_id: str,
    db: AsyncSession = Depends(get_db),
):
    """
    Clear a conversation session and free its memory.
    """
    svc = CopilotService(db)
    svc.clear_session(session_id)
    return {"cleared": True, "session_id": session_id}


# ── Quick ask (no session) ────────────────────────────────────────────────────

@router.get("/ask")
async def copilot_ask(
    q: str,
    db: AsyncSession = Depends(get_db),
):
    """
    Stateless single-turn question via GET query param.
    Convenience endpoint for simple lookups — no session memory.

    Example: GET /api/v1/copilot/ask?q=Should+I+buy+AAPL
    """
    if not q.strip():
        raise HTTPException(status_code=422, detail="q cannot be empty")
    try:
        svc = CopilotService(db)
        result = await svc.chat(message=q.strip())
        return result
    except Exception as exc:
        logger.exception("[Copilot] ask failed: %s", exc)
        raise HTTPException(status_code=500, detail=str(exc))
