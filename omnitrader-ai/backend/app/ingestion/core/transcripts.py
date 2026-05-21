"""
transcripts.py
==============
Fetches SEC 8-K earnings releases and summarizes them with Claude API.
Uses EDGAR free API (no auth required).
"""
import asyncio
import json
import logging
import re
from datetime import datetime, timedelta
from typing import Optional

import httpx
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.dialects.postgresql import insert as pg_insert

from app.db.session import async_session_factory
from app.models.market_data import EarningsTranscript
from anthropic import AsyncAnthropic

logger = logging.getLogger("omnitrader.ingestion.transcripts")

EDGAR_BASE = "https://data.sec.gov"
TICKERS_URL = "https://www.sec.gov/files/company_tickers.json"
HEADERS = {"User-Agent": "OmniTrader research@omnitrader.ai"}

_CIK_CACHE: dict[str, str] = {}
_CIK_LOADED = False


async def _load_cik_map(client: httpx.AsyncClient) -> dict[str, str]:
    """Fetch SEC company_tickers.json and return {TICKER: zero-padded CIK}."""
    global _CIK_CACHE, _CIK_LOADED
    if _CIK_LOADED:
        return _CIK_CACHE

    try:
        resp = await client.get(TICKERS_URL, headers=HEADERS, timeout=30)
        resp.raise_for_status()
        data = resp.json()
        # data is {idx: {cik_str, ticker, title}}
        mapping: dict[str, str] = {}
        for entry in data.values():
            ticker = str(entry.get("ticker", "")).upper()
            cik = str(entry.get("cik_str", "")).zfill(10)
            if ticker:
                mapping[ticker] = cik
        _CIK_CACHE = mapping
        _CIK_LOADED = True
        logger.info("Loaded %d CIK mappings from SEC", len(mapping))
        return mapping
    except Exception as exc:
        logger.warning("Failed to load CIK map: %s", exc)
        return {}


async def _get_8k_filings(
    client: httpx.AsyncClient,
    cik: str,
    days_back: int = 90,
) -> list[dict]:
    """
    Fetch EDGAR submissions for a CIK and return recent 8-K filings.
    Returns list of {accession, filing_date, doc_url}.
    """
    url = f"{EDGAR_BASE}/submissions/CIK{cik}.json"
    try:
        resp = await client.get(url, headers=HEADERS, timeout=30)
        resp.raise_for_status()
        data = resp.json()
    except Exception as exc:
        logger.debug("EDGAR submissions fetch failed for CIK %s: %s", cik, exc)
        return []

    cutoff = datetime.utcnow() - timedelta(days=days_back)
    filings: list[dict] = []

    recent = data.get("filings", {}).get("recent", {})
    forms = recent.get("form", [])
    dates = recent.get("filingDate", [])
    accessions = recent.get("accessionNumber", [])

    for form, date_str, accession in zip(forms, dates, accessions):
        if form != "8-K":
            continue
        try:
            filing_dt = datetime.strptime(date_str, "%Y-%m-%d")
        except ValueError:
            continue
        if filing_dt < cutoff:
            continue

        # Build the filing index URL
        acc_no_dashes = accession.replace("-", "")
        doc_url = (
            f"https://www.sec.gov/Archives/edgar/data/"
            f"{int(cik)}/{acc_no_dashes}/{accession}-index.htm"
        )
        filings.append(
            {
                "accession": accession,
                "filing_date": date_str,
                "doc_url": doc_url,
            }
        )

    return filings


async def _fetch_document(client: httpx.AsyncClient, accession_url: str) -> str:
    """
    Fetch the 8-K filing index page, find the first .htm/.html document,
    download it, strip HTML tags, and return the first 8000 chars.
    """
    try:
        resp = await client.get(accession_url, headers=HEADERS, timeout=30)
        resp.raise_for_status()
        index_html = resp.text
    except Exception as exc:
        logger.debug("Failed to fetch filing index %s: %s", accession_url, exc)
        return ""

    # Extract links from the index to find primary document
    # EDGAR index pages list documents; look for .htm/.html links
    links = re.findall(r'href="([^"]+\.html?)"', index_html, re.IGNORECASE)
    if not links:
        # Try JSON-based index
        json_url = accession_url.replace("-index.htm", "-index.json")
        try:
            resp2 = await client.get(json_url, headers=HEADERS, timeout=30)
            if resp2.status_code == 200:
                idx_data = resp2.json()
                for doc in idx_data.get("directory", {}).get("item", []):
                    name = doc.get("name", "")
                    if name.endswith(".htm") or name.endswith(".html"):
                        links.append(name)
                        break
        except Exception:
            pass

    if not links:
        return ""

    # Resolve relative link to absolute
    base = accession_url.rsplit("/", 1)[0]
    primary_link = links[0]
    if not primary_link.startswith("http"):
        primary_link = f"{base}/{primary_link}"

    try:
        resp3 = await client.get(primary_link, headers=HEADERS, timeout=30)
        resp3.raise_for_status()
        raw_html = resp3.text
    except Exception as exc:
        logger.debug("Failed to fetch primary doc %s: %s", primary_link, exc)
        return ""

    # Strip HTML tags
    text = re.sub(r"<[^>]+>", " ", raw_html)
    text = re.sub(r"\s+", " ", text).strip()
    return text[:8000]


async def _summarize_with_claude(
    ticker: str,
    text: str,
    fiscal_date: str,
) -> dict:
    """
    Use Claude Haiku to extract earnings data from 8-K text.
    Returns dict with: summary, key_metrics, management_tone,
    guidance_direction, sentiment_score.
    """
    client = AsyncAnthropic()

    prompt = f"""You are a financial analyst. Analyze this SEC 8-K earnings release for {ticker} (fiscal date: {fiscal_date}).

Extract the following and respond in JSON only (no prose before or after):
{{
  "summary": "<1-paragraph summary of the key earnings results>",
  "key_metrics": {{
    "revenue": "<revenue figure or null>",
    "eps": "<EPS figure or null>",
    "guidance": "<forward guidance statement or null>"
  }},
  "management_tone": "<one of: POSITIVE, NEUTRAL, NEGATIVE>",
  "guidance_direction": "<one of: RAISE, MAINTAIN, LOWER, NA>",
  "sentiment_score": <float between -1.0 (very negative) and 1.0 (very positive)>
}}

8-K text:
{text}"""

    try:
        message = await client.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=1024,
            messages=[{"role": "user", "content": prompt}],
        )
        raw = message.content[0].text.strip()

        # Extract JSON from response
        json_match = re.search(r"\{.*\}", raw, re.DOTALL)
        if json_match:
            result = json.loads(json_match.group())
        else:
            result = json.loads(raw)

        # Validate/normalise fields
        management_tone = str(result.get("management_tone", "NEUTRAL")).upper()
        if management_tone not in ("POSITIVE", "NEUTRAL", "NEGATIVE"):
            management_tone = "NEUTRAL"

        guidance_direction = str(result.get("guidance_direction", "NA")).upper()
        if guidance_direction not in ("RAISE", "MAINTAIN", "LOWER", "NA"):
            guidance_direction = "NA"

        try:
            sentiment_score = float(result.get("sentiment_score", 0.0))
            sentiment_score = max(-1.0, min(1.0, sentiment_score))
        except (TypeError, ValueError):
            sentiment_score = 0.0

        return {
            "summary": result.get("summary", ""),
            "key_metrics": result.get("key_metrics", {}),
            "management_tone": management_tone,
            "guidance_direction": guidance_direction,
            "sentiment_score": sentiment_score,
        }
    except Exception as exc:
        logger.warning("Claude summarization failed for %s: %s", ticker, exc)
        return {
            "summary": "",
            "key_metrics": {},
            "management_tone": "NEUTRAL",
            "guidance_direction": "NA",
            "sentiment_score": 0.0,
        }


class TranscriptService:
    """
    Fetches SEC 8-K filings for a list of tickers, summarizes the latest
    earnings release with Claude, and upserts results to earnings_transcripts.
    """

    async def run_batch(
        self,
        tickers: list[str],
        days_back: int = 90,
    ) -> dict:
        """
        Process each ticker: fetch 8-K filings, summarize latest one,
        upsert to earnings_transcripts. Rate limit: 0.2s between tickers.
        """
        results = {"processed": 0, "skipped": 0, "errors": 0}

        async with httpx.AsyncClient() as http_client:
            # Load CIK map once
            cik_map = await _load_cik_map(http_client)

            async with async_session_factory() as db:
                for ticker in tickers:
                    ticker = ticker.upper()
                    try:
                        cik = cik_map.get(ticker)
                        if not cik:
                            logger.debug("No CIK found for %s", ticker)
                            results["skipped"] += 1
                            await asyncio.sleep(0.2)
                            continue

                        filings = await _get_8k_filings(http_client, cik, days_back)
                        if not filings:
                            logger.debug("No 8-K filings found for %s", ticker)
                            results["skipped"] += 1
                            await asyncio.sleep(0.2)
                            continue

                        # Use the most recent filing
                        latest = filings[0]
                        fiscal_date = latest["filing_date"]
                        doc_text = await _fetch_document(http_client, latest["doc_url"])

                        if not doc_text:
                            logger.debug("Empty document for %s filing %s", ticker, latest["accession"])
                            results["skipped"] += 1
                            await asyncio.sleep(0.2)
                            continue

                        # Summarize with Claude
                        analysis = await _summarize_with_claude(ticker, doc_text, fiscal_date)

                        # Upsert to DB
                        # Map to EarningsTranscript columns:
                        #   earnings_date, fiscal_period, source_url, raw_text,
                        #   ai_summary, management_tone, key_topics, sentiment_score,
                        #   guidance_change
                        stmt = pg_insert(EarningsTranscript).values(
                            ticker=ticker,
                            earnings_date=fiscal_date,
                            fiscal_period=None,
                            source_url=latest["doc_url"],
                            raw_text=doc_text[:3000],
                            ai_summary=analysis["summary"],
                            management_tone=analysis["management_tone"],
                            key_topics=analysis["key_metrics"],
                            sentiment_score=analysis["sentiment_score"],
                            guidance_change=analysis["guidance_direction"],
                        )

                        # ON CONFLICT (ticker, earnings_date) DO UPDATE
                        stmt = stmt.on_conflict_do_update(
                            constraint="uq_transcript_ticker_date",
                            set_={
                                "ai_summary": stmt.excluded.ai_summary,
                                "management_tone": stmt.excluded.management_tone,
                                "key_topics": stmt.excluded.key_topics,
                                "sentiment_score": stmt.excluded.sentiment_score,
                                "guidance_change": stmt.excluded.guidance_change,
                                "raw_text": stmt.excluded.raw_text,
                                "source_url": stmt.excluded.source_url,
                            },
                        )
                        await db.execute(stmt)
                        await db.commit()

                        results["processed"] += 1
                        logger.info("Processed transcript for %s (%s)", ticker, fiscal_date)

                    except Exception as exc:
                        logger.error("Error processing transcript for %s: %s", ticker, exc)
                        results["errors"] += 1
                        await db.rollback()

                    await asyncio.sleep(0.2)

        return results
