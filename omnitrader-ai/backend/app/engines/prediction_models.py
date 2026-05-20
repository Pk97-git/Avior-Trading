"""
engines/prediction_models.py
=============================
ML prediction models for stock return forecasting.

Models
------
XGBoostPredictor    — gradient boosting (tabular, feature importance)
LightGBMPredictor   — fast gradient boosting (faster than XGB on large data)
LSTMPredictor       — sequence model (PyTorch if available, numpy fallback)
TransformerPredictor — attention-based sequence model (numpy implementation)
EnsemblePredictor   — weighted average of all models

Common interface
----------------
All models implement:
  fit(X: np.ndarray, y: np.ndarray) -> self
  predict(X: np.ndarray) -> np.ndarray          # continuous return prediction
  predict_proba(X: np.ndarray) -> np.ndarray    # P(return > threshold)
  feature_importance() -> dict[str, float]      # name → importance score
  save(path: str) -> None
  load(path: str) -> None

Target variable: 5-day forward return (continuous regression)
Classification threshold: > 0.5% = BUY signal (1), else 0
"""
from __future__ import annotations

import logging
import os
import pickle
from typing import Optional

import numpy as np

logger = logging.getLogger(__name__)

# ── Optional heavy imports (graceful degradation) ──────────────────────────────

try:
    import xgboost as xgb
    HAS_XGB = True
except ImportError:
    HAS_XGB = False
    logger.warning("xgboost not installed — XGBoostPredictor will be unavailable")

try:
    import lightgbm as lgb
    HAS_LGB = True
except ImportError:
    HAS_LGB = False
    logger.warning("lightgbm not installed — LightGBMPredictor will be unavailable")

try:
    import torch
    import torch.nn as nn
    HAS_TORCH = True
except ImportError:
    HAS_TORCH = False
    logger.info("torch not installed — LSTM/Transformer will use numpy fallback")

try:
    from sklearn.preprocessing import StandardScaler
    from sklearn.model_selection import train_test_split
    from sklearn.metrics import mean_squared_error, r2_score
    HAS_SKLEARN = True
except ImportError:
    HAS_SKLEARN = False


# ── Base class ─────────────────────────────────────────────────────────────────

class BasePredictor:
    """Abstract base — all predictors implement this interface."""
    name: str = "base"

    def fit(self, X: np.ndarray, y: np.ndarray) -> "BasePredictor":
        raise NotImplementedError

    def predict(self, X: np.ndarray) -> np.ndarray:
        raise NotImplementedError

    def predict_proba(self, X: np.ndarray, threshold: float = 0.5) -> np.ndarray:
        """P(return > threshold%). Default: sigmoid of prediction."""
        preds = self.predict(X)
        return 1 / (1 + np.exp(-(preds - threshold) * 2))

    def feature_importance(self) -> dict[str, float]:
        return {}

    def evaluate(self, X: np.ndarray, y: np.ndarray) -> dict:
        preds = self.predict(X)
        mse = float(np.mean((preds - y) ** 2))
        rmse = float(np.sqrt(mse))
        mae = float(np.mean(np.abs(preds - y)))
        direction_acc = float(np.mean(np.sign(preds) == np.sign(y))) * 100
        return {
            "mse": round(mse, 4), "rmse": round(rmse, 4), "mae": round(mae, 4),
            "direction_accuracy_pct": round(direction_acc, 2),
        }

    def save(self, path: str) -> None:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "wb") as f:
            pickle.dump(self, f)

    @classmethod
    def load(cls, path: str) -> "BasePredictor":
        with open(path, "rb") as f:
            return pickle.load(f)


# ── XGBoost Predictor ──────────────────────────────────────────────────────────

class XGBoostPredictor(BasePredictor):
    name = "xgboost"

    def __init__(self, n_estimators: int = 300, max_depth: int = 6,
                 learning_rate: float = 0.05, subsample: float = 0.8,
                 colsample_bytree: float = 0.8):
        self.params = dict(
            n_estimators=n_estimators, max_depth=max_depth,
            learning_rate=learning_rate, subsample=subsample,
            colsample_bytree=colsample_bytree,
            objective="reg:squarederror", eval_metric="rmse",
            random_state=42, n_jobs=-1, tree_method="hist",
        )
        self.model = None
        self.feature_names_: list[str] = []

    def fit(self, X: np.ndarray, y: np.ndarray, feature_names: Optional[list[str]] = None) -> "XGBoostPredictor":
        if not HAS_XGB:
            raise ImportError("xgboost not installed")
        self.feature_names_ = feature_names or [f"f{i}" for i in range(X.shape[1])]
        self.model = xgb.XGBRegressor(**self.params)
        self.model.fit(X, y, eval_set=[(X, y)], verbose=False)
        return self

    def predict(self, X: np.ndarray) -> np.ndarray:
        if self.model is None:
            raise RuntimeError("Model not trained yet")
        return self.model.predict(X).astype(float)

    def feature_importance(self) -> dict[str, float]:
        if self.model is None:
            return {}
        scores = self.model.feature_importances_
        return {name: round(float(score), 6) for name, score in zip(self.feature_names_, scores)}


# ── LightGBM Predictor ─────────────────────────────────────────────────────────

class LightGBMPredictor(BasePredictor):
    name = "lightgbm"

    def __init__(self, n_estimators: int = 300, max_depth: int = 6,
                 learning_rate: float = 0.05, num_leaves: int = 63,
                 subsample: float = 0.8, colsample_bytree: float = 0.8):
        self.params = dict(
            n_estimators=n_estimators, max_depth=max_depth,
            learning_rate=learning_rate, num_leaves=num_leaves,
            subsample=subsample, colsample_bytree=colsample_bytree,
            objective="regression", metric="rmse",
            random_state=42, n_jobs=-1, verbose=-1,
            force_col_wise=True,
        )
        self.model = None
        self.feature_names_: list[str] = []

    def fit(self, X: np.ndarray, y: np.ndarray, feature_names: Optional[list[str]] = None) -> "LightGBMPredictor":
        if not HAS_LGB:
            raise ImportError("lightgbm not installed")
        self.feature_names_ = feature_names or [f"f{i}" for i in range(X.shape[1])]
        self.model = lgb.LGBMRegressor(**self.params)
        self.model.fit(X, y)
        return self

    def predict(self, X: np.ndarray) -> np.ndarray:
        if self.model is None:
            raise RuntimeError("Model not trained yet")
        return self.model.predict(X).astype(float)

    def feature_importance(self) -> dict[str, float]:
        if self.model is None:
            return {}
        scores = self.model.feature_importances_
        total = scores.sum() or 1.0
        return {name: round(float(score / total), 6) for name, score in zip(self.feature_names_, scores)}


# ── PyTorch LSTM (used when torch is available) ────────────────────────────────

if HAS_TORCH:
    class _LSTMNet(nn.Module):
        def __init__(self, input_size: int, hidden_size: int = 64, num_layers: int = 2, dropout: float = 0.2):
            super().__init__()
            self.lstm = nn.LSTM(
                input_size=input_size, hidden_size=hidden_size,
                num_layers=num_layers, dropout=dropout if num_layers > 1 else 0,
                batch_first=True,
            )
            self.fc = nn.Sequential(
                nn.Linear(hidden_size, 32),
                nn.ReLU(),
                nn.Dropout(dropout),
                nn.Linear(32, 1),
            )

        def forward(self, x):
            # x: (batch, seq_len, input_size)
            out, _ = self.lstm(x)
            return self.fc(out[:, -1, :]).squeeze(-1)  # use last timestep


class LSTMPredictor(BasePredictor):
    """
    LSTM sequence model for time-series return prediction.
    Uses a sliding window of `seq_len` days as input.
    Falls back to a simple exponential weighted regression if torch is unavailable.
    """
    name = "lstm"

    def __init__(self, seq_len: int = 20, hidden_size: int = 64, num_layers: int = 2,
                 lr: float = 0.001, epochs: int = 50, batch_size: int = 32):
        self.seq_len = seq_len
        self.hidden_size = hidden_size
        self.num_layers = num_layers
        self.lr = lr
        self.epochs = epochs
        self.batch_size = batch_size
        self.model = None
        self.scaler = None
        self._use_torch = HAS_TORCH
        self._weights: Optional[np.ndarray] = None  # for numpy fallback

    def _make_sequences(self, X: np.ndarray) -> np.ndarray:
        """Convert flat feature matrix to (n_samples, seq_len, n_features) sequences."""
        seqs = []
        for i in range(self.seq_len, len(X)):
            seqs.append(X[i - self.seq_len: i])
        return np.array(seqs, dtype=np.float32)

    def fit(self, X: np.ndarray, y: np.ndarray, feature_names: Optional[list[str]] = None) -> "LSTMPredictor":
        # Normalize features
        if HAS_SKLEARN:
            from sklearn.preprocessing import StandardScaler
            self.scaler = StandardScaler()
            X_scaled = self.scaler.fit_transform(X)
        else:
            self.scaler = None
            X_scaled = (X - X.mean(0)) / (X.std(0) + 1e-8)

        if self._use_torch:
            self._fit_torch(X_scaled, y)
        else:
            self._fit_numpy_fallback(X_scaled, y)
        return self

    def _fit_torch(self, X_scaled: np.ndarray, y: np.ndarray) -> None:
        """Train LSTM with PyTorch."""
        seqs = self._make_sequences(X_scaled)
        targets = y[self.seq_len:].astype(np.float32)

        # Align (drop NaN targets)
        valid = ~np.isnan(targets)
        seqs, targets = seqs[valid], targets[valid]

        n_features = seqs.shape[2]
        self.model = _LSTMNet(n_features, self.hidden_size, self.num_layers)
        optimizer = torch.optim.Adam(self.model.parameters(), lr=self.lr, weight_decay=1e-5)
        criterion = nn.MSELoss()

        X_t = torch.tensor(seqs)
        y_t = torch.tensor(targets)

        self.model.train()
        n = len(X_t)
        for epoch in range(self.epochs):
            perm = torch.randperm(n)
            total_loss = 0.0
            for start in range(0, n, self.batch_size):
                idx = perm[start: start + self.batch_size]
                xb, yb = X_t[idx], y_t[idx]
                pred = self.model(xb)
                loss = criterion(pred, yb)
                optimizer.zero_grad()
                loss.backward()
                torch.nn.utils.clip_grad_norm_(self.model.parameters(), 1.0)
                optimizer.step()
                total_loss += loss.item()
            if (epoch + 1) % 10 == 0:
                logger.debug("[LSTM] epoch %d/%d loss=%.4f", epoch+1, self.epochs, total_loss)

    def _fit_numpy_fallback(self, X_scaled: np.ndarray, y: np.ndarray) -> None:
        """Simple exponential weighted linear regression as fallback."""
        # Use last seq_len rows weighted by recency as a simple sequence model
        weights = np.exp(np.linspace(-1, 0, self.seq_len))
        weights /= weights.sum()
        # For each sample, compute weighted feature sum
        X_seq = np.array([
            (X_scaled[max(0, i - self.seq_len): i] * weights[-min(i, self.seq_len):, None]).sum(0)
            for i in range(self.seq_len, len(X_scaled))
        ])
        y_seq = y[self.seq_len:]
        valid = ~np.isnan(y_seq)
        X_seq, y_seq = X_seq[valid], y_seq[valid]
        # Ridge regression solution
        lam = 0.01
        A = X_seq.T @ X_seq + lam * np.eye(X_seq.shape[1])
        b = X_seq.T @ y_seq
        self._weights = np.linalg.solve(A, b)

    def predict(self, X: np.ndarray) -> np.ndarray:
        if self.scaler is not None:
            X_scaled = self.scaler.transform(X)
        else:
            X_scaled = (X - X.mean(0)) / (X.std(0) + 1e-8)

        if self._use_torch and self.model is not None:
            seqs = self._make_sequences(X_scaled)
            self.model.eval()
            with torch.no_grad():
                preds = self.model(torch.tensor(seqs)).numpy()
            # Pad front with zeros to match input length
            return np.concatenate([np.zeros(self.seq_len), preds])

        if self._weights is not None:
            weights = np.exp(np.linspace(-1, 0, self.seq_len))
            weights /= weights.sum()
            result = []
            for i in range(len(X_scaled)):
                w_X = (X_scaled[max(0, i - self.seq_len): i + 1] * weights[-min(i+1, self.seq_len):, None]).sum(0)
                result.append(float(w_X @ self._weights))
            return np.array(result)

        return np.zeros(len(X))


# ── Transformer Predictor — attention mechanism in numpy ───────────────────────

class TransformerPredictor(BasePredictor):
    """
    Lightweight Transformer predictor using multi-head self-attention (numpy).

    Architecture:
      Input → Linear projection → Multi-head attention → FF layer → Output

    This is a compact numpy implementation suitable for inference without PyTorch.
    For production, replace with a PyTorch nn.Transformer.
    """
    name = "transformer"

    def __init__(self, seq_len: int = 20, d_model: int = 32,
                 n_heads: int = 4, n_layers: int = 2, lr: float = 0.001, epochs: int = 30):
        self.seq_len = seq_len
        self.d_model = d_model
        self.n_heads = n_heads
        self.n_layers = n_layers
        self.lr = lr
        self.epochs = epochs
        self.scaler = None
        # Weight matrices (initialized at fit time)
        self._W_in: Optional[np.ndarray] = None   # input projection
        self._W_out: Optional[np.ndarray] = None  # output head
        self._trained = False

    def _attention(self, Q: np.ndarray, K: np.ndarray, V: np.ndarray) -> np.ndarray:
        """Scaled dot-product attention. Q/K/V: (seq, d_head)"""
        d_k = Q.shape[-1]
        scores = Q @ K.T / np.sqrt(d_k)
        scores = scores - scores.max(axis=-1, keepdims=True)  # numerical stability
        attn = np.exp(scores) / (np.exp(scores).sum(axis=-1, keepdims=True) + 1e-9)
        return attn @ V

    def _forward(self, X_seq: np.ndarray) -> np.ndarray:
        """
        X_seq: (seq_len, n_features)
        Returns: scalar prediction
        """
        # Project input to d_model
        Z = X_seq @ self._W_in  # (seq_len, d_model)

        # Multi-head attention (simplified: share weights across heads)
        d_head = self.d_model // self.n_heads
        attn_out = np.zeros_like(Z)
        for h in range(self.n_heads):
            start, end = h * d_head, (h + 1) * d_head
            Q = Z[:, start:end]
            K = Z[:, start:end]
            V = Z[:, start:end]
            attn_out[:, start:end] = self._attention(Q, K, V)

        # Residual + mean pooling
        Z = Z + attn_out
        pooled = Z.mean(axis=0)  # (d_model,)

        # Output projection
        return float(pooled @ self._W_out)

    def fit(self, X: np.ndarray, y: np.ndarray, feature_names: Optional[list[str]] = None) -> "TransformerPredictor":
        if HAS_SKLEARN:
            from sklearn.preprocessing import StandardScaler
            self.scaler = StandardScaler()
            X_scaled = self.scaler.fit_transform(X).astype(np.float64)
        else:
            X_scaled = ((X - X.mean(0)) / (X.std(0) + 1e-8)).astype(np.float64)

        n_features = X_scaled.shape[1]
        n_samples = len(X_scaled)
        rng = np.random.default_rng(42)

        # Initialize weights
        self._W_in  = rng.normal(0, 0.1, (n_features, self.d_model))
        self._W_out = rng.normal(0, 0.1, (self.d_model,))

        # Simple gradient descent (finite difference approximation for simplicity)
        for epoch in range(self.epochs):
            total_loss = 0.0

            # Cap at 200 samples per epoch; ensure index stays within bounds
            i_max = min(n_samples, self.seq_len + 200)
            for i in range(self.seq_len, i_max):
                # Bounds check: ensure target index is valid
                if i >= len(y):
                    break
                target = y[i]
                if np.isnan(target):
                    continue

                seq = X_scaled[i - self.seq_len: i]
                pred = self._forward(seq)
                loss = (pred - target) ** 2
                total_loss += loss

                # Gradient of output layer (chain rule)
                grad_out = 2 * (pred - target)
                pooled = (seq @ self._W_in + self._attention_pool(seq, self._W_in)).mean(0)

                # Update W_out
                self._W_out -= self.lr * grad_out * pooled

                # Update W_in (approximate gradient via perturbation)
                eps = 1e-4
                # Only update top min(n_features, 10) features for cost control
                n_feat_update = min(n_features, 10)
                for j in range(n_feat_update):
                    for k in range(self.d_model):
                        self._W_in[j, k] += eps
                        pred_plus = self._forward(seq)
                        self._W_in[j, k] -= 2 * eps
                        pred_minus = self._forward(seq)
                        self._W_in[j, k] += eps  # restore
                        grad = (pred_plus - pred_minus) / (2 * eps)
                        self._W_in[j, k] -= self.lr * grad_out * grad

            if (epoch + 1) % 10 == 0:
                logger.debug("[Transformer] epoch %d/%d loss=%.4f", epoch+1, self.epochs, total_loss)

        self._trained = True
        return self

    def _attention_pool(self, seq: np.ndarray, W_in: np.ndarray) -> np.ndarray:
        Z = seq @ W_in
        d_head = self.d_model // self.n_heads
        out = np.zeros_like(Z)
        for h in range(self.n_heads):
            s, e = h * d_head, (h+1) * d_head
            out[:, s:e] = self._attention(Z[:, s:e], Z[:, s:e], Z[:, s:e])
        return out

    def predict(self, X: np.ndarray) -> np.ndarray:
        if not self._trained or self._W_in is None:
            return np.zeros(len(X))

        if self.scaler is not None:
            X_scaled = self.scaler.transform(X).astype(np.float64)
        else:
            X_scaled = ((X - X.mean(0)) / (X.std(0) + 1e-8)).astype(np.float64)

        preds = []
        for i in range(len(X_scaled)):
            start = max(0, i - self.seq_len + 1)
            seq = X_scaled[start: i + 1]
            if len(seq) < self.seq_len:
                seq = np.pad(seq, ((self.seq_len - len(seq), 0), (0, 0)))
            preds.append(self._forward(seq))
        return np.array(preds)


# ── Ensemble Predictor ─────────────────────────────────────────────────────────

class EnsemblePredictor(BasePredictor):
    """
    Weighted ensemble of XGBoost + LightGBM + LSTM + Transformer.

    Weights are computed after training by inverse-MSE weighting on validation set
    (better models get higher weight).
    """
    name = "ensemble"

    def __init__(self) -> None:
        self.models: list[BasePredictor] = []
        self.weights: list[float] = []
        self.feature_names_: list[str] = []
        self._trained = False

    def fit(self, X: np.ndarray, y: np.ndarray, feature_names: Optional[list[str]] = None) -> "EnsemblePredictor":
        self.feature_names_ = feature_names or [f"f{i}" for i in range(X.shape[1])]

        # Train/val split (80/20)
        split = int(len(X) * 0.8)
        X_tr, X_val = X[:split], X[split:]
        y_tr, y_val = y[:split], y[split:]

        # Only use rows where y is not NaN
        tr_valid = ~np.isnan(y_tr)
        val_valid = ~np.isnan(y_val)
        X_tr, y_tr = X_tr[tr_valid], y_tr[tr_valid]
        X_val, y_val = X_val[val_valid], y_val[val_valid]

        candidates = []
        if HAS_XGB:
            candidates.append(XGBoostPredictor())
        if HAS_LGB:
            candidates.append(LightGBMPredictor())
        candidates.append(LSTMPredictor(epochs=30))
        candidates.append(TransformerPredictor(epochs=20))

        trained = []
        val_mses = []
        for m in candidates:
            try:
                m.fit(X_tr, y_tr, feature_names=self.feature_names_)
                if len(X_val) > 0:
                    preds = m.predict(X_val)
                    preds = preds[-len(y_val):]  # align (LSTM shifts)
                    mse = float(np.nanmean((preds - y_val) ** 2))
                else:
                    mse = 1.0
                trained.append(m)
                val_mses.append(mse)
                logger.info("[Ensemble] %s val_mse=%.4f", m.name, mse)
            except Exception as e:
                logger.warning("[Ensemble] %s training failed: %s", m.name, e)

        if not trained:
            raise RuntimeError("All models failed to train")

        self.models = trained
        # Inverse-MSE weights (lower MSE → higher weight)
        inv_mses = [1 / (mse + 1e-6) for mse in val_mses]
        total = sum(inv_mses)
        self.weights = [w / total for w in inv_mses]
        self._trained = True
        logger.info("[Ensemble] weights: %s", {m.name: round(w, 3) for m, w in zip(self.models, self.weights)})
        return self

    def predict(self, X: np.ndarray) -> np.ndarray:
        if not self._trained:
            return np.zeros(len(X))
        all_preds = []
        for model, weight in zip(self.models, self.weights):
            try:
                p = model.predict(X)
                p = p[-len(X):]  # align
                if len(p) < len(X):
                    p = np.pad(p, (len(X) - len(p), 0))
                all_preds.append(p * weight)
            except Exception as e:
                logger.warning("[Ensemble] predict failed for %s: %s", model.name, e)
        if not all_preds:
            return np.zeros(len(X))
        return np.sum(all_preds, axis=0)

    def feature_importance(self) -> dict[str, float]:
        """Weighted average of feature importances from models that support it."""
        combined: dict[str, float] = {}
        total_w = 0.0
        for model, weight in zip(self.models, self.weights):
            imp = model.feature_importance()
            if imp:
                for name, score in imp.items():
                    combined[name] = combined.get(name, 0.0) + score * weight
                total_w += weight
        if total_w > 0:
            combined = {k: round(v / total_w, 6) for k, v in combined.items()}
        return dict(sorted(combined.items(), key=lambda x: -x[1]))

    def model_weights(self) -> dict[str, float]:
        return {m.name: round(w, 4) for m, w in zip(self.models, self.weights)}
