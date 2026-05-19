from typing import Optional, List, Dict, Tuple
"""
agents/memory.py
================
MemoryAgent — finds historical market regimes similar to the current one
and reports what happened to prices in the 30/60/90 days that followed.

Strategy:
  1. Read the latest market_snapshot features (JSONB) for this ticker or
     the global snapshot if no per-ticker snapshot exists.
  2. Find the top-3 most similar historical snapshots using a simple
     normalised cosine similarity on the feature vector extracted from JSONB.
  3. For each analog date, look up the actual 30/60/90-day forward return
     from stock_prices.
  4. Return confidence + analog summary.

Fallback: if market_snapshots is empty, returns neutral with a note.

Score formula:
  avg_30d_return > 5%  → score 72
  avg_30d_return 0–5%  → score 58
  avg_30d_return −5–0% → score 42
  avg_30d_return < −5% → score 30
"""
import logging
import math
from datetime import datetime, timedelta, timezone
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import text

logger = logging.getLogger(__name__)

# Feature keys extracted from market_snapshots.features JSONB
FEATURE_KEYS = [
    "vix", "us10y", "us2y", "fedfunds", "cpi", "dxy",
    "price_vs_sma200", "rsi_14", "fii_30d_net",
]


def _cosine_sim(a: list[float], b: list[float]) -> float:
    dot  = sum(x * y for x, y in zip(a, b))
    norm_a = math.sqrt(sum(x * x for x in a))
    norm_b = math.sqrt(sum(y * y for y in b))
    if norm_a == 0 or norm_b == 0:
        return 0.0
    return dot / (norm_a * norm_b)


def _extract_features(features_json: dict) -> Optional[list[float]]:
    vals = []
    for k in FEATURE_KEYS:
        v = features_json.get(k)
        if v is None:
            return None
        vals.append(float(v))
    return vals


class MemoryAgent:
    def __init__(self, db: AsyncSession, ticker: str):
        self.db = db
        self.ticker = ticker

    async def _latest_snapshot(self) -> Optional[dict]:
        """Fetch the most recent market snapshot features."""
        query = text("""
            SELECT features, time FROM market_snapshots
            WHERE features IS NOT NULL
            ORDER BY time DESC
            LIMIT 1
        """)
        result = await self.db.execute(query)
        row = result.fetchone()
        return {"features": row.features, "time": row.time} if row else None

    async def _all_snapshots(self) -> list[dict]:
        """Fetch all historical snapshots (excluding last 90 days)."""
        cutoff = datetime.now(timezone.utc) - timedelta(days=90)
        query = text("""
            SELECT time, features FROM market_snapshots
            WHERE features IS NOT NULL AND time < :cutoff
            ORDER BY time DESC
            LIMIT 500
        """)
        result = await self.db.execute(query, {"cutoff": cutoff})
        return [{"time": r.time, "features": r.features} for r in result.fetchall()]

    async def _forward_return(self, from_date: datetime, days: int) -> Optional[float]:
        """Calculate actual forward return for this ticker starting from `from_date`."""
        to_date = from_date + timedelta(days=days + 10)  # buffer for non-trading days
        query = text("""
            SELECT close, time FROM stock_prices
            WHERE ticker = :ticker
              AND time BETWEEN :start AND :end
              AND close IS NOT NULL
            ORDER BY time ASC
            LIMIT 1
        """)
        r_start = await self.db.execute(query, {
            "ticker": self.ticker, "start": from_date,
            "end": from_date + timedelta(days=5)
        })
        row_start = r_start.fetchone()

        r_end = await self.db.execute(text("""
            SELECT close, time FROM stock_prices
            WHERE ticker = :ticker
              AND time BETWEEN :start AND :end
              AND close IS NOT NULL
            ORDER BY time DESC
            LIMIT 1
        """), {"ticker": self.ticker, "start": from_date + timedelta(days=days - 5),
               "end": to_date})
        row_end = r_end.fetchone()

        if not row_start or not row_end or row_start.close == 0:
            return None
        return ((row_end.close - row_start.close) / row_start.close) * 100

    async def analyze(self) -> dict:
        """
        Returns:
            {
                "score": int,
                "confidence": float,
                "analogs": list[dict],
                "thesis": list[str],
            }
        """
        try:
            current = await self._latest_snapshot()
            if not current:
                return {
                    "score": 50, "confidence": 0.0, "analogs": [],
                    "thesis": ["No market snapshots available yet. Neutral score."],
                }

            current_feats = _extract_features(current["features"])
            if current_feats is None:
                return {
                    "score": 50, "confidence": 0.0, "analogs": [],
                    "thesis": ["Snapshot feature vector incomplete. Neutral score."],
                }

            historical = await self._all_snapshots()
            if not historical:
                return {
                    "score": 50, "confidence": 0.0, "analogs": [],
                    "thesis": ["Insufficient historical snapshots for analog search."],
                }

            # Rank by cosine similarity
            scored = []
            for snap in historical:
                feats = _extract_features(snap["features"])
                if feats is None:
                    continue
                sim = _cosine_sim(current_feats, feats)
                scored.append({"time": snap["time"], "sim": sim})

            scored.sort(key=lambda x: x["sim"], reverse=True)
            top3 = scored[:3]

            # Fetch forward returns for each analog
            analogs = []
            forward_30d = []
            for a in top3:
                r30 = await self._forward_return(a["time"], 30)
                r60 = await self._forward_return(a["time"], 60)
                r90 = await self._forward_return(a["time"], 90)
                analogs.append({
                    "date": a["time"].date().isoformat(),
                    "similarity": round(a["sim"], 3),
                    "forward_30d_pct": round(r30, 1) if r30 is not None else None,
                    "forward_60d_pct": round(r60, 1) if r60 is not None else None,
                    "forward_90d_pct": round(r90, 1) if r90 is not None else None,
                })
                if r30 is not None:
                    forward_30d.append(r30)

            avg_30d = sum(forward_30d) / len(forward_30d) if forward_30d else None
            confidence = top3[0]["sim"] if top3 else 0.0

            # Score
            if avg_30d is None:
                score = 50
            elif avg_30d > 5:
                score = 72
            elif avg_30d > 0:
                score = 58
            elif avg_30d > -5:
                score = 42
            else:
                score = 30

            # Thesis
            thesis = []
            if analogs:
                thesis.append(
                    f"Found {len(analogs)} similar historical setups "
                    f"(best match: {analogs[0]['date']}, similarity {analogs[0]['similarity']:.2f})."
                )
            if avg_30d is not None:
                direction = "gained" if avg_30d > 0 else "lost"
                thesis.append(
                    f"In similar past conditions, {self.ticker} {direction} "
                    f"{abs(avg_30d):.1f}% on average over 30 days."
                )

            logger.info("MemoryAgent %s: score=%d confidence=%.2f analogs=%d",
                        self.ticker, score, confidence, len(analogs))
            return {
                "score": score,
                "confidence": round(confidence, 3),
                "analogs": analogs,
                "thesis": thesis,
            }

        except Exception as e:
            logger.error("MemoryAgent %s: %s", self.ticker, e)
            return {
                "score": 50, "confidence": 0.0, "analogs": [],
                "thesis": [f"Historical memory analysis failed: {e}"],
            }
