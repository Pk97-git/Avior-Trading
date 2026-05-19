"""
api/sectors.py
==============
Sector rotation REST endpoints backed by SectorRotationEngine.

GET /sectors/rotation         — ranked sectors with rotating-in/out detection
GET /sectors/rotation/history — price history + momentum for a single sector ETF
"""
import logging
from datetime import datetime, timedelta, timezone
from typing import Optional

import yfinance as yf
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import text

from app.db.session import get_db
from app.engines.sector_rotation import SectorRotationEngine

router = APIRouter()
logger = logging.getLogger(__name__)

# ── In-memory cache: stores last-week's rankings so we can detect rotation ─────
# Structure: {"timestamp": datetime, "rankings": [{"etf": str, "rank_4w": int}, ...]}
_last_week_cache: dict = {}
_CACHE_TTL_HOURS = 24 * 7  # refresh the "last week" snapshot after 7 days


def _build_rank_map(rankings: list[dict]) -> dict[str, int]:
    """Return {etf: rank_4w} from a rankings list."""
    return {r["etf"]: r["rank_4w"] for r in rankings}


def _get_cached_last_week() -> Optional[list[dict]]:
    """Return last-week rankings from cache if still valid (< 7 days old)."""
    if not _last_week_cache:
        return None
    age = datetime.now(timezone.utc) - _last_week_cache["timestamp"]
    if age.total_seconds() > _CACHE_TTL_HOURS * 3600:
        return None
    return _last_week_cache.get("rankings")


def _store_last_week(rankings: list[dict]) -> None:
    """Persist current rankings as the 'last week' snapshot."""
    _last_week_cache["timestamp"] = datetime.now(timezone.utc)
    _last_week_cache["rankings"] = [
        {"etf": r["etf"], "sector": r["sector"], "rank_4w": r["rank_4w"]}
        for r in rankings
    ]


# ── Endpoints ──────────────────────────────────────────────────────────────────

@router.get("/rotation")
async def get_sector_rotation(db: AsyncSession = Depends(get_db)):
    """
    Return ranked sector ETFs sorted by 4-week momentum (best first),
    plus rotation signals comparing current ranks to last week's snapshot.
    """
    engine = SectorRotationEngine(db)
    rankings = await engine.calculate()

    # ── Compute composite_score and signal for each sector ────────────────────
    for r in rankings:
        c4  = r.get("change_4w")
        c12 = r.get("change_12w")
        if c4 is not None and c12 is not None:
            composite_score = round(c4 * 0.6 + c12 * 0.4, 2)
        else:
            composite_score = None
        r["composite_score"] = composite_score

        # Signal determination
        if composite_score is None:
            r["signal"] = "NEUTRAL"
        elif composite_score > 5:
            r["signal"] = "BUY"
        elif composite_score < -5:
            r["signal"] = "AVOID"
        else:
            r["signal"] = "HOLD"

    # Sort by composite_score desc (None → end)
    rankings.sort(
        key=lambda x: x["composite_score"] if x["composite_score"] is not None else -9999,
        reverse=True,
    )
    # Re-assign composite rank
    for i, r in enumerate(rankings):
        r["composite_rank"] = i + 1

    # ── Rotation detection via last-week cache ─────────────────────────────────
    last_week = _get_cached_last_week()
    rotating_in:  list[dict] = []
    rotating_out: list[dict] = []

    if last_week:
        last_rank_map = _build_rank_map(last_week)
        for r in rankings:
            etf = r["etf"]
            current_rank = r["rank_4w"]
            prev_rank    = last_rank_map.get(etf)
            if prev_rank is None:
                continue
            delta = prev_rank - current_rank   # positive = improved rank (rotating in)
            r["rank_change"] = delta
            if delta >= 2:
                rotating_in.append({"etf": etf, "sector": r["sector"], "rank_change": delta,
                                     "rank_4w": current_rank, "composite_score": r["composite_score"]})
            elif delta <= -2:
                rotating_out.append({"etf": etf, "sector": r["sector"], "rank_change": delta,
                                      "rank_4w": current_rank, "composite_score": r["composite_score"]})
    else:
        for r in rankings:
            r["rank_change"] = None

    # ── Persist current rankings so they become next call's "last week" ────────
    # Only update the cache if it's empty or older than TTL
    if not _last_week_cache or (
        datetime.now(timezone.utc) - _last_week_cache.get("timestamp", datetime.min.replace(tzinfo=timezone.utc))
    ).total_seconds() > _CACHE_TTL_HOURS * 3600:
        _store_last_week(rankings)

    # ── Slice top/bottom 3 ─────────────────────────────────────────────────────
    scored = [r for r in rankings if r["composite_score"] is not None]
    top_3    = scored[:3]    if len(scored) >= 3 else scored
    bottom_3 = scored[-3:][::-1] if len(scored) >= 3 else scored[::-1]

    return {
        "rankings":        rankings,
        "top_3_sectors":   [{"etf": r["etf"], "sector": r["sector"],
                              "composite_score": r["composite_score"]} for r in top_3],
        "bottom_3_sectors":[{"etf": r["etf"], "sector": r["sector"],
                              "composite_score": r["composite_score"]} for r in bottom_3],
        "rotating_in":     rotating_in,
        "rotating_out":    rotating_out,
        "updated_at":      datetime.now(timezone.utc),
    }


@router.get("/rotation/history")
async def get_sector_history(
    sector_etf: str = Query(..., description="Sector ETF ticker, e.g. XLK"),
    days:       int = Query(90,  ge=7, le=365),
    db:         AsyncSession = Depends(get_db),
):
    """
    Return daily price history for a sector ETF with return % and momentum metrics.
    Tries stock_prices table first; falls back to yfinance if insufficient data.
    """
    ticker = sector_etf.upper()
    since  = datetime.now(timezone.utc) - timedelta(days=days)

    # ── Try DB first ───────────────────────────────────────────────────────────
    price_q = text("""
        SELECT time, close
        FROM stock_prices
        WHERE ticker = :ticker AND time >= :since AND close IS NOT NULL
        ORDER BY time ASC
    """)
    result = await db.execute(price_q, {"ticker": ticker, "since": since})
    rows = result.fetchall()

    prices: list[dict] = []
    if len(rows) >= 10:
        for row in rows:
            prices.append({"date": row.time, "close": row.close, "return_pct": None})
    else:
        # ── Fall back to yfinance ──────────────────────────────────────────────
        logger.info("Sector ETF %s not in DB (got %d rows) — fetching from yfinance", ticker, len(rows))
        try:
            import asyncio
            loop = asyncio.get_event_loop()
            df = await loop.run_in_executor(
                None,
                lambda: yf.download(ticker, period=f"{days}d", interval="1d",
                                    progress=False, auto_adjust=True)
            )
            if df.empty:
                raise HTTPException(status_code=404, detail=f"No price data found for {ticker}")
            for ts, row_data in df.iterrows():
                close_val = float(row_data["Close"]) if hasattr(row_data["Close"], "__float__") else float(row_data["Close"].iloc[0])
                prices.append({
                    "date":       ts.to_pydatetime().replace(tzinfo=timezone.utc),
                    "close":      round(close_val, 4),
                    "return_pct": None,
                })
        except HTTPException:
            raise
        except Exception as exc:
            logger.error("yfinance fetch failed for %s: %s", ticker, exc)
            raise HTTPException(status_code=502, detail=f"Could not retrieve price data for {ticker}: {exc}")

    if not prices:
        raise HTTPException(status_code=404, detail=f"No price data available for {ticker}")

    # ── Compute daily return_pct ───────────────────────────────────────────────
    for i in range(1, len(prices)):
        prev_close = prices[i - 1]["close"]
        if prev_close and prev_close != 0:
            prices[i]["return_pct"] = round((prices[i]["close"] / prev_close - 1) * 100, 4)

    # ── Compute 4-week and 12-week momentum ───────────────────────────────────
    def _momentum(price_list: list[dict], weeks: int) -> Optional[float]:
        if len(price_list) < 2:
            return None
        cutoff = datetime.now(timezone.utc) - timedelta(weeks=weeks)
        old = [p for p in price_list if p["date"] <= cutoff]
        if not old:
            return None
        old_price = old[-1]["close"]
        new_price = price_list[-1]["close"]
        if not old_price:
            return None
        return round((new_price / old_price - 1) * 100, 2)

    momentum_4w  = _momentum(prices, 4)
    momentum_12w = _momentum(prices, 12)

    return {
        "ticker":       ticker,
        "prices":       prices,
        "momentum_4w":  momentum_4w,
        "momentum_12w": momentum_12w,
    }
