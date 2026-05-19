"""
Promoter Holdings Service — Phase 2 (India)
=============================================
Fetches quarterly shareholding patterns from NSE for Indian stocks.
Tracks promoter % changes as a key institutional signal.
"""
import requests
import pandas as pd
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.dialects.postgresql import insert as pg_insert
from app.models.market_data import PromoterHolding
from datetime import datetime
from typing import List, Dict

# Browser-based scraper — primary path
try:
    from app.ingestion.institutional.browser import NSEBrowserScraper, PLAYWRIGHT_AVAILABLE
except ImportError:
    PLAYWRIGHT_AVAILABLE = False
    NSEBrowserScraper = None


class PromoterHoldingService:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def _upsert_holdings(self, records: List[Dict]):
        if not records:
            return
        stmt = pg_insert(PromoterHolding).values(records)
        stmt = stmt.on_conflict_do_update(
            index_elements=["ticker", "quarter_end"],
            set_={
                "promoter_pct": stmt.excluded.promoter_pct,
                "fii_pct": stmt.excluded.fii_pct,
                "dii_pct": stmt.excluded.dii_pct,
                "public_pct": stmt.excluded.public_pct,
                "promoter_pct_change": stmt.excluded.promoter_pct_change,
                "meta_data": stmt.excluded.meta_data,
            }
        )
        await self.db.execute(stmt)
        await self.db.commit()

    async def fetch_nse_shareholding(self, ticker_symbol: str):
        """
        Fetches shareholding pattern from NSE.
        Primary:  Playwright browser session (real Chromium — bypasses NSE bot detection)
        Fallback: requests.Session → yfinance major holders
        """
        nse_symbol = ticker_symbol.replace(".NS", "").replace(".BO", "")
        raw = []

        # ── Primary: Browser (Playwright) ─────────────────────────────────
        if PLAYWRIGHT_AVAILABLE:
            try:
                scraper = NSEBrowserScraper()
                raw = await scraper.fetch_promoter_holdings(nse_symbol)
            except Exception as e:
                print(f"  [Browser] Promoter holdings error: {e}. Trying requests...")

        # ── Fallback ①: requests.Session ──────────────────────────────────
        if not raw:
            try:
                headers = {
                    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36",
                    "Accept": "application/json",
                    "Referer": "https://www.nseindia.com/",
                }
                s = requests.Session()
                s.get("https://www.nseindia.com", headers=headers, timeout=10)
                url = f"https://www.nseindia.com/api/corporate-share-holdings-master?symbol={nse_symbol}"
                resp = s.get(url, headers=headers, timeout=15)
                if resp.status_code == 200:
                    data = resp.json()
                    for item in (data if isinstance(data, list) else []):
                        date_str = item.get("date", item.get("quarter", ""))
                        for fmt in ["%d-%b-%Y", "%B %Y", "%Y-%m-%d"]:
                            try:
                                quarter_end = datetime.strptime(date_str, fmt)
                                break
                            except ValueError:
                                continue
                        else:
                            continue
                        raw.append({
                            "quarter_end": quarter_end,
                            "promoter_pct": float(item.get("promoterAndPromoterGroupTotal", 0) or 0),
                            "fii_pct": float(item.get("foreignPortfolioInvestors", 0) or 0),
                            "dii_pct": float(item.get("mutualFunds", 0) or 0),
                            "public_pct": float(item.get("publicShareholding", 0) or 0),
                        })
            except Exception as e:
                print(f"  [Requests] Promoter holdings error: {e}")

        # ── Fallback ②: yfinance major holders ───────────────────────────
        if not raw:
            await self._fetch_yfinance_holders(ticker_symbol)

        # ── Store valid records ──────────────────────────────────────────
        records = []
        for item in raw:
            records.append({
                "ticker": ticker_symbol,
                "quarter_end": item["quarter_end"],
                "promoter_pct": item.get("promoter_pct"),
                "fii_pct": item.get("fii_pct"),
                "dii_pct": item.get("dii_pct"),
                "public_pct": item.get("public_pct"),
                "promoter_pct_change": None,
                "source": "NSE",
                "meta_data": {},
            })

        # Compute QoQ promoter % change
        records.sort(key=lambda x: x["quarter_end"])
        for i in range(1, len(records)):
            prev = records[i - 1]["promoter_pct"]
            curr = records[i]["promoter_pct"]
            if prev is not None and curr is not None:
                records[i]["promoter_pct_change"] = round(curr - prev, 4)

        await self._upsert_holdings(records)
        print(f"  Ingested {len(records)} promoter holding records for {ticker_symbol} ✅")

    async def _fetch_yfinance_holders(self, ticker_symbol: str):
        """Fallback: use yfinance major holders as approximate promoter data."""
        import yfinance as yf
        try:
            t = yf.Ticker(ticker_symbol)
            holders = t.major_holders

            if holders is None or holders.empty:
                return

            # yfinance major_holders has rows like: [pct, description]
            records = []
            now = datetime.utcnow().replace(day=1)  # Approximate current quarter

            holder_dict = {}
            for idx, row in holders.iterrows():
                try:
                    val = float(row.iloc[0]) * 100 if pd.notna(row.iloc[0]) else 0
                    if idx == "insidersPercentHeld":
                        holder_dict["promoter_pct"] = val
                    elif idx == "institutionsPercentHeld":
                        holder_dict["fii_pct"] = val
                except Exception:
                    continue

            if holder_dict:
                records.append({
                    "ticker": ticker_symbol,
                    "quarter_end": now,
                    "promoter_pct": holder_dict.get("promoter_pct"),
                    "fii_pct": holder_dict.get("fii_pct"),
                    "dii_pct": None,
                    "public_pct": None,
                    "promoter_pct_change": None,
                    "source": "yfinance_fallback",
                    "meta_data": holder_dict,
                })
                await self._upsert_holdings(records)
                print(f"  Ingested yfinance holder data for {ticker_symbol} (fallback)")

        except Exception as e:
            print(f"  [ERROR] yfinance holders fallback for {ticker_symbol}: {e}")

    async def fetch_all_india_holdings(self, india_tickers: List[str]):
        """Fetch promoter holdings for all Indian tickers."""
        for ticker in india_tickers:
            if ".NS" in ticker or ".BO" in ticker:
                await self.fetch_nse_shareholding(ticker)
