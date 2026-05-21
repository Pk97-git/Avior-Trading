"""
Fetches SEC Form 4 (insider transaction) filings via:
1. SEC EDGAR full-text search API for each ticker
2. RSS feed: https://www.sec.gov/cgi-bin/browse-edgar?action=getcompany&type=4&dateb=&owner=include&count=40&search_text=&output=atom
3. Parse the filing index to extract transaction details
"""
import asyncio
import logging
import re
from datetime import datetime, timezone, timedelta
from typing import Optional
import httpx
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, text
from app.models.market_data import InsiderTransaction, Stock

logger = logging.getLogger("omnitrader.insider")

SEC_HEADERS = {
    "User-Agent": "OmniTrader AI research@omnitrader.ai",
    "Accept-Encoding": "gzip, deflate",
}

class SecForm4Service:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def fetch_for_ticker(self, ticker: str, days_back: int = 90) -> list[dict]:
        """
        Fetch Form 4 filings for a given ticker via SEC EDGAR.

        Steps:
        1. Look up the company's CIK from: https://efts.sec.gov/LATEST/search-index?q=%22{ticker}%22&dateRange=custom&startdt={start}&enddt={end}&forms=4
        2. For each filing found, fetch the filing index JSON to get transaction details
        3. Parse the XML filing for: reportingOwner (name, role), nonDerivativeTransaction rows

        Since full XML parsing is complex, use a simpler approach:
        Use EDGAR EFTS search API to get filing summaries.
        URL: https://efts.sec.gov/LATEST/search-index?q=%22{ticker}%22&forms=4&dateRange=custom&startdt={start_date}&enddt={today}

        Parse the JSON hits array. Each hit has:
        - _source.period_of_report → transaction date
        - _source.file_date → filed date
        - _source.display_names → list of filer names
        - _source.entity_name → company name

        For the actual transaction details (amount, price), fetch the filing document
        from the accession URL and parse the text.

        Since XML parsing is complex, fall back to yfinance insider data as a simpler approach:
        Use yfinance ticker.insider_transactions (returns a DataFrame with Date, Shares, Value, Insider, Position, Transaction)

        Primary approach: yfinance (simpler, more reliable)
        Fallback: return empty list

        Return list of dicts: {
            ticker, filed_date, transaction_date, insider_name, insider_role,
            transaction_type ("P"=purchase/"S"=sale/"A"=award),
            shares, price_per_share, total_value, shares_owned_after
        }
        """
        try:
            import yfinance as yf

            def _fetch():
                t = yf.Ticker(ticker)
                df = t.insider_transactions
                if df is None or df.empty:
                    return []

                results = []
                cutoff = datetime.now() - timedelta(days=days_back)

                for _, row in df.iterrows():
                    try:
                        txn_date = row.get("Date") or row.get("Start Date")
                        if txn_date is None:
                            continue
                        # Convert to datetime if it's a Timestamp
                        if hasattr(txn_date, 'to_pydatetime'):
                            txn_date = txn_date.to_pydatetime()
                        if hasattr(txn_date, 'replace'):
                            if txn_date.tzinfo is None:
                                txn_date = txn_date.replace(tzinfo=timezone.utc)
                        if txn_date < cutoff.replace(tzinfo=timezone.utc):
                            continue

                        shares = float(row.get("Shares", 0) or 0)
                        value  = float(row.get("Value", 0) or 0)
                        price  = (value / shares) if shares and shares != 0 else None

                        insider_name = str(row.get("Insider", "") or "")
                        position     = str(row.get("Position", "") or "")
                        txn_type_raw = str(row.get("Transaction", "") or "")

                        # Classify transaction type
                        txn_type = "P"  # default purchase
                        lower = txn_type_raw.lower()
                        if "sale" in lower or "sell" in lower:
                            txn_type = "S"
                        elif "award" in lower or "grant" in lower or "automatic" in lower:
                            txn_type = "A"
                        elif "purchase" in lower or "buy" in lower:
                            txn_type = "P"

                        results.append({
                            "ticker":            ticker,
                            "filed_date":        txn_date,
                            "transaction_date":  txn_date,
                            "insider_name":      insider_name[:200],
                            "insider_role":      position[:100],
                            "transaction_type":  txn_type,
                            "shares":            abs(shares),
                            "price_per_share":   price,
                            "total_value":       abs(value),
                            "shares_owned_after": float(row.get("Shares Owned After", 0) or 0),
                        })
                    except Exception:
                        continue

                return results

            return await asyncio.to_thread(_fetch)

        except Exception as e:
            logger.warning("[Form4] Failed for %s: %s", ticker, e)
            return []

    async def upsert_transactions(self, transactions: list[dict]) -> int:
        """Save transactions to DB. Returns count of new rows inserted."""
        if not transactions:
            return 0

        inserted = 0
        for t in transactions:
            # Check for existing record (same ticker + date + insider + type)
            existing = await self.db.execute(
                select(InsiderTransaction).where(
                    InsiderTransaction.ticker == t["ticker"],
                    InsiderTransaction.transaction_date == t["transaction_date"],
                    InsiderTransaction.insider_name == t["insider_name"],
                    InsiderTransaction.transaction_type == t["transaction_type"],
                ).limit(1)
            )
            if existing.scalars().first():
                continue

            row = InsiderTransaction(**t)
            self.db.add(row)
            inserted += 1

        if inserted:
            await self.db.commit()
        return inserted

    async def run_batch(self, tickers: list[str]) -> dict:
        """Process a list of tickers. Returns {processed, inserted, errors}."""
        processed = 0
        inserted  = 0
        errors    = 0

        for ticker in tickers:
            try:
                txns = await self.fetch_for_ticker(ticker)
                n = await self.upsert_transactions(txns)
                inserted  += n
                processed += 1
            except Exception as e:
                logger.error("[Form4] Error for %s: %s", ticker, e)
                errors += 1
            await asyncio.sleep(0.3)  # rate limit

        return {"processed": processed, "inserted": inserted, "errors": errors}
