"""
agents/cross_asset.py
======================
Cross-Asset Sensitivity Agent
Measures rolling 90-day correlation between a stock's daily returns and
key macro shocks: 10Y yield, VIX, USD, Oil, Gold.

Returns:
    {
        "score": int (0-100),
        "thesis": list[str],
        "cross_asset_sensitivity": {
            "US10Y": float,   # rolling Pearson correlation
            "VIX":   float,
            "DXY":   float,
            "OIL":   float,
            "GOLD":  float,
        }
    }

Score interpretation:
  High positive beta to VIX or negative beta to 10Y → risk-off exposure → lower score
  Positive beta to macro growth proxies (oil, equal-weight) → higher score
"""
import logging
from datetime import datetime, timedelta, timezone
from typing import Optional

from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import text

logger = logging.getLogger(__name__)

MACRO_TICKERS = {
    "US10Y": "^TNX",        # 10Y US Treasury yield (Yahoo)
    "VIX":   "^VIX",
    "DXY":   "DX-Y.NYB",   # USD Index
    "OIL":   "CL=F",        # WTI crude futures
    "GOLD":  "GC=F",
}

LOOKBACK_DAYS = 90


def _pct_returns(prices: list[float]) -> list[float]:
    if len(prices) < 2:
        return []
    return [(prices[i] - prices[i-1]) / prices[i-1] for i in range(1, len(prices))]


def _pearson(x: list[float], y: list[float]) -> Optional[float]:
    n = min(len(x), len(y))
    if n < 10:
        return None
    x, y = x[-n:], y[-n:]
    mx, my = sum(x)/n, sum(y)/n
    num   = sum((xi - mx)*(yi - my) for xi, yi in zip(x, y))
    den_x = sum((xi - mx)**2 for xi in x) ** 0.5
    den_y = sum((yi - my)**2 for yi in y) ** 0.5
    if den_x == 0 or den_y == 0:
        return None
    return round(num / (den_x * den_y), 3)


class CrossAssetAgent:
    def __init__(self, db: AsyncSession, ticker: str):
        self.db = db
        self.ticker = ticker.upper()

    async def analyze(self) -> dict:
        try:
            since = datetime.now(timezone.utc) - timedelta(days=LOOKBACK_DAYS + 10)

            stock_prices = await self._get_prices(self.ticker, since)
            if len(stock_prices) < 20:
                return {"score": 50, "thesis": ["Insufficient price history for cross-asset analysis."],
                        "cross_asset_sensitivity": {}}

            stock_rets = _pct_returns(stock_prices)
            correlations = {}

            for label, macro_ticker in MACRO_TICKERS.items():
                macro_prices = await self._get_prices(macro_ticker, since)
                if len(macro_prices) >= 20:
                    macro_rets = _pct_returns(macro_prices)
                    corr = _pearson(stock_rets, macro_rets)
                    if corr is not None:
                        correlations[label] = corr

            score = self._compute_score(correlations)
            thesis = self._build_thesis(correlations)

            return {
                "score": score,
                "thesis": thesis,
                "cross_asset_sensitivity": correlations
            }

        except Exception as e:
            logger.error("CrossAssetAgent failed for %s: %s", self.ticker, e)
            return {"score": 50, "thesis": ["Cross-asset analysis unavailable."],
                    "cross_asset_sensitivity": {}}

    async def _get_prices(self, ticker: str, since: str) -> list[float]:
        res = await self.db.execute(text("""
            SELECT close FROM stock_prices
            WHERE ticker = :t AND time >= :since AND close IS NOT NULL
            ORDER BY time ASC
        """), {"t": ticker, "since": since})
        return [r.close for r in res.fetchall()]

    def _compute_score(self, corr: dict[str, float]) -> int:
        """
        Score heuristic:
        - High positive beta to VIX → risky, lowers score (VIX spike = drawdown)
        - Negative beta to US10Y → rate-sensitive, lowers score in rising-rate regime
        - Positive beta to OIL → growth proxy, raises score
        - Neutral DXY/GOLD → marginal impact
        """
        if not corr:
            return 50

        adj = 0.0
        if "VIX"   in corr: adj -= corr["VIX"]   * 15    # high VIX beta is bad
        if "US10Y" in corr: adj += corr["US10Y"]  * 10    # positive rate beta = value tilt (good)
        if "OIL"   in corr: adj += corr["OIL"]    * 8     # growth proxy
        if "DXY"   in corr: adj -= corr["DXY"]    * 5     # strong USD hurts multinationals
        if "GOLD"  in corr: adj -= corr["GOLD"]   * 3     # high gold beta = defensive/fearful

        return int(max(20, min(80, 50 + adj)))

    def _build_thesis(self, corr: dict[str, float]) -> list[str]:
        if not corr:
            return ["No macro correlation data available."]

        labels = {
            "VIX":   ("risk-off (VIX spike exposure)", "defensive (low VIX beta)"),
            "US10Y": ("rate-resilient", "rate-sensitive"),
            "DXY":   ("USD-headwind exposure", "USD-tailwind exposure"),
            "OIL":   ("macro growth-linked", "decoupled from oil cycle"),
            "GOLD":  ("safe-haven correlated", "risk-asset correlated"),
        }
        bullets = []
        for label, val in sorted(corr.items(), key=lambda x: abs(x[1]), reverse=True):
            if label not in labels:
                continue
            direction_idx = 0 if val > 0 else 1
            if label == "US10Y": direction_idx = 0 if val > 0 else 1
            if label == "VIX":   direction_idx = 0 if val > 0 else 1  # high VIX beta = risk-off is bad

            direction = labels[label][direction_idx]
            strength  = "strongly" if abs(val) > 0.5 else "moderately" if abs(val) > 0.25 else "weakly"
            bullets.append(f"Cross-asset/{label}: {strength} correlated (ρ={val:+.2f}) — {direction}")

        return bullets[:5]
