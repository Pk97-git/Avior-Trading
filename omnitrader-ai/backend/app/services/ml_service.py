"""
services/ml_service.py
=======================
MLService — trains, stores, and serves predictions from all ML models.

Responsibilities
----------------
• Build feature matrices via FeatureEngineer
• Train XGBoost, LightGBM, LSTM, Transformer, DQN ensemble per ticker
• Persist models to disk (MODEL_DIR = /tmp/omnitrader_models/)
• Serve ensemble predictions with per-model breakdown
• Track model accuracy metrics (direction accuracy, RMSE)
• Cache last prediction per ticker (5-minute TTL)

Model storage
-------------
  /tmp/omnitrader_models/{ticker}/ensemble.pkl
  /tmp/omnitrader_models/{ticker}/rl_agent.pkl
  /tmp/omnitrader_models/{ticker}/metadata.json
"""
from __future__ import annotations

import json
import logging
import os
import time
from datetime import datetime, timezone
from typing import Optional

import numpy as np
from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger(__name__)

MODEL_DIR = os.getenv("ML_MODEL_DIR", "/tmp/omnitrader_models")
PREDICTION_CACHE_TTL = 300  # 5 minutes


class _PredictionCache:
    def __init__(self, ttl: int = PREDICTION_CACHE_TTL):
        self._cache: dict[str, tuple[float, dict]] = {}  # ticker → (timestamp, result)
        self.ttl = ttl

    def get(self, ticker: str) -> Optional[dict]:
        if ticker in self._cache:
            ts, result = self._cache[ticker]
            if time.time() - ts < self.ttl:
                return result
        return None

    def set(self, ticker: str, result: dict) -> None:
        self._cache[ticker] = (time.time(), result)

_cache = _PredictionCache()


class MLService:
    """
    Train and serve ML predictions for a stock ticker.

    Usage:
        svc = MLService(db)
        result = await svc.train(ticker="RELIANCE.NS")
        pred   = await svc.predict(ticker="RELIANCE.NS")
    """

    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    def _model_dir(self, ticker: str) -> str:
        return os.path.join(MODEL_DIR, ticker.upper().replace(".", "_"))

    def _metadata_path(self, ticker: str) -> str:
        return os.path.join(self._model_dir(ticker), "metadata.json")

    def _ensemble_path(self, ticker: str) -> str:
        return os.path.join(self._model_dir(ticker), "ensemble.pkl")

    def _rl_path(self, ticker: str) -> str:
        return os.path.join(self._model_dir(ticker), "rl_agent.pkl")

    def get_model_status(self, ticker: str) -> dict:
        meta_path = self._metadata_path(ticker)
        if not os.path.exists(meta_path):
            return {"trained": False, "ticker": ticker}
        try:
            with open(meta_path) as f:
                meta = json.load(f)
            meta["trained"] = True
            return meta
        except Exception:
            return {"trained": False, "ticker": ticker, "error": "metadata corrupted"}

    async def train(self, ticker: str, lookback_days: int = 500) -> dict:
        """
        Train all ML models for a ticker.

        Steps:
          1. Build feature matrix (FeatureEngineer)
          2. Train EnsemblePredictor (XGBoost + LightGBM + LSTM + Transformer)
          3. Train DQNTradingAgent
          4. Evaluate on holdout (last 20% of data)
          5. Save models + metadata to disk

        Returns:
          {ticker, trained_at, n_samples, n_features, metrics, model_weights, feature_importance_top10}
        """
        from app.engines.feature_engineering import FeatureEngineer
        from app.engines.prediction_models import EnsemblePredictor
        from app.engines.rl_agent import DQNTradingAgent

        logger.info("[MLService] Starting training for %s (lookback=%d days)", ticker, lookback_days)
        start_time = time.time()

        # 1. Build features
        fe = FeatureEngineer(self.db)
        X_df, y = await fe.build(ticker=ticker, lookback_days=lookback_days)
        feature_names = list(X_df.columns)
        X = X_df.values.astype(np.float32)
        y_arr = y.values.astype(np.float32)

        logger.info("[MLService] %s: %d samples × %d features", ticker, len(X), len(feature_names))

        # 2. Train ensemble
        ensemble = EnsemblePredictor()
        ensemble.fit(X, y_arr, feature_names=feature_names)

        # 3. Train RL agent on daily returns
        daily_returns = X_df.get("ret_1d", X_df.iloc[:, 0]).values.astype(np.float32)
        rl_agent = DQNTradingAgent(n_features=len(feature_names), episodes=30)
        rl_history = rl_agent.train(X, daily_returns, episodes=30)

        # 4. Evaluate on holdout (last 20%)
        split = int(len(X) * 0.8)
        X_val, y_val = X[split:], y_arr[split:]
        val_valid = ~np.isnan(y_val)
        metrics = {}
        if val_valid.sum() > 5:
            preds = ensemble.predict(X_val)
            preds = preds[-val_valid.sum():]
            y_eval = y_val[val_valid]
            if len(preds) >= len(y_eval):
                preds = preds[-len(y_eval):]
            rmse = float(np.sqrt(np.nanmean((preds - y_eval) ** 2)))
            direction_acc = float(np.mean(np.sign(preds) == np.sign(y_eval))) * 100
            metrics = {
                "rmse": round(rmse, 4),
                "direction_accuracy_pct": round(direction_acc, 2),
                "val_samples": int(val_valid.sum()),
            }

        # 5. Save models
        model_dir = self._model_dir(ticker)
        os.makedirs(model_dir, exist_ok=True)
        ensemble.save(self._ensemble_path(ticker))
        rl_agent.save(self._rl_path(ticker))

        # Feature importance top 10
        fi = ensemble.feature_importance()
        top10 = dict(list(fi.items())[:10])

        metadata = {
            "ticker":         ticker.upper(),
            "trained_at":     datetime.now(timezone.utc).isoformat(),
            "n_samples":      len(X),
            "n_features":     len(feature_names),
            "feature_names":  feature_names,
            "metrics":        metrics,
            "model_weights":  ensemble.model_weights(),
            "rl_history":     {k: v for k, v in rl_history.items() if k != "episode_rewards"},
            "training_sec":   round(time.time() - start_time, 1),
        }
        with open(self._metadata_path(ticker), "w") as f:
            json.dump(metadata, f, indent=2)

        _cache.set(ticker, {})  # invalidate cache
        logger.info("[MLService] %s training complete in %.1fs", ticker, time.time() - start_time)

        result = {**metadata, "feature_importance_top10": top10}
        return result

    async def predict(self, ticker: str) -> dict:
        """
        Get ensemble prediction for a ticker.

        Returns:
          {ticker, prediction: {return_5d_pct, direction, confidence, signal},
           model_breakdown, rl_action, feature_importance_top10, model_age_hours}
        """
        # Check cache
        cached = _cache.get(ticker.upper())
        if cached:
            return {**cached, "from_cache": True}

        from app.engines.feature_engineering import FeatureEngineer
        from app.engines.prediction_models import EnsemblePredictor
        from app.engines.rl_agent import DQNTradingAgent

        # Load models
        ensemble_path = self._ensemble_path(ticker)
        rl_path       = self._rl_path(ticker)
        meta_path     = self._metadata_path(ticker)

        if not os.path.exists(ensemble_path):
            raise FileNotFoundError(
                f"No trained model for {ticker}. Call POST /predictions/train/{ticker} first."
            )

        ensemble = EnsemblePredictor.load(ensemble_path)
        rl_agent  = DQNTradingAgent.load(rl_path)

        with open(meta_path) as f:
            meta = json.load(f)

        # Build latest features (last 60 rows for sequence models)
        fe = FeatureEngineer(self.db)
        X_df, _ = await fe.build(ticker=ticker, lookback_days=100)
        X = X_df.values.astype(np.float32)

        # Ensemble prediction (last row = today)
        preds = ensemble.predict(X)
        latest_pred = float(preds[-1])

        # Direction and signal
        if latest_pred > 1.0:
            direction = "UP"
            signal = "BUY"
        elif latest_pred < -1.0:
            direction = "DOWN"
            signal = "SELL"
        else:
            direction = "FLAT"
            signal = "HOLD"

        # Probability estimate
        confidence = min(100, max(0, int(abs(latest_pred) * 20)))  # scale to 0-100

        # RL action for latest state
        state = X[-1]
        state_with_pos = np.concatenate([state, [0.0, 0.0]])  # flat position
        rl_result = rl_agent.predict_action(state_with_pos)

        # Per-model breakdown
        breakdown = {}
        for model in ensemble.models:
            try:
                model_preds = model.predict(X)
                breakdown[model.name] = round(float(model_preds[-1]), 4)
            except Exception:
                pass

        # Feature importance
        fi = ensemble.feature_importance()
        top10 = dict(list(fi.items())[:10])

        # Model age
        trained_at = meta.get("trained_at", "")
        try:
            age_hours = (datetime.now(timezone.utc) - datetime.fromisoformat(trained_at)).total_seconds() / 3600
        except Exception:
            age_hours = 0.0

        result = {
            "ticker": ticker.upper(),
            "prediction": {
                "return_5d_pct": round(latest_pred, 4),
                "direction":     direction,
                "signal":        signal,
                "confidence":    confidence,
            },
            "model_breakdown":       breakdown,
            "model_weights":         ensemble.model_weights(),
            "rl_action":             rl_result,
            "feature_importance_top10": top10,
            "training_metrics":      meta.get("metrics", {}),
            "model_age_hours":       round(age_hours, 1),
            "from_cache":            False,
        }
        _cache.set(ticker.upper(), result)
        return result

    async def get_feature_values(self, ticker: str) -> dict:
        """Return latest feature values for a ticker (for explainability)."""
        from app.engines.feature_engineering import FeatureEngineer
        fe = FeatureEngineer(self.db)
        X_df, _ = await fe.build(ticker=ticker, lookback_days=60)

        meta = self.get_model_status(ticker)
        fi = {}
        if meta.get("trained"):
            from app.engines.prediction_models import EnsemblePredictor
            path = self._ensemble_path(ticker)
            if os.path.exists(path):
                ensemble = EnsemblePredictor.load(path)
                fi = ensemble.feature_importance()

        latest = X_df.iloc[-1].to_dict()
        # Merge with importance scores
        features_with_importance = {
            name: {"value": round(float(val), 4), "importance": round(fi.get(name, 0.0), 6)}
            for name, val in latest.items()
        }
        return {
            "ticker": ticker.upper(),
            "features": features_with_importance,
            "feature_count": len(features_with_importance),
            "as_of": X_df.index[-1].isoformat() if hasattr(X_df.index[-1], 'isoformat') else str(X_df.index[-1]),
        }
