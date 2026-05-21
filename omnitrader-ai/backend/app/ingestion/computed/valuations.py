"""
ingestion/computed/valuations.py
==================================
ValuationService — computes DCF, EV/EBITDA, P/B, P/S, PEG, margin of safety.

Sources:
  - company_financials: revenue, net_income, eps, free_cash_flow, total_assets,
                        total_liabilities, debt_to_equity, roic
  - stock_prices:       current close price
  - macro_data:         US10Y for risk-free rate in WACC

DCF Methodology:
  1. Base FCF = latest free_cash_flow
  2. Project 5 years at growth_rate (= min(rev_cagr, 25%))
  3. Terminal value = FCF_5 * (1 + terminal_g) / (WACC - terminal_g)
  4. Discount back at WACC
  5. Divide by estimated shares outstanding

WACC estimate:
  WACC = risk_free + equity_premium * beta_proxy
  beta_proxy = 1.0 (default), equity_premium = 5.5%
  risk_free = 10-year treasury yield from macro_data (fallback 4.5%)
"""
import logging
import math
from datetime import date, timedelta
from typing import Optional

from sqlalchemy import text
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import AsyncSessionLocal
from app.models.market_data import ValuationMetrics, CompanyFinancials

logger = logging.getLogger(__name__)

EQUITY_RISK_PREMIUM = 0.055   # 5.5% market risk premium
TERMINAL_GROWTH     = 0.025   # 2.5% perpetuity growth
DEFAULT_RISK_FREE   = 0.045   # 4.5% fallback if macro data missing


async def _get_risk_free_rate(db: AsyncSession) -> float:
    """Fetch latest 10Y US Treasury yield from macro_data."""
    try:
        result = await db.execute(text("""
            SELECT value FROM macro_data
            WHERE indicator IN ('US10Y', 'TNX')
            ORDER BY time DESC LIMIT 1
        """))
        row = result.fetchone()
        if row and row.value:
            v = row.value
            return v / 100 if v > 1 else v   # handle percent vs decimal
    except Exception:
        pass
    return DEFAULT_RISK_FREE


def _safe_float(v) -> Optional[float]:
    if v is None:
        return None
    try:
        f = float(v)
        return None if math.isnan(f) or math.isinf(f) else f
    except (TypeError, ValueError):
        return None


def _dcf(fcf: float, growth_rate: float, wacc: float,
         terminal_g: float, years: int = 5) -> Optional[float]:
    """Returns total DCF value (not per-share — divide by shares elsewhere)."""
    if wacc <= terminal_g or wacc <= 0:
        return None
    g = min(growth_rate, 0.25)  # cap at 25%

    pv_fcfs = 0.0
    current_fcf = fcf
    for yr in range(1, years + 1):
        current_fcf *= (1 + g)
        pv_fcfs += current_fcf / ((1 + wacc) ** yr)

    # Terminal value
    terminal_fcf = current_fcf * (1 + terminal_g)
    terminal_value = terminal_fcf / (wacc - terminal_g)
    pv_terminal = terminal_value / ((1 + wacc) ** years)

    return pv_fcfs + pv_terminal


class ValuationService:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def run_batch(self, tickers: list[str]) -> dict:
        stored_total = 0
        failed = []
        today = date.today()
        risk_free = await _get_risk_free_rate(self.db)

        for ticker in tickers:
            try:
                n = await self._compute_and_store(ticker, today, risk_free)
                stored_total += n
            except Exception as e:
                logger.warning("[Valuation] %s: %s", ticker, e)
                failed.append(ticker)

        logger.info("ValuationService: %d rows, %d failed", stored_total, len(failed))
        return {"stored": stored_total, "failed": failed}

    async def _compute_and_store(self, ticker: str, today: date, risk_free: float) -> int:
        # Load financials (last 5 periods, ascending)
        result = await self.db.execute(text("""
            SELECT fiscal_date, revenue, net_income, eps, free_cash_flow,
                   total_assets, total_liabilities, pe_ratio, debt_to_equity, roic,
                   operating_margin
            FROM company_financials
            WHERE ticker = :t
            ORDER BY fiscal_date ASC
        """), {"t": ticker})
        rows = result.fetchall()
        if not rows:
            return 0

        # Latest price
        price_res = await self.db.execute(text("""
            SELECT close FROM stock_prices WHERE ticker = :t AND close IS NOT NULL
            ORDER BY time DESC LIMIT 1
        """), {"t": ticker})
        price_row = price_res.fetchone()
        if not price_row:
            return 0
        price = price_row.close

        latest = rows[-1]
        revenue = _safe_float(latest.revenue)
        net_income = _safe_float(latest.net_income)
        eps = _safe_float(latest.eps)
        fcf = _safe_float(latest.free_cash_flow)
        assets = _safe_float(latest.total_assets)
        liabs = _safe_float(latest.total_liabilities)
        pe_stored = _safe_float(latest.pe_ratio)
        de_ratio = _safe_float(latest.debt_to_equity)

        # ── P/E ─────────────────────────────────────────────────────────────
        pe_ratio = pe_stored
        if pe_ratio is None and eps and eps > 0:
            pe_ratio = price / eps

        # ── EPS growth rate (for PEG) ─────────────────────────────────────
        eps_list = [_safe_float(r.eps) for r in rows[-4:] if _safe_float(r.eps) is not None]
        eps_growth = None
        if len(eps_list) >= 2 and eps_list[0] and eps_list[0] > 0:
            eps_growth = ((eps_list[-1] / eps_list[0]) ** (1 / max(len(eps_list)-1, 1)) - 1) * 100

        # ── PEG ──────────────────────────────────────────────────────────────
        peg_ratio = None
        if pe_ratio and eps_growth and eps_growth > 0:
            peg_ratio = pe_ratio / eps_growth

        # ── P/B ──────────────────────────────────────────────────────────────
        pb_ratio = None
        if assets and liabs and price and net_income and net_income != 0:
            book_value = assets - liabs
            # Estimate shares from EPS if possible, else skip
            if eps and eps != 0 and net_income:
                shares = net_income / eps
                bvps = book_value / shares if shares > 0 else None
                if bvps and bvps > 0:
                    pb_ratio = price / bvps

        # ── P/S ──────────────────────────────────────────────────────────────
        ps_ratio = None
        if revenue and eps and eps != 0 and net_income and net_income != 0:
            shares = net_income / eps
            rev_per_share = revenue / shares if shares > 0 else None
            if rev_per_share and rev_per_share > 0:
                ps_ratio = price / rev_per_share

        # ── EV / EBITDA ───────────────────────────────────────────────────────
        ev = None
        ev_ebitda = None
        if de_ratio is not None and net_income and eps and eps != 0:
            shares = net_income / eps
            mkt_cap = price * shares
            # Estimate debt from D/E and equity
            equity = (assets - liabs) if (assets and liabs) else None
            if equity and equity > 0:
                debt_est = de_ratio * equity
                cash_est = assets * 0.05 if assets else 0   # rough 5% cash ratio
                ev = mkt_cap + debt_est - cash_est

            # EBITDA proxy: net_income + (revenue * operating_margin * 0.3 for D&A estimate)
            om = _safe_float(latest.operating_margin)
            if om and revenue:
                if om < 1:
                    om *= 100
                op_income = revenue * (om / 100)
                da_est = revenue * 0.05   # rough D&A ~5% of revenue
                ebitda = op_income + da_est
                if ebitda > 0 and ev:
                    ev_ebitda = ev / ebitda

        # ── Revenue CAGR (for DCF growth estimate) ────────────────────────────
        rev_list = [_safe_float(r.revenue) for r in rows[-5:] if _safe_float(r.revenue)]
        rev_cagr = 0.05  # default 5%
        if len(rev_list) >= 2 and rev_list[0] > 0:
            rev_cagr = (rev_list[-1] / rev_list[0]) ** (1 / max(len(rev_list)-1, 1)) - 1

        # ── DCF ───────────────────────────────────────────────────────────────
        dcf_value = None
        wacc = risk_free + EQUITY_RISK_PREMIUM   # simplified WACC (beta=1)
        if fcf and fcf > 0 and eps and eps != 0 and net_income and net_income != 0:
            shares = net_income / eps
            total_dcf = _dcf(fcf, rev_cagr, wacc, TERMINAL_GROWTH)
            if total_dcf and shares > 0:
                dcf_value = total_dcf / shares

        # ── Margin of safety ──────────────────────────────────────────────────
        margin_of_safety = None
        if dcf_value and dcf_value > 0:
            margin_of_safety = ((dcf_value - price) / dcf_value) * 100

        # ── Valuation label ───────────────────────────────────────────────────
        label = "UNKNOWN"
        if pe_ratio and peg_ratio and margin_of_safety is not None:
            if margin_of_safety > 30 and (pe_ratio < 15 or peg_ratio < 1):
                label = "DEEP_VALUE"
            elif margin_of_safety > 10 or pe_ratio < 20:
                label = "FAIR"
            elif margin_of_safety < -20 or pe_ratio > 40:
                label = "EXPENSIVE"
            else:
                label = "OVERVALUED"
        elif pe_ratio:
            label = "DEEP_VALUE" if pe_ratio < 12 else "FAIR" if pe_ratio < 25 else "EXPENSIVE"

        # ── Composite valuation score (0–100, higher = cheaper) ──────────────
        composite = 50.0
        if pe_ratio:
            composite += (25 - pe_ratio) * 0.5
        if peg_ratio:
            composite += (1.5 - peg_ratio) * 10
        if margin_of_safety is not None:
            composite += margin_of_safety * 0.3
        composite = max(0, min(100, composite))

        record = {
            "ticker":           ticker,
            "computed_date":    today,
            "current_price":    price,
            "pe_ratio":         _safe_float(pe_ratio),
            "pb_ratio":         _safe_float(pb_ratio),
            "ps_ratio":         _safe_float(ps_ratio),
            "peg_ratio":        _safe_float(peg_ratio),
            "ev_ebitda":        _safe_float(ev_ebitda),
            "ev":               _safe_float(ev),
            "dcf_value":        _safe_float(dcf_value),
            "wacc":             wacc * 100,
            "terminal_growth":  TERMINAL_GROWTH * 100,
            "margin_of_safety": _safe_float(margin_of_safety),
            "valuation_label":  label,
            "composite_score":  float(composite),
        }

        stmt = pg_insert(ValuationMetrics).values([record])
        stmt = stmt.on_conflict_do_update(
            constraint="uq_valuation_ticker_date",
            set_={k: stmt.excluded[k] for k in record if k not in ("ticker", "computed_date")},
        )
        await self.db.execute(stmt)
        await self.db.commit()
        return 1
