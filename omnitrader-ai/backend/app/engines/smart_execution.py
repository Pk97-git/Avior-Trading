"""
engines/smart_execution.py
==========================
Smart execution engine for optimized order placement.

Strategies:
  DIRECT  — single order, best for small orders in liquid stocks
  TWAP    — Time-Weighted Average Price, splits evenly over time
  VWAP    — Volume-Weighted Average Price, weighted by intraday volume profile
  ICEBERG — Shows partial quantity, hides true order size
  ADAPTIVE — Auto-selects based on order size vs Average Daily Volume

Usage:
    engine = SmartExecutionEngine(db)
    plan = await engine.analyze_order("AAPL", "BUY", 1000, urgency="NORMAL")
    # plan.strategy, plan.slices, plan.estimated_slippage_bps
"""
from __future__ import annotations

import logging
import statistics
from dataclasses import dataclass, field
from math import ceil, sqrt
from typing import List, Optional

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger(__name__)


# ──────────────────────────────────────────────────────────────────────────────
# Dataclasses
# ──────────────────────────────────────────────────────────────────────────────

@dataclass
class OrderSlice:
    slice_index: int
    qty: float
    delay_seconds: int          # relative to submission time
    order_type: str             # "MARKET" or "LIMIT"
    limit_price_offset_pct: float  # 0.0 = at market; negative = below (for buy)


@dataclass
class SlippageEstimate:
    spread_bps: float           # bid-ask spread component
    market_impact_bps: float    # price impact from order size
    total_bps: float            # spread_bps/2 + market_impact_bps
    order_fraction_pct: float   # order_size / adv * 100


@dataclass
class ExecutionPlan:
    ticker: str
    side: str
    total_qty: float
    strategy: str               # DIRECT, TWAP, VWAP, ICEBERG, ADAPTIVE
    slices: List[OrderSlice]
    estimated_slippage_bps: float
    estimated_market_impact_bps: float
    adv_usd: float              # average daily volume in USD
    duration_minutes: int       # total execution window
    reasoning: str              # human-readable explanation


# ──────────────────────────────────────────────────────────────────────────────
# Engine
# ──────────────────────────────────────────────────────────────────────────────

class SmartExecutionEngine:
    """
    Enterprise-grade smart order execution engine.

    Selects an execution strategy (DIRECT / TWAP / VWAP / ICEBERG) based on
    order size relative to average daily volume, and constructs a sequenced
    list of OrderSlice objects that a caller can submit over time.
    """

    # ── Strategy thresholds (order as % of ADV) ───────────────────────────────
    DIRECT_THRESHOLD_PCT = 0.10    # < 0.1% ADV → DIRECT
    ICEBERG_THRESHOLD_PCT = 1.0    # 0.1–1% ADV → ICEBERG
    VWAP_THRESHOLD_PCT = 5.0       # 1–5% ADV → VWAP
    # > 5% ADV → TWAP

    # Iceberg: show this fraction of total order
    ICEBERG_SHOW_FRACTION = 0.10   # show 10% at a time

    # Market impact coefficient (Almgren-Chriss simplified)
    IMPACT_COEFFICIENT = 10.0      # bps per sqrt(order_fraction)

    # Typical bid-ask spreads by liquidity tier
    SPREAD_LIQUID_BPS = 2.0        # large-cap US (e.g. AAPL, MSFT)
    SPREAD_MIDCAP_BPS = 8.0        # mid-cap
    SPREAD_ILLIQUID_BPS = 20.0     # small-cap or India mid-cap
    SPREAD_INDIA_BPS = 5.0         # NSE large-cap

    # US intraday volume profile (30-min buckets starting 9:30 ET)
    # Indexes: 0=9:30-10:00, 1=10:00-10:30, ..., 13=15:30-16:00
    US_VOLUME_PROFILE = [
        0.105, 0.065, 0.055, 0.050, 0.048, 0.045,
        0.048, 0.048, 0.048, 0.048, 0.050, 0.060,
        0.075, 0.105,
    ]  # sums to ~1.0

    # India NSE intraday volume profile (30-min buckets starting 9:15 IST)
    # Indexes: 0=9:15-9:45, 1=9:45-10:15, ..., 11=14:45-15:15, 12=15:15-15:30
    INDIA_VOLUME_PROFILE = [
        0.130, 0.085, 0.070, 0.065, 0.060, 0.058,
        0.058, 0.058, 0.060, 0.065, 0.075, 0.095,
        0.121,
    ]

    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    # ── Public API ─────────────────────────────────────────────────────────────

    async def analyze_order(
        self,
        ticker: str,
        side: str,
        qty: float,
        urgency: str = "NORMAL",
    ) -> ExecutionPlan:
        """
        Analyse a proposed order and return an ExecutionPlan with the optimal
        strategy and a list of time-sliced child orders.

        Args:
            ticker:  Stock symbol (e.g. "AAPL" or "RELIANCE.NS").
            side:    "BUY" or "SELL".
            qty:     Total number of shares / units.
            urgency: "HIGH" (fill immediately), "NORMAL" (balanced), "LOW" (patient).

        Returns:
            ExecutionPlan
        """
        ticker = ticker.upper()
        side = side.upper()
        urgency = urgency.upper()

        # ── 1. Fetch ADV from DB ───────────────────────────────────────────────
        adv_q = text("""
            SELECT AVG(volume) as adv, AVG(close) as avg_price
            FROM stock_prices
            WHERE ticker = :ticker
              AND time >= NOW() - INTERVAL '30 days'
        """)
        result = await self.db.execute(adv_q, {"ticker": ticker})
        row = result.fetchone()

        adv = float(row.adv) if row and row.adv else 0.0
        avg_price = float(row.avg_price) if row and row.avg_price else 1.0

        adv_usd = adv * avg_price

        # ── 2. Order fraction ─────────────────────────────────────────────────
        if adv > 0 and avg_price > 0:
            order_fraction_pct = (qty * avg_price) / (adv * avg_price) * 100
        else:
            order_fraction_pct = 0.0

        # ── 3. Strategy selection ─────────────────────────────────────────────
        if urgency == "HIGH":
            strategy = "DIRECT"
            duration_minutes = 0
            reasoning = (
                "Urgency=HIGH: single market order placed immediately regardless of size."
            )
        elif urgency == "LOW" and order_fraction_pct >= self.ICEBERG_THRESHOLD_PCT:
            strategy = "TWAP"
            duration_minutes = 120
            reasoning = (
                f"Urgency=LOW with order at {order_fraction_pct:.2f}% of ADV: "
                "patient TWAP over 2 hours to minimise market impact."
            )
        else:
            # NORMAL urgency — threshold-based selection
            if order_fraction_pct < self.DIRECT_THRESHOLD_PCT:
                strategy = "DIRECT"
                duration_minutes = 0
                reasoning = (
                    f"Order is {order_fraction_pct:.3f}% of ADV "
                    f"(< {self.DIRECT_THRESHOLD_PCT}% threshold): "
                    "tiny order — DIRECT market order."
                )
            elif order_fraction_pct < self.ICEBERG_THRESHOLD_PCT:
                strategy = "ICEBERG"
                duration_minutes = 30
                reasoning = (
                    f"Order is {order_fraction_pct:.2f}% of ADV "
                    f"({self.DIRECT_THRESHOLD_PCT}–{self.ICEBERG_THRESHOLD_PCT}% range): "
                    "ICEBERG to hide order size."
                )
            elif order_fraction_pct < self.VWAP_THRESHOLD_PCT:
                strategy = "VWAP"
                duration_minutes = 60
                reasoning = (
                    f"Order is {order_fraction_pct:.2f}% of ADV "
                    f"({self.ICEBERG_THRESHOLD_PCT}–{self.VWAP_THRESHOLD_PCT}% range): "
                    "VWAP over 60 minutes to track intraday liquidity."
                )
            else:
                strategy = "TWAP"
                duration_minutes = 120
                reasoning = (
                    f"Order is {order_fraction_pct:.2f}% of ADV "
                    f"(> {self.VWAP_THRESHOLD_PCT}% threshold): "
                    "large order — TWAP over 2 hours to minimise impact."
                )

        # ── 4. Slippage estimate ──────────────────────────────────────────────
        slip = await self._estimate_slippage(ticker, qty, avg_price, adv)

        # ── 5. Build slices ───────────────────────────────────────────────────
        country = "IN" if (ticker.endswith(".NS") or ticker.endswith(".BO")) else "US"

        if strategy == "DIRECT":
            slices = self._split_direct(ticker, side, qty)
        elif strategy == "TWAP":
            slices = self._split_twap(ticker, side, qty, duration_minutes=duration_minutes)
        elif strategy == "VWAP":
            slices = self._split_vwap(
                ticker, side, qty, country=country, duration_minutes=duration_minutes
            )
        else:  # ICEBERG
            slices = self._split_iceberg(ticker, side, qty)

        return ExecutionPlan(
            ticker=ticker,
            side=side,
            total_qty=qty,
            strategy=strategy,
            slices=slices,
            estimated_slippage_bps=slip.total_bps,
            estimated_market_impact_bps=slip.market_impact_bps,
            adv_usd=adv_usd,
            duration_minutes=duration_minutes,
            reasoning=reasoning,
        )

    async def estimate_execution_cost(
        self,
        ticker: str,
        qty: float,
        price: float,
    ) -> dict:
        """
        Public endpoint method — returns a cost summary dictionary without
        building a full ExecutionPlan.

        Returns:
            {
                "ticker": str,
                "qty": float,
                "price": float,
                "order_value_usd": float,
                "spread_bps": float,
                "market_impact_bps": float,
                "total_slippage_bps": float,
                "estimated_cost_usd": float,
                "adv_usd": float,
                "order_fraction_pct": float,
                "recommended_strategy": str,
            }
        """
        ticker = ticker.upper()

        # Fetch ADV
        adv_q = text("""
            SELECT AVG(volume) as adv, AVG(close) as avg_price
            FROM stock_prices
            WHERE ticker = :ticker
              AND time >= NOW() - INTERVAL '30 days'
        """)
        result = await self.db.execute(adv_q, {"ticker": ticker})
        row = result.fetchone()
        adv = float(row.adv) if row and row.adv else 0.0
        avg_price_db = float(row.avg_price) if row and row.avg_price else price or 1.0
        adv_usd = adv * avg_price_db

        slip = await self._estimate_slippage(ticker, qty, price, adv)

        # Determine recommended strategy
        if slip.order_fraction_pct < self.DIRECT_THRESHOLD_PCT:
            recommended = "DIRECT"
        elif slip.order_fraction_pct < self.ICEBERG_THRESHOLD_PCT:
            recommended = "ICEBERG"
        elif slip.order_fraction_pct < self.VWAP_THRESHOLD_PCT:
            recommended = "VWAP"
        else:
            recommended = "TWAP"

        return {
            "ticker": ticker,
            "qty": qty,
            "price": price,
            "order_value_usd": qty * price,
            "spread_bps": slip.spread_bps,
            "market_impact_bps": slip.market_impact_bps,
            "total_slippage_bps": slip.total_bps,
            "estimated_cost_usd": qty * price * (slip.total_bps / 10_000),
            "adv_usd": adv_usd,
            "order_fraction_pct": slip.order_fraction_pct,
            "recommended_strategy": recommended,
        }

    async def get_execution_quality_report(self, days: int = 30) -> dict:
        """
        Analyse historical fill quality from the orders table.

        Returns a dict with aggregate slippage statistics and per-broker
        breakdown.
        """
        sql = text("""
            SELECT o.ticker, o.side, o.qty, o.limit_price, o.filled_price,
                   o.order_type, o.created_at, o.filled_at, o.broker,
                   sp.close as reference_price
            FROM orders o
            LEFT JOIN LATERAL (
                SELECT close FROM stock_prices
                WHERE ticker = o.ticker AND time <= o.created_at
                ORDER BY time DESC LIMIT 1
            ) sp ON true
            WHERE o.status = 'FILLED'
              AND o.filled_at IS NOT NULL
              AND o.created_at >= NOW() - :days * INTERVAL '1 day'
        """)
        result = await self.db.execute(sql, {"days": days})
        rows = result.fetchall()

        if not rows:
            return {
                "total_orders": 0,
                "avg_slippage_bps": 0.0,
                "p50_slippage_bps": 0.0,
                "p90_slippage_bps": 0.0,
                "avg_fill_seconds": 0.0,
                "by_broker": {},
            }

        slippages: List[float] = []
        fill_seconds: List[float] = []
        by_broker: dict = {}

        for row in rows:
            filled_price = row.filled_price
            reference_price = row.reference_price

            if filled_price and reference_price and reference_price > 0:
                slip_bps = abs(filled_price - reference_price) / reference_price * 10_000
            else:
                slip_bps = 0.0

            slippages.append(slip_bps)

            if row.filled_at and row.created_at:
                delta = (row.filled_at - row.created_at).total_seconds()
                fill_seconds.append(max(0.0, delta))

            broker_name = row.broker or "unknown"
            if broker_name not in by_broker:
                by_broker[broker_name] = {"orders": 0, "slippages": []}
            by_broker[broker_name]["orders"] += 1
            by_broker[broker_name]["slippages"].append(slip_bps)

        avg_slippage = sum(slippages) / len(slippages) if slippages else 0.0
        avg_fill_secs = sum(fill_seconds) / len(fill_seconds) if fill_seconds else 0.0

        sorted_slip = sorted(slippages)
        n = len(sorted_slip)
        p50 = sorted_slip[n // 2] if n else 0.0
        p90 = sorted_slip[int(n * 0.90)] if n else 0.0

        broker_summary = {}
        for bname, bdata in by_broker.items():
            bslips = bdata["slippages"]
            bslips_sorted = sorted(bslips)
            bn = len(bslips_sorted)
            broker_summary[bname] = {
                "orders": bdata["orders"],
                "avg_slippage_bps": sum(bslips) / bn if bn else 0.0,
                "p50_slippage_bps": bslips_sorted[bn // 2] if bn else 0.0,
                "p90_slippage_bps": bslips_sorted[int(bn * 0.90)] if bn else 0.0,
            }

        return {
            "total_orders": len(rows),
            "avg_slippage_bps": round(avg_slippage, 4),
            "p50_slippage_bps": round(p50, 4),
            "p90_slippage_bps": round(p90, 4),
            "avg_fill_seconds": round(avg_fill_secs, 2),
            "by_broker": broker_summary,
        }

    # ── Private helpers ────────────────────────────────────────────────────────

    async def _estimate_slippage(
        self,
        ticker: str,
        qty: float,
        price: float,
        adv: float,
    ) -> SlippageEstimate:
        """
        Estimate execution slippage using a simplified Almgren-Chriss model.

        Components:
          - Half-spread cost (one side of the bid-ask spread).
          - Market impact: IMPACT_COEFFICIENT * sqrt(order_fraction) * 100 bps.
        """
        if adv > 0 and price > 0:
            order_fraction = (qty * price) / (adv * price)
        else:
            order_fraction = 0.0

        market_impact_bps = self.IMPACT_COEFFICIENT * sqrt(order_fraction) * 100

        # Spread determination
        if ticker.endswith(".NS") or ticker.endswith(".BO"):
            spread_bps = self.SPREAD_INDIA_BPS
        elif adv > 500_000:
            spread_bps = self.SPREAD_LIQUID_BPS
        elif adv > 50_000:
            spread_bps = self.SPREAD_MIDCAP_BPS
        else:
            spread_bps = self.SPREAD_ILLIQUID_BPS

        # Half-spread for one side + market impact
        total_bps = spread_bps / 2 + market_impact_bps

        order_fraction_pct = order_fraction * 100

        return SlippageEstimate(
            spread_bps=spread_bps,
            market_impact_bps=round(market_impact_bps, 4),
            total_bps=round(total_bps, 4),
            order_fraction_pct=round(order_fraction_pct, 6),
        )

    def _split_direct(
        self,
        ticker: str,
        side: str,
        qty: float,
    ) -> List[OrderSlice]:
        """Return a single market order slice."""
        return [
            OrderSlice(
                slice_index=0,
                qty=qty,
                delay_seconds=0,
                order_type="MARKET",
                limit_price_offset_pct=0.0,
            )
        ]

    def _split_twap(
        self,
        ticker: str,
        side: str,
        qty: float,
        duration_minutes: int = 60,
        n_slices: int = 12,
    ) -> List[OrderSlice]:
        """
        Split the order into n_slices equal-size limit orders distributed
        evenly across duration_minutes.

        Limit price offset: buy slightly below market (-0.02%), sell slightly
        above (+0.02%) to improve fill quality.
        """
        n_slices = max(1, n_slices)
        interval_seconds = (duration_minutes * 60) // n_slices
        slice_qty = qty / n_slices
        limit_offset = -0.02 if side == "BUY" else 0.02

        slices: List[OrderSlice] = []
        for i in range(n_slices):
            slices.append(
                OrderSlice(
                    slice_index=i,
                    qty=slice_qty,
                    delay_seconds=i * interval_seconds,
                    order_type="LIMIT",
                    limit_price_offset_pct=limit_offset,
                )
            )
        return slices

    def _split_vwap(
        self,
        ticker: str,
        side: str,
        qty: float,
        country: str = "US",
        duration_minutes: int = 60,
    ) -> List[OrderSlice]:
        """
        Split the order using the intraday volume profile to weight each
        30-minute bucket's participation.

        Chooses the US or India profile based on country.
        """
        profile = self.INDIA_VOLUME_PROFILE if country == "IN" else self.US_VOLUME_PROFILE

        n_buckets = max(1, duration_minutes // 30)
        raw_weights = profile[:n_buckets]

        total_weight = sum(raw_weights)
        if total_weight <= 0:
            total_weight = 1.0
        weights = [w / total_weight for w in raw_weights]

        limit_offset = -0.02 if side == "BUY" else 0.02

        slices: List[OrderSlice] = []
        for i, w in enumerate(weights):
            slices.append(
                OrderSlice(
                    slice_index=i,
                    qty=qty * w,
                    delay_seconds=i * 30 * 60,
                    order_type="LIMIT",
                    limit_price_offset_pct=limit_offset,
                )
            )
        return slices

    def _split_iceberg(
        self,
        ticker: str,
        side: str,
        qty: float,
    ) -> List[OrderSlice]:
        """
        Break the order into small visible clips (ICEBERG_SHOW_FRACTION of total)
        released every 30 seconds.

        The last slice receives any fractional remainder so the total exactly
        equals the requested qty.
        """
        show_qty = max(1.0, qty * self.ICEBERG_SHOW_FRACTION)
        n_slices = ceil(qty / show_qty)

        slices: List[OrderSlice] = []
        remaining = qty
        for i in range(n_slices):
            chunk = min(show_qty, remaining)
            remaining -= chunk
            slices.append(
                OrderSlice(
                    slice_index=i,
                    qty=chunk,
                    delay_seconds=i * 30,
                    order_type="LIMIT",
                    limit_price_offset_pct=0.0,
                )
            )
        return slices
