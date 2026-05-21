"""
api/quant.py
=============
POST /quant/monte-carlo/trade       — single trade Monte Carlo
POST /quant/monte-carlo/portfolio   — portfolio Monte Carlo
POST /quant/var                     — VaR and CVaR calculation
GET  /quant/garch/{ticker}          — GARCH volatility forecast
GET  /quant/regime/{ticker}         — HMM regime detection
"""
import asyncio
import logging
from typing import Optional, List

import yfinance as yf
import pandas as pd
from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field

from app.engines.quant_math import (
    monte_carlo_trade, monte_carlo_portfolio,
    compute_var_cvar, fit_garch, fit_hmm_regime,
)

router = APIRouter()
logger = logging.getLogger(__name__)


async def _fetch_returns(ticker: str, period: str = "2y") -> Optional[pd.Series]:
    loop = asyncio.get_event_loop()
    try:
        df = await loop.run_in_executor(None, lambda: yf.download(
            ticker, period=period, interval="1d", auto_adjust=True, progress=False, threads=False
        ))
        if df is None or len(df) < 30:
            return None
        if isinstance(df.columns, pd.MultiIndex):
            df.columns = df.columns.get_level_values(0)
        close = df["Close"] if "Close" in df.columns else df.iloc[:, 3]
        return close.pct_change().dropna()
    except Exception as e:
        logger.warning("Returns fetch failed for %s: %s", ticker, e)
        return None


class MonteCarloTradeRequest(BaseModel):
    ticker:         str
    entry_price:    float = Field(..., gt=0)
    stop_loss:      float = Field(..., gt=0)
    take_profit:    float = Field(..., gt=0)
    position_value: float = Field(..., gt=0)
    days_horizon:   int   = Field(10, ge=1, le=60)
    n_simulations:  int   = Field(10000, ge=1000, le=50000)


class VaRRequest(BaseModel):
    ticker:          str
    portfolio_value: float = Field(..., gt=0)
    period:          str   = Field("1y")
    method:          str   = Field("historical")
    confidence_levels: List[float] = Field([0.90, 0.95, 0.99])


@router.post("/monte-carlo/trade")
async def run_monte_carlo_trade(req: MonteCarloTradeRequest):
    returns = await _fetch_returns(req.ticker, period="1y")
    if returns is None:
        raise HTTPException(404, detail=f"No price data for {req.ticker}")
    daily_vol = float(returns.std()) * (252 ** 0.5)
    result = monte_carlo_trade(
        entry_price=req.entry_price, stop_loss=req.stop_loss,
        take_profit=req.take_profit, win_rate=0.5,
        daily_vol=daily_vol, position_value=req.position_value,
        days_horizon=req.days_horizon, n_simulations=req.n_simulations,
    )
    result["ticker"] = req.ticker.upper()
    result["annual_vol_pct"] = round(daily_vol * 100, 2)
    return result


@router.post("/var")
async def compute_var(req: VaRRequest):
    returns = await _fetch_returns(req.ticker, period=req.period)
    if returns is None:
        raise HTTPException(404, detail=f"No price data for {req.ticker}")
    valid_methods = {"historical", "parametric", "cornish_fisher"}
    if req.method not in valid_methods:
        raise HTTPException(422, detail=f"method must be one of {sorted(valid_methods)}")
    result = compute_var_cvar(returns, req.portfolio_value, req.confidence_levels, req.method)
    result["ticker"] = req.ticker.upper()
    return result


@router.get("/garch/{ticker}")
async def get_garch(ticker: str, period: str = Query("2y")):
    t = ticker.strip().upper()
    returns = await _fetch_returns(t, period=period)
    if returns is None:
        raise HTTPException(404, detail=f"No data for {t}")
    result = fit_garch(returns)
    result["ticker"] = t
    return result


@router.get("/regime/{ticker}")
async def get_regime(ticker: str, period: str = Query("2y")):
    t = ticker.strip().upper()
    returns = await _fetch_returns(t, period=period)
    if returns is None:
        raise HTTPException(404, detail=f"No data for {t}")
    result = fit_hmm_regime(returns)
    result["ticker"] = t
    return result
