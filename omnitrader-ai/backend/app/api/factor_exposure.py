"""
api/factor_exposure.py
======================
GET /factor-exposure/portfolio   — factor decomposition of open portfolio
GET /factor-exposure/ticker/{t}  — factor scores for a single stock
"""
import asyncio
import logging
from typing import Optional

import yfinance as yf
import pandas as pd
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import get_db
from app.engines.factor_engine import compute_stock_factors, normalise_factors, compute_portfolio_exposure

router = APIRouter()
logger = logging.getLogger(__name__)


async def _fetch_prices(ticker: str) -> tuple:
    loop = asyncio.get_event_loop()
    try:
        df = await loop.run_in_executor(None, lambda: yf.download(
            ticker, period="1y", interval="1d", auto_adjust=True, progress=False, threads=False
        ))
        if df is None or len(df) == 0:
            return ticker, None
        if isinstance(df.columns, pd.MultiIndex):
            df.columns = df.columns.get_level_values(0)
        close_col = "Close" if "Close" in df.columns else df.columns[-1]
        return ticker, df[close_col].dropna()
    except Exception as e:
        logger.warning("Fetch failed for %s: %s", ticker, e)
        return ticker, None


@router.get("/portfolio")
async def get_portfolio_factor_exposure(db: AsyncSession = Depends(get_db)):
    """
    Compute factor exposure breakdown for all open portfolio positions.
    Fetches price history via yfinance and AI scores from DB.
    """
    # Load portfolio
    try:
        result = await db.execute(text("""
            SELECT p.ticker, p.shares, p.market_value, p.current_price,
                   a.final_score
            FROM portfolio p
            LEFT JOIN ai_analysis a ON a.ticker = p.ticker
                AND a.analysis_date = (SELECT MAX(analysis_date) FROM ai_analysis WHERE ticker = p.ticker)
            WHERE p.status = 'OPEN'
        """))
        rows = result.fetchall()
    except Exception as e:
        logger.warning("Portfolio query failed: %s", e)
        rows = []

    if not rows:
        return {
            "message": "No open positions. Add positions to your portfolio to see factor exposure.",
            "exposures": {},
            "holdings": [],
        }

    total_value = sum(float(r.market_value or (r.current_price or 0) * r.shares) for r in rows)

    # Fetch price history for all tickers in parallel
    tickers = [r.ticker for r in rows]
    fetch_results = await asyncio.gather(*[_fetch_prices(t) for t in tickers])
    price_map = dict(fetch_results)

    # Compute factors for each holding
    raw_factors = []
    for r in rows:
        prices = price_map.get(r.ticker)
        ai_score = float(r.final_score) if r.final_score else None
        factors = compute_stock_factors(r.ticker, prices, ai_score)
        if factors:
            raw_factors.append(factors)

    normalised = normalise_factors(raw_factors)
    norm_map = {f["ticker"]: f for f in normalised}

    # Merge with portfolio weights
    holdings = []
    for r in rows:
        mv = float(r.market_value or (r.current_price or 0) * r.shares)
        weight = (mv / total_value * 100) if total_value > 0 else 0
        nf = norm_map.get(r.ticker, {})
        holdings.append({
            "ticker":     r.ticker,
            "weight_pct": round(weight, 2),
            "market_value": round(mv, 2),
            "momentum":   nf.get("momentum", 0),
            "volatility": nf.get("volatility", 0),
            "value":      nf.get("value", 0),
            "trend":      nf.get("trend", 0),
            "quality":    nf.get("quality", 0),
        })

    portfolio_exposure = compute_portfolio_exposure(holdings)

    return {
        "portfolio_value": round(total_value, 2),
        "position_count":  len(holdings),
        "holdings":        sorted(holdings, key=lambda x: -x["weight_pct"]),
        **portfolio_exposure,
    }


@router.get("/ticker/{ticker}")
async def get_ticker_factors(ticker: str, db: AsyncSession = Depends(get_db)):
    """Factor scores for a single stock."""
    t = ticker.upper()

    result_db = await db.execute(text("""
        SELECT final_score FROM ai_analysis
        WHERE ticker = :ticker ORDER BY analysis_date DESC LIMIT 1
    """), {"ticker": t})
    ai_row = result_db.fetchone()
    ai_score = float(ai_row.final_score) if ai_row and ai_row.final_score else None

    _, prices = await _fetch_prices(t)
    if prices is None:
        raise HTTPException(404, detail=f"No price data for {t}")

    raw = compute_stock_factors(t, prices, ai_score)
    if not raw:
        raise HTTPException(422, detail="Insufficient price history")

    return raw
