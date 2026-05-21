"""
api/stress_testing.py
=====================
POST /stress-test/run     — run stress test on portfolio or custom positions
GET  /stress-test/scenarios — list available scenarios
"""
import logging
from typing import Optional, List
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import get_db
from app.engines.stress_test import run_stress_test, SCENARIOS

router = APIRouter()
logger = logging.getLogger(__name__)


class PositionInput(BaseModel):
    ticker:        str
    shares:        float
    entry_price:   float
    current_price: float
    stop_loss:     Optional[float] = None
    market_value:  Optional[float] = None  # auto-computed if None


class StressTestRequest(BaseModel):
    positions:      List[PositionInput] = []   # if empty, uses DB portfolio
    portfolio_cash: float = Field(0.0, ge=0)
    custom_shock:   Optional[float] = Field(None, ge=-0.9, le=-0.01)
    country:        str = Field("IN")


@router.post("/run")
async def run_stress(req: StressTestRequest, db: AsyncSession = Depends(get_db)):
    """
    Run portfolio stress test. If positions is empty, loads from portfolio DB.
    Fetches price history via yfinance for beta estimation.
    """
    import asyncio
    import yfinance as yf

    positions = [p.model_dump() for p in req.positions]

    # Load from DB if not provided
    if not positions:
        try:
            result = await db.execute(text("""
                SELECT p.ticker, p.shares, p.entry_price, p.current_price,
                       p.stop_loss, p.market_value
                FROM portfolio p
                WHERE p.status = 'OPEN'
            """))
            rows = result.fetchall()
            positions = [
                {
                    "ticker":        r.ticker,
                    "shares":        float(r.shares or 0),
                    "entry_price":   float(r.entry_price or 0),
                    "current_price": float(r.current_price or r.entry_price or 0),
                    "stop_loss":     float(r.stop_loss) if r.stop_loss else None,
                    "market_value":  float(r.market_value) if r.market_value else None,
                }
                for r in rows
            ]
        except Exception as e:
            logger.warning("Could not load portfolio: %s", e)

    if not positions:
        return {"error": "No open positions found. Add positions to your portfolio or provide them in the request."}

    # Fill market_value
    for p in positions:
        if not p.get("market_value"):
            p["market_value"] = p["current_price"] * p["shares"]

    # Fetch price history for beta estimation
    loop = asyncio.get_event_loop()
    tickers = [p["ticker"] for p in positions]
    benchmark = "^NSEI" if req.country == "IN" else "^GSPC"

    async def _fetch(ticker):
        try:
            import pandas as pd
            df = await loop.run_in_executor(None, lambda: yf.download(
                ticker, period="1y", interval="1d", auto_adjust=True, progress=False, threads=False
            ))
            if df is not None and len(df) > 0:
                if isinstance(df.columns, pd.MultiIndex):
                    df.columns = df.columns.get_level_values(0)
                return ticker, df["Close"] if "Close" in df.columns else df.iloc[:, 3]
        except Exception:
            pass
        return ticker, None

    results = await asyncio.gather(*[_fetch(t) for t in tickers + [benchmark]])
    price_history = {t: s for t, s in results if s is not None and t != benchmark}
    mkt_series = next((s for t, s in results if t == benchmark and s is not None), None)

    try:
        stress_result = run_stress_test(
            positions=positions,
            price_history=price_history,
            market_history=mkt_series,
            custom_shock=req.custom_shock,
            portfolio_cash=req.portfolio_cash,
        )
        return stress_result
    except Exception as e:
        logger.exception("Stress test failed: %s", e)
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/scenarios")
async def list_scenarios():
    return {"scenarios": SCENARIOS}
