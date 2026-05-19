from typing import Optional, List, Dict, Tuple
"""
agents/executive.py
===================
ExecutiveTrader — Regime-Adaptive Weighted Scoring Engine.

Combines 7 agent scores into a single final conviction score,
with weights that shift dynamically based on the macro regime.

Regime Weight Table:
  ─────────────────────────────────────────────────────────────
  Agent           Risk-On   Risk-Off   Transition   Unknown
  ─────────────────────────────────────────────────────────────
  Fundamental      0.28       0.35       0.28        0.28
  Technical        0.22       0.15       0.20        0.22
  Macro            0.12       0.22       0.18        0.18
  Institutional    0.16       0.15       0.14        0.14
  Sentiment        0.10       0.03       0.08        0.08
  Vision           0.10       0.05       0.10        0.10
  Factor           0.02       0.05       0.02        0.00
  ─────────────────────────────────────────────────────────────

Signal thresholds:
  final_score ≥ 70 → STRONG_BUY
  final_score ≥ 55 → ACCUMULATE
  final_score ≤ 35 → DISTRIBUTION
  else             → AVOID
"""
import logging

logger = logging.getLogger(__name__)

STRONG_BUY   = "STRONG_BUY"
ACCUMULATE   = "ACCUMULATE"
AVOID        = "AVOID"
DISTRIBUTION = "DISTRIBUTION"

# Regime-adaptive weight tables (must sum to 1.0)
REGIME_WEIGHTS = {
    "Risk-On": {
        "fundamental":   0.28,
        "technical":     0.22,
        "macro":         0.12,
        "institutional": 0.16,
        "sentiment":     0.10,
        "vision":        0.10,
        "factor":        0.02,
    },
    "Risk-Off": {
        "fundamental":   0.35,
        "technical":     0.15,
        "macro":         0.22,
        "institutional": 0.15,
        "sentiment":     0.03,
        "vision":        0.05,
        "factor":        0.05,
    },
    "Transition": {
        "fundamental":   0.28,
        "technical":     0.20,
        "macro":         0.18,
        "institutional": 0.14,
        "sentiment":     0.08,
        "vision":        0.10,
        "factor":        0.02,
    },
    "Unknown": {
        "fundamental":   0.28,
        "technical":     0.22,
        "macro":         0.18,
        "institutional": 0.14,
        "sentiment":     0.08,
        "vision":        0.10,
        "factor":        0.00,
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
            weights[agent] = max(0.0, weights[agent] + delta)
    total = sum(weights.values())
    if total > 0:
        weights = {k: v / total for k, v in weights.items()}
    return weights


class ExecutiveTrader:
    """Regime-adaptive weighted combination of agent scores → trading signal."""

    def decide(
        self,
        fundamental_score:   int,
        technical_score:     int,
        macro_score:         int,
        institutional_score: int,
        sentiment_score:     int,
        vision_score:        int       = 50,
        factor_score:        int       = 50,
        # Thesis lists from each agent
        fundamental_thesis:   Optional[List[str]] = None,
        technical_thesis:     Optional[List[str]] = None,
        macro_thesis:         Optional[List[str]] = None,
        institutional_thesis: Optional[List[str]] = None,
        sentiment_thesis:     Optional[List[str]] = None,
        vision_thesis:        Optional[List[str]] = None,
        factor_thesis:        Optional[List[str]] = None,
        regime:               str = "Unknown",
        weight_nudge:         Optional[Dict[str, float]] = None,
    ) -> dict:

        weights = _resolve_weights(regime, weight_nudge)

        weighted = (
            fundamental_score   * weights["fundamental"]   +
            technical_score     * weights["technical"]     +
            macro_score         * weights["macro"]         +
            institutional_score * weights["institutional"] +
            sentiment_score     * weights["sentiment"]     +
            vision_score        * weights["vision"]        +
            factor_score        * weights["factor"]
        )
        final_score = int(round(max(0, min(100, weighted))))

        if final_score >= 70:
            signal = STRONG_BUY
        elif final_score >= 55:
            signal = ACCUMULATE
        elif final_score <= 35:
            signal = DISTRIBUTION
        else:
            signal = AVOID

        # Build executive thesis summary
        all_thesis = []
        for agent_name, thesis in [
            ("Fundamentals",   fundamental_thesis),
            ("Technicals",     technical_thesis),
            ("Macro",          macro_thesis),
            ("Institutional",  institutional_thesis),
            ("Factors",        factor_thesis),
            ("Sentiment",      sentiment_thesis),
            ("Vision",         vision_thesis),
        ]:
            if thesis and len(thesis) > 0:
                all_thesis.append(thesis[0])

        # Regime-weight disclosure
        w = weights
        weight_note = (
            f"Regime '{regime}': weights Fund={w['fundamental']:.0%} "
            f"Tech={w['technical']:.0%} Macro={w['macro']:.0%} "
            f"Inst={w['institutional']:.0%}"
        )

        signal_thesis = [
            f"Final conviction: {final_score}/100 → {signal}.",
            weight_note,
        ] + all_thesis[:4]
        
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
            except Exception as e:
                logger.warning(f"ExecutiveTrader LLM thesis synthesis failed: {e}")

        logger.info(
            "ExecutiveTrader regime=%s: score=%d signal=%s "
            "[fund=%d tech=%d macro=%d inst=%d sent=%d vis=%d fac=%d]",
            regime, final_score, signal,
            fundamental_score, technical_score, macro_score,
            institutional_score, sentiment_score, vision_score, factor_score,
        )

        return {
            "final_score":   final_score,
            "signal":        signal,
            "signal_thesis": signal_thesis,
        }
