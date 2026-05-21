"""
rebalancer.py
=============
RebalancerService — AI-driven portfolio rebalancing with natural-language alerts.

Features:
  1. Concentration analysis — sector, country, single-stock exposure
  2. NL alerts — "You are overexposed to tech (42% vs 25% max)"
  3. Rebalancing suggestions — ranked list of trades to restore target weights
  4. Multi-broker consolidated view — unified positions from all broker accounts

Target weights (defaults, user can override):
  Sector max: 30%
  Single stock max: 10%
  Country max: 60% (for diversified portfolios)
  Cash min: 5%
"""
import logging
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import text

logger = logging.getLogger("omnitrader.services.rebalancer")

SECTOR_MAX_PCT    = 0.30   # 30% max in any one sector
STOCK_MAX_PCT     = 0.10   # 10% max in any one stock
COUNTRY_MAX_PCT   = 0.60   # 60% max in any one country
CASH_MIN_PCT      = 0.05   # 5% min cash buffer

SECTOR_TARGET_WEIGHTS = {
    "Technology":    0.20, "Financials":    0.15, "Healthcare":    0.12,
    "Consumer":      0.10, "Energy":        0.08, "Industrials":   0.08,
    "Materials":     0.05, "Utilities":     0.05, "Real Estate":   0.05,
    "Communication": 0.07, "Other":         0.05,
}


class RebalancerService:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def get_consolidated_positions(self) -> list[dict]:
        """
        Query all open positions with stock metadata.
        Returns list of position dicts sorted by current_value descending.
        """
        result = await self.db.execute(text("""
            SELECT p.ticker, p.quantity, p.current_price, p.current_value,
                   p.avg_price, p.unrealized_pnl, p.unrealized_pnl_pct,
                   s.name, s.sector, s.country, s.exchange
            FROM portfolio_positions p
            LEFT JOIN stocks s ON s.ticker = p.ticker
            WHERE p.status = 'OPEN'
            ORDER BY p.current_value DESC NULLS LAST
        """))
        rows = result.fetchall()

        positions = []
        for row in rows:
            positions.append({
                "ticker":             row.ticker,
                "quantity":           row.quantity,
                "current_price":      row.current_price,
                "current_value":      row.current_value,
                "avg_price":          row.avg_price,
                "unrealized_pnl":     row.unrealized_pnl,
                "unrealized_pnl_pct": row.unrealized_pnl_pct,
                "name":               row.name,
                "sector":             row.sector,
                "country":            row.country,
                "exchange":           row.exchange,
            })
        return positions

    async def analyze_concentration(self) -> dict:
        """
        Analyze portfolio concentration across sectors, countries, and individual stocks.
        Returns weights, alerts, and a concentration score.
        """
        positions = await self.get_consolidated_positions()

        total_value = sum(
            (p["current_value"] or 0.0) for p in positions
        )

        if total_value == 0:
            return {"error": "No open positions"}

        # Sector weights
        sector_totals: dict[str, float] = {}
        country_totals: dict[str, float] = {}
        stock_totals: dict[str, float] = {}

        for p in positions:
            val = p["current_value"] or 0.0
            sector  = p["sector"]  or "Other"
            country = p["country"] or "Unknown"
            ticker  = p["ticker"]

            sector_totals[sector]   = sector_totals.get(sector, 0.0)   + val
            country_totals[country] = country_totals.get(country, 0.0) + val
            stock_totals[ticker]    = stock_totals.get(ticker, 0.0)    + val

        sector_weights  = {k: v / total_value for k, v in
                           sorted(sector_totals.items(),  key=lambda x: x[1], reverse=True)}
        country_weights = {k: v / total_value for k, v in
                           sorted(country_totals.items(), key=lambda x: x[1], reverse=True)}
        stock_weights   = {k: v / total_value for k, v in
                           sorted(stock_totals.items(),   key=lambda x: x[1], reverse=True)}

        alerts = self._generate_alerts(sector_weights, country_weights, stock_weights, total_value)
        concentration_score = self._concentration_score(sector_weights, stock_weights)

        # Top 10 holdings
        top_holdings = [
            {
                "ticker": ticker,
                "weight": round(w, 6),
                "value":  round(stock_totals[ticker], 2),
            }
            for ticker, w in list(stock_weights.items())[:10]
        ]

        return {
            "total_value":        round(total_value, 2),
            "position_count":     len(positions),
            "sector_weights":     {k: round(v, 6) for k, v in sector_weights.items()},
            "country_weights":    {k: round(v, 6) for k, v in country_weights.items()},
            "top_holdings":       top_holdings,
            "alerts":             alerts,
            "concentration_score": concentration_score,
        }

    def _generate_alerts(
        self,
        sector_weights: dict,
        country_weights: dict,
        stock_weights: dict,
        total_value: float,
    ) -> list[str]:
        """Generate natural-language alerts for concentration risks."""
        warnings: list[str] = []
        positives: list[str] = []

        # Sector overexposure
        for sector, w in sector_weights.items():
            if w > SECTOR_MAX_PCT:
                warnings.append(
                    f"⚠️ Overexposed to {sector}: {w:.0%} of portfolio "
                    f"(max recommended: {SECTOR_MAX_PCT:.0%})"
                )

        # Single-stock overexposure
        for ticker, w in stock_weights.items():
            if w > STOCK_MAX_PCT:
                warnings.append(
                    f"⚠️ {ticker} is {w:.0%} of portfolio — consider trimming "
                    f"(max recommended: {STOCK_MAX_PCT:.0%})"
                )

        # Country concentration
        for country, w in country_weights.items():
            if w > COUNTRY_MAX_PCT:
                warnings.append(
                    f"⚠️ {country} exposure at {w:.0%} — geographic concentration risk"
                )

        # Positive signals
        if not any(w > 0.20 for w in sector_weights.values()):
            positives.append("✅ Sector diversification is healthy")

        if stock_weights and max(stock_weights.values()) < 0.08:
            positives.append("✅ No single stock dominates the portfolio")

        return warnings + positives

    def _concentration_score(
        self,
        sector_weights: dict,
        stock_weights: dict,
    ) -> int:
        """
        Compute a 0–100 diversification score (100 = well diversified).
        Deductions for sectors over SECTOR_MAX_PCT and stocks over STOCK_MAX_PCT.
        """
        score = 100.0

        for w in sector_weights.values():
            if w > SECTOR_MAX_PCT:
                score -= (w - SECTOR_MAX_PCT) * 200

        for w in stock_weights.values():
            if w > STOCK_MAX_PCT:
                score -= (w - STOCK_MAX_PCT) * 300

        return max(0, min(100, int(score)))

    async def suggest_rebalancing(self, risk_profile: str = "MODERATE") -> list[dict]:
        """
        Generate ranked rebalancing trade suggestions.
        """
        analysis = await self.analyze_concentration()
        if "error" in analysis:
            return []

        total_value     = analysis["total_value"]
        sector_weights  = analysis["sector_weights"]
        stock_weights   = {h["ticker"]: h["weight"] for h in analysis["top_holdings"]}
        suggestions: list[dict] = []

        # Fetch all positions for sector membership
        positions = await self.get_consolidated_positions()
        ticker_sector: dict[str, str] = {
            p["ticker"]: (p["sector"] or "Other") for p in positions
        }
        ticker_value: dict[str, float] = {
            p["ticker"]: (p["current_value"] or 0.0) for p in positions
        }

        # Fetch BUY signals from the last 7 days
        buy_res = await self.db.execute(text("""
            SELECT ticker FROM ai_analysis
            WHERE signal = 'BUY' AND analysis_date >= NOW() - INTERVAL '7 days'
        """))
        buy_tickers = {row.ticker for row in buy_res.fetchall()}

        # --- Sector overweight: suggest REDUCE ---
        for sector, actual_w in sector_weights.items():
            target_w = SECTOR_TARGET_WEIGHTS.get(sector, 0.05)
            if actual_w > target_w + 0.05:
                overweight_pct = actual_w - target_w
                # Find the largest holding in this sector
                sector_holdings = [
                    (t, v) for t, v in ticker_value.items()
                    if ticker_sector.get(t) == sector
                ]
                if not sector_holdings:
                    continue
                largest_ticker, largest_val = max(sector_holdings, key=lambda x: x[1])
                suggested_amount = round(overweight_pct * total_value, 2)
                priority = "HIGH" if overweight_pct > 0.10 else "MEDIUM"
                suggestions.append({
                    "action":           "REDUCE",
                    "ticker":           largest_ticker,
                    "reason":           (
                        f"{sector} sector is {actual_w:.0%} of portfolio vs "
                        f"{target_w:.0%} target — trim {largest_ticker} to rebalance"
                    ),
                    "suggested_amount": suggested_amount,
                    "priority":         priority,
                    "current_weight":   round(actual_w, 6),
                    "target_weight":    round(target_w, 6),
                })

        # --- Sector underweight: suggest BUY if we have signals ---
        for sector, target_w in SECTOR_TARGET_WEIGHTS.items():
            actual_w = sector_weights.get(sector, 0.0)
            if actual_w < target_w - 0.05:
                gap_pct = target_w - actual_w
                # Look for BUY signals in this sector from the stocks table
                sector_buy_res = await self.db.execute(text("""
                    SELECT s.ticker
                    FROM stocks s
                    WHERE s.sector = :sector
                      AND s.ticker = ANY(:tickers)
                    LIMIT 1
                """), {"sector": sector, "tickers": list(buy_tickers) if buy_tickers else ["__none__"]})
                sector_buy_row = sector_buy_res.fetchone()
                if not sector_buy_row:
                    continue
                buy_ticker = sector_buy_row.ticker
                suggested_amount = round(gap_pct * total_value, 2)
                priority = "MEDIUM" if gap_pct > 0.05 else "LOW"
                suggestions.append({
                    "action":           "BUY",
                    "ticker":           buy_ticker,
                    "reason":           (
                        f"{sector} sector is underweight at {actual_w:.0%} vs "
                        f"{target_w:.0%} target — BUY signal available for {buy_ticker}"
                    ),
                    "suggested_amount": suggested_amount,
                    "priority":         priority,
                    "current_weight":   round(actual_w, 6),
                    "target_weight":    round(target_w, 6),
                })

        # --- Single-stock overexposure: trim to 8% ---
        for ticker, w in stock_weights.items():
            if w > STOCK_MAX_PCT:
                trim_to     = 0.08
                trim_amount = round((w - trim_to) * total_value, 2)
                suggestions.append({
                    "action":           "REDUCE",
                    "ticker":           ticker,
                    "reason":           (
                        f"{ticker} is {w:.0%} of portfolio — trim to ~{trim_to:.0%} "
                        f"to reduce single-stock concentration risk"
                    ),
                    "suggested_amount": trim_amount,
                    "priority":         "HIGH",
                    "current_weight":   round(w, 6),
                    "target_weight":    trim_to,
                })

        # Sort by priority: HIGH → MEDIUM → LOW
        priority_order = {"HIGH": 0, "MEDIUM": 1, "LOW": 2}
        suggestions.sort(key=lambda x: priority_order.get(x["priority"], 3))

        return suggestions

    async def get_rebalancing_report(self, risk_profile: str = "MODERATE") -> dict:
        """
        Combined report: concentration analysis + rebalancing suggestions.
        """
        concentration = await self.analyze_concentration()
        suggestions   = await self.suggest_rebalancing(risk_profile)

        return {
            **concentration,
            "risk_profile":  risk_profile,
            "suggestions":   suggestions,
            "suggestion_count": len(suggestions),
        }
