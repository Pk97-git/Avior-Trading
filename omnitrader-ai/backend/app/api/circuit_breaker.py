"""
api/circuit_breaker.py
======================
Circuit Breaker status endpoint.

GET /circuit-breaker/status — returns current trading circuit-breaker state
"""
import logging

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import get_db
from app.engines.circuit_breaker import CircuitBreakerEngine

router = APIRouter()
logger = logging.getLogger(__name__)


@router.get("/status")
async def get_circuit_breaker_status(db: AsyncSession = Depends(get_db)):
    """
    Returns the current circuit-breaker state.

    Evaluates all rules simultaneously:
      - VIX thresholds (HALT > 35, CAUTION > 25)
      - Portfolio daily P&L (HALT if < -2%)
      - Portfolio drawdown from peak (CAUTION if > 10%)
      - Yield curve inversion (CAUTION if US10Y - US2Y < -0.8%)

    Response:
    {
        "trading_allowed": bool,
        "caution":         bool,
        "status":          "CLEAR" | "CAUTION" | "HALT",
        "reasons":         [str],
        "vix":             float | null,
        "daily_pnl_pct":   float | null,
        "drawdown_pct":    float | null,
    }
    """
    engine = CircuitBreakerEngine(db)
    return await engine.check()
