"""
api/position_sizing.py
======================
POST /position-size/calculate  — compute Kelly + fixed risk position size
GET  /position-size/explain    — plain-English guide to position sizing
"""
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field
from typing import Optional
from app.engines.position_sizer import compute_position_size

router = APIRouter()


class SizeRequest(BaseModel):
    portfolio_value: float = Field(..., gt=0, description="Total portfolio in ₹ or $")
    entry_price:     float = Field(..., gt=0)
    stop_loss:       float = Field(..., gt=0)
    take_profit:     float = Field(..., gt=0)
    win_rate:        float = Field(0.55, ge=0.01, le=0.99, description="Historical win rate 0-1")
    max_risk_pct:    float = Field(2.0,  ge=0.5,  le=5.0,  description="Max % of portfolio to risk")
    country:         str   = Field("IN")


@router.post("/calculate")
async def calculate_position_size(req: SizeRequest):
    try:
        result = compute_position_size(
            portfolio_value=req.portfolio_value,
            entry_price=req.entry_price,
            stop_loss=req.stop_loss,
            take_profit=req.take_profit,
            win_rate=req.win_rate,
            max_risk_pct=req.max_risk_pct,
            country=req.country,
        )
        # Convert dataclass to dict
        import dataclasses
        return dataclasses.asdict(result)
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/explain")
async def explain_position_sizing():
    return {
        "title": "How Position Sizing Works",
        "summary": "Position sizing answers: 'How much money should I put into this trade?' It's the most important decision in trading — more important than entry timing.",
        "methods": [
            {
                "name": "Kelly Criterion",
                "formula": "f* = Win Rate - (1 - Win Rate) / (Reward/Risk)",
                "use_case": "Mathematically optimal fraction of capital to deploy",
                "caution": "Full Kelly is volatile. Professionals use Half Kelly."
            },
            {
                "name": "Fixed 2% Risk Rule",
                "formula": "Shares = (Portfolio × 2%) / (Entry - Stop)",
                "use_case": "Never risk more than 2% of total portfolio on one trade",
                "caution": "Conservative but reliable. Standard at most funds."
            },
            {
                "name": "Recommended: min(Half Kelly, 2% Risk)",
                "formula": "Take the smaller of the two methods",
                "use_case": "Captures Kelly's mathematical edge while protecting downside",
                "caution": "This is what OmniTrader recommends."
            }
        ],
        "key_insight": "If you risk the same fixed % on every trade, a string of losses can never blow up your account. This is why professionals survive when retail traders don't."
    }
