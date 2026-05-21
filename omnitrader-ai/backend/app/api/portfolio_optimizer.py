"""
api/portfolio_optimizer.py
===========================
POST /portfolio-optimizer/frontier  — efficient frontier
POST /portfolio-optimizer/risk-parity
POST /portfolio-optimizer/black-litterman
GET  /portfolio-optimizer/current   — optimize existing portfolio from DB
"""
import asyncio
import logging
from typing import List, Optional, Dict

import yfinance as yf
import pandas as pd
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import get_db
from app.engines.portfolio_optimizer import (
    compute_efficient_frontier, compute_risk_parity, compute_black_litterman,
    RISK_FREE_RATE,
)

router = APIRouter()
logger = logging.getLogger(__name__)


async def _fetch_returns_multi(tickers: list, period: str = "1y") -> pd.DataFrame:
    loop = asyncio.get_event_loop()
    results = {}

    async def _fetch_one(t):
        try:
            df = await loop.run_in_executor(None, lambda: yf.download(
                t, period=period, interval="1d", auto_adjust=True, progress=False, threads=False
            ))
            if df is None or len(df) < 30:
                return t, None
            if isinstance(df.columns, pd.MultiIndex):
                df.columns = df.columns.get_level_values(0)
            close = df["Close"] if "Close" in df.columns else df.iloc[:, 3]
            return t, close.pct_change().dropna()
        except Exception:
            return t, None

    fetch_results = await asyncio.gather(*[_fetch_one(t) for t in tickers])
    for t, s in fetch_results:
        if s is not None:
            results[t] = s

    if not results:
        return pd.DataFrame()
    return pd.DataFrame(results).dropna()


class FrontierRequest(BaseModel):
    tickers: List[str] = Field(..., min_length=2, max_length=15)
    period:  str = Field("1y")
    rf:      float = Field(RISK_FREE_RATE)
    n_points: int = Field(30, ge=10, le=50)


class BLView(BaseModel):
    assets:          List[str]
    expected_return: float = Field(..., description="Expected annual return, e.g. 0.18 for 18%")
    confidence:      float = Field(0.5, ge=0.1, le=0.9)


class BLRequest(BaseModel):
    tickers:      List[str]
    market_caps:  Dict[str, float] = Field(default_factory=dict)
    views:        List[BLView] = Field(default_factory=list)
    period:       str = Field("1y")
    rf:           float = Field(RISK_FREE_RATE)
    risk_aversion: float = Field(2.5)


@router.post("/frontier")
async def efficient_frontier(req: FrontierRequest):
    tickers = [t.strip().upper() for t in req.tickers]
    returns = await _fetch_returns_multi(tickers, req.period)
    if returns.empty or returns.shape[1] < 2:
        raise HTTPException(422, "Could not fetch sufficient data for the given tickers")
    result = compute_efficient_frontier(returns, n_points=req.n_points, rf=req.rf)
    return result


@router.post("/risk-parity")
async def risk_parity(req: FrontierRequest):
    tickers = [t.strip().upper() for t in req.tickers]
    returns = await _fetch_returns_multi(tickers, req.period)
    if returns.empty:
        raise HTTPException(422, "Could not fetch data for given tickers")
    result = compute_risk_parity(returns, rf=req.rf)
    return result


@router.post("/black-litterman")
async def black_litterman(req: BLRequest):
    tickers = [t.strip().upper() for t in req.tickers]
    returns = await _fetch_returns_multi(tickers, req.period)
    if returns.empty:
        raise HTTPException(422, "Could not fetch data")
    views_dicts = [v.model_dump() for v in req.views]
    result = compute_black_litterman(
        returns, req.market_caps, views_dicts, req.rf, req.risk_aversion
    )
    return result


@router.get("/current")
async def optimize_current_portfolio(db: AsyncSession = Depends(get_db)):
    """Load open positions from DB and run all three optimizations."""
    try:
        result = await db.execute(text("""
            SELECT ticker, shares, market_value, current_price
            FROM portfolio WHERE status = 'OPEN'
        """))
        rows = result.fetchall()
    except Exception as e:
        raise HTTPException(500, detail=str(e))

    if not rows or len(rows) < 2:
        return {"message": "Need at least 2 open positions to optimize.", "positions": len(rows or [])}

    tickers = [r.ticker for r in rows]
    market_caps = {r.ticker: float(r.market_value or 1e9) * 1000 for r in rows}  # proxy

    returns = await _fetch_returns_multi(tickers, "1y")
    if returns.empty or returns.shape[1] < 2:
        raise HTTPException(422, "Insufficient price history for portfolio tickers")

    frontier = compute_efficient_frontier(returns)
    rp       = compute_risk_parity(returns)
    bl       = compute_black_litterman(returns, market_caps, views=[])

    return {
        "tickers":        tickers,
        "efficient_frontier": frontier,
        "risk_parity":    rp,
        "black_litterman": bl,
    }
