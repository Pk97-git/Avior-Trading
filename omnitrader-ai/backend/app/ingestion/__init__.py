"""
OmniTrader AI — Data Ingestion Package
========================================
Folder layout:

app/ingestion/
├── core/           Phase 1 — Prices, Fundamentals, Macro
├── institutional/  Phase 2 — FII/DII, 13F, Bulk Deals, Promoter Holdings
├── sentiment/      Phase 4 — RSS, Reddit, Stocktwits, LLM scoring
├── computed/       Phase 3 — Embeddings, Chart generation, Regime labels
└── infra/          Shared infrastructure — Universe, Rate limiter, Monitor
"""

# ── Core ──────────────────────────────────────────────────────────────────────
from app.ingestion.core.prices import DataIngestionService, CRYPTO_UNIVERSE, INDEX_UNIVERSE
from app.ingestion.core.macro_fundamental import MacroService, FundamentalService

# ── Institutional ─────────────────────────────────────────────────────────────
from app.ingestion.institutional.us_india import InstitutionalService
from app.ingestion.institutional.promoter import PromoterHoldingService

# ── Sentiment ─────────────────────────────────────────────────────────────────
from app.ingestion.sentiment.feeds import SentimentService, LLMSentimentScorer

# ── Computed ──────────────────────────────────────────────────────────────────
from app.ingestion.computed.features import FeatureExtractor, MarketSnapshotService, RegimeLabelService
from app.ingestion.computed.charts import ChartGenerationService

# ── Infra ─────────────────────────────────────────────────────────────────────
from app.ingestion.infra.universe import UniverseManager
from app.ingestion.infra.rate_limiter import TokenBucket, PriorityIngestionQueue, IngestionScheduler, RateLimiterRegistry
from app.ingestion.infra.monitor import DataIntegrityMonitor

__all__ = [
    # Core
    "DataIngestionService", "CRYPTO_UNIVERSE", "INDEX_UNIVERSE",
    "MacroService", "FundamentalService",
    # Institutional
    "InstitutionalService", "PromoterHoldingService",
    # Sentiment
    "SentimentService", "LLMSentimentScorer",
    # Computed
    "FeatureExtractor", "MarketSnapshotService", "RegimeLabelService", "ChartGenerationService",
    # Infra
    "UniverseManager", "TokenBucket", "PriorityIngestionQueue",
    "IngestionScheduler", "RateLimiterRegistry", "DataIntegrityMonitor",
]
