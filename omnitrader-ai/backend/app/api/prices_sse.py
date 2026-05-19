"""
api/prices_sse.py
=================
Server-Sent Events endpoint for live price streaming.

GET /prices/stream?tickers=AAPL,MSFT,...

Streams price updates every 30 seconds for the requested tickers.
Each event carries: ticker, price, change_pct, ts.

Stream terminates after 5 minutes (10 iterations); clients reconnect.
"""
from __future__ import annotations

import asyncio
import json
import logging
from datetime import datetime, timezone
from typing import AsyncGenerator

from fastapi import APIRouter, Depends, Query
from fastapi.responses import StreamingResponse
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import get_db

router = APIRouter()
logger = logging.getLogger(__name__)

_MAX_TICKERS   = 20
_INTERVAL_SECS = 30
_MAX_ITER      = 10   # 10 × 30 s = 5 minutes


async def _price_event_generator(
    tickers: list[str],
    db: AsyncSession,
) -> AsyncGenerator[str, None]:
    """
    Async generator that yields SSE-formatted strings.

    Emits:
      - A keepalive comment every ~15 seconds (halfway through each interval)
      - A data event per ticker every 30 seconds
    """
    iteration = 0

    while iteration < _MAX_ITER:
        # ── Fetch latest close per ticker ─────────────────────────────────────
        try:
            result = await db.execute(
                text("""
                    SELECT DISTINCT ON (ticker) ticker, close, time
                    FROM stock_prices
                    WHERE ticker = ANY(:tickers)
                    ORDER BY ticker, time DESC
                """),
                {"tickers": tickers},
            )
            rows = result.fetchall()
        except Exception as exc:
            logger.warning("[SSE] Price query failed: %s", exc)
            rows = []

        # Build a map for quick lookup of previous close (for change_pct)
        prev_prices: dict[str, float] = {}
        if rows:
            try:
                prev_result = await db.execute(
                    text("""
                        SELECT DISTINCT ON (ticker) ticker, close
                        FROM stock_prices
                        WHERE ticker = ANY(:tickers)
                          AND time < (
                              SELECT MAX(time) FROM stock_prices
                              WHERE ticker = ANY(:tickers)
                          )
                        ORDER BY ticker, time DESC
                    """),
                    {"tickers": tickers},
                )
                for prev_row in prev_result.fetchall():
                    prev_prices[prev_row.ticker] = float(prev_row.close)
            except Exception:
                pass   # change_pct will be 0.0 if unavailable

        # ── Emit events ───────────────────────────────────────────────────────
        now_iso = datetime.now(timezone.utc).isoformat()

        for row in rows:
            ticker     = row.ticker
            price      = float(row.close)
            prev_price = prev_prices.get(ticker, price)

            if prev_price and prev_price != 0:
                change_pct = round(((price - prev_price) / prev_price) * 100, 4)
            else:
                change_pct = 0.0

            payload = json.dumps({
                "ticker":     ticker,
                "price":      round(price, 4),
                "change_pct": change_pct,
                "ts":         now_iso,
            })
            yield f"data: {payload}\n\n"

        iteration += 1

        if iteration >= _MAX_ITER:
            # Signal end-of-stream so the client knows to reconnect
            yield "event: end\ndata: {\"message\": \"stream_end\"}\n\n"
            break

        # ── Wait interval, emitting a keepalive halfway through ───────────────
        await asyncio.sleep(_INTERVAL_SECS / 2)
        yield ": keepalive\n\n"
        await asyncio.sleep(_INTERVAL_SECS / 2)


@router.get("/stream")
async def price_stream(
    tickers: str = Query(..., description="Comma-separated tickers, max 20"),
    db: AsyncSession = Depends(get_db),
):
    """
    SSE stream that emits price updates every 30 seconds.

    Query parameter:
      tickers  — comma-separated ticker symbols (max 20), e.g. AAPL,MSFT,TSLA

    Each event:
      data: {"ticker": "AAPL", "price": 182.34, "change_pct": 1.2, "ts": "..."}

    The stream closes after 5 minutes; clients should reconnect automatically
    (EventSource does this by default).
    """
    # Parse and sanitise tickers
    parsed = [t.strip().upper() for t in tickers.split(",") if t.strip()]
    parsed = list(dict.fromkeys(parsed))   # deduplicate, preserve order
    parsed = parsed[:_MAX_TICKERS]

    if not parsed:
        async def _empty():
            yield ": no tickers provided\n\n"
        return StreamingResponse(
            _empty(),
            media_type="text/event-stream",
            headers={
                "Cache-Control":    "no-cache",
                "X-Accel-Buffering": "no",
            },
        )

    logger.info("[SSE] Opening price stream for %d tickers: %s", len(parsed), parsed)

    return StreamingResponse(
        _price_event_generator(parsed, db),
        media_type="text/event-stream",
        headers={
            "Cache-Control":    "no-cache",
            "X-Accel-Buffering": "no",
        },
    )
