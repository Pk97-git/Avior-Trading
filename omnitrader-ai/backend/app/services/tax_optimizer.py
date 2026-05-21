"""
tax_optimizer.py
================
TaxOptimizerService — computes tax liability and suggests tax-loss harvesting.

India Tax Rules (FY):
  Equity (listed, STT paid):
    STCG (held < 12 months): flat 15%
    LTCG (held ≥ 12 months): 10% on gains > ₹1,00,000 (₹1 lakh exempt per year)
  Debt MF / Bonds: taxed at slab (20% for high earners — we use 20% as proxy)
  Dividend: taxed at slab (use 30% proxy for high earners)
  STT: 0.1% buy + 0.1% sell on delivery equity

US Tax Rules:
  Short-term capital gains (held < 365 days): 37% (top bracket proxy)
  Long-term capital gains (held ≥ 365 days): 20% (top bracket proxy)
  Net Investment Income Tax (NIIT): 3.8% on investment income above threshold
  Wash-sale rule: cannot repurchase same/substantially identical security
    within 30 days before or after harvesting loss

Tax-Loss Harvesting:
  Identify open positions with unrealized losses
  Estimate tax savings from realising the loss
  Flag wash-sale risk for any BUY signals on same ticker within last 30 days
  Suggest correlated replacement ticker (sector peer) to maintain exposure
"""
import logging
from datetime import date, datetime, timedelta, timezone
from typing import Optional
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import text

logger = logging.getLogger("omnitrader.services.tax_optimizer")

# ── Tax rate constants ─────────────────────────────────────────────────────────
INDIA_STCG_RATE   = 0.15
INDIA_LTCG_RATE   = 0.10
INDIA_LTCG_EXEMPT = 100_000   # ₹1 lakh annual exemption
INDIA_STT_RATE    = 0.001     # 0.1% each side delivery

US_STCG_RATE      = 0.37
US_LTCG_RATE      = 0.20
US_NIIT_RATE      = 0.038     # Net Investment Income Tax

# Correlated replacement tickers (for wash-sale avoidance)
SECTOR_PEERS = {
    "AAPL":  ["MSFT", "GOOGL"],   "MSFT": ["AAPL", "GOOGL"],
    "GOOGL": ["MSFT", "META"],    "AMZN": ["GOOGL", "SHOP"],
    "TSLA":  ["RIVN", "NIO"],     "META": ["SNAP", "PINS"],
    "JPM":   ["BAC", "WFC"],      "BAC":  ["JPM", "C"],
    "XOM":   ["CVX", "COP"],      "CVX":  ["XOM", "COP"],
    "RELIANCE.NS": ["ONGC.NS", "BPCL.NS"],
    "TCS.NS": ["INFY.NS", "WIPRO.NS"],   "INFY.NS": ["TCS.NS", "HCL.NS"],
    "HDFCBANK.NS": ["ICICIBANK.NS", "AXISBANK.NS"],
}


class TaxOptimizerService:
    def __init__(self, db: AsyncSession):
        self.db = db

    def _is_india(self, ticker: str) -> bool:
        return ".NS" in ticker or ".BO" in ticker

    def _holding_period_days(self, entry_date) -> int:
        if isinstance(entry_date, datetime):
            entry_date = entry_date.date()
        return (date.today() - entry_date).days

    def _india_tax(self, gain: float, holding_days: int, cumulative_ltcg: float = 0) -> dict:
        is_long_term = holding_days >= 365
        if is_long_term:
            term = "LTCG"
            rate = INDIA_LTCG_RATE
            if gain > 0:
                taxable = max(0.0, gain + cumulative_ltcg - INDIA_LTCG_EXEMPT)
                tax = taxable * INDIA_LTCG_RATE
            else:
                taxable = 0.0
                tax = 0.0
        else:
            term = "STCG"
            rate = INDIA_STCG_RATE
            tax = gain * INDIA_STCG_RATE if gain > 0 else 0.0

        return {
            "tax": tax,
            "rate": rate,
            "term": term,
            "is_long_term": is_long_term,
        }

    def _us_tax(self, gain: float, holding_days: int) -> dict:
        is_long_term = holding_days >= 365
        rate = (US_LTCG_RATE + US_NIIT_RATE) if is_long_term else (US_STCG_RATE + US_NIIT_RATE)
        tax = max(0.0, gain * rate)
        term = "LTCG" if is_long_term else "STCG"

        return {
            "tax": tax,
            "rate": rate,
            "term": term,
            "is_long_term": is_long_term,
        }

    async def get_portfolio_tax_summary(self) -> dict:
        today = date.today()
        # FY start: India = Apr 1 current year, US = Jan 1 current year
        india_fy_start = date(today.year, 4, 1) if today.month >= 4 else date(today.year - 1, 4, 1)
        us_fy_start = date(today.year, 1, 1)
        # Use the earlier of the two as the query bound
        fy_start = min(india_fy_start, us_fy_start)

        try:
            result = await self.db.execute(
                text("""
                    SELECT ticker, entry_price, current_price, quantity, entry_date,
                           exit_price, exit_date, status, country
                    FROM portfolio_positions
                    WHERE entry_date >= :fy_start
                    ORDER BY entry_date
                """),
                {"fy_start": fy_start},
            )
            rows = result.mappings().all()
        except Exception as e:
            logger.error("get_portfolio_tax_summary query failed: %s", e)
            rows = []

        summary = {
            "india": {
                "STCG": {"unrealized_gains": 0.0, "unrealized_losses": 0.0,
                          "realized_gains": 0.0, "tax_liability": 0.0},
                "LTCG": {"unrealized_gains": 0.0, "unrealized_losses": 0.0,
                          "realized_gains": 0.0, "tax_liability": 0.0},
            },
            "us": {
                "STCG": {"unrealized_gains": 0.0, "unrealized_losses": 0.0,
                          "realized_gains": 0.0, "tax_liability": 0.0},
                "LTCG": {"unrealized_gains": 0.0, "unrealized_losses": 0.0,
                          "realized_gains": 0.0, "tax_liability": 0.0},
            },
            "total_unrealized_gains": 0.0,
            "total_unrealized_losses": 0.0,
            "total_realized_gains": 0.0,
            "total_realized_tax_liability": 0.0,
            "estimated_tax_if_all_sold": 0.0,
            "positions_count": len(rows),
            "fy_start": str(fy_start),
        }

        # Track cumulative India LTCG for the exemption calculation
        cumulative_india_ltcg = 0.0

        for row in rows:
            ticker = row["ticker"]
            entry_price = float(row["entry_price"] or 0)
            current_price = float(row["current_price"] or entry_price)
            quantity = float(row["quantity"] or 0)
            entry_date = row["entry_date"]
            exit_price = row["exit_price"]
            status = row["status"]
            country = (row["country"] or "").upper()

            if isinstance(entry_date, datetime):
                entry_date = entry_date.date()

            holding_days = self._holding_period_days(entry_date)
            is_india = self._is_india(ticker) or country in ("IN", "INDIA")
            country_key = "india" if is_india else "us"

            if status == "OPEN":
                unrealized_gain = (current_price - entry_price) * quantity

                if is_india:
                    tax_info = self._india_tax(unrealized_gain, holding_days, cumulative_india_ltcg)
                else:
                    tax_info = self._us_tax(unrealized_gain, holding_days)

                term = tax_info["term"]
                bucket = summary[country_key][term]

                if unrealized_gain >= 0:
                    bucket["unrealized_gains"] += unrealized_gain
                    summary["total_unrealized_gains"] += unrealized_gain
                else:
                    bucket["unrealized_losses"] += unrealized_gain
                    summary["total_unrealized_losses"] += unrealized_gain

                summary["estimated_tax_if_all_sold"] += tax_info["tax"]

            elif status == "CLOSED" and exit_price is not None:
                realized_gain = (float(exit_price) - entry_price) * quantity

                if is_india:
                    tax_info = self._india_tax(realized_gain, holding_days, cumulative_india_ltcg)
                    if tax_info["is_long_term"] and realized_gain > 0:
                        cumulative_india_ltcg += realized_gain
                else:
                    tax_info = self._us_tax(realized_gain, holding_days)

                term = tax_info["term"]
                bucket = summary[country_key][term]
                bucket["realized_gains"] += realized_gain
                bucket["tax_liability"] += tax_info["tax"]
                summary["total_realized_gains"] += realized_gain
                summary["total_realized_tax_liability"] += tax_info["tax"]

        return summary

    async def get_harvesting_opportunities(self) -> list[dict]:
        try:
            result = await self.db.execute(
                text("""
                    SELECT p.ticker, p.entry_price, p.current_price, p.quantity,
                           p.entry_date, p.status, s.country, s.sector
                    FROM portfolio_positions p
                    LEFT JOIN stocks s ON s.ticker = p.ticker
                    WHERE p.status = 'OPEN' AND p.current_price < p.entry_price
                    ORDER BY (p.current_price - p.entry_price) * p.quantity ASC
                    LIMIT 20
                """)
            )
            rows = result.mappings().all()
        except Exception as e:
            logger.error("get_harvesting_opportunities query failed: %s", e)
            rows = []

        opportunities = []
        for row in rows:
            ticker = row["ticker"]
            entry_price = float(row["entry_price"] or 0)
            current_price = float(row["current_price"] or entry_price)
            quantity = float(row["quantity"] or 0)
            entry_date = row["entry_date"]
            country = row["country"] or ""
            sector = row["sector"] or ""

            if isinstance(entry_date, datetime):
                entry_date = entry_date.date()

            holding_days = self._holding_period_days(entry_date)
            unrealized_loss = (current_price - entry_price) * quantity  # negative number

            is_india = self._is_india(ticker) or (country or "").upper() in ("IN", "INDIA")
            if is_india:
                tax_info = self._india_tax(abs(unrealized_loss), holding_days)
            else:
                tax_info = self._us_tax(abs(unrealized_loss), holding_days)

            tax_savings = abs(unrealized_loss) * tax_info["rate"]

            # Check wash-sale risk: any BUY signal in last 30 days
            wash_sale_risk = False
            try:
                ws_result = await self.db.execute(
                    text("""
                        SELECT COUNT(*) FROM ai_analysis
                        WHERE ticker = :t AND signal = 'BUY'
                          AND analysis_date >= NOW() - INTERVAL '30 days'
                    """),
                    {"t": ticker},
                )
                wash_sale_count = ws_result.scalar() or 0
                wash_sale_risk = wash_sale_count > 0
            except Exception as e:
                logger.warning("Wash-sale check failed for %s: %s", ticker, e)

            replacement = SECTOR_PEERS.get(ticker, [])

            if tax_savings > 1000:
                priority = "HIGH"
            elif tax_savings > 200:
                priority = "MEDIUM"
            else:
                priority = "LOW"

            opportunities.append({
                "ticker": ticker,
                "sector": sector,
                "country": country,
                "unrealized_loss": round(unrealized_loss, 2),
                "tax_savings_estimate": round(tax_savings, 2),
                "holding_days": holding_days,
                "term": tax_info["term"],
                "wash_sale_risk": wash_sale_risk,
                "suggested_replacement": replacement[:2],
                "action": "HARVEST_LOSS",
                "priority": priority,
            })

        return opportunities

    async def get_year_end_summary(self) -> dict:
        tax_summary = await self.get_portfolio_tax_summary()
        harvesting_opportunities = await self.get_harvesting_opportunities()

        total_potential_savings = sum(
            opp["tax_savings_estimate"] for opp in harvesting_opportunities
        )
        net_tax_if_harvest = (
            tax_summary["total_realized_tax_liability"] - total_potential_savings
        )

        # Build actionable recommendations
        recommendations = []

        high_priority = [o for o in harvesting_opportunities if o["priority"] == "HIGH"]
        medium_priority = [o for o in harvesting_opportunities if o["priority"] == "MEDIUM"]

        if high_priority:
            recommendations.append({
                "type": "HARVEST_HIGH_PRIORITY",
                "message": (
                    f"Harvest losses on {len(high_priority)} position(s) "
                    f"({', '.join(o['ticker'] for o in high_priority)}) "
                    f"for estimated savings of "
                    f"₹/$ {sum(o['tax_savings_estimate'] for o in high_priority):,.2f}."
                ),
                "tickers": [o["ticker"] for o in high_priority],
            })

        if medium_priority:
            recommendations.append({
                "type": "HARVEST_MEDIUM_PRIORITY",
                "message": (
                    f"Consider harvesting losses on {len(medium_priority)} medium-priority "
                    f"position(s) for additional savings of "
                    f"₹/$ {sum(o['tax_savings_estimate'] for o in medium_priority):,.2f}."
                ),
                "tickers": [o["ticker"] for o in medium_priority],
            })

        wash_sale_risks = [o for o in harvesting_opportunities if o["wash_sale_risk"]]
        if wash_sale_risks:
            recommendations.append({
                "type": "WASH_SALE_WARNING",
                "message": (
                    f"Wash-sale risk detected for {len(wash_sale_risks)} ticker(s): "
                    f"{', '.join(o['ticker'] for o in wash_sale_risks)}. "
                    "Wait 30 days after harvesting before repurchasing."
                ),
                "tickers": [o["ticker"] for o in wash_sale_risks],
            })

        if net_tax_if_harvest < tax_summary["total_realized_tax_liability"]:
            recommendations.append({
                "type": "NET_TAX_REDUCTION",
                "message": (
                    f"By harvesting all identified losses, your estimated net tax liability "
                    f"drops from ₹/$ {tax_summary['total_realized_tax_liability']:,.2f} "
                    f"to ₹/$ {max(0, net_tax_if_harvest):,.2f}."
                ),
            })

        return {
            **tax_summary,
            "harvesting_opportunities": harvesting_opportunities,
            "total_potential_tax_savings": round(total_potential_savings, 2),
            "net_tax_if_harvest": round(max(0.0, net_tax_if_harvest), 2),
            "recommendations": recommendations,
            "generated_at": datetime.now(timezone.utc).isoformat(),
        }
