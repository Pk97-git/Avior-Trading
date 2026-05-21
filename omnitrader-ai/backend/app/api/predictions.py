"""
api/predictions.py
==================
ML Prediction API endpoints.

POST /predictions/train/{ticker}    — train all models (runs in background)
GET  /predictions/{ticker}          — ensemble prediction + RL action
GET  /predictions/{ticker}/features — feature values + importance scores
GET  /predictions/{ticker}/status   — model status, age, accuracy
GET  /predictions/leaderboard       — compare model accuracy across tickers
"""
import asyncio
import logging
from typing import Optional

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import get_db
from app.services.ml_service import MLService

router = APIRouter()
logger = logging.getLogger(__name__)


@router.post("/train/{ticker}")
async def train_models(
    ticker: str,
    background_tasks: BackgroundTasks,
    lookback_days: int = Query(500, ge=100, le=2000),
    db: AsyncSession = Depends(get_db),
):
    """
    Train all ML models for a ticker: XGBoost, LightGBM, LSTM, Transformer, DQN.

    Runs as a background task (~2-5 minutes). Poll GET /predictions/{ticker}/status
    to check when training completes.

    Feature groups trained on:
    - Momentum (12): RSI, MACD, returns 1d/5d/20d/60d/252d, MA crossovers
    - Volatility (8): ATR, realized vol, Bollinger bandwidth, Parkinson
    - Volume (5): OBV slope, MFI, volume ratio, large-block flag
    - Macro (5): VIX, 10Y yield, USD, crude oil, FII flow
    - Sentiment (4): news sentiment 7d/30d, momentum, insider buy
    - Earnings (4): EPS surprise, revenue surprise, beat flag, days since earnings
    - Calendar (4): day of week, month (sin/cos encoded)
    """
    t = ticker.upper()
    logger.info("[Predictions] Training requested for %s", t)

    async def _train_task():
        try:
            async with db.__class__(db.bind) as new_db:
                svc = MLService(new_db)
                await svc.train(t, lookback_days=lookback_days)
        except Exception as exc:
            logger.error("[Predictions] Training failed for %s: %s", t, exc)

    # Use a simple asyncio task since BackgroundTasks doesn't support async sessions well
    asyncio.create_task(_train_task())

    return {
        "status":      "training_started",
        "ticker":      t,
        "lookback_days": lookback_days,
        "message":     f"Training {t} with {lookback_days} days of data. Check GET /predictions/{t}/status for progress.",
        "models":      ["XGBoost", "LightGBM", "LSTM", "Transformer", "DQN-RL", "Ensemble"],
        "features":    42,
    }


@router.get("/{ticker}")
async def get_prediction(
    ticker: str,
    db: AsyncSession = Depends(get_db),
):
    """
    Get the ensemble ML prediction for a ticker.

    Returns:
    - **prediction**: 5-day forward return estimate, direction (UP/DOWN/FLAT), signal (BUY/SELL/HOLD), confidence
    - **model_breakdown**: each model's individual prediction
    - **model_weights**: inverse-MSE derived ensemble weights
    - **rl_action**: DQN agent recommended action (BUY/HOLD/SELL) with Q-values
    - **feature_importance_top10**: most influential features driving this prediction
    - **training_metrics**: holdout RMSE and direction accuracy

    Models must be trained first via POST /predictions/train/{ticker}.
    """
    try:
        svc = MLService(db)
        result = await svc.predict(ticker.upper())
        return result
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    except Exception as exc:
        logger.exception("[Predictions] predict failed for %s: %s", ticker, exc)
        raise HTTPException(status_code=500, detail=str(exc))


@router.get("/{ticker}/features")
async def get_features(
    ticker: str,
    db: AsyncSession = Depends(get_db),
):
    """
    Get the current feature values for a ticker with importance scores.

    Useful for understanding what data is driving the model's prediction.
    Sorted by importance (most influential first).
    """
    try:
        svc = MLService(db)
        result = await svc.get_feature_values(ticker.upper())
        # Sort by importance descending
        result["features"] = dict(
            sorted(result["features"].items(), key=lambda x: -x[1]["importance"])
        )
        return result
    except Exception as exc:
        logger.exception("[Predictions] feature fetch failed for %s: %s", ticker, exc)
        raise HTTPException(status_code=500, detail=str(exc))


@router.get("/{ticker}/status")
async def model_status(
    ticker: str,
    db: AsyncSession = Depends(get_db),
):
    """
    Check the training status and accuracy of models for a ticker.
    Returns training metadata, accuracy metrics, and model age.
    """
    svc = MLService(db)
    status = svc.get_model_status(ticker.upper())
    return status


@router.get("/leaderboard")
async def leaderboard(
    db: AsyncSession = Depends(get_db),
):
    """
    Model performance leaderboard across all trained tickers.
    Shows direction accuracy and RMSE for each trained ticker.
    """
    import os, json
    from app.services.ml_service import MODEL_DIR

    results = []
    if not os.path.exists(MODEL_DIR):
        return {"tickers": [], "count": 0}

    for ticker_dir in os.listdir(MODEL_DIR):
        meta_path = os.path.join(MODEL_DIR, ticker_dir, "metadata.json")
        if os.path.exists(meta_path):
            try:
                with open(meta_path) as f:
                    meta = json.load(f)
                results.append({
                    "ticker":                meta.get("ticker", ticker_dir),
                    "trained_at":            meta.get("trained_at"),
                    "n_samples":             meta.get("n_samples"),
                    "direction_accuracy_pct": meta.get("metrics", {}).get("direction_accuracy_pct"),
                    "rmse":                  meta.get("metrics", {}).get("rmse"),
                    "training_sec":          meta.get("training_sec"),
                    "model_weights":         meta.get("model_weights", {}),
                })
            except Exception:
                pass

    results.sort(key=lambda x: -(x.get("direction_accuracy_pct") or 0))
    return {"tickers": results, "count": len(results)}
