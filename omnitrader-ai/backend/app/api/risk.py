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

    # ── Sharpe Ratio ──────────────────────────────────────────────────────────
    try:
        rf_res = await db.execute(text("""
            SELECT value FROM macro_data WHERE indicator = 'US10Y'
            ORDER BY time DESC LIMIT 1
        """))
        rf_row = rf_res.fetchone()
        risk_free_annual = float(rf_row.value) / 100 if rf_row else 0.045
        risk_free_daily  = risk_free_annual / 252

        # Use portfolio daily returns (from P&L history or price-weighted returns)
        returns_res = await db.execute(text("""
            SELECT DATE(sp.time) AS d,
                   SUM(sp.close * p.quantity) AS port_value
            FROM stock_prices sp
            JOIN portfolio_positions p ON p.ticker = sp.ticker
            WHERE p.status = 'OPEN' AND sp.time >= NOW() - INTERVAL '252 days'
            GROUP BY DATE(sp.time)
            ORDER BY d
        """))
        port_rows = returns_res.fetchall()

        if len(port_rows) >= 20:
            values = [r.port_value for r in port_rows]
            daily_returns = [(values[i] - values[i-1]) / values[i-1]
                             for i in range(1, len(values)) if values[i-1] > 0]
            if daily_returns:
                mean_r = sum(daily_returns) / len(daily_returns)
                std_r = (sum((r - mean_r)**2 for r in daily_returns) / len(daily_returns))**0.5
                sharpe = ((mean_r - risk_free_daily) / std_r * (252**0.5)) if std_r > 0 else None
            else:
                sharpe = None
        else:
            sharpe = None
            port_rows = []
    except Exception:
        sharpe = None
        port_rows = []

    # ── Beta vs benchmark ─────────────────────────────────────────────────────
    try:
        # Determine dominant market (India vs US) from positions
        country_res = await db.execute(text("""
            SELECT s.country, COUNT(*) as n
            FROM portfolio_positions p
            JOIN stocks s ON s.ticker = p.ticker
            WHERE p.status = 'OPEN'
            GROUP BY s.country ORDER BY n DESC LIMIT 1
        """))
        country_row = country_res.fetchone()
        benchmark = "^NSEI" if (country_row and country_row.country == "IN") else "SPY"

        bench_res = await db.execute(text("""
            SELECT DATE(time) as d, close
            FROM stock_prices
            WHERE ticker = :b AND time >= NOW() - INTERVAL '252 days'
            ORDER BY d
        """), {"b": benchmark})
        bench_rows = bench_res.fetchall()

        if len(bench_rows) >= 20 and len(port_rows) >= 20:
            # Align dates
            bench_map = {r.d: r.close for r in bench_rows}
            port_map  = {r.d: r.port_value for r in port_rows}
            common = sorted(set(bench_map) & set(port_map))

            if len(common) >= 20:
                port_vals  = [port_map[d] for d in common]
                bench_vals = [bench_map[d] for d in common]
                port_ret  = [(port_vals[i]-port_vals[i-1])/port_vals[i-1]  for i in range(1,len(port_vals))  if port_vals[i-1]>0]
                bench_ret = [(bench_vals[i]-bench_vals[i-1])/bench_vals[i-1] for i in range(1,len(bench_vals)) if bench_vals[i-1]>0]
                n = min(len(port_ret), len(bench_ret))
                if n >= 10:
                    cov = sum((port_ret[i]-sum(port_ret)/n)*(bench_ret[i]-sum(bench_ret)/n) for i in range(n)) / n
                    var_b = sum((r-sum(bench_ret)/n)**2 for r in bench_ret) / n
                    beta = cov / var_b if var_b > 0 else None
                else:
                    beta = None
            else:
                beta = None
        else:
            beta = None
    except Exception:
        beta = None
        benchmark = "SPY"

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
        "sharpe_ratio":               round(sharpe, 4) if sharpe is not None else None,
        "beta":                       round(beta, 4) if beta is not None else None,
        "beta_benchmark":             benchmark,
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
