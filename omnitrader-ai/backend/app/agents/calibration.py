from typing import Optional, List, Dict, Tuple
"""
agents/calibration.py
======================
Probability Calibration — Platt Scaling
Converts raw final_score (0-100) into a calibrated win probability (0.0–1.0)
using logistic regression trained on historical analysis vs actual 30-day returns.

Falls back to a sigmoid approximation if not enough historical data exists.

Returns:
    calibrated_prob: float (0.0–1.0)
"""
import logging
import math
from datetime import datetime, timedelta, timezone

from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import text

logger = logging.getLogger(__name__)

# Platt scaling parameters (pre-fitted defaults — overridden by fitted values)
DEFAULT_A = -0.08   # slope (negative because high score = high prob)
DEFAULT_B = 4.0     # intercept


def _sigmoid(x: float) -> float:
    return 1.0 / (1.0 + math.exp(-x))


def _logistic_regression_fit(scores: list[float], labels: list[float]) -> tuple[float, float]:
    """
    Minimal gradient descent Platt scaling without scipy dependency.
    labels: 1.0 if 30d return > 3%, else 0.0
    Returns (a, b) such that prob = sigmoid(a * score + b)
    """
    n = len(scores)
    if n < 20:
        return DEFAULT_A, DEFAULT_B

    a, b = DEFAULT_A, DEFAULT_B
    lr = 0.001
    for _ in range(500):  # gradient descent iterations
        da, db = 0.0, 0.0
        for s, y in zip(scores, labels):
            p = _sigmoid(a * s + b)
            da += (p - y) * s
            db += (p - y)
        a -= lr * da / n
        b -= lr * db / n

    return round(a, 6), round(b, 6)


class CalibrationEngine:
    """
    Trains on historical (final_score, 30d_return) pairs and
    converts a new score to a win probability.
    """

    def __init__(self, db: AsyncSession):
        self.db = db
        self._a = DEFAULT_A
        self._b = DEFAULT_B
        self._fitted = False

    async def fit(self) -> None:
        """Load historical analysis vs outcomes and fit logistic regression."""
        try:
            # Join ai_analysis with 30-day forward return from stock_prices
            res = await self.db.execute(text("""
                SELECT a.final_score,
                       (p_future.close - p_now.close) / NULLIF(p_now.close, 0) AS return_30d
                FROM ai_analysis a
                JOIN stock_prices p_now ON p_now.ticker = a.ticker
                    AND DATE(p_now.time) = DATE(a.analysis_date)
                JOIN stock_prices p_future ON p_future.ticker = a.ticker
                    AND DATE(p_future.time) = DATE(a.analysis_date + INTERVAL '30 days')
                WHERE a.analysis_date < NOW() - INTERVAL '31 days'
                LIMIT 2000
            """))
            rows = res.fetchall()

            if len(rows) < 20:
                logger.info("[Calibration] Not enough history to fit — using defaults.")
                return

            scores = [float(r.final_score) for r in rows]
            labels = [1.0 if r.return_30d is not None and r.return_30d > 0.03 else 0.0 for r in rows]

            self._a, self._b = _logistic_regression_fit(scores, labels)
            self._fitted = True
            logger.info("[Calibration] Fitted Platt scaling: a=%.4f b=%.4f on %d examples", self._a, self._b, len(rows))

        except Exception as e:
            logger.warning("[Calibration] Fit failed (%s) — using defaults.", e)

    def predict(self, final_score: int) -> float:
        """Convert final_score to calibrated win probability."""
        prob = _sigmoid(self._a * final_score + self._b)
        return round(max(0.05, min(0.95, prob)), 3)
