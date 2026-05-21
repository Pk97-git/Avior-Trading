"""
api/alpha_signals.py
=====================
GET  /alpha/earnings-quality/{ticker}  — Sloan accruals score
GET  /alpha/momentum/rankings          — cross-sectional momentum for universe
GET  /alpha/momentum/{ticker}          — single ticker momentum rank
POST /alpha/filing-tone                — tone analysis on any financial text
"""
import asyncio
import logging

import yfinance as yf
import pandas as pd
from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import get_db
from app.engines.alpha_signals import (
    compute_earnings_quality,
    compute_cross_sectional_momentum,
    analyse_filing_tone,
)

router = APIRouter()
logger = logging.getLogger(__name__)


@router.get("/earnings-quality/{ticker}")
async def get_earnings_quality(ticker: str, db: AsyncSession = Depends(get_db)):
    """
    Compute Sloan earnings quality score from DB financials.
    """
    t = ticker.strip().upper()
    try:
        result = await db.execute(text("""
            SELECT net_income, operating_cash_flow, total_assets, revenue
            FROM company_financials
            WHERE ticker = :ticker
            ORDER BY period_end DESC LIMIT 2
        """), {"ticker": t})
        rows = result.fetchall()
    except Exception as e:
        logger.warning("Financials query failed: %s", e)
        rows = []

    if not rows:
        return {
            "ticker": t,
            "score": None,
            "quality": "NO_DATA",
            "note": "No financial data in DB. Trigger fundamentals ingestion first.",
        }

    latest = rows[0]
    prev   = rows[1] if len(rows) > 1 else None

    quality = compute_earnings_quality(
        net_income=float(latest.net_income) if latest.net_income else None,
        cfo=float(latest.operating_cash_flow) if latest.operating_cash_flow else None,
        total_assets=float(latest.total_assets) if latest.total_assets else None,
        prev_total_assets=float(prev.total_assets) if prev and prev.total_assets else None,
    )
    quality["ticker"] = t
    return quality


@router.get("/momentum/rankings")
async def get_momentum_rankings(
    country: str = Query("IN"),
    limit:   int = Query(50, ge=10, le=200),
    db: AsyncSession = Depends(get_db),
):
    """
    Cross-sectional momentum ranking across stock universe.
    Uses DB price data (fast — no yfinance per stock).
    Returns top and bottom decile with LONG/SHORT signals.
    """
    country_clause = "" if country.upper() == "ALL" else "WHERE s.country = :country"
    params: dict = {}
    if country.upper() != "ALL":
        params["country"] = country.upper()

    try:
        result = await db.execute(text(f"""
            SELECT s.ticker,
                   MAX(CASE WHEN p.date >= NOW() - INTERVAL '5 days'  THEN p.close END) as price_now,
                   MAX(CASE WHEN p.date BETWEEN NOW() - INTERVAL '35 days'  AND NOW() - INTERVAL '20 days' THEN p.close END) as price_1m,
                   MAX(CASE WHEN p.date BETWEEN NOW() - INTERVAL '265 days' AND NOW() - INTERVAL '250 days' THEN p.close END) as price_12m
            FROM stocks s
            JOIN stock_prices p ON p.ticker = s.ticker
            {country_clause}
            GROUP BY s.ticker
            HAVING MAX(CASE WHEN p.date >= NOW() - INTERVAL '5 days' THEN p.close END) IS NOT NULL
               AND MAX(CASE WHEN p.date BETWEEN NOW() - INTERVAL '265 days' AND NOW() - INTERVAL '250 days' THEN p.close END) IS NOT NULL
            LIMIT :limit
        """), {**params, "limit": limit})
        rows = result.fetchall()
    except Exception as e:
        logger.error("Momentum ranking query failed: %s", e)
        raise HTTPException(500, detail=str(e))

    results = []
    for r in rows:
        p_now = float(r.price_now) if r.price_now else None
        p_1m  = float(r.price_1m)  if r.price_1m  else None
        p_12m = float(r.price_12m) if r.price_12m else None

        if p_now and p_12m and p_12m > 0:
            momentum_end   = p_1m if p_1m else p_now
            momentum_12_1  = (momentum_end - p_12m) / p_12m
            results.append({
                "ticker":        r.ticker,
                "current_price": p_now,
                "momentum_12_1": round(momentum_12_1, 4),
                "momentum_pct":  round(momentum_12_1 * 100, 2),
            })

    if not results:
        return {"count": 0, "rankings": [], "message": "No data available. Ensure price history covers 12 months."}

    results.sort(key=lambda x: -x["momentum_12_1"])
    n = len(results)
    for i, r in enumerate(results):
        rank = i + 1
        decile = min(10, int(rank / n * 10) + 1)
        r["rank"]   = rank
        r["decile"] = decile
        r["signal"] = (
            "STRONG_LONG"  if decile == 1 else
            "LONG"         if decile <= 3 else
            "SHORT"        if decile == 10 else
            "AVOID"        if decile >= 8 else
            "NEUTRAL"
        )

    top10    = [r for r in results if r["signal"] in ("STRONG_LONG", "LONG")][:10]
    bottom10 = [r for r in results if r["signal"] in ("STRONG_SHORT", "SHORT", "AVOID")][-10:]

    return {
        "country":   country,
        "total_ranked": n,
        "top_momentum":    top10,
        "bottom_momentum": bottom10,
        "all_rankings":    results,
        "methodology": "Jegadeesh-Titman (1993): 12-1 month momentum. Long top decile, short bottom decile.",
    }


class FilingToneRequest(BaseModel):
    text:   str
    ticker: str = ""


@router.post("/filing-tone")
async def analyse_text_tone(req: FilingToneRequest):
    if len(req.text.strip()) < 20:
        raise HTTPException(422, "Text too short for analysis")
    return analyse_filing_tone(req.text, req.ticker.upper())
