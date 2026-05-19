"""
Institutional Flow Service — Phase 2
======================================
Handles:
- US: SEC EDGAR 13F filings (quarterly institutional holdings)
- US: ETF flows via yfinance (sector ETF price/volume as proxy)
- US: Options Put/Call ratios via CBOE
- India: FII/DII daily flows via NSE
- India: Bulk/Block deals via NSE
- India: Promoter holding changes via NSE filings
"""
import requests
import pandas as pd
from bs4 import BeautifulSoup
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.dialects.postgresql import insert as pg_insert
from app.models.market_data import InstitutionalFlow
from datetime import datetime, timedelta
from typing import List, Dict, Any
import json

# Browser-based scraper (preferred — bypasses NSE bot detection)
try:
    from app.ingestion.institutional.browser import NSEBrowserScraper, PLAYWRIGHT_AVAILABLE
except ImportError:
    PLAYWRIGHT_AVAILABLE = False
    NSEBrowserScraper = None


class InstitutionalService:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def _upsert_flows(self, records: List[Dict]):
        if not records:
            return
        stmt = pg_insert(InstitutionalFlow).values(records)
        stmt = stmt.on_conflict_do_nothing(index_elements=["date", "entity_type", "market"])
        await self.db.execute(stmt)
        await self.db.commit()

    # ─── India: FII/DII Daily Flows ──────────────────────────────────────────

    async def fetch_india_fii_dii(self, days_back: int = 30):
        """
        Fetches FII/DII daily net flows from NSE India.
        Primary: Playwright browser session (bypasses NSE bot detection).
        Fallback: requests.Session with browser-like headers.
        """
        raw = []

        # ── Primary: real browser (Playwright) ──────────────────────────────
        if PLAYWRIGHT_AVAILABLE:
            try:
                scraper = NSEBrowserScraper()
                raw = await scraper.fetch_fii_dii()
            except Exception as e:
                print(f"  [Browser] FII/DII error: {e}. Trying requests fallback...")

        # ── Fallback: requests.Session ──────────────────────────────────────
        if not raw:
            try:
                headers = {
                    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36",
                    "Accept": "application/json",
                    "Referer": "https://www.nseindia.com/",
                }
                s = requests.Session()
                s.get("https://www.nseindia.com", headers=headers, timeout=10)
                resp = s.get("https://www.nseindia.com/api/fiidiiTradeReact", headers=headers, timeout=15)
                if resp.status_code == 200:
                    data = resp.json()
                    for item in data:
                        try:
                            dt = datetime.strptime(item.get("date", ""), "%d-%b-%Y")
                            raw.append({
                                "date": dt,
                                "fii_net": float(str(item.get("fiiNetValue", 0)).replace(",", "") or 0),
                                "dii_net": float(str(item.get("diiNetValue", 0)).replace(",", "") or 0),
                                "fii_buy": float(str(item.get("fiiBuyValue", 0)).replace(",", "") or 0),
                                "fii_sell": float(str(item.get("fiiSellValue", 0)).replace(",", "") or 0),
                                "dii_buy": float(str(item.get("diiBuyValue", 0)).replace(",", "") or 0),
                                "dii_sell": float(str(item.get("diiSellValue", 0)).replace(",", "") or 0),
                            })
                        except Exception:
                            continue
            except Exception as e:
                print(f"  [ERROR] FII/DII requests fallback: {e}")

        # ── Store to DB ─────────────────────────────────────────────────────
        records = []
        for item in raw:
            dt = item["date"]
            for entity_type, buy_k, sell_k, net_k in [
                ("FII", "fii_buy", "fii_sell", "fii_net"),
                ("DII", "dii_buy", "dii_sell", "dii_net"),
            ]:
                records.append({
                    "date": dt,
                    "entity_type": entity_type,
                    "market": "INDIA",
                    "buy_value": item.get(buy_k),
                    "sell_value": item.get(sell_k),
                    "net_value": item.get(net_k),
                    "meta_data": {},
                })

        await self._upsert_flows(records)
        print(f"  Ingested {len(records)} FII/DII flow records")

    # ─── India: Bulk/Block Deals ─────────────────────────────────────────────

    async def fetch_india_bulk_deals(self, from_date: str = "01-01-2024"):
        """
        Fetches bulk deals from NSE.
        Primary: Playwright browser session.
        Fallback: requests.Session.
        """
        raw = []

        # ── Primary: browser ─────────────────────────────────────────────────
        if PLAYWRIGHT_AVAILABLE:
            try:
                scraper = NSEBrowserScraper()
                raw = await scraper.fetch_bulk_deals(from_date)
            except Exception as e:
                print(f"  [Browser] Bulk deals error: {e}. Trying requests fallback...")

        # ── Fallback: requests.Session ───────────────────────────────────────
        if not raw:
            try:
                headers = {
                    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36",
                    "Accept": "application/json",
                    "Referer": "https://www.nseindia.com/",
                }
                s = requests.Session()
                s.get("https://www.nseindia.com", headers=headers, timeout=10)
                url = f"https://www.nseindia.com/api/historical/bulk-deals?from={from_date}&to=31-12-2025"
                response = s.get(url, headers=headers, timeout=15)

                if response.status_code != 200:
                    raise ConnectionError(f"NSE bulk deals returned {response.status_code}")

                data = response.json().get("data", [])
            except Exception:
                data = []

            records = []

            for item in data:
                try:
                    dt = datetime.strptime(item.get("BD_DT_DATE", ""), "%d-%b-%Y")
                    qty = float(str(item.get("BD_QTY_TRD", 0)).replace(",", "") or 0)
                    price = float(str(item.get("BD_TP_WATP", 0)).replace(",", "") or 0)
                    value = qty * price

                    buy_sell = item.get("BD_BUYSELL", "B")
                    records.append({
                        "date": dt,
                        "entity_type": "BULK_DEAL",
                        "market": "INDIA",
                        "buy_value": value if buy_sell == "B" else 0,
                        "sell_value": value if buy_sell == "S" else 0,
                        "net_value": value if buy_sell == "B" else -value,
                        "meta_data": {
                            "ticker": item.get("BD_SYMBOL"),
                            "client": item.get("BD_CLIENT_NAME"),
                            "qty": qty,
                            "price": price,
                        },
                    })
                except Exception:
                    continue

            await self._upsert_flows(records)
            print(f"  Ingested {len(records)} bulk deal records")



    # ─── US: SEC EDGAR 13F ───────────────────────────────────────────────────

    async def fetch_us_13f(self, cik_list: List[str] = None):
        """
        Fetches 13F filings from SEC EDGAR for major hedge funds.
        Uses EDGAR full-text search API.
        Default CIKs: Berkshire, Bridgewater, Renaissance, Citadel
        """
        if cik_list is None:
            # CIK numbers for major institutional filers
            cik_list = [
                "0001067983",  # Berkshire Hathaway
                "0001350694",  # Bridgewater Associates
                "0001037389",  # Renaissance Technologies
            ]

        headers = {"User-Agent": "OmniTrader research@omnitrader.ai"}

        for cik in cik_list:
            try:
                # Get recent 13F filings
                url = f"https://data.sec.gov/submissions/CIK{cik}.json"
                response = requests.get(url, headers=headers, timeout=15)

                if response.status_code != 200:
                    continue

                data = response.json()
                entity_name = data.get("name", cik)
                filings = data.get("filings", {}).get("recent", {})

                forms = filings.get("form", [])
                dates = filings.get("filingDate", [])
                accessions = filings.get("accessionNumber", [])

                # Find 13F-HR filings
                for i, form in enumerate(forms):
                    if form == "13F-HR" and i < len(dates):
                        filing_date = datetime.strptime(dates[i], "%Y-%m-%d")

                        records = [{
                            "date": filing_date,
                            "entity_type": "13F_INSTITUTION",
                            "market": "US",
                            "buy_value": None,
                            "sell_value": None,
                            "net_value": None,
                            "meta_data": {
                                "entity": entity_name,
                                "cik": cik,
                                "accession": accessions[i] if i < len(accessions) else None,
                                "form": form,
                            },
                        }]
                        await self._upsert_flows(records)
                        break  # Only latest filing for now

                print(f"  Ingested 13F metadata for {entity_name}")

            except Exception as e:
                print(f"  [ERROR] 13F for CIK {cik}: {e}")

    # ─── US: Options Put/Call Ratio ──────────────────────────────────────────

    async def fetch_options_put_call(self, tickers: List[str]):
        """
        Fetches options Put/Call ratio via yfinance options chain.
        Stored as a flow proxy for institutional sentiment.
        """
        import yfinance as yf

        for ticker_symbol in tickers:
            try:
                t = yf.Ticker(ticker_symbol)
                exp_dates = t.options
                if not exp_dates:
                    continue

                # Use nearest expiry
                nearest = exp_dates[0]
                chain = t.option_chain(nearest)

                put_volume = chain.puts["volume"].sum()
                call_volume = chain.calls["volume"].sum()
                pc_ratio = put_volume / call_volume if call_volume > 0 else None

                if pc_ratio:
                    records = [{
                        "date": datetime.utcnow().replace(hour=0, minute=0, second=0, microsecond=0),
                        "entity_type": "OPTIONS_PC_RATIO",
                        "market": "US",
                        "buy_value": float(call_volume),
                        "sell_value": float(put_volume),
                        "net_value": float(pc_ratio),
                        "meta_data": {"ticker": ticker_symbol, "expiry": nearest},
                    }]
                    await self._upsert_flows(records)
                    print(f"  P/C ratio for {ticker_symbol}: {pc_ratio:.2f}")

            except Exception as e:
                print(f"  [ERROR] Options P/C for {ticker_symbol}: {e}")

    # ─── US: Sector ETF Flows (Proxy) ────────────────────────────────────────

    async def fetch_sector_etf_flows(self):
        """
        Uses sector ETF price/volume as a proxy for sector rotation flows.
        """
        import yfinance as yf

        sector_etfs = {
            "XLK": "Technology",
            "XLF": "Financials",
            "XLE": "Energy",
            "XLV": "Healthcare",
            "XLI": "Industrials",
            "XLY": "Consumer Discretionary",
            "XLP": "Consumer Staples",
            "XLB": "Materials",
            "XLRE": "Real Estate",
            "XLU": "Utilities",
            "XLC": "Communication Services",
        }

        records = []
        for etf, sector in sector_etfs.items():
            try:
                t = yf.Ticker(etf)
                hist = t.history(period="5d")
                if hist.empty:
                    continue

                last = hist.iloc[-1]
                records.append({
                    "date": hist.index[-1].to_pydatetime().replace(tzinfo=None),
                    "entity_type": f"SECTOR_ETF_{etf}",
                    "market": "US",
                    "buy_value": float(last["Volume"]),
                    "sell_value": 0,
                    "net_value": float(last["Close"]),
                    "meta_data": {"etf": etf, "sector": sector},
                })
            except Exception as e:
                print(f"  [ERROR] Sector ETF {etf}: {e}")

        await self._upsert_flows(records)
        print(f"  Ingested {len(records)} sector ETF flow records")
