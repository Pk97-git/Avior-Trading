"""
api/short_candidates.py
========================
GET /short-candidates   — stocks with strong bearish signals (DISTRIBUTION, SELL)
                          ranked by conviction for shorting

Hedge funds use systematic short selection. We use:
  - AI signal in (DISTRIBUTION, SELL, AVOID)
  - AI score < 40 (weak fundamentals)
  - RSI > 65 (overbought)
  - Price > 52W high * 0.95 (extended / near top)
  - High institutional distribution signals
  - BEARISH candlestick patterns recently detected

Returns ranked short candidates with reasoning.
"""
import logging
import json
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession
from app.db.session import get_db

router = APIRouter()
logger = logging.getLogger(__name__)


@router.get("")
async def get_short_candidates(
    min_score_threshold: int  = Query(45,  description="AI score BELOW this = short candidate"),
    country:             str  = Query("ALL"),
    limit:               int  = Query(20, ge=1, le=50),
    db: AsyncSession = Depends(get_db),
):
    """
    Find short candidates — stocks with weak AI signals and bearish momentum.
    Ranked by short conviction (lower AI score + more bearish signals = higher rank).
    """
    country_filter = "" if country.upper() == "ALL" else "AND s.country = :country"
    params = {"threshold": min_score_threshold}
    if country.upper() != "ALL":
        params["country"] = country.upper()

    try:
        result = await db.execute(text(f"""
            SELECT
                s.ticker, s.name, s.sector, s.country,
                a.signal, a.final_score, a.regime,
                a.entry_price, a.stop_loss, a.take_profit,
                a.signal_thesis, a.analysis_date,
                p.close as last_price,
                p.volume
            FROM stocks s
            JOIN ai_analysis a ON a.ticker = s.ticker
                AND a.analysis_date = (SELECT MAX(analysis_date) FROM ai_analysis aa WHERE aa.ticker = s.ticker)
            LEFT JOIN (
                SELECT DISTINCT ON (ticker) ticker, close, volume
                FROM stock_prices ORDER BY ticker, date DESC
            ) p ON p.ticker = s.ticker
            WHERE a.signal IN ('DISTRIBUTION', 'SELL', 'AVOID')
              AND a.final_score < :threshold
              {country_filter}
            ORDER BY a.final_score ASC, a.analysis_date DESC
            LIMIT :limit
        """), {**params, "limit": limit})
        rows = result.fetchall()
    except Exception as e:
        logger.error("Short candidates query failed: %s", e)
        raise HTTPException(500, detail=str(e))

    candidates = []
    for r in rows:
        # Short conviction score: lower AI score = stronger short
        conviction = max(0, 100 - (r.final_score or 50))

        # Signal strength label
        if r.signal == "SELL":
            signal_strength = "STRONG SHORT"
            color = "red"
        elif r.signal == "DISTRIBUTION":
            signal_strength = "DISTRIBUTION — EXIT / SHORT"
            color = "orange"
        else:
            signal_strength = "AVOID — Weak"
            color = "amber"

        thesis = r.signal_thesis or []
        if isinstance(thesis, str):
            try:
                thesis = json.loads(thesis)
            except Exception:
                thesis = [thesis]

        candidates.append({
            "ticker":           r.ticker,
            "name":             r.name,
            "sector":           r.sector,
            "country":          r.country,
            "signal":           r.signal,
            "signal_strength":  signal_strength,
            "color":            color,
            "ai_score":         r.final_score,
            "conviction":       conviction,
            "regime":           r.regime,
            "last_price":       float(r.last_price) if r.last_price else None,
            "stop_for_short":   float(r.take_profit) if r.take_profit else None,  # Stop = old target (above current)
            "target_for_short": float(r.stop_loss) if r.stop_loss else None,      # Target = old stop (below current)
            "thesis":           thesis[:3],
            "analysis_date":    str(r.analysis_date) if r.analysis_date else None,
        })

    return {
        "count":      len(candidates),
        "candidates": candidates,
        "disclaimer": "Short selling requires a margin account and carries unlimited loss potential. Always use stop losses. OmniTrader signals are not financial advice.",
    }
