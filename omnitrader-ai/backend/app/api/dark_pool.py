"""
api/dark_pool.py
================
GET /dark-pool/{ticker}      — institutional activity for a specific ticker
GET /dark-pool/scan/universe — scan universe for recent unusual volume
"""
import asyncio
import datetime
import logging
from typing import Optional

import yfinance as yf
import pandas as pd
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import get_db
from app.engines.dark_pool_proxy import detect_institutional_activity

router = APIRouter()
logger = logging.getLogger(__name__)


async def _fetch_ohlcv(ticker: str, period: str = "60d") -> Optional[pd.DataFrame]:
    loop = asyncio.get_event_loop()
    try:
        df = await loop.run_in_executor(None, lambda: yf.download(
            ticker, period=period, interval="1d", auto_adjust=True, progress=False, threads=False
        ))
        if df is None or len(df) == 0:
            return None
        if isinstance(df.columns, pd.MultiIndex):
            df.columns = df.columns.get_level_values(0)
        return df
    except Exception as e:
        logger.warning("OHLCV fetch failed for %s: %s", ticker, e)
        return None


@router.get("/scan/universe")
async def scan_universe_dark_pool(
    country: str = Query("ALL"),
    min_vol_ratio: float = Query(2.5, description="Minimum volume ratio to include"),
    limit:   int = Query(20, ge=1, le=40),
    db: AsyncSession = Depends(get_db),
):
    """
    Scan the stock universe for unusual volume activity today.
    Uses stored price data from DB (fast — no yfinance calls per stock).
    """
    country_clause = "" if country.upper() == "ALL" else "AND s.country = :country"
    params: dict = {"min_vol_ratio": min_vol_ratio, "limit": limit}
    if country.upper() != "ALL":
        params["country"] = country.upper()

    try:
        result = await db.execute(text(f"""
            WITH latest AS (
                SELECT DISTINCT ON (ticker) ticker, date, close, volume
                FROM stock_prices
                ORDER BY ticker, date DESC
            ),
            avg_vol AS (
                SELECT ticker, AVG(volume) as avg_20d
                FROM stock_prices
                WHERE date >= NOW() - INTERVAL '25 days'
                GROUP BY ticker
                HAVING COUNT(*) >= 10
            )
            SELECT s.ticker, s.name, s.sector, s.country,
                   l.close as current_price, l.volume as today_volume,
                   av.avg_20d,
                   l.volume / NULLIF(av.avg_20d, 0) as vol_ratio,
                   l.date
            FROM stocks s
            JOIN latest l ON l.ticker = s.ticker
            JOIN avg_vol av ON av.ticker = s.ticker
            WHERE l.volume / NULLIF(av.avg_20d, 0) >= :min_vol_ratio
              {country_clause}
            ORDER BY l.volume / NULLIF(av.avg_20d, 0) DESC
            LIMIT :limit
        """), params)
        rows = result.fetchall()
    except Exception as e:
        logger.error("Dark pool scan failed: %s", e)
        raise HTTPException(500, detail=str(e))

    results = []
    for r in rows:
        vol_ratio = float(r.vol_ratio) if r.vol_ratio else 0
        results.append({
            "ticker":         r.ticker,
            "name":           r.name,
            "sector":         r.sector,
            "country":        r.country,
            "current_price":  float(r.current_price) if r.current_price else None,
            "today_volume":   int(r.today_volume) if r.today_volume else 0,
            "avg_20d_volume": int(r.avg_20d) if r.avg_20d else 0,
            "vol_ratio":      round(vol_ratio, 2),
            "date":           str(r.date)[:10] if r.date else None,
            "signal": (
                "BREAKOUT_VOLUME" if vol_ratio >= 5 else
                "SURGE" if vol_ratio >= 3 else
                "ELEVATED"
            ),
        })

    return {
        "scan_date":    datetime.datetime.utcnow().strftime("%Y-%m-%d"),
        "count":        len(results),
        "results":      results,
        "disclaimer":   "Volume proxy for institutional activity. High volume alone does not confirm institutional intent.",
    }


@router.get("/{ticker}")
async def get_dark_pool_signals(
    ticker: str,
    period: str = Query("60d", description="60d | 90d | 6mo"),
):
    """
    Detect institutional activity footprints for a ticker.
    Returns volume surge events, accumulation/distribution signals.
    """
    t = ticker.strip().upper()
    df = await _fetch_ohlcv(t, period=period)
    if df is None or len(df) < 25:
        raise HTTPException(404, detail=f"Insufficient data for {t}")

    events = detect_institutional_activity(df, lookback_volume=20, scan_days=15)

    # Summary
    bullish_events = [e for e in events if e.get("is_bullish")]
    bearish_events = [e for e in events if e.get("is_bearish")]
    accumulation   = [e for e in events if e["signal_type"] == "ACCUMULATION"]
    distribution   = [e for e in events if e["signal_type"] == "DISTRIBUTION"]

    if len(accumulation) > len(distribution) and len(accumulation) >= 2:
        overall_signal = "ACCUMULATION_PATTERN"
        overall_note   = f"{len(accumulation)} accumulation events in last 15 days — institutions appear to be building positions"
    elif len(distribution) > len(accumulation) and len(distribution) >= 2:
        overall_signal = "DISTRIBUTION_PATTERN"
        overall_note   = f"{len(distribution)} distribution events in last 15 days — institutions may be exiting"
    elif events:
        overall_signal = "MIXED_SIGNALS"
        overall_note   = f"{len(events)} unusual volume events — no clear directional bias"
    else:
        overall_signal = "NO_UNUSUAL_ACTIVITY"
        overall_note   = "No unusual volume detected in the last 15 trading days"

    return {
        "ticker":          t,
        "overall_signal":  overall_signal,
        "overall_note":    overall_note,
        "events_found":    len(events),
        "accumulation_count": len(accumulation),
        "distribution_count": len(distribution),
        "events":          events,
        "disclaimer":      "This is a proxy for institutional activity based on public volume data. Actual dark pool prints require Bloomberg Terminal access.",
    }
