"""
api/charts.py
=============
Chart data API — serves pre-computed OHLCV + indicators in
lightweight-charts compatible format.

Endpoints
---------
GET /charts/ohlcv/{ticker}          — OHLCV + all indicators (SMA/EMA/BB/RSI/MACD/ATR)
GET /charts/annotations/{ticker}    — AI signal markers + entry/stop/target levels
GET /charts/heatmap/sectors         — sector performance heatmap data
GET /charts/heatmap/market          — stock-level heatmap (treemap data)
GET /charts/multi/{ticker}          — multi-timeframe OHLCV (1D/1W/1M/3M in one call)
"""
from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timedelta, timezone
from typing import Optional

import pandas as pd
import yfinance as yf
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import get_db

router = APIRouter()
logger = logging.getLogger(__name__)


# ─── Helper Functions ─────────────────────────────────────────────────────────

def _rsi(s: pd.Series, n: int = 14) -> pd.Series:
    delta = s.diff()
    gain = delta.clip(lower=0).rolling(n).mean()
    loss = (-delta.clip(upper=0)).rolling(n).mean()
    rs = gain / loss.replace(0, 1e-9)
    return 100 - (100 / (1 + rs))

def _macd(s: pd.Series):
    ema12 = s.ewm(span=12, adjust=False).mean()
    ema26 = s.ewm(span=26, adjust=False).mean()
    macd = ema12 - ema26
    signal = macd.ewm(span=9, adjust=False).mean()
    hist = macd - signal
    return macd, signal, hist

def _bollinger(s: pd.Series, n: int = 20, std: float = 2.0):
    mid = s.rolling(n).mean()
    sd = s.rolling(n).std()
    return mid + std * sd, mid, mid - std * sd

def _atr(df: pd.DataFrame, n: int = 14) -> pd.Series:
    h, l, c = df["High"], df["Low"], df["Close"]
    tr = pd.concat([h - l, (h - c.shift()).abs(), (l - c.shift()).abs()], axis=1).max(axis=1)
    return tr.rolling(n).mean()

def _to_tv(series: pd.Series) -> list[dict]:
    """Convert pandas Series (DatetimeIndex) to lightweight-charts [{time, value}] format."""
    out = []
    for ts, v in series.dropna().items():
        if hasattr(ts, 'date'):
            t = ts.date().isoformat()
        else:
            t = str(ts)[:10]
        if pd.notna(v):
            out.append({"time": t, "value": round(float(v), 4)})
    return out

def _fetch_ohlcv(ticker: str, period: str, interval: str) -> pd.DataFrame:
    """Synchronous yfinance fetch — run in executor."""
    df = yf.download(ticker, period=period, interval=interval, progress=False, auto_adjust=True)
    if df is None or len(df) == 0:
        return pd.DataFrame()
    # Flatten multi-level columns if present
    if isinstance(df.columns, pd.MultiIndex):
        df.columns = df.columns.get_level_values(0)
    return df


# ─── Endpoints ────────────────────────────────────────────────────────────────

@router.get("/ohlcv/{ticker}")
async def get_ohlcv(
    ticker: str,
    period: str = Query("1y", description="1mo 3mo 6mo 1y 2y 5y max"),
    interval: str = Query("1d", description="1d 1wk 1mo (intraday: 5m 15m 1h 4h)"),
):
    """
    Returns OHLCV data + full indicator suite ready for lightweight-charts.

    Indicators included (all computed server-side):
      SMA 20, 50, 200 | EMA 9, 21 | Bollinger Bands (20,2) |
      RSI 14 | MACD (12/26/9) | ATR 14 | Volume SMA 20

    Time format: YYYY-MM-DD strings (lightweight-charts native format)
    """
    VALID_PERIODS = {"1mo", "3mo", "6mo", "1y", "2y", "5y", "max"}
    VALID_INTERVALS = {"1d", "1wk", "1mo", "5m", "15m", "30m", "1h", "4h"}
    if period not in VALID_PERIODS:
        raise HTTPException(422, f"Invalid period. Valid: {sorted(VALID_PERIODS)}")
    if interval not in VALID_INTERVALS:
        raise HTTPException(422, f"Invalid interval. Valid: {sorted(VALID_INTERVALS)}")

    try:
        loop = asyncio.get_event_loop()
        df = await loop.run_in_executor(None, _fetch_ohlcv, ticker.upper(), period, interval)
        if df.empty:
            raise HTTPException(404, f"No price data found for {ticker}")

        ohlcv = []
        for ts, row in df.iterrows():
            t = ts.date().isoformat() if hasattr(ts, 'date') else str(ts)[:10]
            ohlcv.append({
                "time":   t,
                "open":   round(float(row["Open"]),   4),
                "high":   round(float(row["High"]),   4),
                "low":    round(float(row["Low"]),    4),
                "close":  round(float(row["Close"]),  4),
                "volume": int(row["Volume"]) if pd.notna(row.get("Volume", 0)) else 0,
            })

        close = df["Close"]
        bb_up, bb_mid, bb_lo = _bollinger(close)
        macd_line, macd_sig, macd_hist = _macd(close)
        indicators = {
            "sma20":        _to_tv(close.rolling(20).mean()),
            "sma50":        _to_tv(close.rolling(50).mean()),
            "sma200":       _to_tv(close.rolling(200).mean()),
            "ema9":         _to_tv(close.ewm(span=9, adjust=False).mean()),
            "ema21":        _to_tv(close.ewm(span=21, adjust=False).mean()),
            "bb_upper":     _to_tv(bb_up),
            "bb_mid":       _to_tv(bb_mid),
            "bb_lower":     _to_tv(bb_lo),
            "rsi":          _to_tv(_rsi(close)),
            "macd_line":    _to_tv(macd_line),
            "macd_signal":  _to_tv(macd_sig),
            "macd_hist":    _to_tv(macd_hist),
            "atr":          _to_tv(_atr(df)),
            "volume_sma20": _to_tv(df["Volume"].rolling(20).mean()),
        }

        latest = df.iloc[-1]
        prev = df.iloc[-2] if len(df) > 1 else df.iloc[-1]
        change = float(latest["Close"]) - float(prev["Close"])
        stats = {
            "current_price": round(float(latest["Close"]), 4),
            "open":          round(float(latest["Open"]),  4),
            "high":          round(float(latest["High"]),  4),
            "low":           round(float(latest["Low"]),   4),
            "volume":        int(latest.get("Volume", 0)),
            "change":        round(change, 4),
            "change_pct":    round(change / float(prev["Close"]) * 100, 4) if float(prev["Close"]) > 0 else 0,
            "week_52_high":  round(float(df["High"].rolling(252).max().iloc[-1]), 4),
            "week_52_low":   round(float(df["Low"].rolling(252).min().iloc[-1]),  4),
        }

        return {
            "ticker":    ticker.upper(),
            "period":    period,
            "interval":  interval,
            "ohlcv":     ohlcv,
            "indicators": indicators,
            "stats":     stats,
            "bar_count": len(ohlcv),
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.exception("get_ohlcv failed for %s: %s", ticker, e)
        raise HTTPException(500, f"Failed to fetch chart data for {ticker}: {e}")


@router.get("/annotations/{ticker}")
async def get_annotations(
    ticker: str,
    days: int = Query(365, ge=30, le=1825),
    db: AsyncSession = Depends(get_db),
):
    """
    AI signal annotations for charting — BUY/SELL markers + price levels.
    Returns markers in lightweight-charts setMarkers() format.
    """
    try:
        since = datetime.now(timezone.utc) - timedelta(days=days)
        result = await db.execute(text("""
            SELECT analysis_date::date as signal_date, signal, final_score,
                   entry_price, stop_loss, take_profit, atr_14, regime
            FROM ai_analysis
            WHERE ticker = :ticker AND analysis_date >= :since
            ORDER BY analysis_date ASC
        """), {"ticker": ticker.upper(), "since": since})
        rows = result.fetchall()

        markers = []
        for r in rows:
            sig = (r.signal or "").upper()
            if sig in ("BUY", "PROACTIVE_SWING"):
                markers.append({
                    "time":     r.signal_date.isoformat(),
                    "position": "belowBar",
                    "color":    "#22c55e",
                    "shape":    "arrowUp",
                    "text":     f"▲ {r.final_score or ''}",
                    "size":     1,
                })
            elif sig in ("SELL", "REDUCE"):
                markers.append({
                    "time":     r.signal_date.isoformat(),
                    "position": "aboveBar",
                    "color":    "#ef4444",
                    "shape":    "arrowDown",
                    "text":     f"▼ {r.final_score or ''}",
                    "size":     1,
                })

        latest_result = await db.execute(text("""
            SELECT signal, final_score, entry_price, stop_loss, take_profit, regime
            FROM ai_analysis
            WHERE ticker = :ticker
            ORDER BY analysis_date DESC LIMIT 1
        """), {"ticker": ticker.upper()})
        latest = latest_result.fetchone()

        current_levels = None
        if latest and latest.entry_price:
            current_levels = {
                "signal": latest.signal,
                "score":  latest.final_score,
                "entry":  round(float(latest.entry_price), 4) if latest.entry_price else None,
                "stop":   round(float(latest.stop_loss), 4) if latest.stop_loss else None,
                "target": round(float(latest.take_profit), 4) if latest.take_profit else None,
                "regime": latest.regime,
            }

        return {
            "ticker":         ticker.upper(),
            "markers":        markers,
            "current_levels": current_levels,
            "signal_count":   len(markers),
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.exception("get_annotations failed for %s: %s", ticker, e)
        raise HTTPException(500, f"Failed to fetch annotations for {ticker}: {e}")


@router.get("/heatmap/sectors")
async def sector_heatmap(
    period: str = Query("1mo", description="1d 1wk 1mo 3mo"),
    country: str = Query("IN", description="IN or US"),
    db: AsyncSession = Depends(get_db),
):
    """
    Sector performance heatmap data.
    Returns each sector's return, stock count, avg AI score, top/worst performers.
    """
    try:
        period_map = {"1d": "5d", "1wk": "1mo", "1mo": "3mo", "3mo": "6mo"}
        yf_period = period_map.get(period, "3mo")

        result = await db.execute(text("""
            SELECT DISTINCT s.sector, s.ticker, s.company_name
            FROM stocks s
            WHERE s.sector IS NOT NULL
              AND s.sector != ''
              AND (:country = '' OR s.country = :country)
            LIMIT 200
        """), {"country": country.upper()})
        rows = result.fetchall()

        sectors: dict[str, list[str]] = {}
        ticker_names: dict[str, str] = {}
        for r in rows:
            sectors.setdefault(r.sector, []).append(r.ticker)
            ticker_names[r.ticker] = r.company_name or r.ticker

        ai_scores: dict[str, float] = {}
        for sector, tickers in sectors.items():
            res = await db.execute(text("""
                SELECT AVG(a.final_score) as avg_score
                FROM ai_analysis a
                JOIN stocks s ON s.ticker = a.ticker
                WHERE s.sector = :sector AND a.analysis_date > now() - interval '30 days'
            """), {"sector": sector})
            row = res.fetchone()
            ai_scores[sector] = round(float(row.avg_score or 50), 1)

        loop = asyncio.get_event_loop()
        sector_returns = {}

        for sector, tickers in sectors.items():
            sample = tickers[:5]
            try:
                def _fetch_batch(tkrs=sample, per=yf_period):
                    data = yf.download(tkrs, period=per, interval="1d", progress=False, auto_adjust=True)
                    return data

                data = await loop.run_in_executor(None, _fetch_batch)

                if data is not None and not data.empty:
                    close = data["Close"] if "Close" in data.columns else data
                    if isinstance(close, pd.Series):
                        close = close.to_frame()
                    returns = {}
                    for t in close.columns:
                        col = close[t].dropna()
                        if len(col) >= 2:
                            r = (col.iloc[-1] / col.iloc[0] - 1) * 100
                            returns[str(t)] = float(r)

                    if returns:
                        avg_ret = sum(returns.values()) / len(returns)
                        best_ticker = max(returns, key=returns.get)
                        worst_ticker = min(returns, key=returns.get)
                        sector_returns[sector] = {
                            "return_pct": round(avg_ret, 2),
                            "best":  {"ticker": best_ticker,  "return_pct": round(returns[best_ticker],  2)},
                            "worst": {"ticker": worst_ticker, "return_pct": round(returns[worst_ticker], 2)},
                        }
            except Exception as e:
                logger.warning("Sector heatmap fetch failed for %s: %s", sector, e)
                sector_returns[sector] = {"return_pct": 0.0, "best": None, "worst": None}

        result_sectors = []
        for sector, tickers in sectors.items():
            ret_data = sector_returns.get(sector, {"return_pct": 0.0})
            result_sectors.append({
                "name":             sector,
                "return_pct":       ret_data.get("return_pct", 0.0),
                "stock_count":      len(tickers),
                "avg_ai_score":     ai_scores.get(sector, 50.0),
                "best_performer":   ret_data.get("best"),
                "worst_performer":  ret_data.get("worst"),
                "color_intensity":  min(abs(ret_data.get("return_pct", 0.0)) / 5.0, 1.0),
            })

        result_sectors.sort(key=lambda x: x["return_pct"], reverse=True)
        return {"period": period, "country": country.upper(), "sectors": result_sectors}
    except HTTPException:
        raise
    except Exception as e:
        logger.exception("sector_heatmap failed: %s", e)
        raise HTTPException(500, f"Failed to fetch sector heatmap: {e}")


@router.get("/heatmap/market")
async def market_heatmap(
    metric: str = Query("return_1d", description="return_1d return_1w return_1mo ai_score"),
    country: str = Query("IN", description="IN or US"),
    limit: int = Query(50, ge=10, le=100),
    db: AsyncSession = Depends(get_db),
):
    """
    Stock-level heatmap for treemap rendering.
    Returns stocks with market_cap (for sizing) and metric value (for color).
    """
    try:
        result = await db.execute(text("""
            SELECT s.ticker, s.company_name, s.sector, s.market_cap,
                   a.signal, a.final_score, a.entry_price
            FROM stocks s
            LEFT JOIN LATERAL (
                SELECT signal, final_score, entry_price
                FROM ai_analysis
                WHERE ticker = s.ticker
                ORDER BY analysis_date DESC LIMIT 1
            ) a ON true
            WHERE (:country = '' OR s.country = :country)
              AND s.market_cap IS NOT NULL
              AND s.market_cap > 0
            ORDER BY s.market_cap DESC
            LIMIT :limit
        """), {"country": country.upper(), "limit": limit})
        rows = result.fetchall()

        tickers = [r.ticker for r in rows]
        period_map = {"return_1d": "5d", "return_1w": "1mo", "return_1mo": "3mo", "ai_score": "5d"}
        yf_period = period_map.get(metric, "5d")

        loop = asyncio.get_event_loop()
        returns_map: dict[str, float] = {}

        if metric != "ai_score" and tickers:
            try:
                def _fetch_all(tkrs=tickers, per=yf_period):
                    data = yf.download(tkrs, period=per, interval="1d", progress=False, auto_adjust=True)
                    return data

                data = await loop.run_in_executor(None, _fetch_all)
                if data is not None and not data.empty:
                    close = data.get("Close", data)
                    if isinstance(close, pd.Series):
                        close = close.to_frame()
                    for t in close.columns:
                        col = close[t].dropna()
                        if len(col) >= 2:
                            returns_map[str(t)] = float((col.iloc[-1] / col.iloc[0] - 1) * 100)
            except Exception as e:
                logger.warning("Market heatmap fetch failed: %s", e)

        stocks = []
        for r in rows:
            if metric == "ai_score":
                value = float(r.final_score or 50)
            else:
                value = returns_map.get(r.ticker, 0.0)

            stocks.append({
                "ticker":     r.ticker,
                "name":       (r.company_name or r.ticker)[:20],
                "sector":     r.sector or "Unknown",
                "market_cap": float(r.market_cap or 0),
                "value":      round(value, 2),
                "signal":     r.signal or "HOLD",
                "ai_score":   int(r.final_score or 50),
            })

        stocks.sort(key=lambda x: x["market_cap"], reverse=True)
        return {"metric": metric, "country": country.upper(), "stocks": stocks, "count": len(stocks)}
    except HTTPException:
        raise
    except Exception as e:
        logger.exception("market_heatmap failed: %s", e)
        raise HTTPException(500, f"Failed to fetch market heatmap: {e}")


@router.get("/multi/{ticker}")
async def multi_timeframe(ticker: str):
    """
    Multi-timeframe OHLCV for the last 60 bars on 4 timeframes: daily, weekly, monthly, 3-monthly.
    Returns all 4 in a single call to minimize round trips.
    """
    loop = asyncio.get_event_loop()

    timeframes = [
        ("1D", "6mo",  "1d"),
        ("1W", "2y",   "1wk"),
        ("1M", "5y",   "1mo"),
    ]

    async def _fetch_tf(label, period, interval):
        df = await loop.run_in_executor(None, _fetch_ohlcv, ticker.upper(), period, interval)
        if df.empty:
            return label, []
        bars = []
        for ts, row in df.tail(80).iterrows():
            t = ts.date().isoformat() if hasattr(ts, 'date') else str(ts)[:10]
            bars.append({
                "time":   t,
                "open":   round(float(row["Open"]),  4),
                "high":   round(float(row["High"]),  4),
                "low":    round(float(row["Low"]),   4),
                "close":  round(float(row["Close"]), 4),
                "volume": int(row.get("Volume", 0)) if pd.notna(row.get("Volume", 0)) else 0,
            })
        return label, bars

    results = await asyncio.gather(*[_fetch_tf(*tf) for tf in timeframes], return_exceptions=True)

    data = {}
    for item in results:
        if isinstance(item, Exception):
            continue
        label, bars = item
        data[label] = bars

    return {"ticker": ticker.upper(), "timeframes": data}
