# OmniTrader AI

**Autonomous Multi-Market Trading Intelligence System**

OmniTrader AI is an institutional-grade, multi-agent automated trading research platform designed to identify high-conviction investment opportunities in US and Indian equity markets. It combines Fundamental, Technical, Macro, and Sentiment analysis into a single "Regime-Weighted Confidence Score".

## 🧠 System Architecture

The system operates like a hedge fund's brain, composed of specialized engines:

1.  **Macro Regime Engine**: Detects the global market state (e.g., "Inflationary Boom", "Deflationary Bust") and assesses stability.
2.  **Cross-Asset Sensitivity Matrix**: Calculates dynamic Betas of stocks against Yields, USD, and Oil.
3.  **Factor Decomposition**: Decomposes returns into Value, Growth, Momentum, Quality, and Low Volatility factors.
4.  **Sector Rotation Engine**: Identifies leading sectors using Relative Strength and Momentum.
5.  **Historical Memory**: Uses `pgvector` to find historical market analogs and calibrate forward event probabilities.
6.  **Risk & Execution**: Manages portfolio exposure, properly sizes positions based on volatility (ATR), and models execution friction.

## 🛠 Tech Stack

### Backend ("The Brain")
*   **Language**: Python 3.11+
*   **Framework**: FastAPI (Async API)
*   **Orchestration**: Prefect (Workflow automation)
*   **Database**: 
    *   TimescaleDB (Time-series data)
    *   DuckDB (Analytical queries)
    *   PostgreSQL + pgvector (Vector embeddings)
*   **ML Ops**: MLflow (Experiment tracking)

### Frontend ("The Face")
*   **Framework**: Next.js 14
*   **Styling**: TailwindCSS
*   **Visualization**: Recharts

## 🚀 Getting Started

### Prerequisites
*   Python 3.11+
*   Node.js 18+
*   Docker (for Database stack)

### Installation
(Instructions to be added)
