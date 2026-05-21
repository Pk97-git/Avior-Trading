"""
engines/regime.py
=================
MacroRegimeClassifier — reads the latest macro_data values and classifies
the current global macro regime with reasoning.

Regime definitions (in priority order):
  RECESSION_RISK      — yield_curve < -0.5 AND unemployment_rising AND VIX > 20
  RISK_OFF            — VIX > 25 OR (yield_curve < -0.3 AND VIX > 20)
  TIGHTENING          — fed_funds_rising AND VIX < 25 AND yield_curve > -0.3
  LIQUIDITY_EXPANSION — fed_funds_falling OR (M2_growth > 0 AND VIX < 20)
  RISK_ON             — VIX < 18 AND yield_curve > 0 AND NOT fed_tightening
  TRANSITION          — no rule fires clearly
  UNKNOWN             — insufficient data

This is rule-based for Phase 2; can be replaced by an ML classifier in Phase 5.
"""
import logging
from datetime import datetime, timedelta, timezone
from typing import Optional

from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import text

logger = logging.getLogger(__name__)

# ── Regime label constants ─────────────────────────────────────────────────────
RECESSION_RISK       = "RECESSION_RISK"
RISK_OFF             = "RISK_OFF"
TIGHTENING           = "TIGHTENING"
LIQUIDITY_EXPANSION  = "LIQUIDITY_EXPANSION"
RISK_ON              = "RISK_ON"
TRANSITION           = "TRANSITION"
UNKNOWN              = "UNKNOWN"

# Macro indicator keys expected in macro_data table
INDICATORS = ["VIX", "US10Y", "US2Y", "FEDFUNDS", "M2", "UNRATE", "CPI", "DXY", "INR=X"]


class MacroRegimeClassifier:
    """Reads macro_data and classifies the current global macro regime."""

    def __init__(self, db: AsyncSession):
        self.db = db

    # ── Private helpers ────────────────────────────────────────────────────────

    async def _fetch_latest(self) -> dict:
        """Fetch the most-recent value for each macro indicator."""
        query = text("""
            SELECT DISTINCT ON (indicator)
                indicator, value, time
            FROM macro_data
            WHERE indicator = ANY(:indicators)
            ORDER BY indicator, time DESC
        """)
        result = await self.db.execute(query, {"indicators": INDICATORS})
        rows = result.fetchall()
        return {row.indicator: {"value": row.value, "time": row.time} for row in rows}

    async def _fetch_trend(self, indicator: str, lookback_days: int = 90) -> float:
        """
        Return the change in an indicator over lookback_days.
        Positive = rising, Negative = falling.  Returns 0.0 if insufficient data.
        """
        since = datetime.now(timezone.utc) - timedelta(days=lookback_days)
        query = text("""
            SELECT value, time
            FROM macro_data
            WHERE indicator = :ind AND time >= :since
            ORDER BY time ASC
        """)
        result = await self.db.execute(query, {"ind": indicator, "since": since})
        rows = result.fetchall()
        if len(rows) < 2:
            return 0.0
        return rows[-1].value - rows[0].value

    # ── Public interface ───────────────────────────────────────────────────────

    async def classify(self) -> dict:
        """
        Classify the current macro regime.

        Returns:
            {
                "regime":     str,           # one of the regime constants above
                "confidence": float,         # 0.0–1.0
                "features":   dict,          # latest indicator values used
                "reasoning":  list[str],     # human-readable rule explanations
            }
        """
        latest          = await self._fetch_latest()
        fedfunds_trend  = await self._fetch_trend("FEDFUNDS",  lookback_days=90)
        m2_trend        = await self._fetch_trend("M2",        lookback_days=90)
        unrate_trend    = await self._fetch_trend("UNRATE",    lookback_days=90)

        def val(key: str) -> Optional[float]:
            return latest.get(key, {}).get("value")

        vix       = val("VIX")
        us10y     = val("US10Y")
        us2y      = val("US2Y")
        fedfunds  = val("FEDFUNDS")
        m2        = val("M2")
        unrate    = val("UNRATE")
        cpi       = val("CPI")
        dxy       = val("DXY")
        inr       = val("INR=X")

        yield_curve = (us10y - us2y) if (us10y is not None and us2y is not None) else None

        # Derived booleans
        fed_tightening  = fedfunds_trend > 0.10   # rising by at least 10 bps over 90d
        fed_easing      = fedfunds_trend < -0.10  # falling by at least 10 bps over 90d
        m2_growing      = m2_trend > 0
        unemployment_rising = unrate_trend > 0.2  # rising by more than 0.2 pp

        features = {
            "VIX":                vix,
            "US10Y":              us10y,
            "US2Y":               us2y,
            "yield_curve":        round(yield_curve, 3) if yield_curve is not None else None,
            "FEDFUNDS":           fedfunds,
            "fedfunds_trend_90d": round(fedfunds_trend, 3),
            "M2":                 m2,
            "m2_trend_90d":       round(m2_trend, 3),
            "UNRATE":             unrate,
            "unrate_trend_90d":   round(unrate_trend, 3),
            "CPI":                cpi,
            "DXY":                dxy,
            "INR_USD":            inr,
        }

        # Track reasoning strings
        reasoning: list[str] = []

        # ── 1. RECESSION_RISK (highest priority) ──────────────────────────────
        # yield_curve < -0.5 AND unemployment_rising AND VIX > 20
        recession_conditions = []
        recession_met        = 0
        if yield_curve is not None:
            if yield_curve < -0.5:
                recession_met += 1
                recession_conditions.append(f"yield curve deeply inverted at {yield_curve:.2f}")
            elif yield_curve < -0.3:
                recession_conditions.append(f"yield curve mildly inverted at {yield_curve:.2f}")
        if unemployment_rising:
            recession_met += 1
            recession_conditions.append(
                f"unemployment rising ({unrate_trend:+.2f} pp over 90d)"
            )
        if vix is not None and vix > 20:
            recession_met += 1
            recession_conditions.append(f"VIX elevated at {vix:.1f}")

        if recession_met >= 3 or (
            recession_met >= 2 and yield_curve is not None and yield_curve < -0.5
        ):
            reasoning.extend([f"RECESSION_RISK: {c}" for c in recession_conditions])
            confidence = 0.9 if recession_met == 3 else 0.6
            logger.info("Regime: RECESSION_RISK (conditions: %s)", recession_conditions)
            return {
                "regime":     RECESSION_RISK,
                "confidence": confidence,
                "features":   features,
                "reasoning":  reasoning,
            }

        # ── 2. RISK_OFF ───────────────────────────────────────────────────────
        # VIX > 25 OR (yield_curve < -0.3 AND VIX > 20)
        riskoff_conditions = []
        riskoff_strong     = False
        if vix is not None and vix > 25:
            riskoff_strong = True
            riskoff_conditions.append(f"VIX spike to {vix:.1f} (>25, fear dominant)")
        if yield_curve is not None and yield_curve < -0.3 and vix is not None and vix > 20:
            riskoff_conditions.append(
                f"inverted yield curve ({yield_curve:.2f}) combined with elevated VIX ({vix:.1f})"
            )
            riskoff_strong = riskoff_strong or True

        if riskoff_conditions:
            reasoning.extend([f"RISK_OFF: {c}" for c in riskoff_conditions])
            confidence = 0.9 if riskoff_strong and vix is not None and vix > 30 else 0.7
            logger.info("Regime: RISK_OFF (conditions: %s)", riskoff_conditions)
            return {
                "regime":     RISK_OFF,
                "confidence": confidence,
                "features":   features,
                "reasoning":  reasoning,
            }

        # ── 3. TIGHTENING ─────────────────────────────────────────────────────
        # fed_funds_rising AND VIX < 25 AND yield_curve > -0.3
        tightening_conditions = []
        if fed_tightening:
            tightening_conditions.append(
                f"Fed Funds rising ({fedfunds_trend:+.2f} pp over 90d)"
            )
            if vix is not None and vix < 25:
                tightening_conditions.append(f"VIX contained at {vix:.1f} (<25)")
            if yield_curve is not None and yield_curve > -0.3:
                tightening_conditions.append(
                    f"yield curve not deeply inverted ({yield_curve:.2f})"
                )

            # Require at least fed rising + one other condition
            if (
                len(tightening_conditions) >= 2
                and (vix is None or vix < 25)
                and (yield_curve is None or yield_curve > -0.3)
            ):
                reasoning.extend([f"TIGHTENING: {c}" for c in tightening_conditions])
                confidence = 0.9 if fedfunds_trend > 0.5 else 0.6
                logger.info("Regime: TIGHTENING (trend=%.2f)", fedfunds_trend)
                return {
                    "regime":     TIGHTENING,
                    "confidence": confidence,
                    "features":   features,
                    "reasoning":  reasoning,
                }

        # ── 4. LIQUIDITY_EXPANSION ────────────────────────────────────────────
        # fed_funds_falling OR (M2_growth > 0 AND VIX < 20)
        liquidity_conditions = []
        if fed_easing:
            liquidity_conditions.append(
                f"Fed Funds falling ({fedfunds_trend:+.2f} pp over 90d)"
            )
        if m2_growing and vix is not None and vix < 20:
            liquidity_conditions.append(
                f"M2 growing ({m2_trend:+.2f} over 90d) with calm VIX ({vix:.1f})"
            )

        if liquidity_conditions:
            reasoning.extend([f"LIQUIDITY_EXPANSION: {c}" for c in liquidity_conditions])
            confidence = 0.9 if fed_easing and m2_growing else 0.6
            logger.info("Regime: LIQUIDITY_EXPANSION (conditions: %s)", liquidity_conditions)
            return {
                "regime":     LIQUIDITY_EXPANSION,
                "confidence": confidence,
                "features":   features,
                "reasoning":  reasoning,
            }

        # ── 5. RISK_ON ────────────────────────────────────────────────────────
        # VIX < 18 AND yield_curve > 0 AND NOT fed_tightening
        risk_on_conditions = []
        risk_on_strong     = False
        if vix is not None and vix < 18:
            risk_on_conditions.append(f"VIX low at {vix:.1f} (<18, low fear)")
            risk_on_strong = True
        if yield_curve is not None and yield_curve > 0:
            risk_on_conditions.append(
                f"yield curve positive at {yield_curve:.2f} (no inversion)"
            )
        if not fed_tightening:
            risk_on_conditions.append("Fed not in active tightening cycle")

        if len(risk_on_conditions) >= 2:
            reasoning.extend([f"RISK_ON: {c}" for c in risk_on_conditions])
            confidence = 0.9 if risk_on_strong and len(risk_on_conditions) == 3 else 0.6
            logger.info("Regime: RISK_ON (VIX=%.1f)", vix or 0)
            return {
                "regime":     RISK_ON,
                "confidence": confidence,
                "features":   features,
                "reasoning":  reasoning,
            }

        # ── 6. TRANSITION (fallback) ──────────────────────────────────────────
        # None of the above fired clearly
        transition_notes = []
        if vix is not None:
            transition_notes.append(f"VIX={vix:.1f} (between thresholds)")
        if yield_curve is not None:
            transition_notes.append(f"yield_curve={yield_curve:.2f}")
        if fedfunds_trend != 0:
            transition_notes.append(f"Fed Funds trend={fedfunds_trend:+.2f}")

        reasoning.append(
            "TRANSITION: no single regime rule fired conclusively — "
            + ", ".join(transition_notes)
        )
        logger.info("Regime: TRANSITION (%s)", transition_notes)
        return {
            "regime":     TRANSITION,
            "confidence": 0.5,
            "features":   features,
            "reasoning":  reasoning,
        }
