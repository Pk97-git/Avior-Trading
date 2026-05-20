"""
api/intelligence.py
===================
Trade Intelligence API — decision-ready trade setups for human approval.

Endpoints
---------
GET  /opportunities              — list active setups (filterable, paginated)
GET  /opportunities/{ticker}     — full TradeBrief for a ticker
POST /opportunities/{ticker}/execute — place the recommended trade
POST /opportunities/{ticker}/skip    — mark setup as SKIPPED
POST /scan                       — trigger a fresh market scan (async)
GET  /daily-brief                — top 5 SWING + top 3 LONG_TERM setups
GET  /analyze/{ticker}           — on-demand deep-dive TradeBrief (no DB)
"""
import asyncio
import logging
from datetime import datetime
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Body
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import get_db
from app.engines.trade_scanner import TradeScanner
from app.engines.trade_analyzer import TradeAnalyzer

router = APIRouter()
logger = logging.getLogger(__name__)


@router.get("/opportunities")
async def list_opportunities(
    trade_type: Optional[str] = Query(None, description="SWING | LONG_TERM"),
    min_confidence: int = Query(50, ge=0, le=100),
    verdict: Optional[str] = Query(None, description="BUY | WAIT | SKIP | EXECUTE"),
    limit: int = Query(20, ge=1, le=50),
    db: AsyncSession = Depends(get_db),
):
    """
    List active trade opportunities sorted by conviction score.
    """
    try:
        where_clauses = [
            "status = 'ACTIVE'",
            "expires_at > now()",
            "confidence >= :min_confidence",
        ]
        params: dict = {"min_confidence": min_confidence, "limit": limit}

        if trade_type:
            where_clauses.append("trade_type = :trade_type")
            params["trade_type"] = trade_type.upper()

        if verdict:
            where_clauses.append("verdict = :verdict")
            params["verdict"] = verdict.upper()

        where_sql = " AND ".join(where_clauses)
        sql = text(
            f"SELECT * FROM trade_opportunities WHERE {where_sql} "
            f"ORDER BY confidence DESC LIMIT :limit"
        )
        result = await db.execute(sql, params)
        rows = [dict(r._mapping) for r in result.fetchall()]
        return {
            "opportunities": rows,
            "count": len(rows),
            "filters": {
                "trade_type": trade_type,
                "min_confidence": min_confidence,
                "verdict": verdict,
                "limit": limit,
            },
        }
    except Exception as exc:
        logger.exception("[Intelligence] list_opportunities failed: %s", exc)
        raise HTTPException(status_code=500, detail=str(exc))


@router.get("/opportunities/{ticker}")
async def get_opportunity(
    ticker: str,
    db: AsyncSession = Depends(get_db),
):
    """
    Get the stored trade setup for a specific ticker.
    For a fresh on-demand analysis use /analyze/{ticker} instead.
    """
    result = await db.execute(
        text(
            "SELECT * FROM trade_opportunities "
            "WHERE ticker = :t AND status = 'ACTIVE' "
            "ORDER BY confidence DESC LIMIT 1"
        ),
        {"t": ticker.upper()},
    )
    row = result.fetchone()
    if not row:
        raise HTTPException(status_code=404, detail=f"No active opportunity found for {ticker}")
    return dict(row._mapping)


@router.post("/scan")
async def trigger_scan(
    db: AsyncSession = Depends(get_db),
):
    """
    Trigger a fresh market scan. Runs asynchronously — returns immediately
    with a job token; use GET /opportunities to see results after ~60s.
    """
    asyncio.create_task(TradeScanner(db).run_scan())
    return {
        "status": "scan_started",
        "message": "Scanning universe. Results available in ~60s via GET /opportunities",
    }


@router.post("/opportunities/{ticker}/execute")
async def execute_opportunity(
    ticker: str,
    qty: Optional[float] = Body(None, description="Override quantity (uses suggested_qty from brief if omitted)"),
    notes: Optional[str] = Body(None),
    db: AsyncSession = Depends(get_db),
):
    """
    Execute the recommended trade for a ticker.
    Places a limit order at entry_price using the order manager.
    """
    try:
        result = await db.execute(
            text(
                "SELECT * FROM trade_opportunities "
                "WHERE ticker = :t AND status = 'ACTIVE' "
                "ORDER BY confidence DESC LIMIT 1"
            ),
            {"t": ticker.upper()},
        )
        row = result.fetchone()
        if not row:
            raise HTTPException(status_code=404, detail=f"No active opportunity found for {ticker}")

        row = dict(row._mapping)

        # Determine quantity
        signals = row.get("signals") or {}
        suggested_qty = signals.get("suggested_qty") if isinstance(signals, dict) else None
        final_qty = qty or suggested_qty or 1

        from app.services.order_manager import OrderManager
        mgr = OrderManager(db)
        order_result = await mgr.submit_order(
            ticker=ticker.upper(),
            side="BUY",
            qty=final_qty,
            order_type="LIMIT",
            limit_price=row["entry_price"],
            notes=notes or f"Trade Intelligence: {row['setup_name']}",
        )

        # Update status to EXECUTED
        await db.execute(
            text(
                "UPDATE trade_opportunities SET status='EXECUTED', updated_at=now() "
                "WHERE ticker = :t AND trade_type = :tt"
            ),
            {"t": ticker.upper(), "tt": row["trade_type"]},
        )
        await db.commit()

        return {
            "executed": True,
            "ticker": ticker.upper(),
            "order": order_result,
            "brief_summary": {
                "setup_name": row.get("setup_name"),
                "verdict": row.get("verdict"),
                "entry_price": row.get("entry_price"),
                "stop_price": row.get("stop_price"),
                "target_price": row.get("target_price"),
                "risk_reward": row.get("risk_reward"),
                "confidence": row.get("confidence"),
            },
        }
    except HTTPException:
        raise
    except Exception as exc:
        logger.exception("[Intelligence] execute_opportunity failed for %s: %s", ticker, exc)
        raise HTTPException(status_code=500, detail=str(exc))


@router.post("/opportunities/{ticker}/skip")
async def skip_opportunity(
    ticker: str,
    trade_type: Optional[str] = Body(None),
    db: AsyncSession = Depends(get_db),
):
    """Mark a trade opportunity as SKIPPED."""
    if trade_type:
        await db.execute(
            text(
                "UPDATE trade_opportunities SET status='SKIPPED', updated_at=now() "
                "WHERE ticker = :t AND trade_type = :tt"
            ),
            {"t": ticker.upper(), "tt": trade_type.upper()},
        )
    else:
        await db.execute(
            text(
                "UPDATE trade_opportunities SET status='SKIPPED', updated_at=now() "
                "WHERE ticker = :t"
            ),
            {"t": ticker.upper()},
        )
    await db.commit()
    return {"skipped": True, "ticker": ticker.upper()}


@router.get("/daily-brief")
async def daily_brief(
    db: AsyncSession = Depends(get_db),
):
    """
    Today's curated trade ideas: top 5 SWING + top 3 LONG_TERM.
    The zero-effort morning digest — read it, decide, execute or skip.
    """
    swing = await db.execute(text(
        "SELECT * FROM trade_opportunities WHERE status='ACTIVE' AND expires_at > now() "
        "AND trade_type='SWING' ORDER BY confidence DESC LIMIT 5"
    ))
    long_term = await db.execute(text(
        "SELECT * FROM trade_opportunities WHERE status='ACTIVE' AND expires_at > now() "
        "AND trade_type='LONG_TERM' ORDER BY confidence DESC LIMIT 3"
    ))
    swing_rows = [dict(r._mapping) for r in swing.fetchall()]
    lt_rows    = [dict(r._mapping) for r in long_term.fetchall()]

    return {
        "date": datetime.utcnow().date().isoformat(),
        "swing_trades": swing_rows,
        "long_term_picks": lt_rows,
        "total_active": len(swing_rows) + len(lt_rows),
        "message": (
            "Your daily brief is ready. Review each setup — entry, stop, target, and thesis are pre-computed. "
            "Your job: execute or skip."
        ),
    }


@router.get("/analyze/{ticker}")
async def analyze_ticker(
    ticker: str,
    trade_type: str = Query("SWING", description="SWING | LONG_TERM"),
    db: AsyncSession = Depends(get_db),
):
    """
    On-demand deep analysis for any ticker. Fetches fresh data and returns
    a full TradeBrief — entry, stop, target, thesis, risk metrics, fundamentals.
    This does NOT require the ticker to be in the opportunities table.
    """
    try:
        analyzer = TradeAnalyzer(db)
        brief = await analyzer.analyze(ticker=ticker.upper(), trade_type=trade_type.upper())
        return brief
    except Exception as exc:
        logger.exception("[Intelligence] analyze failed for %s: %s", ticker, exc)
        raise HTTPException(status_code=500, detail=str(exc))
