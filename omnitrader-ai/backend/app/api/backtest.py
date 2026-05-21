"""
api/backtest.py
===============
Backtest API endpoints.

POST /backtest/run          — full historical backtest using ai_analysis signals
GET  /backtest/quick-stats  — 90-day P&L estimate from stored entry/stop/target levels
"""
from __future__ import annotations

import logging
from datetime import date, datetime, timedelta, timezone
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import get_db
from app.engines.backtest import BacktestEngine
from app.engines.strategy_backtest import (
    StrategyBacktestEngine,
    ALL_STRATEGIES,
    STRATEGY_DESCRIPTIONS,
)

router = APIRouter()
logger = logging.getLogger(__name__)


# ── Request / Response Models ──────────────────────────────────────────────────


class BacktestRequest(BaseModel):
    start_date:     date                = Field(..., description="Backtest start date (YYYY-MM-DD)")
    end_date:       date                = Field(..., description="Backtest end date (YYYY-MM-DD)")
    initial_capital: float             = Field(100_000.0, ge=1_000, description="Starting portfolio cash")
    signal_filter:  List[str]          = Field(
        default=["BUY"],
        description="Signals that trigger entry",
    )
    max_positions:  int                 = Field(10, ge=1, le=100, description="Max concurrent positions")
    max_hold_days:  int                 = Field(30, ge=1, le=365, description="Force-exit after N days")
    use_kelly:      bool                = Field(True, description="Use half-Kelly sizing when available")
    country:        Optional[str]       = Field(None, description="Filter by country: US or IN")


class StrategyBacktestRequest(BaseModel):
    strategy:         str              = Field(..., description=f"Strategy name. One of: {ALL_STRATEGIES}")
    tickers:          List[str]        = Field(..., min_items=1, description="List of ticker symbols to trade")
    start_date:       date             = Field(..., description="Backtest start date (YYYY-MM-DD)")
    end_date:         date             = Field(..., description="Backtest end date (YYYY-MM-DD)")
    initial_capital:  float            = Field(100_000.0, ge=1_000)
    country:          str              = Field("IN", description="IN or US — determines transaction cost model and benchmark")
    max_positions:    int              = Field(5, ge=1, le=20)
    stop_loss_pct:    float            = Field(5.0, ge=0, le=50, description="Fixed stop-loss % below entry. 0 = disabled.")
    take_profit_pct:  float            = Field(15.0, ge=0, le=200, description="Fixed take-profit % above entry. 0 = disabled.")
    apply_slippage:   bool             = Field(True, description="Apply realistic slippage model")
    apply_costs:      bool             = Field(True, description="Apply transaction costs (brokerage, STT, etc.)")


class CompareRequest(BaseModel):
    result_a: dict = Field(..., description="First backtest result (from /strategy or /run)")
    result_b: dict = Field(..., description="Second backtest result to compare against")
    label_a:  str  = Field("Strategy A", description="Label for first result")
    label_b:  str  = Field("Strategy B", description="Label for second result")


# ── POST /backtest/run ─────────────────────────────────────────────────────────


@router.post("/run")
async def run_backtest(
    req: BacktestRequest,
    db: AsyncSession = Depends(get_db),
):
    """
    Execute a full historical backtest.

    Simulates daily trading decisions using signals stored in ai_analysis
    and actual OHLCV data from stock_prices. Returns equity curve, trade log,
    monthly returns, and portfolio performance metrics.
    """
    # Basic validation
    if req.end_date <= req.start_date:
        raise HTTPException(status_code=422, detail="end_date must be after start_date")
    if (req.end_date - req.start_date).days < 5:
        raise HTTPException(status_code=422, detail="Backtest window must be at least 5 days")

    valid_signals = {"BUY", "HOLD", "REDUCE", "SELL", "PROACTIVE_SWING"}
    bad_signals = [s for s in req.signal_filter if s.upper() not in valid_signals]
    if bad_signals:
        raise HTTPException(
            status_code=422,
            detail=f"Invalid signal(s): {bad_signals}. Valid values: {sorted(valid_signals)}",
        )

    logger.info(
        "Backtest run: %s → %s | signals=%s | capital=%.0f | country=%s",
        req.start_date, req.end_date, req.signal_filter, req.initial_capital, req.country,
    )

    try:
        engine = BacktestEngine(
            db=db,
            start_date=req.start_date,
            end_date=req.end_date,
            initial_capital=req.initial_capital,
            signal_filter=req.signal_filter,
            max_positions=req.max_positions,
            use_kelly=req.use_kelly,
            max_hold_days=req.max_hold_days,
            country=req.country,
        )
        result = await engine.run()
        return result

    except Exception as exc:
        logger.exception("Backtest run failed: %s", exc)
        raise HTTPException(status_code=500, detail=f"Backtest failed: {str(exc)}")


# ── GET /backtest/quick-stats ──────────────────────────────────────────────────


@router.get("/quick-stats")
async def quick_stats(
    country: Optional[str] = Query(None, description="Filter by country: US or IN"),
    db: AsyncSession = Depends(get_db),
):
    """
    90-day signal performance summary using stored entry/stop/target levels
    from ai_analysis. No simulation required — uses realized levels from the
    latest price data to estimate current P&L for each open signal.

    Returns:
      - Signal counts by type
      - Hit-rate estimates (how many targets/stops have been reached)
      - Average implied return per signal type
      - Total unrealised P&L estimate
    """
    since = datetime.now(timezone.utc) - timedelta(days=90)

    country_clause = ""
    params: dict = {"since": since}
    if country:
        country_clause = "AND s.country = :country"
        params["country"] = country.upper()

    # ── Fetch signals with entry/stop/target ──────────────────────────────────
    signals_sql = text(f"""
        SELECT
            a.ticker,
            a.analysis_date::date     AS signal_date,
            a.signal,
            a.final_score,
            a.entry_price,
            a.stop_loss,
            a.take_profit,
            a.atr_14,
            a.regime
        FROM ai_analysis a
        JOIN stocks s ON s.ticker = a.ticker
        WHERE a.analysis_date >= :since
          AND a.entry_price IS NOT NULL
          {country_clause}
        ORDER BY a.analysis_date DESC
    """)
    sig_result = await db.execute(signals_sql, params)
    signal_rows = sig_result.fetchall()

    if not signal_rows:
        return {
            "window_days":       90,
            "total_signals":     0,
            "signal_counts":     {},
            "hit_rates":         {},
            "avg_implied_return": {},
            "regime_breakdown":  {},
            "top_performers":    [],
            "summary":           "No signals found in the last 90 days.",
        }

    tickers = list({r.ticker for r in signal_rows})

    # ── Fetch latest close price for each ticker ──────────────────────────────
    latest_sql = text("""
        SELECT DISTINCT ON (ticker)
            ticker,
            close AS latest_close,
            time::date AS price_date
        FROM stock_prices
        WHERE ticker = ANY(:tickers)
        ORDER BY ticker, time DESC
    """)
    price_result = await db.execute(latest_sql, {"tickers": tickers})
    latest_prices: dict[str, dict] = {
        r.ticker: {"close": r.latest_close, "date": r.price_date}
        for r in price_result.fetchall()
    }

    # ── Compute per-signal stats ───────────────────────────────────────────────
    by_signal: dict[str, dict] = {}
    regime_breakdown: dict[str, list] = {}
    all_performers: list[dict] = []

    for r in signal_rows:
        sig_type = r.signal or "UNKNOWN"
        entry = r.entry_price
        stop  = r.stop_loss
        target = r.take_profit
        atr   = r.atr_14 or 0.0

        # ATR fallback
        if not stop and atr:
            stop = entry - 2.0 * atr
        if not target and atr:
            target = entry + 6.0 * atr

        latest = latest_prices.get(r.ticker, {}).get("close") or entry

        # Estimate outcome
        if stop and latest <= stop:
            outcome = "STOP_HIT"
            implied_return = (stop - entry) / entry * 100.0 if entry else 0.0
        elif target and latest >= target:
            outcome = "TARGET_HIT"
            implied_return = (target - entry) / entry * 100.0 if entry else 0.0
        else:
            outcome = "OPEN"
            implied_return = (latest - entry) / entry * 100.0 if entry else 0.0

        if sig_type not in by_signal:
            by_signal[sig_type] = {
                "count":          0,
                "target_hits":    0,
                "stop_hits":      0,
                "open":           0,
                "returns":        [],
                "scores":         [],
            }

        by_signal[sig_type]["count"]   += 1
        by_signal[sig_type]["returns"].append(implied_return)
        if r.final_score:
            by_signal[sig_type]["scores"].append(r.final_score)

        if outcome == "TARGET_HIT":
            by_signal[sig_type]["target_hits"] += 1
        elif outcome == "STOP_HIT":
            by_signal[sig_type]["stop_hits"] += 1
        else:
            by_signal[sig_type]["open"] += 1

        # Regime breakdown
        regime = r.regime or "Unknown"
        if regime not in regime_breakdown:
            regime_breakdown[regime] = []
        regime_breakdown[regime].append(implied_return)

        all_performers.append({
            "ticker":         r.ticker,
            "signal":         sig_type,
            "signal_date":    r.signal_date.isoformat() if hasattr(r.signal_date, "isoformat") else str(r.signal_date),
            "entry_price":    round(entry, 4) if entry else None,
            "latest_price":   round(latest, 4) if latest else None,
            "implied_return_pct": round(implied_return, 4),
            "outcome":        outcome,
            "final_score":    r.final_score,
            "regime":         regime,
        })

    # ── Build summary structures ───────────────────────────────────────────────
    signal_counts = {s: d["count"] for s, d in by_signal.items()}

    hit_rates = {}
    for sig_type, d in by_signal.items():
        n = d["count"]
        hit_rates[sig_type] = {
            "target_hit_pct": round(d["target_hits"] / n * 100, 2) if n else 0,
            "stop_hit_pct":   round(d["stop_hits"]   / n * 100, 2) if n else 0,
            "open_pct":       round(d["open"]         / n * 100, 2) if n else 0,
        }

    avg_implied_return = {
        sig_type: round(sum(d["returns"]) / len(d["returns"]), 4) if d["returns"] else 0.0
        for sig_type, d in by_signal.items()
    }

    regime_summary = {
        regime: {
            "count": len(rets),
            "avg_return_pct": round(sum(rets) / len(rets), 4) if rets else 0.0,
        }
        for regime, rets in regime_breakdown.items()
    }

    # Top 10 performers by implied return
    buy_side = [p for p in all_performers if p["signal"] == "BUY"]
    top_performers = sorted(buy_side, key=lambda x: x["implied_return_pct"], reverse=True)[:10]

    total_signals = len(signal_rows)
    total_returns = [p["implied_return_pct"] for p in all_performers if p["signal"] == "BUY"]
    avg_long_return = round(sum(total_returns) / len(total_returns), 4) if total_returns else 0.0

    return {
        "window_days":            90,
        "total_signals":          total_signals,
        "signal_counts":          signal_counts,
        "hit_rates":              hit_rates,
        "avg_implied_return_pct": avg_implied_return,
        "avg_long_return_pct":    avg_long_return,
        "regime_breakdown":       regime_summary,
        "top_performers":         top_performers,
        "summary": (
            f"{total_signals} signals analysed over 90 days. "
            f"Long signals average implied return: {avg_long_return:+.2f}%."
        ),
    }


# ── GET /backtest/strategies ───────────────────────────────────────────────────


@router.get("/strategies")
async def list_strategies():
    """
    List all built-in trading strategies available for backtesting.

    Returns strategy names, descriptions, best-use context, and default parameters.
    """
    return {
        "strategies": [
            {"id": name, **info}
            for name, info in STRATEGY_DESCRIPTIONS.items()
        ],
        "count": len(ALL_STRATEGIES),
    }


# ── POST /backtest/strategy ────────────────────────────────────────────────────


@router.post("/strategy")
async def run_strategy_backtest(
    req: StrategyBacktestRequest,
    db: AsyncSession = Depends(get_db),
):
    """
    Run a built-in strategy backtest with realistic slippage and transaction costs.

    Unlike /run (which uses AI signals from the database), /strategy generates
    its own trading signals from raw price data using the selected algorithm.

    Includes:
    - Equity curve vs benchmark (Nifty 50 for IN, S&P 500 for US)
    - All performance metrics (CAGR, Sharpe, Sortino, Calmar, max drawdown)
    - Full trade log with entry/exit prices, P&L, hold days
    - Cost breakdown: slippage + brokerage/STT/exchange fees
    - Alpha, beta, excess return vs benchmark
    - Monthly return heatmap data

    Example strategies: RSI_MEAN_REVERSION, MACD_CROSSOVER, MA_CROSSOVER,
    MOMENTUM, BOLLINGER_REVERSION, BUY_AND_HOLD
    """
    # Validation
    if req.end_date <= req.start_date:
        raise HTTPException(status_code=422, detail="end_date must be after start_date")
    if (req.end_date - req.start_date).days < 30:
        raise HTTPException(status_code=422, detail="Backtest window must be at least 30 days")
    if req.strategy not in ALL_STRATEGIES:
        raise HTTPException(
            status_code=422,
            detail=f"Unknown strategy '{req.strategy}'. Valid strategies: {ALL_STRATEGIES}"
        )
    if req.country.upper() not in ("IN", "US"):
        raise HTTPException(status_code=422, detail="country must be 'IN' or 'US'")

    # Sanitize tickers
    tickers = [t.strip().upper() for t in req.tickers if t.strip()]
    if not tickers:
        raise HTTPException(status_code=422, detail="At least one ticker required")

    logger.info(
        "Strategy backtest: %s | tickers=%s | %s→%s | capital=%.0f | country=%s",
        req.strategy, tickers, req.start_date, req.end_date, req.initial_capital, req.country
    )

    try:
        engine = StrategyBacktestEngine(
            strategy_name=req.strategy,
            tickers=tickers,
            start_date=req.start_date,
            end_date=req.end_date,
            initial_capital=req.initial_capital,
            country=req.country.upper(),
            max_positions=req.max_positions,
            stop_loss_pct=req.stop_loss_pct,
            take_profit_pct=req.take_profit_pct,
            apply_slippage=req.apply_slippage,
            apply_costs=req.apply_costs,
        )
        result = await engine.run()
        return result
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    except Exception as exc:
        logger.exception("Strategy backtest failed: %s", exc)
        raise HTTPException(status_code=500, detail=f"Strategy backtest failed: {str(exc)}")


# ── POST /backtest/compare ─────────────────────────────────────────────────────


@router.post("/compare")
async def compare_backtests(req: CompareRequest):
    """
    Compare two backtest results side by side.

    Pass results from /run or /strategy as result_a and result_b.
    Returns a detailed head-to-head comparison across all key metrics,
    declaring a winner on each dimension and an overall winner.

    Useful for:
    - Strategy A vs Strategy B on same tickers/period
    - With costs vs without costs
    - Indian broker vs paper (no costs)
    - Short backtest period vs long period
    """
    def _get_metrics(result: dict) -> dict:
        return result.get("metrics", {})

    def _safe(d: dict, key: str, default=0.0):
        v = d.get(key, default)
        return v if v is not None else default

    ma = _get_metrics(req.result_a)
    mb = _get_metrics(req.result_b)

    metrics_to_compare = [
        ("total_return_pct",  "Total Return (%)",      True,  "higher"),
        ("cagr_pct",          "CAGR (%)",              True,  "higher"),
        ("sharpe_ratio",      "Sharpe Ratio",          True,  "higher"),
        ("sortino_ratio",     "Sortino Ratio",         True,  "higher"),
        ("max_drawdown_pct",  "Max Drawdown (%)",      False, "lower (less negative)"),
        ("calmar_ratio",      "Calmar Ratio",          True,  "higher"),
        ("win_rate_pct",      "Win Rate (%)",          True,  "higher"),
        ("profit_factor",     "Profit Factor",         True,  "higher"),
        ("avg_hold_days",     "Avg Hold Days",         None,  "context dependent"),
        ("total_trades",      "Total Trades",          None,  "context dependent"),
    ]

    head_to_head = []
    a_wins = 0
    b_wins = 0

    for key, label, higher_is_better, note in metrics_to_compare:
        va = _safe(ma, key)
        vb = _safe(mb, key)

        if higher_is_better is True:
            winner = req.label_a if va > vb else (req.label_b if vb > va else "TIE")
        elif higher_is_better is False:
            # For drawdown: less negative (closer to 0) is better
            winner = req.label_a if va > vb else (req.label_b if vb > va else "TIE")
        else:
            winner = "N/A"

        if winner == req.label_a:
            a_wins += 1
        elif winner == req.label_b:
            b_wins += 1

        head_to_head.append({
            "metric":          label,
            "label_a":         req.label_a,
            "value_a":         round(va, 4) if isinstance(va, float) else va,
            "label_b":         req.label_b,
            "value_b":         round(vb, 4) if isinstance(vb, float) else vb,
            "winner":          winner,
            "note":            note,
        })

    overall_winner = (
        req.label_a if a_wins > b_wins else
        req.label_b if b_wins > a_wins else "TIE"
    )

    # Return/risk comparison
    ret_a = _safe(ma, "total_return_pct")
    ret_b = _safe(mb, "total_return_pct")
    dd_a  = abs(_safe(ma, "max_drawdown_pct"))
    dd_b  = abs(_safe(mb, "max_drawdown_pct"))

    return {
        "overall_winner":   overall_winner,
        "score":            {req.label_a: a_wins, req.label_b: b_wins},
        "head_to_head":     head_to_head,
        "summary": {
            req.label_a: {
                "return_pct":   ret_a,
                "max_dd_pct":   _safe(ma, "max_drawdown_pct"),
                "sharpe":       _safe(ma, "sharpe_ratio"),
                "total_trades": _safe(ma, "total_trades", 0),
                "costs_paid":   _safe(ma, "total_costs_paid"),
            },
            req.label_b: {
                "return_pct":   ret_b,
                "max_dd_pct":   _safe(mb, "max_drawdown_pct"),
                "sharpe":       _safe(mb, "sharpe_ratio"),
                "total_trades": _safe(mb, "total_trades", 0),
                "costs_paid":   _safe(mb, "total_costs_paid"),
            },
        },
        "insight": (
            f"{overall_winner} wins {max(a_wins, b_wins)} vs {min(a_wins, b_wins)} metrics. "
            f"Return difference: {abs(ret_a - ret_b):.2f}%. "
            f"{'Costs drag: ' + str(round(abs(_safe(ma, 'total_costs_paid') - _safe(mb, 'total_costs_paid')), 2)) if (_safe(ma, 'total_costs_paid') or _safe(mb, 'total_costs_paid')) else ''}"
        ).strip(),
    }
