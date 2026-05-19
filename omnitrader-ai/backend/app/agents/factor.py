from typing import Optional, List, Dict, Tuple
"""
agents/factor.py
================
Factor Decomposition Agent
Decomposes a stock into Value / Growth / Momentum / Quality factor scores
using z-score normalisation against the full universe stored in the DB.

Returns:
    {
        "score": int (0-100),          # composite factor score
        "thesis": list[str],
        "factor_scores": {             # stored in ai_analysis.factor_scores
            "value": float,            # z-score
            "growth": float,
            "momentum": float,
            "quality": float
        }
    }
"""
import logging

from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import text

logger = logging.getLogger(__name__)


class FactorAgent:
    def __init__(self, db: AsyncSession, ticker: str):
        self.db = db
        self.ticker = ticker.upper()

    async def analyze(self) -> dict:
        try:
            value    = await self._value_score()
            growth   = await self._growth_score()
            momentum = await self._momentum_score()
            quality  = await self._quality_score()

            valid = {k: v for k, v in {
                "value": value, "growth": growth,
                "momentum": momentum, "quality": quality
            }.items() if v is not None}

            if not valid:
                return {"score": 50, "thesis": ["Insufficient factor data."], "factor_scores": {}}

            # Composite: equal weights across available factors
            composite_z = sum(valid.values()) / len(valid)

            # Convert z-score to 0-100 (z=+2 → 95, z=-2 → 5)
            import math
            score = int(max(5, min(95, 50 + composite_z * 22.5)))

            thesis = self._build_thesis(valid)
            return {"score": score, "thesis": thesis, "factor_scores": valid}

        except Exception as e:
            logger.error("FactorAgent failed for %s: %s", self.ticker, e)
            return {"score": 50, "thesis": ["Factor analysis unavailable."], "factor_scores": {}}

    async def _latest_financials(self) -> Optional[dict]:
        """Fetch the most recent year's financials for this ticker."""
        res = await self.db.execute(text("""
            SELECT pe_ratio, debt_to_equity, roe, roic, free_cash_flow,
                   revenue, net_income, eps, operating_margin
            FROM company_financials
            WHERE ticker = :t
            ORDER BY fiscal_date DESC
            LIMIT 1
        """), {"t": self.ticker})
        row = res.fetchone()
        return dict(row._mapping) if row else None

    async def _universe_pe_stats(self) -> tuple[float, float]:
        """Get universe-wide mean and stddev of P/E ratios for normalisation."""
        res = await self.db.execute(text("""
            SELECT AVG(pe_ratio) as mean, STDDEV(pe_ratio) as std
            FROM company_financials
            WHERE pe_ratio > 0 AND pe_ratio < 200
              AND fiscal_date >= NOW() - INTERVAL '2 years'
        """))
        row = res.fetchone()
        return (row.mean or 20.0, row.std or 15.0)

    async def _value_score(self) -> Optional[float]:
        """Value factor: low P/E + high FCF yield → positive z-score."""
        fin = await self._latest_financials()
        if not fin or fin.get("pe_ratio") is None:
            return None

        mean_pe, std_pe = await self._universe_pe_stats()
        pe = fin["pe_ratio"]
        if pe <= 0 or std_pe == 0:
            return None

        # Inverted: lower P/E is better (value)
        pe_z = (mean_pe - pe) / std_pe

        # FCF yield bonus (qualitative)
        fcf_bonus = 0.0
        if fin.get("free_cash_flow") and fin["free_cash_flow"] > 0:
            fcf_bonus = 0.3

        return round(min(2.5, max(-2.5, pe_z + fcf_bonus)), 3)

    async def _growth_score(self) -> Optional[float]:
        """Growth factor: consecutive periods of revenue + EPS growth."""
        res = await self.db.execute(text("""
            SELECT revenue, eps, fiscal_date
            FROM company_financials
            WHERE ticker = :t AND revenue IS NOT NULL
            ORDER BY fiscal_date DESC
            LIMIT 4
        """), {"t": self.ticker})
        rows = res.fetchall()
        if len(rows) < 2:
            return None

        rev_growth = (rows[0].revenue - rows[1].revenue) / max(abs(rows[1].revenue), 1)
        eps_growth = 0.0
        if rows[0].eps is not None and rows[1].eps is not None and rows[1].eps != 0:
            eps_growth = (rows[0].eps - rows[1].eps) / abs(rows[1].eps)

        # Normalise: 20% Rev growth = +1 z, 20% EPS growth = +1 z
        rev_z = min(2.0, max(-2.0, rev_growth / 0.20))
        eps_z = min(2.0, max(-2.0, eps_growth / 0.20))
        return round((rev_z + eps_z) / 2, 3)

    async def _momentum_score(self) -> Optional[float]:
        """Momentum: RS vs benchmark (pre-computed 63-day) + 52-week high proximity."""
        is_india = self.ticker.endswith(".NS") or self.ticker.endswith(".BO")

        res = await self.db.execute(text("""
            SELECT rs_vs_spx, rs_vs_nsei, week_52_high
            FROM stock_technicals
            WHERE ticker = :t
            ORDER BY date DESC LIMIT 1
        """), {"t": self.ticker})
        row = res.fetchone()

        if not row:
            return None

        rs = row.rs_vs_nsei if is_india else row.rs_vs_spx
        if rs is None:
            return None

        # rs is ratio: stock_3m_return / benchmark_3m_return
        # rs=1.5 means stock outperformed by 50% of benchmark return → +1z
        z = min(2.0, max(-2.0, (rs - 1.0) / 0.5))

        # 52-week high proximity bonus: need current price
        bonus = 0.0
        if row.week_52_high and row.week_52_high > 0:
            price_res = await self.db.execute(text("""
                SELECT close FROM stock_prices
                WHERE ticker = :t AND close IS NOT NULL
                ORDER BY time DESC LIMIT 1
            """), {"t": self.ticker})
            price_row = price_res.fetchone()
            if price_row and price_row.close:
                proximity = price_row.close / row.week_52_high
                bonus = 0.3 if proximity > 0.90 else 0.0

        return round(z + bonus, 3)

    async def _quality_score(self) -> Optional[float]:
        """Quality: high ROIC + low debt/equity."""
        fin = await self._latest_financials()
        if not fin:
            return None

        roic = fin.get("roic")
        d_e  = fin.get("debt_to_equity")

        if roic is None and d_e is None:
            return None

        roic_z = 0.0
        de_z   = 0.0

        if roic is not None:
            # >15% ROIC = high quality. universe mean ~10%, std ~8%
            roic_z = min(2.0, max(-2.0, (roic - 0.10) / 0.08))

        if d_e is not None:
            # Inverted: lower D/E is better. universe mean ~1.5, std ~1.2
            de_z = min(2.0, max(-2.0, (1.5 - d_e) / 1.2))

        return round((roic_z + de_z) / 2 if roic is not None and d_e is not None else (roic_z or de_z), 3)

    def _build_thesis(self, scores: dict[str, float]) -> list[str]:
        labels = {
            "value":    ("undervalued", "overvalued"),
            "growth":   ("strong revenue/EPS growth", "declining growth"),
            "momentum": ("positive price momentum", "negative momentum"),
            "quality":  ("high-quality balance sheet", "weak quality profile"),
        }
        bullets = []
        for factor, z in sorted(scores.items(), key=lambda x: abs(x[1]), reverse=True):
            direction = labels[factor][0] if z >= 0 else labels[factor][1]
            intensity = "strongly" if abs(z) > 1.5 else "moderately" if abs(z) > 0.7 else "slightly"
            bullets.append(f"Factor/{factor.capitalize()}: {intensity} {direction} (z={z:+.2f})")
        return bullets[:4]
