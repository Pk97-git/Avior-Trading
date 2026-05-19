from typing import Optional, List, Dict, Tuple, Any
"""
engines/regime.py
=================
MacroRegimeClassifier — reads the latest macro_data values and returns
one of five macro regime labels with a confidence score.

Regimes (priority order):
  1. Risk-Off          — VIX > 28 (fear dominates)
  2. Recession Risk    — yield curve inverted (US10Y − US2Y < −0.3)
  3. Tightening        — Fed hiking cycle active + CPI elevated
  4. Liquidity Expansion — Fed easing + VIX calm
  5. Risk-On           — default (no stress signals)

This is rule-based in Phase 2; can be replaced by an ML classifier in Phase 5.
"""
import logging
from datetime import datetime, timedelta, timezone
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import text

logger = logging.getLogger(__name__)

# ── Regime constants ───────────────────────────────────────────────────────────
RISK_OFF             = "Risk-Off"
RECESSION_RISK       = "Recession Risk"
TIGHTENING           = "Tightening"
LIQUIDITY_EXPANSION  = "Liquidity Expansion"
RISK_ON              = "Risk-On"

# Macro indicator keys used in macro_data table
INDICATORS = ["VIX", "US10Y", "US2Y", "FEDFUNDS", "CPI", "DXY", "INR=X"]


class MacroRegimeClassifier:
    """Reads macro_data and classifies the current global macro regime."""

    def __init__(self, db: AsyncSession):
        self.db = db

    async def _fetch_latest(self) -> dict:
        """Fetch the most recent value for each macro indicator."""
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

    async def _fetch_fedfunds_trend(self, lookback_days: int = 90) -> float:
        """
        Returns the change in Fed Funds rate over the last `lookback_days` days.
        Positive = hiking, Negative = cutting.
        """
        since = datetime.now(timezone.utc) - timedelta(days=lookback_days)
        query = text("""
            SELECT value, time FROM macro_data
            WHERE indicator = 'FEDFUNDS' AND time >= :since
            ORDER BY time ASC
        """)
        result = await self.db.execute(query, {"since": since})
        rows = result.fetchall()
        if len(rows) < 2:
            return 0.0
        return rows[-1].value - rows[0].value

    async def classify(self) -> dict:
        """
        Classify the current macro regime.

        Returns:
            {
                "regime": str,
                "confidence": float,   # 0.0–1.0
                "indicators": dict,    # latest values used
            }
        """
        latest = await self._fetch_latest()
        fedfunds_trend = await self._fetch_fedfunds_trend()

        def val(key: str) -> Optional[float]:
            return latest.get(key, {}).get("value")

        vix         = val("VIX")
        us10y       = val("US10Y")
        us2y        = val("US2Y")
        fedfunds    = val("FEDFUNDS")
        cpi         = val("CPI")
        dxy         = val("DXY")
        inr         = val("INR=X")

        indicators_snapshot = {
            "VIX": vix, "US10Y": us10y, "US2Y": us2y,
            "FEDFUNDS": fedfunds, "CPI": cpi, "DXY": dxy, "INR_USD": inr,
            "fedfunds_trend_90d": round(fedfunds_trend, 3),
        }

        # ── Rule cascade (priority order) ─────────────────────────────────────

        # 1. Risk-Off: fear spike
        if vix is not None and vix > 28:
            confidence = min(1.0, (vix - 28) / 20 + 0.6)
            logger.info("Regime: Risk-Off (VIX=%.1f)", vix)
            return {"regime": RISK_OFF, "confidence": round(confidence, 2),
                    "indicators": indicators_snapshot}

        # 2. Recession Risk: yield curve inverted
        if us10y is not None and us2y is not None:
            spread = us10y - us2y
            if spread < -0.3:
                confidence = min(1.0, abs(spread) / 2.0 + 0.5)
                logger.info("Regime: Recession Risk (spread=%.2f)", spread)
                return {"regime": RECESSION_RISK, "confidence": round(confidence, 2),
                        "indicators": indicators_snapshot}

        # 3. Tightening: Fed hiking + inflation elevated
        if fedfunds_trend > 0.25 and cpi is not None and cpi > 4.0:
            confidence = min(1.0, fedfunds_trend / 2.0 + 0.5)
            logger.info("Regime: Tightening (FEDFUNDS trend=%.2f, CPI=%.1f)",
                        fedfunds_trend, cpi)
            return {"regime": TIGHTENING, "confidence": round(confidence, 2),
                    "indicators": indicators_snapshot}

        # 4. Liquidity Expansion: Fed cutting + market calm
        if fedfunds_trend < -0.1 and (vix is None or vix < 20):
            confidence = 0.65
            logger.info("Regime: Liquidity Expansion (FEDFUNDS trend=%.2f)", fedfunds_trend)
            return {"regime": LIQUIDITY_EXPANSION, "confidence": round(confidence, 2),
                    "indicators": indicators_snapshot}

        # 5. Default: Risk-On
        confidence = 0.55 if vix is None else max(0.5, 1.0 - vix / 40)
        logger.info("Regime: Risk-On (VIX=%.1f)", vix or 0)
        return {"regime": RISK_ON, "confidence": round(confidence, 2),
                "indicators": indicators_snapshot}
