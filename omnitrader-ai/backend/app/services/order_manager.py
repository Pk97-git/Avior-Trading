"""
services/order_manager.py
=========================
OrderManager — orchestrates order submission through the full pipeline:

  circuit breaker → market-hours check → position sizing → broker → DB persist

Supports:
  - submit_from_analysis()        : BUY from AI analysis result (signal-driven)
  - submit_bracket_order()        : entry + stop loss + take profit as atomic order
  - submit_stop_order()           : stop-market or stop-limit order
  - submit_trailing_stop_order()  : trailing stop order
  - submit_manual()               : manual BUY/SELL bypassing signal requirements
  - sync_order_statuses()         : poll broker for PENDING order updates
  - sync_broker_positions()       : reconcile broker holdings ↔ portfolio_positions table
"""
from __future__ import annotations

import json

import logging
from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.market_data import Order, PortfolioPosition, Stock
from app.brokers.base import BracketOrderResult
from app.brokers.factory import get_broker
from app.engines.circuit_breaker import CircuitBreakerEngine

logger = logging.getLogger(__name__)


class OrderManager:
    """
    Orchestrates order submission: circuit breaker → market hours → sizing
    → broker → persist to DB.
    """

    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    # ──────────────────────────────────────────────────────────────────────────
    # Helpers
    # ──────────────────────────────────────────────────────────────────────────

    async def _latest_price(self, ticker: str) -> Optional[float]:
        """Return the most recent closing price for a ticker, or None."""
        result = await self.db.execute(
            text("""
                SELECT close FROM stock_prices
                WHERE ticker = :ticker
                ORDER BY time DESC
                LIMIT 1
            """),
            {"ticker": ticker},
        )
        row = result.fetchone()
        return float(row.close) if row and row.close else None

    async def _get_stock_country(self, ticker: str) -> str:
        """Return the country code for a ticker ('US' or 'IN'), defaulting to 'US'."""
        result = await self.db.execute(
            select(Stock.country).where(Stock.ticker == ticker)
        )
        row = result.fetchone()
        return (row.country or "US") if row else "US"

    async def _latest_analysis(self, ticker: str) -> Optional[dict]:
        """Return the most recent AIAnalysis row as a dict, or None."""
        result = await self.db.execute(
            text("""
                SELECT signal, final_score, max_position_pct, entry_price,
                       stop_loss, take_profit, regime
                FROM ai_analysis
                WHERE ticker = :ticker
                ORDER BY analysis_date DESC
                LIMIT 1
            """),
            {"ticker": ticker},
        )
        row = result.fetchone()
        if not row:
            return None
        return {
            "signal":           row.signal,
            "final_score":      row.final_score,
            "max_position_pct": row.max_position_pct,
            "entry_price":      row.entry_price,
            "stop_loss":        row.stop_loss,
            "take_profit":      row.take_profit,
            "regime":           row.regime,
        }

    def _compute_qty(
        self, portfolio_value: float, max_position_pct: float, price: float
    ) -> int:
        """Compute share quantity using half-Kelly sizing, minimum 1."""
        if price <= 0:
            return 1
        raw = (max_position_pct / 100.0) * portfolio_value / price
        return max(1, int(raw))

    # ──────────────────────────────────────────────────────────────────────────
    # Core submission methods
    # ──────────────────────────────────────────────────────────────────────────

    async def submit_from_analysis(
        self,
        ticker: str,
        analysis: Optional[dict] = None,
        notes: Optional[str] = None,
    ) -> dict:
        """
        Submit a BUY order derived from the latest AI analysis for a ticker.

        Steps:
          1. Run circuit-breaker check — abort if HALT.
          2. Load latest analysis if not supplied.
          3. Determine country and broker.
          4. Get current price from DB.
          5. Get account balance to compute position size.
          6. Halve size if circuit breaker is in CAUTION.
          7. Use LIMIT order at last price when market is closed.
          8. Place order via broker.
          9. Persist Order + PortfolioPosition (if BUY fills).

        Returns:
            {
                "status":   "submitted" | "skipped" | "halted",
                "reason":   str,
                "order_id": int | None,   # DB primary key
            }
        """
        ticker = ticker.upper()

        # ── 1. Circuit breaker ────────────────────────────────────────────────
        cb_engine = CircuitBreakerEngine(self.db)
        cb = await cb_engine.check()

        if cb["status"] == "HALT":
            reason = "; ".join(cb["reasons"]) or "Circuit breaker HALT"
            logger.warning("[OrderManager] HALT for %s: %s", ticker, reason)
            return {"status": "halted", "reason": reason, "order_id": None}

        # ── 2. Load analysis ─────────────────────────────────────────────────
        if analysis is None:
            analysis = await self._latest_analysis(ticker)

        if not analysis:
            return {
                "status": "skipped",
                "reason": f"No AI analysis found for {ticker}",
                "order_id": None,
            }

        signal = (analysis.get("signal") or "").upper()
        if signal != "BUY":
            return {
                "status": "skipped",
                "reason": f"Signal '{signal}' is not actionable for entry (need BUY)",
                "order_id": None,
            }

        max_position_pct = float(analysis.get("max_position_pct") or 5.0)
        final_score = analysis.get("final_score")

        # ── 3. Country + broker ───────────────────────────────────────────────
        country = await self._get_stock_country(ticker)
        broker = get_broker(country)

        # ── 4. Current price ─────────────────────────────────────────────────
        current_price = await self._latest_price(ticker)
        if not current_price:
            current_price = analysis.get("entry_price") or 0.0

        if not current_price:
            return {
                "status": "skipped",
                "reason": f"No price data available for {ticker}",
                "order_id": None,
            }

        # ── 5. Position sizing ────────────────────────────────────────────────
        balance = await broker.get_account_balance()
        portfolio_value = balance.portfolio_value or balance.cash or 100_000.0

        qty = self._compute_qty(portfolio_value, max_position_pct, current_price)

        # ── 6. CAUTION → halve position size ─────────────────────────────────
        if cb["status"] == "CAUTION":
            qty = max(1, qty // 2)
            logger.info(
                "[OrderManager] CAUTION mode: halved position size to %d for %s", qty, ticker
            )

        # ── 7. Market-hours check → LIMIT if closed ───────────────────────────
        market_open = broker.is_market_open(country)
        if market_open:
            order_type = "MARKET"
            limit_price = None
        else:
            order_type = "LIMIT"
            limit_price = round(current_price, 4)
            logger.info(
                "[OrderManager] Market closed — using LIMIT @ %.4f for %s", limit_price, ticker
            )

        # ── 8. Place order ────────────────────────────────────────────────────
        result = await broker.place_order(
            ticker=ticker,
            side="BUY",
            qty=qty,
            order_type=order_type,
            limit_price=limit_price,
        )
        logger.info(
            "[OrderManager] %s order for %s: broker_id=%s status=%s",
            broker.name, ticker, result.broker_order_id, result.status,
        )

        # ── 9. Persist Order record ───────────────────────────────────────────
        now = datetime.now(timezone.utc)
        order = Order(
            ticker=ticker,
            created_at=now,
            side="BUY",
            order_type=order_type,
            qty=float(qty),
            limit_price=limit_price,
            broker=broker.name,
            broker_order_id=result.broker_order_id,
            status=result.status,
            filled_qty=result.filled_qty,
            filled_price=result.filled_price,
            filled_at=now if result.status == "FILLED" else None,
            signal=signal,
            final_score=final_score,
            notes=notes or result.message,
        )
        self.db.add(order)
        await self.db.flush()  # get order.id before creating position

        # ── 10. Create PortfolioPosition on fill ──────────────────────────────
        if result.status == "FILLED" and result.filled_price and result.filled_qty:
            fill_price = result.filled_price
            fill_qty = result.filled_qty

            pos = PortfolioPosition(
                ticker=ticker,
                entry_date=now,
                entry_price=fill_price,
                shares=fill_qty,
                position_value=round(fill_price * fill_qty, 2),
                stop_loss=analysis.get("stop_loss"),
                take_profit=analysis.get("take_profit"),
                signal=signal,
                regime=analysis.get("regime"),
                notes=notes,
                is_open=True,
            )
            self.db.add(pos)
            await self.db.flush()
            order.portfolio_position_id = pos.id

        await self.db.commit()
        await self.db.refresh(order)

        return {
            "status":   "submitted",
            "reason":   result.message,
            "order_id": order.id,
            "broker":   broker.name,
            "broker_order_id": result.broker_order_id,
            "order_status": result.status,
            "qty":      qty,
            "order_type": order_type,
            "limit_price": limit_price,
        }

    async def submit_reduce(
        self,
        ticker: str,
        quantity: int,
        analysis: dict,
        notes: Optional[str] = None,
    ) -> dict:
        """
        Submit a partial exit order (REDUCE signal — sell specified quantity).

        Routes through the same broker factory as submit_from_analysis but
        with side=SELL and the caller-supplied quantity.

        Returns:
            {
                "status":   "submitted" | "skipped" | "halted",
                "reason":   str,
                "order_id": int | None,
            }
        """
        ticker = ticker.upper()

        # Circuit breaker (soft check — REDUCE is a defensive action, don't block on CAUTION)
        cb_engine = CircuitBreakerEngine(self.db)
        cb = await cb_engine.check()
        if cb["status"] == "HALT":
            reason = "; ".join(cb["reasons"]) or "Circuit breaker HALT"
            logger.warning("[OrderManager] HALT for REDUCE %s: %s", ticker, reason)
            return {"status": "halted", "reason": reason, "order_id": None}

        if quantity <= 0:
            return {"status": "skipped", "reason": "quantity must be positive", "order_id": None}

        country = await self._get_stock_country(ticker)
        broker = get_broker(country)

        current_price = await self._latest_price(ticker)
        market_open = broker.is_market_open(country)
        if market_open:
            order_type = "MARKET"
            limit_price = None
        else:
            order_type = "LIMIT"
            limit_price = round(current_price, 4) if current_price else None

        signal = (analysis.get("signal") or "REDUCE").upper()
        final_score = analysis.get("final_score")

        result = await broker.place_order(
            ticker=ticker,
            side="SELL",
            qty=quantity,
            order_type=order_type,
            limit_price=limit_price,
        )
        logger.info(
            "[OrderManager] REDUCE %s: qty=%d broker_id=%s status=%s",
            ticker, quantity, result.broker_order_id, result.status,
        )

        now = datetime.now(timezone.utc)
        order = Order(
            ticker=ticker,
            created_at=now,
            side="SELL",
            order_type=order_type,
            qty=float(quantity),
            limit_price=limit_price,
            broker=broker.name,
            broker_order_id=result.broker_order_id,
            status=result.status,
            filled_qty=result.filled_qty,
            filled_price=result.filled_price,
            filled_at=now if result.status == "FILLED" else None,
            signal=signal,
            final_score=final_score,
            notes=notes or result.message,
        )
        self.db.add(order)
        await self.db.flush()
        await self.db.commit()
        await self.db.refresh(order)

        return {
            "status":          "submitted",
            "reason":          result.message,
            "order_id":        order.id,
            "broker":          broker.name,
            "broker_order_id": result.broker_order_id,
            "order_status":    result.status,
            "qty":             quantity,
            "order_type":      order_type,
            "limit_price":     limit_price,
        }

    async def submit_sell(
        self,
        ticker: str,
        quantity: int,
        analysis: dict,
        notes: Optional[str] = None,
    ) -> dict:
        """
        Submit a full exit order (SELL signal).

        Routes through the same broker factory as submit_from_analysis but
        with side=SELL for the full position quantity.

        Returns:
            {
                "status":   "submitted" | "skipped" | "halted",
                "reason":   str,
                "order_id": int | None,
            }
        """
        ticker = ticker.upper()

        # Circuit breaker (soft check — SELL is a defensive action, don't block on CAUTION)
        cb_engine = CircuitBreakerEngine(self.db)
        cb = await cb_engine.check()
        if cb["status"] == "HALT":
            reason = "; ".join(cb["reasons"]) or "Circuit breaker HALT"
            logger.warning("[OrderManager] HALT for SELL %s: %s", ticker, reason)
            return {"status": "halted", "reason": reason, "order_id": None}

        if quantity <= 0:
            return {"status": "skipped", "reason": "quantity must be positive", "order_id": None}

        country = await self._get_stock_country(ticker)
        broker = get_broker(country)

        current_price = await self._latest_price(ticker)
        market_open = broker.is_market_open(country)
        if market_open:
            order_type = "MARKET"
            limit_price = None
        else:
            order_type = "LIMIT"
            limit_price = round(current_price, 4) if current_price else None

        signal = (analysis.get("signal") or "SELL").upper()
        final_score = analysis.get("final_score")

        result = await broker.place_order(
            ticker=ticker,
            side="SELL",
            qty=quantity,
            order_type=order_type,
            limit_price=limit_price,
        )
        logger.info(
            "[OrderManager] SELL %s: qty=%d broker_id=%s status=%s",
            ticker, quantity, result.broker_order_id, result.status,
        )

        now = datetime.now(timezone.utc)
        order = Order(
            ticker=ticker,
            created_at=now,
            side="SELL",
            order_type=order_type,
            qty=float(quantity),
            limit_price=limit_price,
            broker=broker.name,
            broker_order_id=result.broker_order_id,
            status=result.status,
            filled_qty=result.filled_qty,
            filled_price=result.filled_price,
            filled_at=now if result.status == "FILLED" else None,
            signal=signal,
            final_score=final_score,
            notes=notes or result.message,
        )
        self.db.add(order)
        await self.db.flush()
        await self.db.commit()
        await self.db.refresh(order)

        return {
            "status":          "submitted",
            "reason":          result.message,
            "order_id":        order.id,
            "broker":          broker.name,
            "broker_order_id": result.broker_order_id,
            "order_status":    result.status,
            "qty":             quantity,
            "order_type":      order_type,
            "limit_price":     limit_price,
        }

    async def submit_manual(
        self,
        ticker: str,
        side: str,
        qty: float,
        order_type: str = "MARKET",
        limit_price: Optional[float] = None,
        notes: Optional[str] = None,
    ) -> dict:
        """
        Manual order submission bypassing signal requirements.

        Still checks circuit breaker (but only warns — does not block).
        Uses the same broker-selection logic as submit_from_analysis.

        Returns:
            {
                "status":   "submitted" | "rejected",
                "reason":   str,
                "order_id": int | None,
            }
        """
        ticker = ticker.upper()
        side = side.upper()

        if side not in ("BUY", "SELL"):
            return {"status": "rejected", "reason": f"Invalid side '{side}'", "order_id": None}
        if qty <= 0:
            return {"status": "rejected", "reason": "qty must be positive", "order_id": None}

        # Soft circuit-breaker check (log warning, don't block manual orders)
        try:
            cb_engine = CircuitBreakerEngine(self.db)
            cb = await cb_engine.check()
            if cb["status"] == "HALT":
                logger.warning(
                    "[OrderManager] Manual order for %s submitted despite HALT: %s",
                    ticker, cb["reasons"],
                )
        except Exception as exc:
            logger.warning("[OrderManager] Circuit breaker check failed (non-blocking): %s", exc)

        country = await self._get_stock_country(ticker)
        broker = get_broker(country)

        # If no limit_price provided and market is closed, use last close
        market_open = broker.is_market_open(country)
        if not market_open and order_type.upper() == "MARKET":
            order_type = "LIMIT"
            if limit_price is None:
                limit_price = await self._latest_price(ticker)
                if limit_price:
                    limit_price = round(limit_price, 4)
                else:
                    # Can't determine a limit price — reject gracefully
                    return {
                        "status": "rejected",
                        "reason": (
                            "Market is closed and no price data found to set a limit price."
                        ),
                        "order_id": None,
                    }

        result = await broker.place_order(
            ticker=ticker,
            side=side,
            qty=qty,
            order_type=order_type.upper(),
            limit_price=limit_price,
        )

        now = datetime.now(timezone.utc)
        order = Order(
            ticker=ticker,
            created_at=now,
            side=side,
            order_type=order_type.upper(),
            qty=float(qty),
            limit_price=limit_price,
            broker=broker.name,
            broker_order_id=result.broker_order_id,
            status=result.status,
            filled_qty=result.filled_qty,
            filled_price=result.filled_price,
            filled_at=now if result.status == "FILLED" else None,
            signal="MANUAL",
            notes=notes or result.message,
        )
        self.db.add(order)

        # Create PortfolioPosition for filled BUY orders
        if side == "BUY" and result.status == "FILLED" and result.filled_price and result.filled_qty:
            await self.db.flush()
            pos = PortfolioPosition(
                ticker=ticker,
                entry_date=now,
                entry_price=result.filled_price,
                shares=result.filled_qty,
                position_value=round(result.filled_price * result.filled_qty, 2),
                signal="MANUAL",
                notes=notes,
                is_open=True,
            )
            self.db.add(pos)
            await self.db.flush()
            order.portfolio_position_id = pos.id

        await self.db.commit()
        await self.db.refresh(order)

        return {
            "status":          "submitted",
            "reason":          result.message,
            "order_id":        order.id,
            "broker":          broker.name,
            "broker_order_id": result.broker_order_id,
            "order_status":    result.status,
        }

    # ──────────────────────────────────────────────────────────────────────────
    # Synchronisation methods
    # ──────────────────────────────────────────────────────────────────────────

    async def sync_order_statuses(self) -> int:
        """
        Poll the broker for status updates on all PENDING orders.

        For each PENDING order:
          - Calls broker.get_order_status(broker_order_id)
          - Updates Order.status, filled_qty, filled_price, filled_at in DB
          - If newly FILLED and side==BUY, creates a PortfolioPosition if one
            doesn't already exist

        Returns:
            Number of orders updated.
        """
        stmt = select(Order).where(Order.status == "PENDING")
        result = await self.db.execute(stmt)
        pending_orders = result.scalars().all()

        if not pending_orders:
            return 0

        updated = 0
        for order in pending_orders:
            if not order.broker_order_id:
                continue

            country = await self._get_stock_country(order.ticker)
            broker = get_broker(country)

            try:
                fresh = await broker.get_order_status(order.broker_order_id)
            except Exception as exc:
                logger.warning(
                    "[OrderManager] sync status failed for order %d: %s", order.id, exc
                )
                continue

            if fresh.status == order.status:
                continue  # no change

            order.status = fresh.status
            if fresh.filled_qty:
                order.filled_qty = fresh.filled_qty
            if fresh.filled_price:
                order.filled_price = fresh.filled_price
            if fresh.status == "FILLED" and not order.filled_at:
                order.filled_at = datetime.now(timezone.utc)

            # Create position for newly filled BUY orders
            if (
                fresh.status == "FILLED"
                and order.side == "BUY"
                and fresh.filled_price
                and fresh.filled_qty
                and not order.portfolio_position_id
            ):
                pos = PortfolioPosition(
                    ticker=order.ticker,
                    entry_date=order.filled_at or datetime.now(timezone.utc),
                    entry_price=fresh.filled_price,
                    shares=fresh.filled_qty,
                    position_value=round(fresh.filled_price * fresh.filled_qty, 2),
                    signal=order.signal,
                    notes=f"Auto-created from order #{order.id}",
                    is_open=True,
                )
                self.db.add(pos)
                await self.db.flush()
                order.portfolio_position_id = pos.id

            updated += 1
            logger.info(
                "[OrderManager] Order %d (%s) status: %s → %s",
                order.id, order.ticker, order.status, fresh.status,
            )

        await self.db.commit()
        return updated

    async def sync_broker_positions(self) -> dict:
        """
        Reconcile live broker holdings against the portfolio_positions table.

        For each open broker position that has no matching open portfolio
        position, a new PortfolioPosition is created with signal='BROKER_SYNC'.

        Returns:
            {
                "broker_positions":    int,  # total live positions from broker
                "new_positions_added": int,  # positions inserted into DB
                "already_tracked":     int,  # positions already in DB
            }
        """
        # We need to decide which country/broker to use.
        # Query distinct countries across open portfolio positions.
        countries_result = await self.db.execute(
            text("""
                SELECT DISTINCT s.country
                FROM portfolio_positions pp
                JOIN stocks s ON s.ticker = pp.ticker
                WHERE pp.is_open = TRUE
            """)
        )
        countries = [row.country for row in countries_result.fetchall() if row.country]
        if not countries:
            countries = ["US"]  # default

        all_broker_positions = []
        for country in set(countries):
            broker = get_broker(country)
            try:
                positions = await broker.get_positions()
                all_broker_positions.extend(positions)
            except Exception as exc:
                logger.warning(
                    "[OrderManager] sync_broker_positions failed for %s: %s", country, exc
                )

        new_count = 0
        already_count = 0
        now = datetime.now(timezone.utc)

        for bp in all_broker_positions:
            # Check if we already track this ticker in an open position
            existing_result = await self.db.execute(
                select(PortfolioPosition).where(
                    PortfolioPosition.ticker == bp.ticker,
                    PortfolioPosition.is_open == True,  # noqa: E712
                )
            )
            existing = existing_result.scalars().first()

            if existing:
                already_count += 1
                continue

            # New position found at broker but not in DB — create it
            entry_price = bp.avg_price or (bp.current_price or 0.0)
            pos = PortfolioPosition(
                ticker=bp.ticker,
                entry_date=now,
                entry_price=entry_price,
                shares=bp.qty,
                position_value=round(entry_price * bp.qty, 2),
                signal="BROKER_SYNC",
                notes="Synced from broker — no local order record",
                is_open=True,
            )
            self.db.add(pos)
            new_count += 1
            logger.info(
                "[OrderManager] Broker sync: added position %s (%.2f shares @ %.4f)",
                bp.ticker, bp.qty, entry_price,
            )

        await self.db.commit()

        return {
            "broker_positions":    len(all_broker_positions),
            "new_positions_added": new_count,
            "already_tracked":     already_count,
        }

    # ──────────────────────────────────────────────────────────────────────────
    # Advanced order types (Phase E)
    # ──────────────────────────────────────────────────────────────────────────

    async def submit_bracket_order(
        self,
        ticker: str,
        qty: Optional[float] = None,
        entry_type: str = "MARKET",
        entry_price: Optional[float] = None,
        stop_price: Optional[float] = None,
        target_price: Optional[float] = None,
        analysis: Optional[dict] = None,
        notes: Optional[str] = None,
    ) -> dict:
        """
        Submit a bracket order: entry + stop loss + take profit as one atomic order.

        If stop_price/target_price not supplied, derives from latest AI analysis.
        If qty not supplied, uses Kelly sizing from analysis/account balance.
        """
        ticker = ticker.upper()

        cb_engine = CircuitBreakerEngine(self.db)
        cb = await cb_engine.check()
        if cb["status"] == "HALT":
            reason = "; ".join(cb["reasons"]) or "Circuit breaker HALT"
            return {"status": "halted", "reason": reason, "parent_order_id": None}

        if analysis is None:
            analysis = await self._latest_analysis(ticker)

        country = await self._get_stock_country(ticker)
        broker = get_broker(country)

        current_price = await self._latest_price(ticker)
        if not current_price and analysis:
            current_price = analysis.get("entry_price") or 0.0

        if not current_price:
            return {
                "status": "skipped",
                "reason": f"No price data for {ticker}",
                "parent_order_id": None,
            }

        if qty is None:
            balance = await broker.get_account_balance()
            portfolio_value = balance.portfolio_value or balance.cash or 100_000.0
            max_pct = float((analysis or {}).get("max_position_pct") or 5.0)
            if cb["status"] == "CAUTION":
                max_pct /= 2
            qty = self._compute_qty(portfolio_value, max_pct, current_price)

        # Derive stop/target from analysis if not provided
        if stop_price is None and analysis:
            stop_price = analysis.get("stop_loss")
        if target_price is None and analysis:
            target_price = analysis.get("take_profit")

        if stop_price is None or target_price is None:
            return {
                "status": "skipped",
                "reason": "stop_price and target_price are required (or provide an analysis with stop_loss/take_profit)",
                "parent_order_id": None,
            }

        # For LIMIT entry, use supplied entry_price or current_price
        eff_entry_price = entry_price if entry_type.upper() == "LIMIT" else None

        try:
            result = await broker.place_bracket_order(
                ticker=ticker,
                side="BUY",
                qty=float(qty),
                entry_type=entry_type.upper(),
                entry_price=eff_entry_price,
                stop_price=stop_price,
                target_price=target_price,
            )
        except Exception as exc:
            logger.error("[OrderManager] bracket_order failed for %s: %s", ticker, exc)
            return {"status": "error", "reason": str(exc), "parent_order_id": None}

        now = datetime.now(timezone.utc)
        order_notes = notes or result.message
        try:
            order_notes = json.dumps({
                "stop": stop_price,
                "target": target_price,
                "msg": notes or result.message,
            })
        except Exception:
            pass

        order = Order(
            ticker=ticker,
            created_at=now,
            side="BUY",
            order_type="BRACKET",
            qty=float(qty),
            limit_price=eff_entry_price,
            broker=broker.name,
            broker_order_id=result.parent_order_id,
            status=result.status,
            signal=(analysis or {}).get("signal", "BUY"),
            final_score=(analysis or {}).get("final_score"),
            notes=order_notes,
        )
        try:
            order.stop_price = stop_price
            order.target_price = target_price
            order.execution_algo = "BRACKET"
        except Exception:
            pass

        self.db.add(order)
        await self.db.flush()

        if result.status == "FILLED":
            pos = PortfolioPosition(
                ticker=ticker,
                entry_date=now,
                entry_price=eff_entry_price or current_price,
                shares=float(qty),
                position_value=round((eff_entry_price or current_price) * qty, 2),
                stop_loss=stop_price,
                take_profit=target_price,
                signal=(analysis or {}).get("signal", "BUY"),
                regime=(analysis or {}).get("regime"),
                notes=notes,
                is_open=True,
            )
            self.db.add(pos)
            await self.db.flush()
            order.portfolio_position_id = pos.id

        await self.db.commit()
        await self.db.refresh(order)

        logger.info(
            "[OrderManager] Bracket %s: parent=%s stop=%s target=%s status=%s",
            ticker, result.parent_order_id, result.stop_leg_id, result.target_leg_id, result.status,
        )
        return {
            "status": "submitted",
            "reason": result.message,
            "db_order_id": order.id,
            "broker": broker.name,
            "parent_order_id": result.parent_order_id,
            "stop_leg_id": result.stop_leg_id,
            "target_leg_id": result.target_leg_id,
            "order_status": result.status,
            "qty": qty,
            "stop_price": stop_price,
            "target_price": target_price,
        }

    async def submit_stop_order(
        self,
        ticker: str,
        side: str,
        qty: float,
        stop_price: float,
        limit_price: Optional[float] = None,
        notes: Optional[str] = None,
    ) -> dict:
        """
        Submit a stop or stop-limit order.

        stop-market: triggers at stop_price, fills at market (limit_price=None)
        stop-limit:  triggers at stop_price, fills at limit_price or better
        """
        ticker = ticker.upper()
        side = side.upper()

        try:
            cb_engine = CircuitBreakerEngine(self.db)
            cb = await cb_engine.check()
            if cb["status"] == "HALT":
                logger.warning("[OrderManager] HALT — stop order for %s logged only", ticker)
        except Exception as exc:
            logger.warning("[OrderManager] CB check skipped: %s", exc)

        country = await self._get_stock_country(ticker)
        broker = get_broker(country)

        result = await broker.place_stop_order(
            ticker=ticker,
            side=side,
            qty=qty,
            stop_price=stop_price,
            limit_price=limit_price,
        )
        order_type = "STOP_LIMIT" if limit_price is not None else "STOP"

        now = datetime.now(timezone.utc)
        order = Order(
            ticker=ticker,
            created_at=now,
            side=side,
            order_type=order_type,
            qty=float(qty),
            limit_price=limit_price,
            broker=broker.name,
            broker_order_id=result.broker_order_id,
            status=result.status,
            filled_qty=result.filled_qty,
            filled_price=result.filled_price,
            filled_at=now if result.status == "FILLED" else None,
            signal="STOP",
            notes=notes or result.message,
        )
        try:
            order.stop_price = stop_price
        except Exception:
            pass

        self.db.add(order)
        await self.db.commit()
        await self.db.refresh(order)

        logger.info(
            "[OrderManager] Stop order %s %s: trigger=%.4f status=%s",
            side, ticker, stop_price, result.status,
        )
        return {
            "status": "submitted",
            "reason": result.message,
            "order_id": order.id,
            "broker": broker.name,
            "broker_order_id": result.broker_order_id,
            "order_status": result.status,
            "order_type": order_type,
            "stop_price": stop_price,
            "limit_price": limit_price,
        }

    async def submit_trailing_stop_order(
        self,
        ticker: str,
        side: str,
        qty: float,
        trail_amount: float,
        trail_type: str = "ABSOLUTE",
        notes: Optional[str] = None,
    ) -> dict:
        """
        Submit a trailing stop order.

        trail_type: "ABSOLUTE" (fixed dollar/rupee distance) or "PERCENTAGE"
        Supported natively by Alpaca and IBKR; other brokers simulate via stop-market.
        """
        ticker = ticker.upper()
        side = side.upper()
        trail_type = trail_type.upper()

        try:
            cb_engine = CircuitBreakerEngine(self.db)
            await cb_engine.check()
        except Exception:
            pass

        country = await self._get_stock_country(ticker)
        broker = get_broker(country)

        result = await broker.place_trailing_stop_order(
            ticker=ticker,
            side=side,
            qty=qty,
            trail_amount=trail_amount,
            trail_type=trail_type,
        )

        now = datetime.now(timezone.utc)
        trail_desc = f"{trail_amount}{'%' if trail_type == 'PERCENTAGE' else ''}"
        order = Order(
            ticker=ticker,
            created_at=now,
            side=side,
            order_type="TRAILING_STOP",
            qty=float(qty),
            broker=broker.name,
            broker_order_id=result.broker_order_id,
            status=result.status,
            filled_qty=result.filled_qty,
            filled_price=result.filled_price,
            filled_at=now if result.status == "FILLED" else None,
            signal="TRAILING_STOP",
            notes=notes or f"Trail {trail_desc} — {result.message}",
        )
        try:
            order.trail_amount = trail_amount
            order.trail_type = trail_type
        except Exception:
            pass

        self.db.add(order)
        await self.db.commit()
        await self.db.refresh(order)

        logger.info(
            "[OrderManager] Trailing stop %s %s: trail=%s %s status=%s",
            side, ticker, trail_amount, trail_type, result.status,
        )
        return {
            "status": "submitted",
            "reason": result.message,
            "order_id": order.id,
            "broker": broker.name,
            "broker_order_id": result.broker_order_id,
            "order_status": result.status,
            "trail_amount": trail_amount,
            "trail_type": trail_type,
        }
