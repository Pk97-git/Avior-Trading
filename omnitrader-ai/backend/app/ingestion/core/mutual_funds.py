"""
ingestion/core/mutual_funds.py
================================
MutualFundService — India mutual fund NAV and holdings via AMFI.

NAV data:   https://www.amfiindia.com/spages/NAVAll.txt  (daily)
Holdings:   AMFI portfolio disclosures are released monthly in CSV format.
            URL pattern: https://portal.amfiindia.com/DownloadNAVHistoryReport_Po.aspx?mf=...
            We use the simplified all-MF NAV API for daily tracking.

Runs:
  Daily: NAV update (last trading day)
  Monthly: Holdings refresh (portfolio disclosure)
"""
import logging
import re
from datetime import date, datetime
from io import StringIO
from typing import Optional

import httpx
import pandas as pd
from sqlalchemy.dialects.postgresql import insert as pg_insert

from app.db.session import AsyncSessionLocal
from app.models.market_data import MutualFundNav, MutualFundHolding

logger = logging.getLogger(__name__)

AMFI_NAV_URL     = "https://www.amfiindia.com/spages/NAVAll.txt"
AMFI_NAV_HISTORY = "https://www.amfiindia.com/modules/NAVArchive.aspx"

# Category mapping from scheme name keywords
CATEGORY_MAP = {
    "equity":    "Equity",
    "elss":      "Equity",
    "flexi":     "Equity",
    "mid cap":   "Equity",
    "small cap": "Equity",
    "large cap": "Equity",
    "hybrid":    "Hybrid",
    "balanced":  "Hybrid",
    "arbitrage": "Hybrid",
    "debt":      "Debt",
    "liquid":    "Debt",
    "overnight": "Debt",
    "gilt":      "Debt",
    "money market": "Debt",
    "fund of fund": "FoF",
    "index":     "Index",
    "etf":       "ETF",
}


def _guess_category(scheme_name: str) -> str:
    name_lower = scheme_name.lower()
    for kw, cat in CATEGORY_MAP.items():
        if kw in name_lower:
            return cat
    return "Other"


def _extract_fund_house(scheme_name: str) -> str:
    """Extract fund house from scheme name prefix."""
    parts = scheme_name.split(" ")
    # Most fund house names are 1-3 words before "Mutual Fund"
    idx = next((i for i, p in enumerate(parts) if p.lower() in ("mutual", "mf")), None)
    if idx and idx > 0:
        return " ".join(parts[:idx])
    return parts[0] if parts else "Unknown"


class MutualFundService:
    """Fetches and stores mutual fund NAV and portfolio data."""

    async def update_nav(self) -> dict:
        """
        Download and store today's NAV for all AMC schemes.
        Returns: {"stored": int, "error": str|None}
        """
        try:
            text_data = await self._fetch_amfi_nav()
        except Exception as e:
            logger.error("AMFI NAV fetch failed: %s", e)
            return {"stored": 0, "error": str(e)}

        records = self._parse_amfi_nav(text_data)
        if not records:
            return {"stored": 0, "error": "No records parsed from AMFI"}

        stored = await self._upsert_nav(records)
        logger.info("MutualFundService: %d NAV rows stored", stored)
        return {"stored": stored, "error": None}

    async def _fetch_amfi_nav(self) -> str:
        async with httpx.AsyncClient(timeout=60.0) as client:
            resp = await client.get(AMFI_NAV_URL)
            resp.raise_for_status()
            return resp.text

    def _parse_amfi_nav(self, text_data: str) -> list[dict]:
        """
        Parse AMFI NAVAll.txt format:
        Scheme Code;ISIN Div Payout/ISIN Growth;ISIN Div Reinvestment;Scheme Name;Net Asset Value;Date

        Sections are separated by blank lines with header lines like:
        "Open Ended Schemes(Equity Scheme - ...)"
        """
        records = []
        lines = text_data.strip().split("\n")

        for line in lines:
            line = line.strip()
            if not line or ";" not in line:
                continue
            # Skip header rows (contain text like "Scheme Code;...")
            if line.startswith("Scheme Code") or line.startswith("Open Ended") or line.startswith("Close Ended"):
                continue

            parts = line.split(";")
            if len(parts) < 6:
                continue

            try:
                scheme_code = parts[0].strip()
                scheme_name = parts[3].strip()
                nav_str     = parts[4].strip()
                date_str    = parts[5].strip()

                if not scheme_code.isdigit():
                    continue

                nav = float(nav_str) if nav_str not in ("N.A.", "", "-") else None
                if nav is None:
                    continue

                nav_date = datetime.strptime(date_str, "%d-%b-%Y").date()
                fund_house = _extract_fund_house(scheme_name)
                category   = _guess_category(scheme_name)

                records.append({
                    "scheme_code": scheme_code,
                    "scheme_name": scheme_name,
                    "fund_house":  fund_house,
                    "category":    category,
                    "date":        nav_date,
                    "nav":         nav,
                })
            except (ValueError, IndexError):
                continue

        return records

    async def _upsert_nav(self, records: list[dict]) -> int:
        chunk_size = 500
        total = 0
        async with AsyncSessionLocal() as db:
            for i in range(0, len(records), chunk_size):
                chunk = records[i:i + chunk_size]
                stmt = pg_insert(MutualFundNav).values(chunk)
                stmt = stmt.on_conflict_do_update(
                    constraint="uq_mf_nav_scheme_date",
                    set_={"nav": stmt.excluded.nav},
                )
                await db.execute(stmt)
                total += len(chunk)
            await db.commit()
        return total
