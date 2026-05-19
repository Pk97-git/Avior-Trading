"""
tasks.py — re-export shim
==========================
All task functions have moved to their dedicated data-type flow files.
This module re-exports everything so that any existing imports continue
to work without change.

New canonical locations:
  prices_flow.py        — task_prices_high/medium/low
  fundamentals_flow.py  — task_fundamentals
  macro_flow.py         — task_macro_us / task_macro_india / task_macro_global
  institutional_flow.py — task_fii_dii / task_bulk_deals / task_sector_etfs /
                          task_options_pc / task_sec_13f / task_promoter_holdings
  sentiment_flow.py     — task_sentiment_rss / task_sentiment_reddit /
                          task_sentiment_stocktwits
  computed_flow.py      — task_charts / task_snapshots
"""
# Prices
from app.flows.prices_flow import (
    task_prices_high,
    task_prices_medium,
    task_prices_low,
)

# Fundamentals
from app.flows.fundamentals_flow import task_fundamentals

# Macro
from app.flows.macro_flow import (
    task_macro_us,
    task_macro_india,
    task_macro_global,
)

# Institutional
from app.flows.institutional_flow import (
    task_fii_dii,
    task_bulk_deals,
    task_sector_etfs,
    task_options_pc,
    task_sec_13f,
    task_promoter_holdings,
)

# Sentiment
from app.flows.sentiment_flow import (
    task_sentiment_rss,
    task_sentiment_reddit,
    task_sentiment_stocktwits,
)

# Computed
from app.flows.computed_flow import (
    task_charts,
    task_snapshots,
)

# ── Legacy aliases (keep old names working) ───────────────────────────────────
task_ingest_prices_high        = task_prices_high
task_ingest_prices_medium      = task_prices_medium
task_ingest_prices_low         = task_prices_low
task_ingest_fundamentals       = task_fundamentals
task_ingest_us_macro           = task_macro_us
task_ingest_india_macro        = task_macro_india
task_ingest_global_macro       = task_macro_global
task_ingest_fii_dii            = task_fii_dii
task_ingest_bulk_deals         = task_bulk_deals
task_ingest_sector_etfs        = task_sector_etfs
task_ingest_options            = task_options_pc
task_ingest_13f                = task_sec_13f
task_ingest_promoter_holdings  = task_promoter_holdings
task_ingest_rss                = task_sentiment_rss
task_ingest_reddit             = task_sentiment_reddit
task_ingest_stocktwits         = task_sentiment_stocktwits
task_generate_charts           = task_charts
task_compute_snapshots         = task_snapshots

__all__ = [
    "task_prices_high", "task_prices_medium", "task_prices_low",
    "task_fundamentals",
    "task_macro_us", "task_macro_india", "task_macro_global",
    "task_fii_dii", "task_bulk_deals", "task_sector_etfs",
    "task_options_pc", "task_sec_13f", "task_promoter_holdings",
    "task_sentiment_rss", "task_sentiment_reddit", "task_sentiment_stocktwits",
    "task_charts", "task_snapshots",
    # Legacy aliases
    "task_ingest_prices_high", "task_ingest_prices_medium", "task_ingest_prices_low",
    "task_ingest_fundamentals",
    "task_ingest_us_macro", "task_ingest_india_macro", "task_ingest_global_macro",
    "task_ingest_fii_dii", "task_ingest_bulk_deals", "task_ingest_sector_etfs",
    "task_ingest_options", "task_ingest_13f", "task_ingest_promoter_holdings",
    "task_ingest_rss", "task_ingest_reddit", "task_ingest_stocktwits",
    "task_generate_charts", "task_compute_snapshots",
]
