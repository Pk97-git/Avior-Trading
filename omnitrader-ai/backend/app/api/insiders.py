"""
api/insiders.py
===============
Insider transaction endpoints.

GET /insiders/recent       — recent insider buys/sells across the universe
GET /insiders/stats/universe — aggregate activity stats
GET /insiders/{ticker}     — full transaction history for one ticker
"""
import logging
from datetime import datetime, timedelta, timezone
from typing import Optional

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, text

from app.db.session import get_db
from app.models.market_data import InsiderTransaction, Stock

router = APIRouter()
logger = logging.getLogger(__name__)

# ── Helpers ────────────────────────────────────────────────────────────────────

_BULLISH_GRADES = {"buy", "strong buy", "overweight", "outperform", "accumulate", "positive"}
_BEARISH_GRADES = {"sell", "strong sell", "underweight", "underperform", "negative"}


def _compute_signal(transactions: list[dict]) -> str:
    """Derive a trading signal from a list of insider transaction dicts."""
    purchases = [t for t in transactions if t["transaction_type"] == "P"]
    sales     = [t for t in transactions if t["transaction_type"] == "S"]

    if not purchases and sales:
        return "SELL_SIGNAL"

    # Count distinct insiders purchasing within 30 days
    cutoff = datetime.now(timezone.utc) - timedelta(days=30)
    recent_buyers = {
        t["insider_name"]
        for t in purchases
        if t.get("filed_date") and t["filed_date"] >= cutoff
    }
    if len(recent_buyers) >= 3:
        return "STRONG_BUY_SIGNAL"
    if len(recent_buyers) >= 1:
        return "BUY_SIGNAL"
    return "BUY_SIGNAL" if purchases else "SELL_SIGNAL"


def _row_to_txn(row) -> dict:
    filed_date = row.filed_date
    if filed_date and hasattr(filed_date, "astimezone"):
        filed_date = filed_date.astimezone(timezone.utc)
    return {
        "filed_date":       filed_date,
        "insider_name":     row.insider_name,
        "insider_role":     row.insider_role,
        "transaction_type": row.transaction_type,
        "shares":           row.shares,
        "price_per_share":  row.price_per_share,
        "total_value":      row.total_value,
    }


# ── GET /recent ────────────────────────────────────────────────────────────────

@router.get("/recent")
async def get_recent_insiders(
    country:   str           = Query("US",    description="Country filter: US, IN, or ALL"),
    days:      int           = Query(14,      ge=1, le=90),
    min_value: float         = Query(50000,   ge=0),
    action:    str           = Query("P",     description="P=purchase, S=sale, all=both"),
    db:        AsyncSession  = Depends(get_db),
):
    """
    Return top 50 tickers grouped with recent insider activity.
    Includes a signal field per ticker.
    """
    since = datetime.now(timezone.utc) - timedelta(days=days)

    # Build query with stock join
    stmt = (
        select(InsiderTransaction, Stock.sector, Stock.country, Stock.name)
        .join(Stock, Stock.ticker == InsiderTransaction.ticker)
        .where(InsiderTransaction.filed_date >= since)
        .where(InsiderTransaction.total_value >= min_value)
    )

    if action.upper() != "ALL":
        stmt = stmt.where(InsiderTransaction.transaction_type == action.upper())

    if country.upper() != "ALL":
        stmt = stmt.where(Stock.country == country.upper())

    stmt = stmt.order_by(InsiderTransaction.filed_date.desc())

    result = await db.execute(stmt)
    rows = result.fetchall()

    # Group by ticker
    grouped: dict[str, dict] = {}
    for row in rows:
        txn_obj, sector, stk_country, stk_name = row
        ticker = txn_obj.ticker

        if ticker not in grouped:
            grouped[ticker] = {
                "ticker":       ticker,
                "name":         stk_name,
                "sector":       sector,
                "country":      stk_country,
                "transactions": [],
            }

        txn_dict = _row_to_txn(txn_obj)
        grouped[ticker]["transactions"].append(txn_dict)

    # Add signal to each group and cap at 50 tickers
    output = []
    for item in list(grouped.values())[:50]:
        item["signal"] = _compute_signal(item["transactions"])
        output.append(item)

    return output


# ── GET /stats/universe — must be before /{ticker} ────────────────────────────

@router.get("/stats/universe")
async def get_universe_stats(db: AsyncSession = Depends(get_db)):
    """
    Aggregate insider activity across the full universe for the last 30 days.
    Returns most-bought, most-sold, and cluster-buy tickers.
    """
    since = datetime.now(timezone.utc) - timedelta(days=30)

    # Most bought: top 10 by total buy value
    buy_query = text("""
        SELECT ticker, SUM(total_value) AS total_buy_value
        FROM insider_transactions
        WHERE transaction_type = 'P'
          AND filed_date >= :since
          AND total_value IS NOT NULL
        GROUP BY ticker
        ORDER BY total_buy_value DESC
        LIMIT 10
    """)
    buy_res = await db.execute(buy_query, {"since": since})
    most_bought = [
        {"ticker": r.ticker, "total_buy_value": r.total_buy_value}
        for r in buy_res.fetchall()
    ]

    # Most sold: top 10 by total sell value
    sell_query = text("""
        SELECT ticker, SUM(total_value) AS total_sell_value
        FROM insider_transactions
        WHERE transaction_type = 'S'
          AND filed_date >= :since
          AND total_value IS NOT NULL
        GROUP BY ticker
        ORDER BY total_sell_value DESC
        LIMIT 10
    """)
    sell_res = await db.execute(sell_query, {"since": since})
    most_sold = [
        {"ticker": r.ticker, "total_sell_value": r.total_sell_value}
        for r in sell_res.fetchall()
    ]

    # Cluster buys: tickers with 3+ distinct insiders buying in last 30 days
    cluster_query = text("""
        SELECT ticker, COUNT(DISTINCT insider_name) AS buyer_count
        FROM insider_transactions
        WHERE transaction_type = 'P'
          AND filed_date >= :since
        GROUP BY ticker
        HAVING COUNT(DISTINCT insider_name) >= 3
        ORDER BY buyer_count DESC
    """)
    cluster_res = await db.execute(cluster_query, {"since": since})
    cluster_buys = [
        {"ticker": r.ticker, "distinct_buyers": r.buyer_count}
        for r in cluster_res.fetchall()
    ]

    return {
        "most_bought":  most_bought,
        "most_sold":    most_sold,
        "cluster_buys": cluster_buys,
    }


# ── GET /{ticker} ──────────────────────────────────────────────────────────────

@router.get("/{ticker}")
async def get_ticker_insiders(
    ticker: str,
    db:     AsyncSession = Depends(get_db),
):
    """
    Full insider transaction history for a single ticker (last 90 days).
    Includes a summary with buy/sell counts, net value, and signal.
    """
    ticker = ticker.upper()
    since  = datetime.now(timezone.utc) - timedelta(days=90)

    stmt = (
        select(InsiderTransaction)
        .where(InsiderTransaction.ticker == ticker)
        .where(InsiderTransaction.filed_date >= since)
        .order_by(InsiderTransaction.filed_date.desc())
    )
    result = await db.execute(stmt)
    txn_objs = result.scalars().all()

    transactions = [_row_to_txn(t) for t in txn_objs]

    purchases = [t for t in transactions if t["transaction_type"] == "P"]
    sales     = [t for t in transactions if t["transaction_type"] == "S"]

    buy_value  = sum(t["total_value"] or 0 for t in purchases)
    sell_value = sum(t["total_value"] or 0 for t in sales)

    signal = _compute_signal(transactions)

    return {
        "ticker":       ticker,
        "transactions": transactions,
        "summary": {
            "buy_count":  len(purchases),
            "sell_count": len(sales),
            "net_value":  round(buy_value - sell_value, 2),
            "signal":     signal,
        },
    }
