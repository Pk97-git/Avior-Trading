"""
api/screener.py
===============
Custom stock screener API.

POST /screener/run         — execute screener with given conditions
GET  /screener/fields      — available fields + metadata for UI
GET  /screener/templates   — built-in screener templates
POST /screener/save        — save a custom screener template
GET  /screener/saved       — list saved screener templates
"""
import logging
from typing import Any, List, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import get_db
from app.engines.screener_engine import ScreenerEngine

router = APIRouter()
logger = logging.getLogger(__name__)

# ── In-memory saved screeners (simple persistence) ────────────────────────────
_saved_screeners: list[dict] = []


# ── Pydantic models ────────────────────────────────────────────────────────────

class ScreenerCondition(BaseModel):
    field:    str
    operator: str
    value:    Any  # number, string, list


class ScreenerRequest(BaseModel):
    conditions: List[ScreenerCondition] = []
    limit:      int = 50
    name:       Optional[str] = None


class SavedScreener(BaseModel):
    name:        str
    conditions:  List[ScreenerCondition]
    description: Optional[str] = None


# ── Helpers ───────────────────────────────────────────────────────────────────

def _condition_to_dict(c: ScreenerCondition) -> dict:
    return {"field": c.field, "operator": c.operator, "value": c.value}


# ── Endpoints ─────────────────────────────────────────────────────────────────

@router.post("/run")
async def run_screener(
    body: ScreenerRequest,
    db:   AsyncSession = Depends(get_db),
):
    """
    Execute the screener with the given conditions.
    Returns top matches sorted by AI score descending.
    """
    try:
        engine     = ScreenerEngine(db)
        conditions = [_condition_to_dict(c) for c in body.conditions]
        result     = await engine.run(conditions, limit=body.limit)
        return result
    except Exception as exc:
        logger.error("Screener run failed: %s", exc, exc_info=True)
        raise HTTPException(status_code=500, detail=f"Screener failed: {exc}")


@router.get("/fields")
async def get_fields():
    """
    Return all available screener fields with metadata for building the UI.
    """
    fields = [
        # ── Technical ────────────────────────────────────────────────────────
        {
            "field": "rsi_14",
            "label": "RSI (14)",
            "type": "number",
            "group": "Technical",
            "description": "Relative Strength Index — 14 period",
            "typical_range": [0, 100],
        },
        {
            "field": "rsi_7",
            "label": "RSI (7)",
            "type": "number",
            "group": "Technical",
            "description": "Relative Strength Index — 7 period (faster)",
            "typical_range": [0, 100],
        },
        {
            "field": "macd_hist",
            "label": "MACD Histogram",
            "type": "number",
            "group": "Technical",
            "description": "MACD histogram (12/26/9). Positive = bullish momentum",
            "typical_range": [-5, 5],
        },
        {
            "field": "bb_position",
            "label": "BB Position",
            "type": "number",
            "group": "Technical",
            "description": "Bollinger Band position: 0 = at lower band, 1 = at upper band",
            "typical_range": [0, 1],
        },
        {
            "field": "atr_pct",
            "label": "ATR %",
            "type": "number",
            "group": "Technical",
            "description": "Average True Range as % of price (volatility measure)",
            "typical_range": [0, 10],
        },
        {
            "field": "vol_ratio_20d",
            "label": "Volume Ratio (20d)",
            "type": "number",
            "group": "Technical",
            "description": "Today's volume vs 20-day average. >1.5 = elevated volume",
            "typical_range": [0, 5],
        },
        {
            "field": "sma20_pct",
            "label": "SMA20 %",
            "type": "number",
            "group": "Technical",
            "description": "% price is above (+) or below (-) its 20-day moving average",
            "typical_range": [-20, 20],
        },
        {
            "field": "sma50_pct",
            "label": "SMA50 %",
            "type": "number",
            "group": "Technical",
            "description": "% price is above (+) or below (-) its 50-day moving average",
            "typical_range": [-30, 30],
        },
        {
            "field": "sma200_pct",
            "label": "SMA200 %",
            "type": "number",
            "group": "Technical",
            "description": "% price is above (+) or below (-) its 200-day moving average",
            "typical_range": [-50, 50],
        },
        {
            "field": "week52_high_pct",
            "label": "52W High %",
            "type": "number",
            "group": "Technical",
            "description": "% below 52-week high (0 = at high, -20 = 20% below high)",
            "typical_range": [-60, 0],
        },
        {
            "field": "week52_low_pct",
            "label": "52W Low %",
            "type": "number",
            "group": "Technical",
            "description": "% above 52-week low (0 = at low, 50 = 50% above low)",
            "typical_range": [0, 200],
        },
        {
            "field": "price_change_1d",
            "label": "1-Day Change %",
            "type": "number",
            "group": "Technical",
            "description": "Price change % over the last 1 trading day",
            "typical_range": [-10, 10],
        },
        {
            "field": "price_change_5d",
            "label": "5-Day Change %",
            "type": "number",
            "group": "Technical",
            "description": "Price change % over the last 5 trading days (1 week)",
            "typical_range": [-20, 20],
        },
        {
            "field": "price_change_20d",
            "label": "20-Day Change %",
            "type": "number",
            "group": "Technical",
            "description": "Price change % over the last 20 trading days (1 month)",
            "typical_range": [-30, 30],
        },
        # ── AI / Signal ───────────────────────────────────────────────────────
        {
            "field": "ai_score",
            "label": "AI Score",
            "type": "number",
            "group": "AI / Signal",
            "description": "OmniTrader AI composite score 0–100",
            "typical_range": [0, 100],
        },
        {
            "field": "signal",
            "label": "AI Signal",
            "type": "enum",
            "group": "AI / Signal",
            "description": "Latest AI-generated signal classification",
            "options": [
                "STRONG_BUY", "ACCUMULATE", "HOLD",
                "PROACTIVE_SWING", "AVOID", "DISTRIBUTION", "SELL",
            ],
        },
        # ── Fundamental ───────────────────────────────────────────────────────
        {
            "field": "pe_ratio",
            "label": "P/E Ratio",
            "type": "number",
            "group": "Fundamental",
            "description": "Price-to-earnings ratio (trailing)",
            "typical_range": [0, 100],
        },
        {
            "field": "market_cap_cr",
            "label": "Market Cap (Cr)",
            "type": "number",
            "group": "Fundamental",
            "description": "Market capitalisation in crores (India) or USD millions (US)",
            "typical_range": [0, 1000000],
        },
        {
            "field": "revenue_growth_pct",
            "label": "Revenue Growth %",
            "type": "number",
            "group": "Fundamental",
            "description": "YoY revenue growth percentage",
            "typical_range": [-20, 50],
        },
        {
            "field": "roe",
            "label": "ROE %",
            "type": "number",
            "group": "Fundamental",
            "description": "Return on Equity (%)",
            "typical_range": [0, 50],
        },
        {
            "field": "roic",
            "label": "ROIC %",
            "type": "number",
            "group": "Fundamental",
            "description": "Return on Invested Capital (%) — capital efficiency",
            "typical_range": [0, 40],
        },
        {
            "field": "operating_margin",
            "label": "Operating Margin %",
            "type": "number",
            "group": "Fundamental",
            "description": "Operating profit margin (%)",
            "typical_range": [0, 40],
        },
        {
            "field": "debt_to_equity",
            "label": "Debt / Equity",
            "type": "number",
            "group": "Fundamental",
            "description": "Total debt to shareholders equity ratio",
            "typical_range": [0, 5],
        },
        {
            "field": "eps_surprise_pct",
            "label": "EPS Surprise %",
            "type": "number",
            "group": "Fundamental",
            "description": "Last quarter EPS surprise vs consensus estimate (%)",
            "typical_range": [-20, 30],
        },
        # ── Universe ──────────────────────────────────────────────────────────
        {
            "field": "sector",
            "label": "Sector",
            "type": "string",
            "group": "Universe",
            "description": "Industry sector classification",
        },
        {
            "field": "country",
            "label": "Country",
            "type": "enum",
            "group": "Universe",
            "description": "Country of listing",
            "options": ["IN", "US"],
        },
        {
            "field": "name",
            "label": "Company Name",
            "type": "string",
            "group": "Universe",
            "description": "Full company name (use 'contains' operator for partial match)",
        },
    ]
    return fields


@router.get("/templates")
async def get_templates():
    """Return built-in screener templates."""
    return [
        {
            "name": "Oversold Quality Stocks",
            "description": "RSI oversold + high AI score + strong fundamentals",
            "conditions": [
                {"field": "rsi_14",   "operator": "<", "value": 35},
                {"field": "ai_score", "operator": ">", "value": 65},
                {"field": "roic",     "operator": ">", "value": 12},
            ],
        },
        {
            "name": "Momentum Breakouts",
            "description": "Strong price momentum + above all moving averages",
            "conditions": [
                {"field": "price_change_20d", "operator": ">",  "value": 5},
                {"field": "sma50_pct",        "operator": ">",  "value": 2},
                {"field": "sma200_pct",       "operator": ">",  "value": 5},
                {"field": "vol_ratio_20d",    "operator": ">",  "value": 1.5},
            ],
        },
        {
            "name": "Value Plays",
            "description": "Low PE with strong returns on capital",
            "conditions": [
                {"field": "pe_ratio",      "operator": "<", "value": 15},
                {"field": "roe",           "operator": ">", "value": 15},
                {"field": "debt_to_equity","operator": "<", "value": 1},
            ],
        },
        {
            "name": "AI Strong Buy Universe",
            "description": "All stocks with Strong Buy or Accumulate signal",
            "conditions": [
                {"field": "signal",   "operator": "in", "value": ["STRONG_BUY", "ACCUMULATE"]},
                {"field": "ai_score", "operator": ">",  "value": 70},
            ],
        },
        {
            "name": "Oversold Bounce Setups",
            "description": "RSI deeply oversold near 52-week lows — reversal candidates",
            "conditions": [
                {"field": "rsi_14",        "operator": "<", "value": 30},
                {"field": "week52_low_pct","operator": "<", "value": 15},
                {"field": "vol_ratio_20d", "operator": ">", "value": 1.2},
            ],
        },
        {
            "name": "Indian IT Sector",
            "description": "All Indian IT stocks in universe",
            "conditions": [
                {"field": "country", "operator": "=",        "value": "IN"},
                {"field": "sector",  "operator": "contains", "value": "Technology"},
            ],
        },
    ]


@router.post("/save")
async def save_screener(body: SavedScreener):
    """Save a custom screener template (in-memory)."""
    # Deduplicate by name
    global _saved_screeners
    _saved_screeners = [s for s in _saved_screeners if s["name"] != body.name]
    _saved_screeners.append({
        "name":        body.name,
        "description": body.description,
        "conditions":  [_condition_to_dict(c) for c in body.conditions],
    })
    return {"saved": True, "name": body.name, "total": len(_saved_screeners)}


@router.get("/saved")
async def get_saved_screeners():
    """Return all saved screener templates."""
    return _saved_screeners
