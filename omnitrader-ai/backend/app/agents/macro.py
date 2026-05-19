"""
agents/macro.py
===============
MacroAgent — classifies the macro regime and maps it to a 0–100 score
that reflects how favourable the environment is for equity investment.

Regime → base score:
  Liquidity Expansion → 75  (best for equities)
  Risk-On             → 68
  Tightening          → 40  (cost of capital rising)
  Recession Risk      → 28
  Risk-Off            → 22  (fear/flight-to-safety)

Adjustments (applied on top of base):
  VIX ≤ 15            → +7   (ultra-calm)
  VIX 15–20           → +3
  VIX 25–35           → −5
  VIX > 35            → −12  (panic)
  Yield curve spread < −0.5 → −8  (deep inversion)
  India ticker + INR weakening (> 85 USD/INR) → −5
"""
import logging
from sqlalchemy.ext.asyncio import AsyncSession

from app.engines.regime import (
    MacroRegimeClassifier,
    RISK_ON, RISK_OFF, TIGHTENING, LIQUIDITY_EXPANSION, RECESSION_RISK,
)

logger = logging.getLogger(__name__)

_REGIME_BASE_SCORES = {
    LIQUIDITY_EXPANSION: 75,
    RISK_ON:             68,
    TIGHTENING:          40,
    RECESSION_RISK:      28,
    RISK_OFF:            22,
}


class MacroAgent:
    def __init__(self, db: AsyncSession, ticker: str):
        self.db = db
        self.ticker = ticker

    async def analyze(self) -> dict:
        """
        Returns:
            {
                "score": int,      # 0–100
                "regime": str,
                "thesis": list[str],
            }
        """
        try:
            classifier = MacroRegimeClassifier(self.db)
            regime_data = await classifier.classify()
        except Exception as e:
            logger.error("MacroAgent: regime classification failed for %s: %s", self.ticker, e)
            return {
                "score": 50,
                "regime": "Unknown",
                "thesis": ["Macro classification unavailable. Using neutral score."],
            }

        regime     = regime_data["regime"]
        confidence = regime_data["confidence"]
        indicators = regime_data["indicators"]

        base_score = _REGIME_BASE_SCORES.get(regime, 50)
        score      = base_score
        thesis     = []

        # Regime headline
        thesis.append(f"Macro regime: {regime} (confidence {confidence:.0%}).")

        # VIX adjustment
        vix = indicators.get("VIX")
        if vix is not None:
            if vix <= 15:
                score += 7
                thesis.append(f"VIX at {vix:.1f} — market complacency; low vol favours equities.")
            elif vix <= 20:
                score += 3
                thesis.append(f"VIX at {vix:.1f} — calm conditions.")
            elif vix <= 25:
                thesis.append(f"VIX at {vix:.1f} — moderate caution warranted.")
            elif vix <= 35:
                score -= 5
                thesis.append(f"VIX at {vix:.1f} — elevated fear; risk appetite reduced.")
            else:
                score -= 12
                thesis.append(f"VIX at {vix:.1f} — panic levels. Avoid new positions.")

        # Yield curve adjustment
        us10y = indicators.get("US10Y")
        us2y  = indicators.get("US2Y")
        if us10y is not None and us2y is not None:
            spread = us10y - us2y
            if spread < -0.5:
                score -= 8
                thesis.append(f"Yield curve deeply inverted ({spread:.2f}%). Recession risk elevated.")
            elif spread < 0:
                thesis.append(f"Yield curve slightly inverted ({spread:.2f}%).")
            else:
                thesis.append(f"Yield curve positive ({spread:.2f}%) — no immediate recession signal.")

        # India ticker: INR weakness penalty
        is_india = ".NS" in self.ticker or ".BO" in self.ticker
        if is_india:
            inr = indicators.get("INR_USD")
            if inr is not None and inr > 85:
                score -= 5
                thesis.append(f"INR/USD at {inr:.1f} — weak rupee pressures India equities.")

        score = max(0, min(100, score))
        logger.info("MacroAgent %s: score=%d regime=%s", self.ticker, score, regime)

        return {"score": score, "regime": regime, "thesis": thesis}
