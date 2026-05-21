"""
api/analytics.py
=================
REST endpoints for DuckDB-powered analytical queries.

GET /api/analytics/factor-ranks           → cross-sectional factor ranks (today)
GET /api/analytics/rolling-returns?days=30&tickers=AAPL,MSFT
GET /api/analytics/correlation?days=90&tickers=AAPL,MSFT,NVDA
GET /api/analytics/sector-performance?days=30
"""
import logging
from datetime import date
from typing import Optional

from fastapi import APIRouter, Query, HTTPException

from app.analytics.duckdb_engine import DuckDBAnalytics

router = APIRouter(prefix="/api/analytics", tags=["Analytics"])
logger = logging.getLogger(__name__)


def _get_engine() -> DuckDBAnalytics:
    try:
        return DuckDBAnalytics()
    except Exception as e:
        raise HTTPException(status_code=503, detail=f"Analytics engine unavailable: {e}")


@router.get("/factor-ranks")
async def get_factor_ranks(as_of: Optional[str] = Query(None, description="Date YYYY-MM-DD")):
    """Cross-sectional factor ranks across all tickers with technicals data."""
    engine = _get_engine()
    try:
        as_of_date = date.fromisoformat(as_of) if as_of else None
        df = engine.factor_ranks(as_of_date)
        if df.empty:
            return {"data": [], "message": "No factor data available"}
        return {"data": df.to_dict(orient="records")}
    except Exception as e:
        logger.error("factor-ranks error: %s", e)
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/rolling-returns")
async def get_rolling_returns(
    days: int = Query(30, ge=1, le=365),
    tickers: str = Query(..., description="Comma-separated tickers"),
):
    """Rolling n-day price returns for specified tickers."""
    ticker_list = [t.strip().upper() for t in tickers.split(",") if t.strip()]
    if not ticker_list:
        raise HTTPException(status_code=400, detail="No tickers provided")
    if len(ticker_list) > 100:
        raise HTTPException(status_code=400, detail="Max 100 tickers per request")

    engine = _get_engine()
    try:
        df = engine.rolling_returns(ticker_list, days)
        return {"data": df.to_dict(orient="records"), "days": days}
    except Exception as e:
        logger.error("rolling-returns error: %s", e)
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/correlation")
async def get_correlation(
    days: int = Query(90, ge=20, le=365),
    tickers: str = Query(..., description="Comma-separated tickers"),
):
    """Pairwise Pearson correlation of daily returns."""
    ticker_list = [t.strip().upper() for t in tickers.split(",") if t.strip()]
    if len(ticker_list) < 2:
        raise HTTPException(status_code=400, detail="At least 2 tickers required")
    if len(ticker_list) > 30:
        raise HTTPException(status_code=400, detail="Max 30 tickers for correlation matrix")

    engine = _get_engine()
    try:
        df = engine.correlation_matrix(ticker_list, days)
        if df.empty:
            return {"matrix": {}, "tickers": ticker_list}
        return {
            "matrix": df.to_dict(),
            "tickers": list(df.columns),
            "days": days,
        }
    except Exception as e:
        logger.error("correlation error: %s", e)
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/sector-performance")
async def get_sector_performance(days: int = Query(30, ge=1, le=365)):
    """Average and median return by sector over n days."""
    engine = _get_engine()
    try:
        df = engine.sector_performance(days)
        return {"data": df.to_dict(orient="records"), "days": days}
    except Exception as e:
        logger.error("sector-performance error: %s", e)
        raise HTTPException(status_code=500, detail=str(e))
