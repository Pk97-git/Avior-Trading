"""
api/pairs.py
============
GET  /pairs/candidates           — scan sector groups for diverged pairs
GET  /pairs/analyze/{a}/{b}      — deep analysis of a specific pair
GET  /pairs/sectors              — available sector groups
"""
import asyncio
import logging
from typing import Optional

import yfinance as yf
import pandas as pd
from fastapi import APIRouter, HTTPException, Query

from app.engines.pairs_engine import analyze_pair, SECTOR_PAIRS

router = APIRouter()
logger = logging.getLogger(__name__)


async def _fetch_prices(ticker: str) -> tuple[str, Optional[pd.Series]]:
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
        logger.warning("Failed to fetch %s: %s", ticker, e)
        return ticker, None


@router.get("/candidates")
async def get_pair_candidates(
    sector: str = Query("IN_BANKS", description="Sector group to scan"),
    min_zscore: float = Query(1.5, description="Minimum absolute z-score to include"),
):
    """
    Scan a sector group for correlated pairs and return those with significant divergence.
    """
    tickers = SECTOR_PAIRS.get(sector.upper())
    if not tickers:
        raise HTTPException(status_code=404, detail=f"Unknown sector: {sector}. Valid: {list(SECTOR_PAIRS.keys())}")

    # Fetch all tickers in parallel
    results = await asyncio.gather(*[_fetch_prices(t) for t in tickers])
    price_map = {t: s for t, s in results if s is not None}

    if len(price_map) < 2:
        raise HTTPException(status_code=503, detail="Insufficient price data. Check ticker symbols.")

    valid_tickers = list(price_map.keys())
    pairs = []

    # Analyse all unique pairs
    for i in range(len(valid_tickers)):
        for j in range(i + 1, len(valid_tickers)):
            a, b = valid_tickers[i], valid_tickers[j]
            try:
                result = analyze_pair(a, b, price_map[a], price_map[b])
                if result and abs(result["current_zscore"]) >= min_zscore:
                    pairs.append(result)
            except Exception as e:
                logger.warning("Pair %s/%s failed: %s", a, b, e)

    pairs.sort(key=lambda x: -abs(x["current_zscore"]))

    return {
        "sector":       sector,
        "pairs_scanned": len(valid_tickers) * (len(valid_tickers) - 1) // 2,
        "pairs_found":  len(pairs),
        "tradeable":    sum(1 for p in pairs if p["is_tradeable"]),
        "pairs":        pairs,
    }


@router.get("/analyze/{ticker_a}/{ticker_b}")
async def analyze_specific_pair(ticker_a: str, ticker_b: str):
    """Deep analysis of a specific pair with z-score history."""
    a = ticker_a.upper()
    b = ticker_b.upper()

    results = await asyncio.gather(_fetch_prices(a), _fetch_prices(b))
    price_map = {t: s for t, s in results if s is not None}

    if a not in price_map or b not in price_map:
        raise HTTPException(status_code=404, detail="Could not fetch prices for one or both tickers.")

    result = analyze_pair(a, b, price_map[a], price_map[b])
    if result is None:
        raise HTTPException(status_code=422, detail="Pair does not have sufficient correlation or data.")

    return result


@router.get("/sectors")
async def list_sectors():
    return {
        "sectors": [
            {"id": k, "label": k.replace("_", " ").title(), "tickers": v}
            for k, v in SECTOR_PAIRS.items()
        ]
    }
