"""
api/risk.py
===========
Portfolio risk analytics endpoints.

GET /risk/portfolio-risk       — VaR, CVaR, volatility, drawdown, sector/country exposure
GET /risk/correlation-matrix   — return correlations and diversification score
GET /risk/rs-rankings          — IBD-style RS ratings for the universe
GET /risk/rs-rankings/{ticker} — single-ticker RS rating
"""
import logging
from datetime import datetime, timedelta, timezone
from typing import Optional

import numpy as np
import pandas as pd
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import get_db
from app.engines.relative_strength import RelativeStrengthEngine
from app.models.market_data import PortfolioPosition, Stock, StockPrice  # noqa: F401

router = APIRouter()
logger = logging.getLogger(__name__)

_LOOKBACK_DAYS = 90


# ── Helpers ────────────────────────────────────────────────────────────────────

async def _get_open_positions(db: AsyncSession) -> list[tuple]:
    """
    Return all open positions joined with Stock metadata.
    Each row: (PortfolioPosition, name, sector, country)
    """
    stmt = (
        select(PortfolioPosition, Stock.name, Stock.sector, Stock.country)
        .join(Stock, PortfolioPosition.ticker == Stock.ticker, isouter=True)
        .where(PortfolioPosition.is_open == True)  # noqa: E712
    )
    result = await db.execute(stmt)
    return result.fetchall()


async def _fetch_prices_bulk(db: AsyncSession, tickers: list[str], days: int) -> pd.DataFrame:
    """
    Fetch last `days` days of daily closes for all tickers in one query.
    Returns a DataFrame: index=date, columns=tickers.
    """
    since = datetime.now(timezone.utc) - timedelta(days=days)
    price_q = text("""
        SELECT ticker, time, close
        FROM stock_prices
        WHERE ticker = ANY(:tickers)
          AND time >= :since
          AND close IS NOT NULL
        ORDER BY ticker, time
    """)
    result = await db.execute(price_q, {"tickers": tickers, "since": since})
    rows = result.fetchall()

    if not rows:
        return pd.DataFrame()

    df = pd.DataFrame(rows, columns=["ticker", "time", "close"])
    df["time"]  = pd.to_datetime(df["time"], utc=True)
    df["close"] = pd.to_numeric(df["close"], errors="coerce")

    pivot = df.pivot_table(index="time", columns="ticker", values="close", aggfunc="last")
    pivot = pivot.sort_index()
    return pivot


def _compute_var_cvar(returns: np.ndarray, confidence: float) -> tuple[float, float]:
    """
    Historical VaR and CVaR (Expected Shortfall) at given confidence level.
    `returns` is a 1-D array of daily returns (fractions, not percentages).
    VaR is returned as a positive number (loss magnitude).
    """
    if len(returns) < 5:
        return 0.0, 0.0
    cutoff    = np.percentile(returns, (1 - confidence) * 100)
    var       = -cutoff                                          # positive loss
    tail      = returns[returns <= cutoff]
    cvar      = -tail.mean() if len(tail) > 0 else var
    return round(float(var), 6), round(float(cvar), 6)


def _max_drawdown(returns: np.ndarray) -> float:
    """Maximum peak-to-trough drawdown from a series of daily returns (fractions)."""
    if len(returns) == 0:
        return 0.0
    cumulative = np.cumprod(1 + returns)
    running_max = np.maximum.accumulate(cumulative)
    drawdowns   = (cumulative - running_max) / running_max
    return round(float(drawdowns.min()), 6)


# ── Endpoints ──────────────────────────────────────────────────────────────────

@router.get("/portfolio-risk")
async def get_portfolio_risk(db: AsyncSession = Depends(get_db)):
    """
    Compute VaR, CVaR, volatility, drawdown, and exposure breakdowns
    for all open portfolio positions.
    """
    rows = await _get_open_positions(db)
    if not rows:
        return {
            "message":            "No open positions found",
            "position_count":     0,
            "total_portfolio_value": 0.0,
            "var_95":             None,
            "var_99":             None,
            "cvar_95":            None,
            "portfolio_volatility_annualized": None,
            "max_drawdown_90d":   None,
            "sector_exposure":    {},
            "country_exposure":   {},
            "largest_positions":  [],
        }

    tickers = [row[0].ticker for row in rows]
    price_pivot = await _fetch_prices_bulk(db, tickers, _LOOKBACK_DAYS)

    # ── Build position weights ────────────────────────────────────────────────
    pos_values: dict[str, float] = {}
    sector_values: dict[str, float] = {}
    country_values: dict[str, float] = {}
    pos_details: list[dict] = []

    for pos, name, sector, country in rows:
        val = pos.position_value or (pos.entry_price * pos.shares if pos.entry_price and pos.shares else 0.0)
        pos_values[pos.ticker] = pos_values.get(pos.ticker, 0.0) + val

        sec = sector or "Unknown"
        ctr = country or "Unknown"
        sector_values[sec]  = sector_values.get(sec, 0.0) + val
        country_values[ctr] = country_values.get(ctr, 0.0) + val

        pos_details.append({
            "ticker":         pos.ticker,
            "name":           name,
            "sector":         sec,
            "country":        ctr,
            "position_value": round(val, 2),
        })

    total_portfolio_value = sum(pos_values.values())
    if total_portfolio_value == 0:
        total_portfolio_value = 1.0  # avoid division by zero

    # ── Compute daily returns per position ────────────────────────────────────
    returns_df = pd.DataFrame()
    if not price_pivot.empty:
        available_tickers = [t for t in tickers if t in price_pivot.columns]
        if available_tickers:
            returns_df = price_pivot[available_tickers].pct_change().dropna(how="all")

    # ── Portfolio-level daily returns (weighted sum) ──────────────────────────
    portfolio_returns = pd.Series(dtype=float)
    if not returns_df.empty:
        weights = pd.Series({t: pos_values.get(t, 0.0) / total_portfolio_value
                             for t in returns_df.columns})
        portfolio_returns = (returns_df * weights).sum(axis=1).dropna()

    port_arr = portfolio_returns.values if len(portfolio_returns) > 0 else np.array([])

    # ── Risk metrics ──────────────────────────────────────────────────────────
    var_95, cvar_95 = _compute_var_cvar(port_arr, 0.95) if len(port_arr) >= 5 else (None, None)
    var_99, _       = _compute_var_cvar(port_arr, 0.99) if len(port_arr) >= 5 else (None, None)
    vol_annual      = round(float(port_arr.std() * np.sqrt(252)), 6) if len(port_arr) >= 5 else None
    max_dd          = _max_drawdown(port_arr) if len(port_arr) >= 5 else None

    # ── Exposure percentages ──────────────────────────────────────────────────
    sector_exposure  = {k: round(v / total_portfolio_value * 100, 2)
                        for k, v in sector_values.items()}
    country_exposure = {k: round(v / total_portfolio_value * 100, 2)
                        for k, v in country_values.items()}

    # ── Top 5 positions by value ──────────────────────────────────────────────
    largest_positions = sorted(pos_details, key=lambda x: x["position_value"], reverse=True)[:5]

    return {
        "position_count":             len(rows),
        "total_portfolio_value":      round(total_portfolio_value, 2),
        "var_95":                     var_95,
        "var_99":                     var_99,
        "cvar_95":                    cvar_95,
        "portfolio_volatility_annualized": vol_annual,
        "max_drawdown_90d":           max_dd,
        "sector_exposure":            sector_exposure,
        "country_exposure":           country_exposure,
        "largest_positions":          largest_positions,
        "data_points":                int(len(port_arr)),
        "updated_at":                 datetime.now(timezone.utc),
    }


@router.get("/correlation-matrix")
async def get_correlation_matrix(db: AsyncSession = Depends(get_db)):
    """
    Compute return correlation matrix for all open positions.
    Also identifies highly correlated pairs (|corr| > 0.70) and a
    diversification score (1 − mean absolute off-diagonal correlation).
    """
    rows = await _get_open_positions(db)
    if len(rows) < 2:
        raise HTTPException(
            status_code=400,
            detail="Need at least 2 open positions to compute a correlation matrix.",
        )

    tickers = list({row[0].ticker for row in rows})
    price_pivot = await _fetch_prices_bulk(db, tickers, _LOOKBACK_DAYS)

    if price_pivot.empty:
        raise HTTPException(status_code=404, detail="No price data found for open positions.")

    available = [t for t in tickers if t in price_pivot.columns]
    if len(available) < 2:
        raise HTTPException(
            status_code=400,
            detail="Insufficient price history for at least 2 tickers.",
        )

    returns_df = price_pivot[available].pct_change().dropna(how="all")
    if len(returns_df) < 5:
        raise HTTPException(status_code=400, detail="Not enough return observations (need >= 5 days).")

    corr_matrix = returns_df.corr()
    ticker_list = list(corr_matrix.columns)
    matrix_values = [[round(float(v), 4) for v in row] for row in corr_matrix.values]

    # ── High correlations (|corr| > 0.70, off-diagonal pairs) ─────────────────
    high_corrs: list[dict] = []
    n = len(ticker_list)
    for i in range(n):
        for j in range(i + 1, n):
            c = float(corr_matrix.iloc[i, j])
            if abs(c) > 0.70:
                high_corrs.append({
                    "ticker_a":    ticker_list[i],
                    "ticker_b":    ticker_list[j],
                    "correlation": round(c, 4),
                })
    high_corrs.sort(key=lambda x: abs(x["correlation"]), reverse=True)

    # ── Diversification score ─────────────────────────────────────────────────
    # 1 - mean(|off-diagonal correlations|)
    off_diag: list[float] = []
    for i in range(n):
        for j in range(n):
            if i != j:
                off_diag.append(abs(float(corr_matrix.iloc[i, j])))
    div_score = round(1.0 - (sum(off_diag) / len(off_diag)), 4) if off_diag else 1.0

    return {
        "tickers":             ticker_list,
        "matrix":              matrix_values,
        "high_correlations":   high_corrs,
        "diversification_score": div_score,
        "updated_at":          datetime.now(timezone.utc),
    }


@router.get("/rs-rankings")
async def get_rs_rankings(
    country: str           = Query("ALL", description="Country filter: US, IN, or ALL"),
    sector:  Optional[str] = Query(None,  description="Filter by sector name"),
    limit:   int           = Query(100,   ge=1, le=1000),
    db:      AsyncSession  = Depends(get_db),
):
    """
    Return IBD-style RS Ratings for all stocks in the universe (or a subset).
    RS Rating 99 = top performer, 1 = worst performer.
    """
    engine = RelativeStrengthEngine(db)
    try:
        ratings = await engine.compute_rs_ratings(country=country)
    except Exception as exc:
        logger.error("RS rating computation failed: %s", exc)
        raise HTTPException(status_code=500, detail=f"RS computation failed: {exc}")

    if sector:
        sector_upper = sector.upper()
        ratings = [r for r in ratings if (r.get("sector") or "").upper() == sector_upper]

    ratings = ratings[:limit]

    return {
        "total":   len(ratings),
        "country": country,
        "sector":  sector,
        "items":   ratings,
    }


@router.get("/rs-rankings/{ticker}")
async def get_ticker_rs_ranking(
    ticker: str,
    db:     AsyncSession = Depends(get_db),
):
    """
    Return the RS Rating for a single ticker, including its percentile rank
    and quarterly return breakdown.
    """
    ticker = ticker.upper()
    engine = RelativeStrengthEngine(db)
    try:
        result = await engine.get_ticker_rs(ticker)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    except Exception as exc:
        logger.error("RS rating for %s failed: %s", ticker, exc)
        raise HTTPException(status_code=500, detail=f"RS computation failed: {exc}")

    return result
