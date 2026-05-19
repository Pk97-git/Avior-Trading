"""
ingest_flows.py — re-export shim
==================================
Composite flows have moved to orchestrator.py.
This module re-exports them so existing imports continue to work.

Canonical file: app/flows/orchestrator.py
"""
from app.flows.orchestrator import (
    full_initial_load_flow,
    daily_ingest_flow,
    weekly_ingest_flow,
    monthly_ingest_flow,
)

__all__ = [
    "full_initial_load_flow",
    "daily_ingest_flow",
    "weekly_ingest_flow",
    "monthly_ingest_flow",
]
