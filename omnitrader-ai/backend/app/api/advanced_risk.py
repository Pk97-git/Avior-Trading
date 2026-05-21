"""
Advanced Risk Management API
============================
POST /advanced-risk/drawdown         — drawdown metrics
POST /advanced-risk/greeks           — single-option Black-Scholes greeks
POST /advanced-risk/portfolio-greeks — aggregate options book greeks
GET  /advanced-risk/correlation      — fetch returns from yfinance + breakdown
POST /advanced-risk/tail-risk        — composite tail-risk score + hedging rules
"""
from __future__ import annotations

import asyncio
import logging
from typing import Any

import pandas as pd
from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field

from app.engines.drawdown_manager import compute_drawdown_metrics, compute_portfolio_drawdown
from app.engines.options_greeks import black_scholes_greeks, compute_portfolio_greeks
from app.engines.correlation_monitor import detect_correlation_breakdown, compute_rolling_correlation_history
from app.engines.tail_risk import compute_tail_risk_score

logger = logging.getLogger("omnitrader.advanced_risk")
router = APIRouter()


# ─── Pydantic models ───────────────────────────────────────────────────────────

class DrawdownRequest(BaseModel):
    returns: list[float] = Field(default=[], description="Daily P&L returns, e.g. [0.01, -0.02]")
    nav_history: list[dict] = Field(default=[], description="List of {date, nav} dicts")
    positions: list[dict] = Field(default=[], description="List of {ticker, weight, current_pnl_pct}")


class GreeksRequest(BaseModel):
    S: float = Field(..., description="Current stock price")
    K: float = Field(..., description="Strike price")
    T_days: float = Field(..., description="Days to expiry")
    sigma: float = Field(..., description="Implied volatility (e.g. 0.20 for 20%)")
    option_type: str = Field(default="call", description="'call' or 'put'")
    quantity: float = Field(default=1.0, description="Number of contracts")
    r: float = Field(default=0.05, description="Risk-free rate")


class PortfolioGreeksRequest(BaseModel):
    positions: list[dict] = Field(
        ...,
        description="List of {ticker, option_type, S, K, T_days, sigma, quantity, r=0.05}",
    )


class TailRiskRequest(BaseModel):
    max_drawdown_pct: float = Field(default=0.0)
    current_drawdown_pct: float = Field(default=0.0)
    avg_correlation: float = Field(default=0.5)
    var_95_pct: float = Field(default=2.0, description="95% VaR as positive %")
    regime: str = Field(default="NEUTRAL", description="BULL / NEUTRAL / BEAR")
    vix_level: float | None = Field(default=None)
    beta: float | None = Field(default=None)


# ─── Drawdown ──────────────────────────────────────────────────────────────────

@router.post("/drawdown")
async def drawdown_endpoint(req: DrawdownRequest) -> dict[str, Any]:
    """
    Compute drawdown metrics from a returns series and/or NAV history.
    If nav_history + positions are provided, also returns per-position contributions.
    """
    try:
        if req.nav_history and req.positions is not None:
            result = compute_portfolio_drawdown(req.positions, req.nav_history)
        elif req.returns:
            result = compute_drawdown_metrics(req.returns)
        else:
            raise HTTPException(status_code=422, detail="Provide either 'returns' or 'nav_history'.")
        if "error" in result:
            raise HTTPException(status_code=422, detail=result["error"])
        return result
    except HTTPException:
        raise
    except Exception as exc:
        logger.exception("Drawdown computation failed")
        raise HTTPException(status_code=500, detail=str(exc))


# ─── Options Greeks ────────────────────────────────────────────────────────────

@router.post("/greeks")
async def greeks_endpoint(req: GreeksRequest) -> dict[str, Any]:
    """
    Compute Black-Scholes Greeks for a single option.
    """
    try:
        T_years = max(req.T_days / 365.0, 1e-6)
        result = black_scholes_greeks(req.S, req.K, T_years, req.r, req.sigma, req.option_type)
        # Add delta_dollars for convenience
        result["delta_dollars"] = round(result["delta"] * req.S * req.quantity * 100.0, 2)
        result["quantity"] = req.quantity
        return result
    except Exception as exc:
        logger.exception("Greeks computation failed")
        raise HTTPException(status_code=500, detail=str(exc))


@router.post("/portfolio-greeks")
async def portfolio_greeks_endpoint(req: PortfolioGreeksRequest) -> dict[str, Any]:
    """
    Compute aggregate Greeks for an options book.
    """
    try:
        if not req.positions:
            raise HTTPException(status_code=422, detail="At least one position is required.")
        result = compute_portfolio_greeks(req.positions)
        return result
    except HTTPException:
        raise
    except Exception as exc:
        logger.exception("Portfolio Greeks computation failed")
        raise HTTPException(status_code=500, detail=str(exc))


# ─── Correlation Monitor ───────────────────────────────────────────────────────

def _fetch_returns_sync(tickers: list[str], period: str) -> pd.DataFrame:
    """Fetch yfinance closes and compute daily returns. Runs in executor."""
    import yfinance as yf
    raw = yf.download(tickers, period=period, auto_adjust=True, progress=False)
    if raw.empty:
        return pd.DataFrame()
    if isinstance(raw.columns, pd.MultiIndex):
        closes = raw["Close"]
    else:
        closes = raw[["Close"]] if "Close" in raw.columns else raw
    returns = closes.pct_change().dropna(how="all")
    return returns


@router.get("/correlation")
async def correlation_endpoint(
    tickers: str = Query(..., description="Comma-separated tickers, e.g. AAPL,MSFT,GOOG"),
    period: str = Query(default="3mo", description="yfinance period string, e.g. 3mo, 6mo, 1y"),
    lookback_short: int = Query(default=20, ge=5),
    lookback_long: int = Query(default=60, ge=10),
    rolling_window: int = Query(default=20, ge=5),
) -> dict[str, Any]:
    """
    Fetch returns from yfinance (async), detect correlation breakdown,
    and return rolling correlation history.
    """
    try:
        ticker_list = [t.strip().upper() for t in tickers.split(",") if t.strip()]
        if len(ticker_list) < 2:
            raise HTTPException(status_code=422, detail="Need at least 2 tickers.")

        loop = asyncio.get_event_loop()
        returns_df: pd.DataFrame = await loop.run_in_executor(
            None, _fetch_returns_sync, ticker_list, period
        )

        if returns_df.empty:
            raise HTTPException(status_code=404, detail="No data returned from yfinance.")

        breakdown = detect_correlation_breakdown(returns_df, lookback_short, lookback_long)
        rolling = compute_rolling_correlation_history(returns_df, rolling_window)

        if "error" in breakdown:
            raise HTTPException(status_code=422, detail=breakdown["error"])

        return {
            "breakdown": breakdown,
            "rolling_history": rolling,
            "tickers": ticker_list,
            "period": period,
        }
    except HTTPException:
        raise
    except Exception as exc:
        logger.exception("Correlation endpoint failed")
        raise HTTPException(status_code=500, detail=str(exc))


# ─── Tail Risk Score ───────────────────────────────────────────────────────────

@router.post("/tail-risk")
async def tail_risk_endpoint(req: TailRiskRequest) -> dict[str, Any]:
    """
    Compute tail-risk score (0-100) and hedge recommendations.
    """
    try:
        portfolio_data = req.model_dump()
        result = compute_tail_risk_score(portfolio_data)
        return result
    except Exception as exc:
        logger.exception("Tail risk computation failed")
        raise HTTPException(status_code=500, detail=str(exc))
