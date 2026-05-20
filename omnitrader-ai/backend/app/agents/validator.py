from typing import Optional, List, Dict, Tuple
"""
agents/validator.py
====================
Walk-Forward Validation & Bayesian Weight Update

Runs every Sunday (via weekly_ingest_flow) to:
  1. Evaluate recent signal performance (last 90 days) in rolling 30-day windows
  2. Compute hit rate, Sharpe ratio, and avg gain vs avg loss per signal tier
  3. Bayesian-update the regime weights in executive.py if there's enough data
  4. Write a performance summary to the DB (macro_data table with indicator='SIGNAL_PERFORMANCE')

This module is NOT called per-ticker — it's called once per week as a background job.
"""
import json
import logging
from datetime import datetime, timedelta, timezone

from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import text

logger = logging.getLogger(__name__)

FORWARD_DAYS = 30        # evaluate signal quality over 30-day forward returns
MIN_SAMPLES   = 30       # minimum samples needed for Bayesian update
LEARNING_RATE = 0.05     # how aggressively to shift weights


class WalkForwardValidator:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def run(self) -> dict:
        """Full validation run — compute signal performance and update weights."""
        try:
            perf = await self._compute_performance()
            if not perf.get("valid"):
                logger.info("[Validator] Not enough data for walk-forward — skipping weight update.")
                return perf

            await self._store_performance(perf)
            weight_update = await self._bayesian_weight_update(perf)
            return {**perf, "weight_update": weight_update}

        except Exception as e:
            logger.error("[Validator] Walk-forward failed: %s", e)
            return {"valid": False, "error": str(e)}

    async def _compute_performance(self) -> dict:
        """Compute hit rate + Sharpe for each signal tier."""
        cutoff = (datetime.now(timezone.utc) - timedelta(days=FORWARD_DAYS + 2)).strftime("%Y-%m-%d")

        res = await self.db.execute(text("""
            SELECT a.signal, a.final_score,
                   (p_future.close - p_now.close) / NULLIF(p_now.close, 0) AS return_30d
            FROM ai_analysis a
            JOIN stock_prices p_now ON p_now.ticker = a.ticker
                AND DATE(p_now.time) = DATE(a.analysis_date)
            JOIN stock_prices p_future ON p_future.ticker = a.ticker
                AND DATE(p_future.time) = DATE(a.analysis_date + INTERVAL '30 days')
            WHERE a.analysis_date <= :cutoff
              AND a.analysis_date >= :since
        """), {
            "cutoff": cutoff,
            "since": (datetime.now(timezone.utc) - timedelta(days=120)).strftime("%Y-%m-%d")
        })
        rows = res.fetchall()

        if len(rows) < MIN_SAMPLES:
            return {"valid": False, "n_samples": len(rows)}

        by_signal: dict[str, list[float]] = {}
        for r in rows:
            if r.return_30d is None:
                continue
            by_signal.setdefault(r.signal, []).append(float(r.return_30d))

        stats = {}
        all_rets = []
        for signal, rets in by_signal.items():
            n = len(rets)
            mean = sum(rets) / n
            wins = sum(1 for r in rets if r > 0)
            hit_rate = wins / n
            std = (sum((r - mean)**2 for r in rets) / max(n-1, 1)) ** 0.5
            sharpe = mean / std if std > 0 else 0.0
            stats[signal] = {
                "n": n,
                "hit_rate": round(hit_rate, 3),
                "avg_return": round(mean, 4),
                "sharpe": round(sharpe, 3),
            }
            all_rets.extend(rets)

        overall_mean = sum(all_rets) / len(all_rets) if all_rets else 0
        return {
            "valid": True,
            "n_samples": len(rows),
            "overall_hit_rate": round(sum(1 for r in all_rets if r > 0) / len(all_rets), 3),
            "overall_avg_return": round(overall_mean, 4),
            "by_signal": stats,
            "computed_at": datetime.now(timezone.utc).isoformat(),
        }

    async def _store_performance(self, perf: dict) -> None:
        """Store walk-forward results in macro_data for audit trail."""
        try:
            await self.db.execute(text("""
                INSERT INTO macro_data (time, indicator, value, source)
                VALUES (:t, 'SIGNAL_PERFORMANCE', :v, 'walk_forward_validator')
                ON CONFLICT (time, indicator) DO UPDATE SET value = EXCLUDED.value
            """), {
                "t": datetime.now(timezone.utc),
                "v": perf.get("overall_hit_rate", 0.0),
            })
            await self.db.commit()
        except Exception as e:
            logger.warning("[Validator] Could not store performance: %s", e)

    async def _bayesian_weight_update(self, perf: dict) -> dict:
        """
        Nudge regime weights based on which signal tier has been most accurate.
        Computes numeric deltas and persists them to macro_data so ExecutiveTrader
        can load them at score time.
        """
        by_signal = perf.get("by_signal", {})
        buy_hr  = by_signal.get("BUY", {}).get("hit_rate", 0.5)
        dist_hr = by_signal.get("SELL", {}).get("hit_rate", 0.5)

        nudges: dict[str, float] = {}

        if dist_hr > 0.65:
            # Distribution calls are accurate → macro is doing its job, boost it
            nudges["macro"]       = +LEARNING_RATE
            nudges["fundamental"] = nudges.get("fundamental", 0.0) - LEARNING_RATE
            logger.info("[Validator] Distribution signals accurate (HR=%.2f) — nudging macro +%.0f%%.",
                        dist_hr, LEARNING_RATE * 100)

        if buy_hr < 0.45:
            # Buy signals underperforming → reduce fundamental reliance, shift to technical
            nudges["fundamental"] = nudges.get("fundamental", 0.0) - LEARNING_RATE * 0.5
            nudges["technical"]   = nudges.get("technical",   0.0) + LEARNING_RATE * 0.5
            logger.warning("[Validator] Buy signal hit rate low (%.2f) — reducing fundamental weight.", buy_hr)

        if nudges:
            await self._store_weight_nudges(nudges)

        return nudges

    async def _store_weight_nudges(self, nudges: dict[str, float]) -> None:
        """Persist per-agent weight deltas to macro_data for runtime loading by ExecutiveTrader."""
        now = datetime.now(timezone.utc)
        try:
            for agent, delta in nudges.items():
                await self.db.execute(text("""
                    INSERT INTO macro_data (time, indicator, value, source)
                    VALUES (:t, :ind, :v, 'walk_forward_validator')
                    ON CONFLICT (time, indicator) DO UPDATE SET value = EXCLUDED.value
                """), {
                    "t":   now,
                    "ind": f"WEIGHT_NUDGE_{agent.upper()}",
                    "v":   float(delta),
                })
            await self.db.commit()
            logger.info("[Validator] Persisted weight nudges: %s", nudges)
        except Exception as e:
            logger.warning("[Validator] Could not store weight nudges: %s", e)
