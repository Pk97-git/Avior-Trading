"""
Phase 3: Computed Data Layer
==============================
Handles storing computed/derived data that feeds the Historical Memory Engine:
1. Market State Embeddings — vector snapshots for pgvector similarity search
2. Historical Regime Labels — computed by Macro Engine, stored for backtesting
3. Feature Snapshots — versioned feature vectors for Walk-Forward Validation

This module is the bridge between raw ingested data and the AI engines.
"""
import asyncio
import json
import numpy as np
from datetime import datetime, timedelta
from typing import List, Dict, Optional, Any
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from app.models.market_data import (
    MarketSnapshot, RegimeLabel, MacroEconomicData, StockPrice
)
from app.db.session import AsyncSessionLocal


# ─── Feature Extractor ───────────────────────────────────────────────────────

class FeatureExtractor:
    """
    Extracts a standardized feature vector from raw DB data for a given date.
    This vector is used for:
    - Historical similarity search (pgvector)
    - Regime classification input
    - Walk-forward validation datasets
    """

    def __init__(self, db: AsyncSession):
        self.db = db

    async def _get_macro_value(self, indicator: str, as_of: datetime) -> Optional[float]:
        """Get the most recent macro value on or before a given date."""
        result = await self.db.execute(
            select(MacroEconomicData.value)
            .where(MacroEconomicData.indicator == indicator)
            .where(MacroEconomicData.time <= as_of)
            .order_by(MacroEconomicData.time.desc())
            .limit(1)
        )
        row = result.scalar()
        return float(row) if row is not None else None

    async def _get_price_return(self, ticker: str, as_of: datetime, lookback_days: int) -> Optional[float]:
        """Compute N-day return for a ticker."""
        start = as_of - timedelta(days=lookback_days + 10)  # buffer for weekends
        result = await self.db.execute(
            select(StockPrice.close, StockPrice.time)
            .where(StockPrice.ticker == ticker)
            .where(StockPrice.time.between(start, as_of))
            .order_by(StockPrice.time.asc())
        )
        rows = result.all()
        if len(rows) < 2:
            return None
        first_close = rows[0].close
        last_close = rows[-1].close
        if first_close and first_close > 0:
            return (last_close - first_close) / first_close
        return None

    async def extract_features(self, as_of: datetime) -> Dict[str, Optional[float]]:
        """
        Extracts the full feature vector for a given date.
        Returns a dict of feature_name -> value.
        """
        features = {}

        # ── Macro Features ──
        macro_indicators = [
            "VIX_US", "US_YIELD_CURVE_10Y_2Y", "USD_INDEX",
            "Crude_Oil_WTI", "Gold", "FED_FUNDS_RATE",
            "CPI_US", "US_10Y_YIELD", "Bitcoin",
        ]
        for ind in macro_indicators:
            features[ind] = await self._get_macro_value(ind, as_of)

        # ── Market Return Features ──
        # SP500 momentum (proxy via ^GSPC price)
        features["SP500_1M_RETURN"] = await self._get_price_return("^GSPC", as_of, 21)
        features["SP500_3M_RETURN"] = await self._get_price_return("^GSPC", as_of, 63)
        features["NIFTY_1M_RETURN"] = await self._get_price_return("^NSEI", as_of, 21)

        return features

    def features_to_vector(self, features: Dict[str, Optional[float]], dim: int = 64) -> List[float]:
        """
        Converts feature dict to a fixed-size normalized vector.
        Missing values are filled with 0.0.
        Uses a fixed ordering for consistency.
        """
        FEATURE_ORDER = [
            "VIX_US", "US_YIELD_CURVE_10Y_2Y", "USD_INDEX",
            "Crude_Oil_WTI", "Gold", "FED_FUNDS_RATE",
            "CPI_US", "US_10Y_YIELD", "Bitcoin",
            "SP500_1M_RETURN", "SP500_3M_RETURN", "NIFTY_1M_RETURN",
        ]
        vec = [features.get(k) or 0.0 for k in FEATURE_ORDER]

        # Pad or truncate to dim
        if len(vec) < dim:
            vec.extend([0.0] * (dim - len(vec)))
        else:
            vec = vec[:dim]

        return vec


# ─── Market Snapshot Store ────────────────────────────────────────────────────

class MarketSnapshotService:
    """
    Computes and stores market state snapshots for the Historical Memory Engine.
    Each snapshot = feature vector + regime label + timestamp.
    """

    def __init__(self, db: AsyncSession):
        self.db = db
        self.extractor = FeatureExtractor(db)

    async def store_snapshot(self, as_of: datetime, regime_label: str = None):
        """
        Computes features for a given date and stores as a MarketSnapshot.
        The embedding vector is stored in pgvector for similarity search.
        """
        features = await self.extractor.extract_features(as_of)
        vector = self.extractor.features_to_vector(features, dim=1536)

        # Pad to 1536 dims (pgvector schema)
        if len(vector) < 1536:
            vector.extend([0.0] * (1536 - len(vector)))

        snapshot = MarketSnapshot(
            time=as_of,
            regime_label=regime_label or "UNKNOWN",
            embedding=vector,
            features=features,
        )

        # Upsert
        existing = await self.db.execute(
            select(MarketSnapshot).where(MarketSnapshot.time == as_of)
        )
        if existing.scalars().first():
            await self.db.execute(
                MarketSnapshot.__table__.update()
                .where(MarketSnapshot.time == as_of)
                .values(regime_label=regime_label, embedding=vector, features=features)
            )
        else:
            self.db.add(snapshot)

        await self.db.commit()
        print(f"  Stored market snapshot for {as_of.date()}")

    async def backfill_snapshots(self, start_date: datetime, end_date: datetime):
        """
        Backfills historical snapshots for the memory engine.
        Runs weekly to build up the historical similarity database.
        """
        current = start_date
        count = 0
        while current <= end_date:
            # Only weekdays
            if current.weekday() < 5:
                await self.store_snapshot(current)
                count += 1
            current += timedelta(days=1)

        print(f"  Backfilled {count} market snapshots from {start_date.date()} to {end_date.date()}")


# ─── Regime Label Store ───────────────────────────────────────────────────────

class RegimeLabelService:
    """
    Stores computed regime labels from the Macro Engine.
    These are used by:
    - Historical Similarity Engine (find similar past regimes)
    - Walk-Forward Validation (train on past regimes)
    - Scoring Engine (regime-weighted signal weights)
    """

    def __init__(self, db: AsyncSession):
        self.db = db

    async def store_regime(
        self,
        as_of: datetime,
        regime: str,
        confidence: float,
        stability_score: float,
        transition_state: str = None,
        transition_prob: float = None,
        features: Dict = None,
    ):
        """Store a computed regime label."""
        records = [{
            "time": as_of,
            "regime": regime,
            "regime_confidence": confidence,
            "stability_score": stability_score,
            "transition_state": transition_state,
            "transition_prob": transition_prob,
            "features": features or {},
        }]
        stmt = pg_insert(RegimeLabel).values(records)
        stmt = stmt.on_conflict_do_update(
            index_elements=["time"],
            set_={
                "regime": stmt.excluded.regime,
                "regime_confidence": stmt.excluded.regime_confidence,
                "stability_score": stmt.excluded.stability_score,
            }
        )
        await self.db.execute(stmt)
        await self.db.commit()
        print(f"  Stored regime label: {regime} (confidence={confidence:.2f}) for {as_of.date()}")

    async def get_regime_history(self, days: int = 365) -> List[Dict]:
        """Retrieve recent regime history for calibration."""
        cutoff = datetime.utcnow() - timedelta(days=days)
        result = await self.db.execute(
            select(RegimeLabel)
            .where(RegimeLabel.time >= cutoff)
            .order_by(RegimeLabel.time.asc())
        )
        rows = result.scalars().all()
        return [
            {
                "time": r.time,
                "regime": r.regime,
                "confidence": r.regime_confidence,
                "stability": r.stability_score,
            }
            for r in rows
        ]


# ─── Standalone Runner ────────────────────────────────────────────────────────

async def initialize_computed_data():
    """
    One-time initialization: backfills market snapshots for the last 5 years.
    Run after initial_load_flow completes.
    """
    async with AsyncSessionLocal() as session:
        snapshot_svc = MarketSnapshotService(session)
        end = datetime.utcnow()
        start = end - timedelta(days=365 * 5)  # 5 years
        print(f"Backfilling market snapshots from {start.date()} to {end.date()}...")
        await snapshot_svc.backfill_snapshots(start, end)
        print("Computed data initialization complete.")


if __name__ == "__main__":
    asyncio.run(initialize_computed_data())
