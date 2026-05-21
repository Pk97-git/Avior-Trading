from typing import Optional, List, Dict, Tuple
"""
agents/executive.py
===================
ExecutiveTrader — Regime-Adaptive Weighted Scoring Engine.

Combines 5 core agent scores into a single final conviction score,
with weights that shift dynamically based on the macro regime.
Bonus agents (institutional, vision, factor) contribute to thesis only.

Regime Weight Table (5-factor spec):
  ─────────────────────────────────────────────────────────────────────
  Agent         Risk-On  Risk-Off  Tightening  Liq-Exp  Recession  Unknown
  ─────────────────────────────────────────────────────────────────────
  Fundamental    0.25     0.28      0.28        0.22      0.30       0.25
  Technical      0.22     0.15      0.18        0.25      0.12       0.20
  Sentiment      0.15     0.10      0.12        0.15      0.08       0.15
  Macro          0.13     0.20      0.17        0.13      0.22       0.15
  Risk           0.25     0.27      0.25        0.25      0.28       0.25
  ─────────────────────────────────────────────────────────────────────

Signal thresholds (score out of 100):
  BUY    ≥ 65   — Strong conviction: initiate or add to position
  HOLD   50–64  — Maintain existing position, no new buys
  REDUCE 35–49  — Reduce position size by ~50%, risk rising
  SELL   < 35   — Exit position entirely
"""
import logging

logger = logging.getLogger(__name__)

BUY    = "BUY"
HOLD   = "HOLD"
REDUCE = "REDUCE"
SELL   = "SELL"

# Regime-adaptive weight tables (5 spec factors; must sum to 1.0)
REGIME_WEIGHTS = {
    "Risk-On": {
        "fundamental": 0.25, "technical": 0.22, "sentiment": 0.15, "macro": 0.13, "risk": 0.25,
    },
    "Risk-Off": {
        "fundamental": 0.28, "technical": 0.15, "sentiment": 0.10, "macro": 0.20, "risk": 0.27,
    },
    "Tightening": {
        "fundamental": 0.28, "technical": 0.18, "sentiment": 0.12, "macro": 0.17, "risk": 0.25,
    },
    "Liquidity Expansion": {
        "fundamental": 0.22, "technical": 0.25, "sentiment": 0.15, "macro": 0.13, "risk": 0.25,
    },
    "Recession": {
        "fundamental": 0.30, "technical": 0.12, "sentiment": 0.08, "macro": 0.22, "risk": 0.28,
    },
    "Unknown": {  # spec baseline: exactly Tech 20%, Fund 25%, Sent 15%, Macro 15%, Risk 25%
        "fundamental": 0.25, "technical": 0.20, "sentiment": 0.15, "macro": 0.15, "risk": 0.25,
    },
}


def _resolve_weights(regime: str, weight_nudge: Optional[Dict[str, float]] = None) -> dict:
    """
    Map regime string to weight dict. If weight_nudge is provided (from WalkForwardValidator),
    apply the deltas and renormalize so weights still sum to 1.0.
    """
    if regime in REGIME_WEIGHTS:
        base = REGIME_WEIGHTS[regime]
    else:
        base = REGIME_WEIGHTS["Unknown"]
        for key in REGIME_WEIGHTS:
            if key.lower() in regime.lower() or regime.lower() in key.lower():
                base = REGIME_WEIGHTS[key]
                break

    if not weight_nudge:
        return base

    weights = {k: v for k, v in base.items()}
    for agent, delta in weight_nudge.items():
        if agent in weights:
            weights[agent] = max(0.05, weights[agent] + delta)
    total = sum(weights.values())
    if total > 0:
        weights = {k: v / total for k, v in weights.items()}
    return weights


class ExecutiveTrader:
    """Regime-adaptive weighted combination of agent scores → trading signal."""

    def decide(
        self,
        fundamental_score:    int,
        technical_score:      int,
        macro_score:          int,
        institutional_score:  int,
        sentiment_score:      int,
        vision_score:         int       = 50,
        factor_score:         int       = 50,
        risk_score:           int       = 50,  # NEW — RiskAgent output
        # Thesis lists from each agent
        fundamental_thesis:   Optional[List[str]] = None,
        technical_thesis:     Optional[List[str]] = None,
        macro_thesis:         Optional[List[str]] = None,
        institutional_thesis: Optional[List[str]] = None,
        sentiment_thesis:     Optional[List[str]] = None,
        vision_thesis:        Optional[List[str]] = None,
        factor_thesis:        Optional[List[str]] = None,
        risk_thesis:          Optional[List[str]] = None,  # NEW
        regime:               str = "Unknown",
        weight_nudge:         Optional[Dict[str, float]] = None,
    ) -> dict:

        weights = _resolve_weights(regime, weight_nudge)

        # Apply weight nudges if any (already handled in _resolve_weights,
        # but replicated inline per spec for clarity)
        if weight_nudge:
            for k, delta in weight_nudge.items():
                if k in weights:
                    weights[k] = max(0.05, weights[k] + delta)
            total = sum(weights.values())
            weights = {k: v / total for k, v in weights.items()}

        # 5-factor weighted score (bonus agents contribute to thesis only)
        final_score = (
            fundamental_score * weights["fundamental"] +
            technical_score   * weights["technical"]   +
            sentiment_score   * weights["sentiment"]   +
            macro_score       * weights["macro"]       +
            risk_score        * weights["risk"]
        )
        final_score = int(round(max(0, min(100, final_score))))

        # Signal taxonomy: BUY / HOLD / REDUCE / SELL
        if final_score >= 65:
            signal = BUY
        elif final_score >= 50:
            signal = HOLD
        elif final_score >= 35:
            signal = REDUCE
        else:
            signal = SELL

        # Build executive thesis summary from all agents
        all_thesis = []
        for agent_name, thesis in [
            ("Fundamentals",  fundamental_thesis),
            ("Technicals",    technical_thesis),
            ("Macro",         macro_thesis),
            ("Institutional", institutional_thesis),
            ("Factors",       factor_thesis),
            ("Sentiment",     sentiment_thesis),
            ("Vision",        vision_thesis),
            ("Risk",          risk_thesis),
        ]:
            if thesis and len(thesis) > 0:
                all_thesis.append(thesis[0])

        # Regime-weight disclosure
        w = weights
        weight_note = (
            f"Regime '{regime}': weights Fund={w['fundamental']:.0%} "
            f"Tech={w['technical']:.0%} Macro={w['macro']:.0%} "
            f"Sent={w['sentiment']:.0%} Risk={w['risk']:.0%}"
        )

        signal_thesis = [
            f"Final conviction: {final_score}/100 → {signal}.",
            weight_note,
        ] + all_thesis[:4]

        # Augment signal_thesis with risk context when reducing or exiting
        if signal in (REDUCE, SELL) and risk_thesis:
            risk_flags_note = " | ".join(risk_thesis[:2])
            signal_thesis.append(f"Risk factors driving caution: {risk_flags_note}")

        import os
        if os.getenv("GROQ_API_KEY"):
            try:
                from groq import Groq
                client = Groq(api_key=os.getenv("GROQ_API_KEY"))
                prompt = (
                    f"You are a hedge fund portfolio manager. Write a concise, 2-sentence investment thesis "
                    f"explaining why this stock is a {signal} with a score of {final_score}/100. "
                    f"Base your reasoning on these agent signals:\n" + "\n".join(all_thesis)
                )
                response = client.chat.completions.create(
                    model="llama-3.3-70b-versatile",
                    messages=[{"role": "user", "content": prompt}],
                    temperature=0.3,
                    max_tokens=150
                )
                llm_thesis = response.choices[0].message.content.strip()
                signal_thesis = [
                    f"Final conviction: {final_score}/100 → {signal}.",
                    llm_thesis,
                    weight_note
                ]
                if signal in (REDUCE, SELL) and risk_thesis:
                    risk_flags_note = " | ".join(risk_thesis[:2])
                    signal_thesis.append(f"Risk factors driving caution: {risk_flags_note}")
            except Exception as e:
                logger.warning(f"ExecutiveTrader LLM thesis synthesis failed: {e}")

        logger.info(
            "ExecutiveTrader regime=%s: score=%d signal=%s "
            "[fund=%d tech=%d macro=%d inst=%d sent=%d vis=%d fac=%d risk=%d]",
            regime, final_score, signal,
            fundamental_score, technical_score, macro_score,
            institutional_score, sentiment_score, vision_score, factor_score, risk_score,
        )

        return {
            "final_score":   final_score,
            "signal":        signal,
            "signal_thesis": signal_thesis,
        }
