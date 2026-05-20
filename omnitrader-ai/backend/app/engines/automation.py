"""
engines/automation.py
=====================
AutomationEngine — executes user-defined automation rules on schedule.

Rule types:
  AUTO_REBALANCE  — rebalance portfolio when sector/stock drift exceeds threshold
  AUTO_SIP        — systematic investment plan: periodic BUY orders
  AUTO_STOP_LOSS  — run the trailing stop engine (tighten stops after gains)
  AUTO_HEDGE      — reduce equity or buy inverse ETF when regime = Risk-Off/Recession
"""
import logging
from datetime import datetime, timedelta, timezone

from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, text, update

logger = logging.getLogger("omnitrader")

# ── Try importing models (may not exist if migration hasn't run yet) ───────────
try:
    from app.models.market_data import AutomationRule
    _MODELS_AVAILABLE = True
except ImportError:
    AutomationRule = None  # type: ignore
    _MODELS_AVAILABLE = False


class AutomationEngine:
    """
    Executes AutomationRule rows that are due (next_run_at <= NOW or IS NULL).
    """

    def __init__(self, db: AsyncSession):
        self.db = db

    # ─────────────────────────────────────────────────────────────────────────
    # Public entry point
    # ─────────────────────────────────────────────────────────────────────────

    async def run_all_rules(self) -> dict:
        """
        Load all active AutomationRule rows that are due, execute each handler,
        update bookkeeping columns, and return a summary.

        Returns:
            {"executed": int, "results": list[dict]}
        """
        if not _MODELS_AVAILABLE:
            logger.warning("[AutomationEngine] AutomationRule model not available — skipping.")
            return {"executed": 0, "results": [], "error": "models_not_available"}

        now = datetime.now(timezone.utc)

        stmt = select(AutomationRule).where(
            AutomationRule.is_active == True,  # noqa: E712
        )
        rows = (await self.db.execute(stmt)).scalars().all()

        # Filter in Python to handle NULL next_run_at gracefully
        due_rules = [
            r for r in rows
            if r.next_run_at is None or r.next_run_at <= now
        ]

        executed = 0
        results: list[dict] = []

        for rule in due_rules:
            try:
                handler = self._get_handler(rule.rule_type)
                if handler is None:
                    logger.warning("[AutomationEngine] Unknown rule_type: %s", rule.rule_type)
                    result = {"status": "error", "message": f"Unknown rule_type: {rule.rule_type}"}
                else:
                    result = await handler(rule)
                    executed += 1

                # Update bookkeeping
                await self.db.execute(
                    update(AutomationRule)
                    .where(AutomationRule.id == rule.id)
                    .values(
                        last_run_at=now,
                        run_count=(rule.run_count or 0) + 1,
                        last_result=result,
                        next_run_at=self._compute_next_run(rule),
                    )
                )
                await self.db.commit()

                results.append({"id": rule.id, "name": rule.name, "rule_type": rule.rule_type, **result})

            except Exception as exc:
                logger.error("[AutomationEngine] Rule %s (%s) failed: %s", rule.id, rule.rule_type, exc)
                results.append({"id": rule.id, "name": rule.name, "rule_type": rule.rule_type,
                                 "status": "error", "message": str(exc)})

        return {"executed": executed, "results": results}

    # ─────────────────────────────────────────────────────────────────────────
    # Handler dispatch
    # ─────────────────────────────────────────────────────────────────────────

    def _get_handler(self, rule_type: str):
        return {
            "AUTO_REBALANCE": self._run_auto_rebalance,
            "AUTO_SIP":       self._run_auto_sip,
            "AUTO_STOP_LOSS": self._run_auto_stop_loss,
            "AUTO_HEDGE":     self._run_auto_hedge,
        }.get(rule_type)

    # ─────────────────────────────────────────────────────────────────────────
    # Handlers
    # ─────────────────────────────────────────────────────────────────────────

    async def _run_auto_rebalance(self, rule) -> dict:
        """
        Rebalance portfolio when sector/stock drift exceeds threshold.

        Config: {"drift_threshold_pct": 5.0, "dry_run": false}
        """
        try:
            from app.services.rebalancer import RebalancerService
            svc = RebalancerService(self.db)
            suggestions = await svc.suggest_rebalancing()
            alerts = suggestions.get("alerts", [])

            overweights = [a for a in alerts if "Overexposed" in a]
            if not overweights:
                return {"status": "ok", "message": "Portfolio within tolerance", "actions": []}

            dry_run = rule.config.get("dry_run", True) if rule.config else True
            actions = []

            if not dry_run:
                # Execute top suggestion from suggest_rebalancing buys
                for item in (suggestions.get("buys") or [])[:2]:
                    from app.services.order_manager import OrderManager
                    om = OrderManager(self.db)
                    result = await om.submit_from_analysis(ticker=item["ticker"])
                    actions.append({"action": "BUY", "ticker": item["ticker"], "result": result["status"]})

            return {
                "status": "rebalanced" if not dry_run else "dry_run",
                "alerts": overweights,
                "actions": actions,
            }
        except Exception as e:
            return {"status": "error", "message": str(e)}

    async def _run_auto_sip(self, rule) -> dict:
        """
        Systematic investment plan: periodic BUY orders for configured tickers.

        Config: {"tickers": ["NIFTY_BEES.NS", "AAPL", "QQQ"], "amount_per_ticker": 5000, "currency": "INR"}
        """
        config = rule.config or {}
        tickers = config.get("tickers", [])
        amount = float(config.get("amount_per_ticker", 1000))
        results = []
        for ticker in tickers:
            try:
                price_r = await self.db.execute(
                    text("SELECT close FROM stock_prices WHERE ticker=:t ORDER BY time DESC LIMIT 1"),
                    {"t": ticker},
                )
                row = price_r.fetchone()
                if not row or not row.close:
                    results.append({"ticker": ticker, "status": "skipped", "reason": "no price"})
                    continue
                qty = max(1, int(amount / row.close))
                from app.services.order_manager import OrderManager
                om = OrderManager(self.db)
                result = await om.submit_manual(
                    ticker=ticker,
                    side="BUY",
                    qty=qty,
                    order_type="MARKET",
                    notes=f"Auto-SIP rule: {rule.name}",
                )
                results.append({"ticker": ticker, "status": result["status"], "qty": qty})
            except Exception as e:
                results.append({"ticker": ticker, "status": "error", "reason": str(e)})
        return {"status": "completed", "sip_results": results}

    async def _run_auto_stop_loss(self, rule) -> dict:
        """
        Run the trailing stop engine to tighten stop-losses after gains.

        Config: {"atr_multiplier": 2.0}
        """
        try:
            from app.services.trailing_stops import TrailingStopService
            svc = TrailingStopService(self.db)
            result = await svc.run()
            return {
                "status": "completed",
                "updated": len(result.get("updated", [])),
                "needs_exit": len(result.get("needs_exit", [])),
                "skipped": result.get("skipped", 0),
            }
        except Exception as e:
            return {"status": "error", "message": str(e)}

    async def _run_auto_hedge(self, rule) -> dict:
        """
        Buy a hedge position when macro regime turns Risk-Off or Recession.

        Config: {"hedge_ticker": "SBIN.NS", "hedge_amount_pct": 10, "trigger_regime": ["Risk-Off", "Recession"]}
        """
        try:
            from app.engines.regime import MacroRegimeClassifier
            clf = MacroRegimeClassifier(self.db)
            regime_data = await clf.classify()
            regime = regime_data.get("regime", "Unknown")

            config = rule.config or {}
            trigger_regimes = config.get("trigger_regime", ["Risk-Off", "Recession"])
            hedge_ticker = config.get("hedge_ticker", "SBIN.NS")
            hedge_pct = float(config.get("hedge_amount_pct", 10))

            if regime not in trigger_regimes:
                return {
                    "status": "ok",
                    "message": f"Current regime: {regime} — no hedge needed",
                    "regime": regime,
                }

            # Check if hedge already held
            existing = await self.db.execute(
                text("SELECT id FROM portfolio_positions WHERE ticker=:t AND is_open=TRUE LIMIT 1"),
                {"t": hedge_ticker},
            )
            if existing.fetchone():
                return {
                    "status": "ok",
                    "message": f"Hedge {hedge_ticker} already held",
                    "regime": regime,
                }

            # Compute portfolio value
            pv_r = await self.db.execute(text("""
                SELECT SUM(pp.shares * sp.close) AS total
                FROM portfolio_positions pp
                LEFT JOIN LATERAL (
                    SELECT close FROM stock_prices
                    WHERE ticker=pp.ticker
                    ORDER BY time DESC LIMIT 1
                ) sp ON true
                WHERE pp.is_open=TRUE
            """))
            pv_row = pv_r.fetchone()
            portfolio_value = float(pv_row.total or 100_000) if pv_row else 100_000

            hedge_amount = portfolio_value * hedge_pct / 100

            price_r = await self.db.execute(
                text("SELECT close FROM stock_prices WHERE ticker=:t ORDER BY time DESC LIMIT 1"),
                {"t": hedge_ticker},
            )
            price_row = price_r.fetchone()
            if not price_row or not price_row.close:
                return {"status": "skipped", "reason": f"No price for hedge ticker {hedge_ticker}"}

            qty = max(1, int(hedge_amount / price_row.close))
            from app.services.order_manager import OrderManager
            om = OrderManager(self.db)
            result = await om.submit_manual(
                ticker=hedge_ticker,
                side="BUY",
                qty=qty,
                order_type="MARKET",
                notes=f"Auto-hedge: {regime} regime",
            )
            return {
                "status": "hedged",
                "regime": regime,
                "ticker": hedge_ticker,
                "qty": qty,
                "order_status": result["status"],
            }
        except Exception as e:
            return {"status": "error", "message": str(e)}

    # ─────────────────────────────────────────────────────────────────────────
    # Scheduling helpers
    # ─────────────────────────────────────────────────────────────────────────

    def _compute_next_run(self, rule) -> datetime:
        """
        Return the next scheduled run time based on rule_type:
          AUTO_SIP:        weekly  (7 days)
          AUTO_REBALANCE:  daily   (1 day)
          AUTO_STOP_LOSS:  hourly  (1 hour)
          AUTO_HEDGE:      every 4 hours
        """
        now = datetime.now(timezone.utc)
        intervals = {
            "AUTO_SIP":       timedelta(days=7),
            "AUTO_REBALANCE": timedelta(days=1),
            "AUTO_STOP_LOSS": timedelta(hours=1),
            "AUTO_HEDGE":     timedelta(hours=4),
        }
        return now + intervals.get(rule.rule_type, timedelta(days=1))
