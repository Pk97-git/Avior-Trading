import logging
import math
from sqlalchemy.orm import Session
from sqlalchemy import select, text
from app.models.market_data import CompanyFinancials

logger = logging.getLogger("omnitrader.agent.fundamental")


class FundamentalAgent:
    def __init__(self, db: Session, ticker: str):
        self.db = db
        self.ticker = ticker

    async def analyze(self) -> dict:
        """
        Calculates a Fundamental Score (0–100) across 8 dimensions:
          1. Revenue growth (YoY)
          2. 5-year revenue CAGR
          3. Net income profitability + growth
          4. EPS trend (multi-period)
          5. ROIC quality (>15% = high quality)
          6. Operating margin trend (expanding vs contracting)
          7. Free Cash Flow generation
          8. Debt/Equity safety

        Returns: {"score": int, "thesis": list[str]}
        """
        stmt = select(CompanyFinancials).where(
            CompanyFinancials.ticker == self.ticker
        ).order_by(CompanyFinancials.fiscal_date.asc())

        result = await self.db.execute(stmt)
        financials = result.scalars().all()

        if not financials:
            return {"score": 0, "thesis": ["No fundamental data available for this ticker."]}

        score = 50
        thesis = []

        if len(financials) < 2:
            thesis.append(f"Only {len(financials)} period(s) of data. Insufficient for trend analysis.")
            return {"score": score, "thesis": thesis}

        latest = financials[-1]
        previous = financials[-2]

        # ── 1. Revenue Growth (YoY) ───────────────────────────────────────────
        if latest.revenue and previous.revenue and previous.revenue > 0:
            rev_growth = ((latest.revenue - previous.revenue) / previous.revenue) * 100
            if rev_growth > 20:
                score += 18
                thesis.append(f"Exceptional revenue growth: +{rev_growth:.1f}% YoY.")
            elif rev_growth > 10:
                score += 10
                thesis.append(f"Strong revenue growth: +{rev_growth:.1f}% YoY.")
            elif rev_growth > 5:
                score += 5
                thesis.append(f"Moderate revenue growth: +{rev_growth:.1f}% YoY.")
            elif rev_growth < -5:
                score -= 15
                thesis.append(f"Revenue declining: {rev_growth:.1f}% YoY — investigate.")
            else:
                thesis.append(f"Revenue flat: {rev_growth:.1f}% YoY.")

        # ── 2. 5-Year Revenue CAGR ────────────────────────────────────────────
        if len(financials) >= 5:
            base = financials[-5]
            if base.revenue and latest.revenue and base.revenue > 0:
                cagr = (math.pow(latest.revenue / base.revenue, 1 / 4) - 1) * 100
                if cagr > 15:
                    score += 12
                    thesis.append(f"5-yr revenue CAGR {cagr:.1f}% — sustained compounding.")
                elif cagr > 8:
                    score += 6
                    thesis.append(f"5-yr revenue CAGR {cagr:.1f}% — solid long-term growth.")
                elif cagr < 0:
                    score -= 8
                    thesis.append(f"5-yr revenue CAGR {cagr:.1f}% — structural decline.")

        # ── 3. Net Income & Profitability ─────────────────────────────────────
        if latest.net_income is not None:
            if latest.net_income > 0:
                score += 8
                thesis.append("Company is profitable (positive net income).")
                if previous.net_income and previous.net_income > 0:
                    ni_growth = ((latest.net_income - previous.net_income) / previous.net_income) * 100
                    if ni_growth > 25:
                        score += 12
                        thesis.append(f"Exceptional net income growth: +{ni_growth:.1f}% YoY.")
                    elif ni_growth > 10:
                        score += 6
                        thesis.append(f"Net income growing: +{ni_growth:.1f}% YoY.")
                    elif ni_growth < -10:
                        score -= 8
                        thesis.append(f"Net income contracting: {ni_growth:.1f}% YoY.")
            else:
                score -= 18
                thesis.append("Loss-making business — high risk without a clear path to profitability.")

        # ── 4. EPS Trend (multi-period) ───────────────────────────────────────
        eps_vals = [f.eps for f in financials[-4:] if f.eps is not None]
        if len(eps_vals) >= 3:
            rising_count = sum(1 for i in range(1, len(eps_vals)) if eps_vals[i] > eps_vals[i-1])
            if rising_count == len(eps_vals) - 1:
                score += 10
                thesis.append(f"EPS consistently rising for {len(eps_vals)} consecutive periods.")
            elif rising_count >= len(eps_vals) // 2:
                score += 4
                thesis.append(f"EPS improving in {rising_count}/{len(eps_vals)-1} recent periods.")
            else:
                score -= 5
                thesis.append(f"EPS volatile or declining — earnings quality weak.")
        elif len(eps_vals) == 2:
            if eps_vals[1] > eps_vals[0]:
                score += 8
                thesis.append(f"EPS increased: {eps_vals[0]:.2f} → {eps_vals[1]:.2f}.")
            else:
                score -= 4
                thesis.append(f"EPS decreased: {eps_vals[0]:.2f} → {eps_vals[1]:.2f}.")

        # ── 5. ROIC Quality ───────────────────────────────────────────────────
        if latest.roic is not None:
            roic = latest.roic
            # yfinance returns ROIC as decimal (0.18 = 18%) or percent — normalise
            if roic < 1:
                roic = roic * 100
            if roic > 20:
                score += 14
                thesis.append(f"Excellent ROIC {roic:.1f}% — strong capital efficiency (>20%).")
            elif roic > 15:
                score += 8
                thesis.append(f"Good ROIC {roic:.1f}% — above quality threshold of 15%.")
            elif roic > 8:
                score += 2
                thesis.append(f"Adequate ROIC {roic:.1f}%.")
            else:
                score -= 8
                thesis.append(f"Weak ROIC {roic:.1f}% — capital being deployed inefficiently.")

        # ── 6. Operating Margin Trend ─────────────────────────────────────────
        margins = [f.operating_margin for f in financials[-4:] if f.operating_margin is not None]
        if len(margins) >= 2:
            margin_latest = margins[-1]
            margin_prev = margins[-2]
            if margin_latest < 1:
                margin_latest *= 100
            if margin_prev < 1:
                margin_prev *= 100
            delta = margin_latest - margin_prev
            if delta > 2:
                score += 8
                thesis.append(f"Operating margin expanding: {margin_prev:.1f}% → {margin_latest:.1f}% (+{delta:.1f}pp).")
            elif delta > 0:
                score += 3
                thesis.append(f"Operating margin stable: {margin_latest:.1f}%.")
            elif delta < -3:
                score -= 10
                thesis.append(f"Operating margin compressing: {margin_prev:.1f}% → {margin_latest:.1f}% ({delta:.1f}pp) — watch costs.")
            elif delta < -1:
                score -= 4
                thesis.append(f"Slight margin pressure: {margin_latest:.1f}%.")

        # ── 7. Free Cash Flow ──────────────────────────────────────────────────
        if latest.free_cash_flow is not None:
            fcf = latest.free_cash_flow
            if fcf > 0:
                score += 8
                if latest.net_income and latest.net_income > 0:
                    fcf_conversion = (fcf / latest.net_income) * 100
                    if fcf_conversion > 80:
                        score += 5
                        thesis.append(f"Strong FCF: ₹/$ {fcf:,.0f}. Excellent conversion rate ({fcf_conversion:.0f}% of net income).")
                    else:
                        thesis.append(f"Positive FCF: ₹/$ {fcf:,.0f}.")
                else:
                    thesis.append(f"Positive FCF: ₹/$ {fcf:,.0f}.")
            else:
                score -= 6
                thesis.append(f"Negative FCF ({fcf:,.0f}) — burning cash. Monitor closely.")

        # ── 8. Debt / Equity Safety ───────────────────────────────────────────
        if latest.debt_to_equity is not None:
            de = latest.debt_to_equity
            if de < 0.3:
                score += 8
                thesis.append(f"Very low D/E {de:.2f} — fortress balance sheet.")
            elif de < 1.0:
                score += 4
                thesis.append(f"Conservative D/E {de:.2f} — manageable leverage.")
            elif de < 2.0:
                thesis.append(f"Moderate leverage D/E {de:.2f} — monitor debt service.")
            else:
                score -= 10
                thesis.append(f"High leverage D/E {de:.2f} — elevated financial risk.")

        # ── Dividend Yield & Growth ───────────────────────────────────────────
        try:
            div_res = await self.db.execute(text("""
                SELECT yield_fwd, div_cagr_5y
                FROM dividends
                WHERE ticker = :t
                ORDER BY ex_date DESC LIMIT 1
            """), {"t": self.ticker})
            div_row = div_res.fetchone()
            if div_row:
                if div_row.yield_fwd and div_row.yield_fwd > 0:
                    y = div_row.yield_fwd
                    if y > 5:
                        score += 6
                        thesis.append(f"High dividend yield {y:.1f}% — strong income stream.")
                    elif y > 2:
                        score += 3
                        thesis.append(f"Dividend yield {y:.1f}% — returns cash to shareholders.")
                if div_row.div_cagr_5y and div_row.div_cagr_5y > 0:
                    cagr = div_row.div_cagr_5y
                    if cagr > 10:
                        score += 5
                        thesis.append(f"Dividend CAGR {cagr:.1f}% over 5 years — dividend growth compounder.")
                    elif cagr > 5:
                        score += 2
                        thesis.append(f"Dividend growing at {cagr:.1f}% annually.")
        except Exception:
            pass

        # ── Earnings Surprise ─────────────────────────────────────────────────
        try:
            surp_res = await self.db.execute(text("""
                SELECT eps_surprise_pct, fiscal_date
                FROM company_financials
                WHERE ticker = :t AND eps_surprise_pct IS NOT NULL
                ORDER BY fiscal_date DESC LIMIT 1
            """), {"t": self.ticker})
            surp_row = surp_res.fetchone()
            if surp_row:
                s = surp_row.eps_surprise_pct
                if s > 10:
                    score += 8
                    thesis.append(f"Earnings beat consensus by +{s:.1f}% — positive surprise momentum (PEAD).")
                elif s > 3:
                    score += 4
                    thesis.append(f"Earnings beat consensus by +{s:.1f}%.")
                elif s < -10:
                    score -= 8
                    thesis.append(f"Earnings missed consensus by {s:.1f}% — negative surprise risk.")
                elif s < -3:
                    score -= 4
                    thesis.append(f"Earnings slightly missed consensus ({s:.1f}%).")
        except Exception:
            pass

        score = max(0, min(100, score))
        logger.info("FundamentalAgent %s: score=%d", self.ticker, score)

        return {"score": score, "thesis": thesis}
