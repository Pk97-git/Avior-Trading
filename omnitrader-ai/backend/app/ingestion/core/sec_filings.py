"""
ingestion/core/sec_filings.py
==============================
SecFilingsService — fetches SEC 10-K and 10-Q filings from EDGAR for US equities.

Uses the free EDGAR REST APIs (no auth, just proper User-Agent):
  - https://data.sec.gov/submissions/CIK{cik}.json   → filing history
  - https://data.sec.gov/api/xbrl/companyfacts/CIK{cik}.json → XBRL metrics

CIK lookup: https://www.sec.gov/cgi-bin/browse-edgar?action=getcompany&company=AAPL&type=10-K&dateb=&owner=include&count=5&search_text=&action=getcompany

Rate limit: EDGAR allows 10 requests/second from a single IP.
We use a 0.12s delay between calls (safe headroom).
"""
import asyncio
import logging
import re
import time
from datetime import date, datetime, timedelta
from typing import Optional

import httpx
from sqlalchemy.dialects.postgresql import insert as pg_insert

from app.db.session import AsyncSessionLocal
from app.models.market_data import SecFiling

logger = logging.getLogger(__name__)

EDGAR_HEADERS = {
    "User-Agent": "OmniTrader research@omnitrader.ai",
    "Accept":     "application/json",
}

SUBMISSIONS_URL   = "https://data.sec.gov/submissions/CIK{cik}.json"
COMPANY_FACTS_URL = "https://data.sec.gov/api/xbrl/companyfacts/CIK{cik}.json"
CIK_LOOKUP_URL    = "https://efts.sec.gov/LATEST/search-index?q=%22{ticker}%22&dateRange=custom&startdt=2020-01-01&forms=10-K"

# EDGAR CIK ticker mapping (maintained by SEC)
TICKER_CIK_URL = "https://www.sec.gov/files/company_tickers.json"

_TICKER_CIK_CACHE: dict[str, str] = {}
_CACHE_LOADED = False


async def _load_ticker_cik_map(client: httpx.AsyncClient) -> dict[str, str]:
    global _TICKER_CIK_CACHE, _CACHE_LOADED
    if _CACHE_LOADED:
        return _TICKER_CIK_CACHE
    try:
        resp = await client.get(TICKER_CIK_URL, timeout=30.0)
        resp.raise_for_status()
        data = resp.json()
        # Format: {"0": {"cik_str": 320193, "ticker": "AAPL", "title": "Apple Inc."}, ...}
        for entry in data.values():
            ticker = entry.get("ticker", "").upper()
            cik    = str(entry.get("cik_str", "")).zfill(10)
            if ticker:
                _TICKER_CIK_CACHE[ticker] = cik
        _CACHE_LOADED = True
        logger.info("EDGAR ticker→CIK map loaded: %d entries", len(_TICKER_CIK_CACHE))
    except Exception as e:
        logger.warning("Failed to load EDGAR ticker→CIK map: %s", e)
    return _TICKER_CIK_CACHE


# Key XBRL concepts to extract (us-gaap)
XBRL_METRICS = {
    "Revenues":                   "revenue",
    "RevenueFromContractWithCustomerExcludingAssessedTax": "revenue",
    "NetIncomeLoss":              "net_income",
    "EarningsPerShareBasic":      "eps_basic",
    "EarningsPerShareDiluted":    "eps_diluted",
    "OperatingIncomeLoss":        "operating_income",
    "GrossProfit":                "gross_profit",
    "ResearchAndDevelopmentExpense": "rd_expense",
    "CashAndCashEquivalentsAtCarryingValue": "cash",
    "LongTermDebt":               "long_term_debt",
    "StockholdersEquity":         "equity",
    "CommonStockSharesOutstanding": "shares_out",
    "OperatingCashFlow":          "cfo",
    "CapitalExpenditureNet":      "capex",
}


def _extract_latest_xbrl_value(facts: dict, concept: str) -> Optional[float]:
    """Extract the most recent annual/quarterly value for an XBRL concept."""
    try:
        concept_data = facts.get("us-gaap", {}).get(concept, {})
        units = concept_data.get("units", {})
        # Try USD first, then shares
        for unit_type in ("USD", "shares"):
            entries = units.get(unit_type, [])
            if not entries:
                continue
            # Filter to 10-K or 10-Q filed in last 3 years
            cutoff = date.today() - timedelta(days=3*365)
            recent = [
                e for e in entries
                if e.get("form") in ("10-K", "10-Q")
                and e.get("filed", "") >= cutoff.isoformat()
            ]
            if not recent:
                continue
            # Return the most recently filed value
            recent.sort(key=lambda x: x.get("filed", ""), reverse=True)
            val = recent[0].get("val")
            return float(val) if val is not None else None
    except Exception:
        pass
    return None


class SecFilingsService:
    def __init__(self):
        self._delay = 0.12  # 8 req/sec — safely under EDGAR's 10/sec limit

    async def run_batch(self, tickers: list[str], filing_types: list[str] = None) -> dict:
        """
        Fetch recent 10-K and 10-Q filings for a list of US tickers.
        Returns {"stored": int, "failed": list[str]}
        """
        if filing_types is None:
            filing_types = ["10-K", "10-Q"]

        stored_total = 0
        failed = []

        async with httpx.AsyncClient(headers=EDGAR_HEADERS, timeout=30.0) as client:
            cik_map = await _load_ticker_cik_map(client)

            for ticker in tickers:
                # Strip .NS/.BO — only US tickers
                if "." in ticker:
                    continue
                try:
                    cik = cik_map.get(ticker.upper())
                    if not cik:
                        logger.debug("No CIK for %s — skipping", ticker)
                        continue
                    rows = await self._process_ticker(client, ticker, cik, filing_types)
                    stored_total += rows
                    await asyncio.sleep(self._delay)
                except Exception as e:
                    logger.warning("SecFilings failed for %s: %s", ticker, e)
                    failed.append(ticker)
                    await asyncio.sleep(self._delay)

        logger.info("SecFilingsService: %d rows stored, %d failed", stored_total, len(failed))
        return {"stored": stored_total, "failed": failed}

    async def _process_ticker(self, client: httpx.AsyncClient, ticker: str,
                               cik: str, filing_types: list[str]) -> int:
        # 1. Get recent filings from submissions endpoint
        filings = await self._get_recent_filings(client, cik, filing_types)
        if not filings:
            return 0

        # 2. Get XBRL company facts (single call covers all periods)
        xbrl_facts = await self._get_xbrl_facts(client, cik)

        records = []
        for f in filings[:8]:  # last 8 filings (2 years of 10-Qs + 2 annual 10-Ks)
            metrics = {}
            if xbrl_facts:
                for concept, label in XBRL_METRICS.items():
                    val = _extract_latest_xbrl_value(xbrl_facts, concept)
                    if val is not None:
                        metrics[label] = val

            records.append({
                "ticker":       ticker,
                "cik":          cik,
                "filing_type":  f["form"],
                "filed_date":   datetime.strptime(f["filingDate"], "%Y-%m-%d").date(),
                "period_end":   datetime.strptime(f["reportDate"], "%Y-%m-%d").date(),
                "accession_no": f.get("accessionNumber", "").replace("-", ""),
                "filing_url":   f"https://www.sec.gov/Archives/edgar/full-index/{f.get('accessionNumber', '').replace('-', '')}/",
                "xbrl_metrics": metrics if metrics else None,
                "risk_factors": None,
            })

        if not records:
            return 0

        async with AsyncSessionLocal() as db:
            stmt = pg_insert(SecFiling).values(records)
            stmt = stmt.on_conflict_do_update(
                constraint="uq_sec_filing",
                set_={
                    "filed_date":   stmt.excluded.filed_date,
                    "accession_no": stmt.excluded.accession_no,
                    "filing_url":   stmt.excluded.filing_url,
                    "xbrl_metrics": stmt.excluded.xbrl_metrics,
                },
            )
            await db.execute(stmt)
            await db.commit()

        return len(records)

    async def _get_recent_filings(self, client: httpx.AsyncClient, cik: str,
                                   filing_types: list[str]) -> list[dict]:
        url = SUBMISSIONS_URL.format(cik=cik)
        try:
            resp = await client.get(url)
            resp.raise_for_status()
            data = resp.json()
        except Exception as e:
            logger.warning("EDGAR submissions fetch CIK %s: %s", cik, e)
            return []

        recent = data.get("filings", {}).get("recent", {})
        forms        = recent.get("form", [])
        filing_dates = recent.get("filingDate", [])
        report_dates = recent.get("reportDate", [])
        accessions   = recent.get("accessionNumber", [])

        results = []
        for i, form in enumerate(forms):
            if form not in filing_types:
                continue
            if not filing_dates[i] or not report_dates[i]:
                continue
            results.append({
                "form":        form,
                "filingDate":  filing_dates[i],
                "reportDate":  report_dates[i],
                "accessionNumber": accessions[i] if i < len(accessions) else "",
            })
            if len(results) >= 8:
                break

        return results

    async def _get_xbrl_facts(self, client: httpx.AsyncClient, cik: str) -> Optional[dict]:
        url = COMPANY_FACTS_URL.format(cik=cik)
        try:
            await asyncio.sleep(self._delay)
            resp = await client.get(url)
            resp.raise_for_status()
            return resp.json().get("facts", {})
        except Exception as e:
            logger.debug("XBRL facts CIK %s: %s", cik, e)
            return None
