"""
api/patterns.py
===============
FastAPI router for candlestick pattern detection, scanning, and backtesting.

Endpoints
---------
GET  /patterns/list                        — all available pattern codes with metadata
GET  /patterns/scan/today                  — scan all stocks for patterns detected today/yesterday
POST /patterns/backtest                    — backtest a specific pattern on a ticker
GET  /patterns/{ticker}                    — detect patterns on a specific stock's recent candles
GET  /patterns/{ticker}/chart-annotations  — pattern matches in lightweight-charts marker format
"""
from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone
from typing import Optional

import yfinance as yf
from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import get_db

router = APIRouter()
logger = logging.getLogger(__name__)


# ── Pattern emoji map ──────────────────────────────────────────────────────────

_EMOJI_MAP: dict[str, str] = {
    "HAMMER":                  "🔨",
    "MORNING_STAR":            "🔨",
    "ABANDONED_BABY_BULLISH":  "🔨",
    "INVERTED_HAMMER":         "🔨",
    "BULLISH_ENGULFING":       "💚",
    "BEARISH_ENGULFING":       "🔴",
    "HANGING_MAN":             "🔴",
    "MARUBOZU_BEARISH":        "🔴",
    "BEARISH_HARAMI":          "🔴",
    "DOJI":                    "◈",
    "SPINNING_TOP":            "◈",
    "SHOOTING_STAR":           "⭐",
    "EVENING_STAR":            "⭐",
    "ABANDONED_BABY_BEARISH":  "⭐",
    "THREE_WHITE_SOLDIERS":    "🪖",
    "THREE_BLACK_CROWS":       "🐦",
    "TWEEZER_BOTTOM":          "📈",
    "BULLISH_HARAMI":          "📈",
    "MARUBOZU_BULLISH":        "💚",
    "TWEEZER_TOP":             "📉",
}


def _get_emoji(code: str, name: str) -> str:
    """Look up emoji by code, then fall back to generic."""
    return _EMOJI_MAP.get(code.upper(), "◈")


# ── yfinance fetch helper (runs in executor — sync library) ───────────────────

async def _fetch_ohlcv(
    ticker: str,
    period: str = "3mo",
    interval: str = "1d",
) -> Optional[object]:
    """
    Fetch OHLCV with yfinance in a thread executor.
    Returns a DataFrame or None on failure.
    """
    loop = asyncio.get_event_loop()
    try:
        df = await loop.run_in_executor(
            None,
            lambda: yf.download(
                ticker,
                period=period,
                interval=interval,
                auto_adjust=True,
                progress=False,
                threads=False,
            ),
        )
        if df is None or len(df) == 0:
            return None

        # Flatten multi-level columns (yfinance >= 0.2)
        import pandas as pd
        if isinstance(df.columns, pd.MultiIndex):
            df.columns = df.columns.get_level_values(0)

        return df
    except Exception as exc:
        logger.warning("[patterns] yfinance fetch failed for %s: %s", ticker, exc)
        return None


# ── Request / Response models ──────────────────────────────────────────────────

class PatternBacktestRequest(BaseModel):
    ticker:       str
    pattern_code: str          # e.g. "BULLISH_ENGULFING"
    period:       str  = "2y"  # "1y", "2y", "5y"
    country:      str  = "IN"


# ── GET /patterns/list ────────────────────────────────────────────────────────


@router.get("/list")
async def list_patterns():
    """
    Return all available pattern codes with metadata (no computation).

    Response: list of {code, name, bias, category, strength, reliability_pct,
                        description, entry_suggestion, stop_suggestion, emoji}
    """
    from app.engines.candlestick_patterns import CandlestickPatternEngine
    patterns = CandlestickPatternEngine.list_all_patterns()
    return {
        "count":    len(patterns),
        "patterns": patterns,
    }


# ── GET /patterns/scan/today ──────────────────────────────────────────────────


@router.get("/scan/today")
async def scan_today(
    bias:         str = Query("ALL",  description="BULLISH | BEARISH | ALL"),
    min_strength: int = Query(3,      ge=1, le=5, description="Minimum pattern strength 1–5"),
    country:      str = Query("ALL",  description="IN | US | ALL"),
    limit:        int = Query(30,     ge=1, le=50, description="Max results"),
    db: AsyncSession = Depends(get_db),
):
    """
    Scan all stocks in the universe for patterns detected TODAY or YESTERDAY
    (candle_index <= 1).

    Stocks are fetched from the `stocks` table.  Processing is batched in
    groups of 10 concurrently using asyncio.gather with return_exceptions=True
    so one failing ticker never aborts the scan.

    Results are sorted by strength DESC, context_score DESC.
    """
    from app.engines.candlestick_patterns import CandlestickPatternEngine

    bias_filter    = bias.upper()
    country_filter = country.upper()

    # ── Fetch stock universe ────────────────────────────────────────────────
    country_clause = ""
    params: dict = {}
    if country_filter != "ALL":
        country_clause = "WHERE country = :country"
        params["country"] = country_filter

    try:
        result = await db.execute(
            text(f"SELECT ticker, country FROM stocks {country_clause} ORDER BY ticker LIMIT 200"),
            params,
        )
        stock_rows = result.fetchall()
    except Exception as exc:
        logger.error("[patterns/scan] DB error: %s", exc)
        raise HTTPException(status_code=500, detail="Database error fetching stocks")

    if not stock_rows:
        return {
            "scan_date":      datetime.now(timezone.utc).strftime("%Y-%m-%d"),
            "total_scanned":  0,
            "patterns_found": 0,
            "results":        [],
        }

    # ── Process in batches of 10 ───────────────────────────────────────────
    BATCH_SIZE   = 10
    all_findings: list[dict] = []
    total_scanned = 0

    async def _scan_ticker(ticker: str, tkr_country: str) -> list[dict]:
        df = await _fetch_ohlcv(ticker, period="60d", interval="1d")
        if df is None or len(df) < 10:
            return []

        engine  = CandlestickPatternEngine(df)
        matches = engine.detect_all(lookback=len(df))

        # Keep only today/yesterday (candle_index 0 or 1)
        recent = [m for m in matches if m["candle_index"] <= 1]

        # Bias filter
        if bias_filter != "ALL":
            recent = [m for m in recent if m["bias"] == bias_filter]

        # Strength filter
        recent = [m for m in recent if m["strength"] >= min_strength]

        findings = []
        for m in recent:
            findings.append({
                "ticker":          ticker,
                "pattern_name":    m["name"],
                "pattern_code":    m["code"],
                "bias":            m["bias"],
                "strength":        m["strength"],
                "context_score":   m["context_score"],
                "context_notes":   m["context_notes"],
                "candle_date":     m["candle_date"],
                "reliability_pct": m["reliability_pct"],
                "entry_suggestion": m["entry_suggestion"],
                "stop_suggestion":  m["stop_suggestion"],
                "volume_confirmed": m["volume_confirmed"],
                "country":         tkr_country or "",
            })
        return findings

    tickers_list = [(row.ticker, row.country) for row in stock_rows]

    for i in range(0, len(tickers_list), BATCH_SIZE):
        batch = tickers_list[i: i + BATCH_SIZE]
        tasks = [_scan_ticker(t, c) for t, c in batch]
        batch_results = await asyncio.gather(*tasks, return_exceptions=True)

        for idx_b, res in enumerate(batch_results):
            if isinstance(res, Exception):
                logger.warning("[patterns/scan] %s failed: %s", batch[idx_b][0], res)
                continue
            total_scanned += 1
            all_findings.extend(res)

    # ── Sort and truncate ─────────────────────────────────────────────────
    all_findings.sort(key=lambda x: (-x["strength"], -x["context_score"]))
    top_findings = all_findings[:limit]

    return {
        "scan_date":      datetime.now(timezone.utc).strftime("%Y-%m-%d"),
        "total_scanned":  total_scanned,
        "patterns_found": len(all_findings),
        "results":        top_findings,
    }


# ── POST /patterns/backtest ───────────────────────────────────────────────────


@router.post("/backtest")
async def pattern_backtest(req: PatternBacktestRequest):
    """
    Backtest a specific candlestick pattern on a ticker.

    Fetches historical OHLCV, detects all occurrences of the pattern, and
    simulates trades with ATR-based stops, 2:1 R/R targets, and a 10-day
    timeout.  Applies India or US transaction cost model.

    Returns full metrics, equity curve, trade list, and monthly returns.
    """
    from app.engines.pattern_backtest import PatternBacktestEngine

    ticker  = req.ticker.strip().upper()
    country = req.country.strip().upper()
    period  = req.period.strip().lower()

    if not ticker:
        raise HTTPException(status_code=422, detail="ticker is required")
    if country not in ("IN", "US"):
        raise HTTPException(status_code=422, detail="country must be 'IN' or 'US'")
    if period not in ("1y", "2y", "5y"):
        raise HTTPException(status_code=422, detail="period must be '1y', '2y', or '5y'")

    logger.info("[patterns/backtest] %s | pattern=%s | period=%s | country=%s",
                ticker, req.pattern_code, period, country)

    df = await _fetch_ohlcv(ticker, period=period, interval="1d")
    if df is None or len(df) < 30:
        raise HTTPException(
            status_code=404,
            detail=f"Insufficient data for {ticker}. "
                   "The ticker may be delisted or data unavailable."
        )

    try:
        engine = PatternBacktestEngine(df, req.pattern_code, country=country, ticker=ticker)
        result = await engine.run()
    except Exception as exc:
        logger.exception("[patterns/backtest] engine error: %s", exc)
        raise HTTPException(status_code=500, detail=f"Backtest failed: {exc}")

    return result


# ── GET /patterns/{ticker} ────────────────────────────────────────────────────


@router.get("/{ticker}")
async def detect_patterns(
    ticker:       str,
    period:       str = Query("3mo", description="3mo | 6mo | 1y"),
    interval:     str = Query("1d",  description="1d | 1wk"),
    lookback:     int = Query(50,    ge=10, le=100, description="Candles to scan"),
    bias:         str = Query("ALL", description="BULLISH | BEARISH | ALL"),
    min_strength: int = Query(1,     ge=1, le=5),
):
    """
    Detect candlestick patterns on a specific stock's recent candles.

    Fetches OHLCV via yfinance (runs in executor), applies the
    CandlestickPatternEngine, then filters by bias and min_strength.

    Returns pattern matches with full metadata including context score,
    volume confirmation, and trade suggestions.
    """
    from app.engines.candlestick_patterns import CandlestickPatternEngine

    ticker_upper = ticker.strip().upper()

    if period not in ("3mo", "6mo", "1y"):
        raise HTTPException(status_code=422, detail="period must be '3mo', '6mo', or '1y'")
    if interval not in ("1d", "1wk"):
        raise HTTPException(status_code=422, detail="interval must be '1d' or '1wk'")

    df = await _fetch_ohlcv(ticker_upper, period=period, interval=interval)
    if df is None or len(df) < 10:
        raise HTTPException(
            status_code=404,
            detail=f"No data found for ticker '{ticker_upper}'. "
                   "It may be delisted or the symbol is incorrect."
        )

    engine  = CandlestickPatternEngine(df)
    matches = engine.detect_all(lookback=lookback)

    # Filter
    bias_upper = bias.upper()
    if bias_upper != "ALL":
        matches = [m for m in matches if m["bias"] == bias_upper]
    matches = [m for m in matches if m["strength"] >= min_strength]

    bullish_count = sum(1 for m in matches if m["bias"] == "BULLISH")
    bearish_count = sum(1 for m in matches if m["bias"] == "BEARISH")

    # Enrich response shape
    patterns_out = []
    for m in matches:
        patterns_out.append({
            "name":             m["name"],
            "code":             m["code"],
            "bias":             m["bias"],
            "category":         m["category"],
            "strength":         m["strength"],
            "reliability_pct":  m["reliability_pct"],
            "candle_date":      m["candle_date"],
            "candle_index":     m["candle_index"],
            "description":      m["description"],
            "entry_suggestion": m["entry_suggestion"],
            "stop_suggestion":  m["stop_suggestion"],
            "context_score":    m["context_score"],
            "context_notes":    m["context_notes"],
            "volume_confirmed": m["volume_confirmed"],
        })

    return {
        "ticker":         ticker_upper,
        "patterns":       patterns_out,
        "total":          len(patterns_out),
        "bullish_count":  bullish_count,
        "bearish_count":  bearish_count,
        "last_updated":   datetime.now(timezone.utc).isoformat(),
    }


# ── GET /patterns/{ticker}/chart-annotations ──────────────────────────────────


@router.get("/{ticker}/chart-annotations")
async def chart_annotations(
    ticker:       str,
    period:       str = Query("3mo", description="3mo | 6mo | 1y"),
    interval:     str = Query("1d",  description="1d | 1wk"),
    lookback:     int = Query(50,    ge=10, le=100),
    min_strength: int = Query(1,     ge=1, le=5),
):
    """
    Return pattern matches formatted as lightweight-charts marker objects for
    candlestick chart overlay.

    Each marker has:
      time     : ISO date string ("YYYY-MM-DD")
      position : "belowBar" (bullish) | "aboveBar" (bearish/neutral)
      color    : green / red / grey
      shape    : "arrowUp" | "arrowDown" | "circle"
      text     : emoji + short name  (e.g. "🔨 Hammer")
      size     : 1 (strength < 4) or 2 (strength >= 4)
    """
    from app.engines.candlestick_patterns import CandlestickPatternEngine

    ticker_upper = ticker.strip().upper()

    df = await _fetch_ohlcv(ticker_upper, period=period, interval=interval)
    if df is None or len(df) < 10:
        raise HTTPException(
            status_code=404,
            detail=f"No data for '{ticker_upper}'."
        )

    engine  = CandlestickPatternEngine(df)
    matches = engine.detect_all(lookback=lookback)
    matches = [m for m in matches if m["strength"] >= min_strength]

    markers = []
    for m in matches:
        bias = m["bias"]

        if bias == "BULLISH":
            position = "belowBar"
            color    = "#22c55e"   # green
            shape    = "arrowUp"
        elif bias == "BEARISH":
            position = "aboveBar"
            color    = "#ef4444"   # red
            shape    = "arrowDown"
        else:
            position = "aboveBar"
            color    = "#94a3b8"   # slate / neutral
            shape    = "circle"

        emoji = _get_emoji(m["code"], m["name"])
        short_name = m["name"]
        size  = 2 if m["strength"] >= 4 else 1

        markers.append({
            "time":     m["candle_date"],
            "position": position,
            "color":    color,
            "shape":    shape,
            "text":     f"{emoji} {short_name}",
            "size":     size,
        })

    # Sort chronologically
    markers.sort(key=lambda x: x["time"])

    return {"markers": markers}
