"""
engines/rl_agent.py
====================
Reinforcement Learning trading agent using Deep Q-Network (DQN).

Architecture
-----------
State   : feature vector (from FeatureEngineer) + position state (0=flat, 1=long)
Actions : 0=HOLD, 1=BUY, 2=SELL
Reward  : daily P&L of the portfolio given action, penalized for excessive trading

Implementation
--------------
Uses a 3-layer neural network (numpy) as the Q-function approximator.
No external RL framework required — pure numpy DQN.

Training: epsilon-greedy exploration over historical episodes.
Each episode: replay the full price history once, updating Q-network on each step.
"""
from __future__ import annotations

import logging
import os
import pickle
from collections import deque
from typing import Optional

import numpy as np

logger = logging.getLogger(__name__)

ACTION_HOLD = 0
ACTION_BUY  = 1
ACTION_SELL = 2
ACTION_NAMES = {0: "HOLD", 1: "BUY", 2: "SELL"}


# ── Neural network for Q-function (pure numpy) ─────────────────────────────────

class _NumpyQNet:
    """
    3-layer fully connected network: input → 128 → 64 → 3 (Q-values for 3 actions).
    Uses ReLU activations and MSE loss.
    """
    def __init__(self, input_dim: int, lr: float = 0.001):
        rng = np.random.default_rng(42)
        self.lr = lr
        # Layer 1: input → 128
        self.W1 = rng.normal(0, np.sqrt(2.0 / input_dim), (input_dim, 128))
        self.b1 = np.zeros(128)
        # Layer 2: 128 → 64
        self.W2 = rng.normal(0, np.sqrt(2.0 / 128), (128, 64))
        self.b2 = np.zeros(64)
        # Layer 3: 64 → 3
        self.W3 = rng.normal(0, np.sqrt(2.0 / 64), (64, 3))
        self.b3 = np.zeros(3)

    def forward(self, x: np.ndarray) -> np.ndarray:
        self._x = x
        self._h1 = np.maximum(0, x @ self.W1 + self.b1)   # ReLU
        self._h2 = np.maximum(0, self._h1 @ self.W2 + self.b2)  # ReLU
        out = self._h2 @ self.W3 + self.b3
        return out  # (3,) Q-values

    def backward(self, target: np.ndarray, action: int) -> float:
        """Compute loss and update weights for the chosen action only."""
        pred = self.forward(self._x)
        error = np.zeros(3)
        error[action] = pred[action] - target[action]
        loss = float(error[action] ** 2)

        # Layer 3 gradients
        dW3 = self._h2[:, None] @ error[None, :]
        db3 = error
        dh2 = error @ self.W3.T

        # Layer 2 gradients (ReLU)
        dh2_relu = dh2 * (self._h2 > 0)
        dW2 = self._h1[:, None] @ dh2_relu[None, :]
        db2 = dh2_relu
        dh1 = dh2_relu @ self.W2.T

        # Layer 1 gradients (ReLU)
        dh1_relu = dh1 * (self._h1 > 0)
        dW1 = self._x[:, None] @ dh1_relu[None, :]
        db1 = dh1_relu

        # SGD update with gradient clipping
        for (W, dW), (b, db) in [
            ((self.W3, dW3), (self.b3, db3)),
            ((self.W2, dW2), (self.b2, db2)),
            ((self.W1, dW1), (self.b1, db1)),
        ]:
            np.clip(dW, -1.0, 1.0, out=dW)
            np.clip(db, -1.0, 1.0, out=db)
            W -= self.lr * dW
            b -= self.lr * db

        return loss


# ── Trading Environment ────────────────────────────────────────────────────────

class TradingEnvironment:
    """
    Gym-like trading environment.

    State: feature_vector (n_features,) + [position, unrealized_pnl_pct]
    Action: 0=HOLD, 1=BUY (go long), 2=SELL (close long)
    Reward: daily return when long, 0 when flat, minus transaction cost on trade

    No shorting — long-only environment (suitable for Indian retail traders).
    """

    TRANSACTION_COST = 0.002  # 0.20% round-trip (Indian market)

    def __init__(self, features: np.ndarray, returns: np.ndarray) -> None:
        self.features = features     # (T, n_features)
        self.returns  = returns      # (T,) daily returns in %
        self.T = len(features)
        self.reset()

    def reset(self) -> np.ndarray:
        self.t = 0
        self.position = 0            # 0 = flat, 1 = long
        self.entry_price_idx = None
        self.episode_pnl = 0.0
        return self._state()

    def _state(self) -> np.ndarray:
        feat = self.features[self.t]
        extra = np.array([
            float(self.position),
            self.episode_pnl / 100.0,  # normalize
        ], dtype=np.float32)
        return np.concatenate([feat, extra]).astype(np.float32)

    def step(self, action: int) -> tuple[np.ndarray, float, bool]:
        ret = float(self.returns[self.t]) if not np.isnan(self.returns[self.t]) else 0.0
        cost = 0.0

        # Execute action
        if action == ACTION_BUY and self.position == 0:
            self.position = 1
            cost = self.TRANSACTION_COST * 100  # in %
            self.entry_price_idx = self.t

        elif action == ACTION_SELL and self.position == 1:
            self.position = 0
            cost = self.TRANSACTION_COST * 100

        # Reward: if long, earn daily return; subtract costs on trades
        if self.position == 1:
            reward = ret - cost
        else:
            reward = -cost  # just the cost if we traded (0 if we held flat)

        self.episode_pnl += reward
        self.t += 1
        done = self.t >= self.T - 1
        next_state = self._state() if not done else self._state()
        return next_state, reward, done


# ── DQN Agent ──────────────────────────────────────────────────────────────────

class DQNTradingAgent:
    """
    Deep Q-Network trading agent (numpy implementation).

    Uses experience replay buffer and target network for stability.
    Epsilon-greedy exploration: starts at epsilon_start, decays to epsilon_min.
    """

    def __init__(
        self,
        n_features: int,
        lr: float = 0.001,
        gamma: float = 0.95,          # discount factor
        epsilon_start: float = 1.0,
        epsilon_min: float = 0.05,
        epsilon_decay: float = 0.995,
        replay_buffer_size: int = 2000,
        batch_size: int = 32,
        target_update_freq: int = 50,
    ):
        self.gamma = gamma
        self.epsilon = epsilon_start
        self.epsilon_min = epsilon_min
        self.epsilon_decay = epsilon_decay
        self.batch_size = batch_size
        self.target_update_freq = target_update_freq

        state_dim = n_features + 2  # features + position + unrealized pnl

        self.q_net = _NumpyQNet(state_dim, lr)
        self.target_net = _NumpyQNet(state_dim, lr)
        self._sync_target()

        self.replay_buffer: deque = deque(maxlen=replay_buffer_size)
        self.step_count = 0
        self._trained = False
        self.training_history: list[dict] = []

    def _sync_target(self) -> None:
        """Copy q_net weights to target_net."""
        self.target_net.W1 = self.q_net.W1.copy()
        self.target_net.b1 = self.q_net.b1.copy()
        self.target_net.W2 = self.q_net.W2.copy()
        self.target_net.b2 = self.q_net.b2.copy()
        self.target_net.W3 = self.q_net.W3.copy()
        self.target_net.b3 = self.q_net.b3.copy()

    def choose_action(self, state: np.ndarray, training: bool = True) -> int:
        if training and np.random.rand() < self.epsilon:
            return np.random.randint(3)  # random action
        q_vals = self.q_net.forward(state)
        return int(np.argmax(q_vals))

    def store_experience(self, state, action, reward, next_state, done) -> None:
        self.replay_buffer.append((state, action, reward, next_state, done))

    def _sample_batch(self):
        n = min(self.batch_size, len(self.replay_buffer))
        idxs = np.random.choice(len(self.replay_buffer), n, replace=False)
        batch = [self.replay_buffer[i] for i in idxs]
        return batch

    def update(self) -> float:
        if len(self.replay_buffer) < self.batch_size:
            return 0.0

        batch = self._sample_batch()
        total_loss = 0.0

        for state, action, reward, next_state, done in batch:
            # Q-target using target network (Bellman equation)
            if done:
                q_target = reward
            else:
                next_q = self.target_net.forward(next_state)
                q_target = reward + self.gamma * np.max(next_q)

            # Current Q-values
            current_q = self.q_net.forward(state)
            target_q = current_q.copy()
            target_q[action] = q_target

            loss = self.q_net.backward(target_q, action)
            total_loss += loss

        self.step_count += 1
        if self.step_count % self.target_update_freq == 0:
            self._sync_target()

        return total_loss / len(batch)

    def train(self, features: np.ndarray, returns: np.ndarray, episodes: int = 50) -> dict:
        """
        Train the agent by replaying historical data.

        Args:
            features: (T, n_features) feature matrix
            returns:  (T,) daily returns in %
            episodes: number of full passes over the data

        Returns:
            Training history dict with episode rewards and losses
        """
        env = TradingEnvironment(features, returns)
        episode_rewards = []
        episode_losses = []

        for ep in range(episodes):
            state = env.reset()
            total_reward = 0.0
            total_loss = 0.0
            steps = 0

            while True:
                action = self.choose_action(state, training=True)
                next_state, reward, done = env.step(action)
                self.store_experience(state, action, reward, next_state, done)
                loss = self.update()
                total_reward += reward
                total_loss += loss
                steps += 1
                state = next_state
                if done:
                    break

            # Decay epsilon
            self.epsilon = max(self.epsilon_min, self.epsilon * self.epsilon_decay)

            episode_rewards.append(round(total_reward, 4))
            episode_losses.append(round(total_loss / max(steps, 1), 6))

            if (ep + 1) % 10 == 0:
                logger.info("[DQN] ep %d/%d reward=%.2f%% epsilon=%.3f",
                            ep+1, episodes, total_reward, self.epsilon)

        self._trained = True
        self.training_history = {
            "episode_rewards": episode_rewards,
            "episode_losses":  episode_losses,
            "final_epsilon":   round(self.epsilon, 4),
            "total_steps":     self.step_count,
        }
        return self.training_history

    def predict_action(self, state: np.ndarray) -> dict:
        """
        Predict the best action for a given state.

        Returns:
            {action_id, action_name, q_values, confidence}
        """
        q_vals = self.q_net.forward(state)
        action = int(np.argmax(q_vals))
        # Softmax for confidence
        exp_q = np.exp(q_vals - q_vals.max())
        probs = exp_q / exp_q.sum()
        return {
            "action_id":   action,
            "action_name": ACTION_NAMES[action],
            "q_values":    {ACTION_NAMES[i]: round(float(q_vals[i]), 4) for i in range(3)},
            "confidence":  round(float(probs[action]) * 100, 1),
        }

    def save(self, path: str) -> None:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "wb") as f:
            pickle.dump(self, f)

    @classmethod
    def load(cls, path: str) -> "DQNTradingAgent":
        with open(path, "rb") as f:
            return pickle.load(f)
