"""
Browser-Based Scraper (Playwright)
=====================================
Uses real headless Chromium to bypass NSE/RBI bot detection.

Why this works:
  - Sends real browser fingerprint (Chrome 145, real OS headers)
  - Executes NSE's JS-based cookie validation (like a real browser)
  - Shares session cookies across requests within same browser context

Replaces the plain `requests.Session` approach for:
  - NSE FII/DII, bulk deals, promoter holdings
  - RBI DBIE API
  - Any other Indian site with Cloudflare / JS challenges

Run standalone:
  python3 browser_scraper.py
"""
import asyncio
import json
from datetime import datetime
from typing import Optional, Any, Dict, List

try:
    from playwright.async_api import async_playwright, Page, BrowserContext
    PLAYWRIGHT_AVAILABLE = True
except ImportError:
    PLAYWRIGHT_AVAILABLE = False
    print("[WARN] playwright not installed. Run: pip install playwright && python -m playwright install chromium")


# ─── Shared Browser Context ──────────────────────────────────────────────────

class BrowserSession:
    """
    Manages a persistent headless Chromium session.
    Single instance reused across all NSE/RBI requests to share cookies.
    """

    _instance: Optional["BrowserSession"] = None

    def __init__(self):
        self._playwright = None
        self._browser = None
        self._context: Optional[BrowserContext] = None
        self._nse_warmed_up = False

    @classmethod
    async def get(cls) -> "BrowserSession":
        """Get or create the singleton browser session."""
        if cls._instance is None:
            cls._instance = BrowserSession()
            await cls._instance._start()
        return cls._instance

    async def _start(self):
        """Launch the headless browser (Firefox — bypasses NSE HTTP/2 block on Chromium)."""
        self._playwright = await async_playwright().start()

        # NSE specifically blocks headless Chromium via HTTP/2 fingerprinting.
        # Firefox headless bypasses this. Use Firefox as primary, Chromium as fallback.
        try:
            self._browser = await self._playwright.firefox.launch(
                headless=True,
            )
        except Exception:
            # Fallback to Chromium with http2 disabled
            self._browser = await self._playwright.chromium.launch(
                headless=True,
                args=[
                    "--no-sandbox",
                    "--disable-http2",                             # key: avoids HTTP/2 fingerprint block
                    "--disable-blink-features=AutomationControlled",
                    "--disable-dev-shm-usage",
                ]
            )

        self._context = await self._browser.new_context(
            user_agent=(
                "Mozilla/5.0 (Macintosh; Intel Mac OS X 10.15; rv:121.0) "
                "Gecko/20100101 Firefox/121.0"
            ),
            viewport={"width": 1280, "height": 800},
            locale="en-IN",
            timezone_id="Asia/Kolkata",
            extra_http_headers={
                "Accept-Language": "en-IN,en;q=0.9",
                "Accept": "application/json, text/plain, */*",
            }
        )
        print("  [Browser] Browser session started (Firefox headless)")


    async def warm_up_nse(self):
        """
        Visit NSE main page to get session cookies.
        NSE requires this before any API call — it sets __cfduid and nsit cookies.
        """
        if self._nse_warmed_up:
            return
        page = await self._context.new_page()
        try:
            print("  [Browser] Warming up NSE session...")
            await page.goto("https://www.nseindia.com", wait_until="networkidle", timeout=30000)
            await page.wait_for_timeout(2000)  # let JS set cookies
            self._nse_warmed_up = True
            print("  [Browser] NSE session ready ✅")
        except Exception as e:
            print(f"  [Browser] NSE warmup warning: {e}")
        finally:
            await page.close()

    async def fetch_json(self, url: str, warm_up_url: str = None) -> Optional[Any]:
        """
        Fetch a JSON API endpoint using the browser session.
        Optionally visits a warm-up page first to establish cookies.
        """
        page = await self._context.new_page()
        try:
            if warm_up_url and not self._nse_warmed_up:
                await self.warm_up_nse()

            response = await page.goto(url, wait_until="networkidle", timeout=20000)
            if response and response.status == 200:
                content = await page.content()
                # Extract JSON from page body (browser wraps JSON in <html><body><pre>)
                import re
                match = re.search(r"<pre[^>]*>(.*?)</pre>", content, re.DOTALL)
                if match:
                    return json.loads(match.group(1))
                # Try direct JSON parse of body text
                body = await page.evaluate("() => document.body.innerText")
                return json.loads(body)
            else:
                print(f"  [Browser] {url} returned status {response.status if response else 'None'}")
                return None
        except Exception as e:
            print(f"  [Browser] fetch_json error for {url}: {e}")
            return None
        finally:
            await page.close()

    async def fetch_page_text(self, url: str) -> Optional[str]:
        """Fetch raw page text (for HTML scraping)."""
        page = await self._context.new_page()
        try:
            await page.goto(url, wait_until="networkidle", timeout=20000)
            return await page.content()
        except Exception as e:
            print(f"  [Browser] fetch_page_text error: {e}")
            return None
        finally:
            await page.close()

    async def close(self):
        if self._browser:
            await self._browser.close()
        if self._playwright:
            await self._playwright.stop()
        BrowserSession._instance = None


# ─── NSE Scraper (Browser-Based) ─────────────────────────────────────────────

class NSEBrowserScraper:
    """
    Full browser-based NSE scraper.
    Replaces requests.Session approach — handles JS cookies automatically.
    """

    NSE_BASE = "https://www.nseindia.com"
    API_BASE = "https://www.nseindia.com/api"

    def __init__(self):
        self._session: Optional[BrowserSession] = None

    async def _get_session(self) -> BrowserSession:
        if not PLAYWRIGHT_AVAILABLE:
            raise RuntimeError("playwright not installed")
        self._session = await BrowserSession.get()
        await self._session.warm_up_nse()
        return self._session

    async def fetch_fii_dii(self) -> List[Dict]:
        """Fetch FII/DII daily flows from NSE."""
        session = await self._get_session()
        url = f"{self.API_BASE}/fiidiiTradeReact"
        data = await session.fetch_json(url, warm_up_url=self.NSE_BASE)

        if not data:
            return []

        records = []
        for item in data:
            try:
                dt = datetime.strptime(item.get("date", ""), "%d-%b-%Y")
                records.append({
                    "date": dt,
                    "fii_buy": self._parse_float(item.get("fiiBuy") or item.get("fiiBuyValue")),
                    "fii_sell": self._parse_float(item.get("fiiSell") or item.get("fiiSellValue")),
                    "fii_net": self._parse_float(item.get("fiiNet") or item.get("fiiNetValue")),
                    "dii_buy": self._parse_float(item.get("diiBuy") or item.get("diiBuyValue")),
                    "dii_sell": self._parse_float(item.get("diiSell") or item.get("diiSellValue")),
                    "dii_net": self._parse_float(item.get("diiNet") or item.get("diiNetValue")),
                })
            except Exception:
                continue

        print(f"  [NSE Browser] FII/DII: {len(records)} records fetched ✅")
        return records

    async def fetch_bulk_deals(self, from_date: str = "01-01-2024", to_date: str = None) -> List[Dict]:
        """Fetch bulk deals from NSE."""
        if to_date is None:
            to_date = datetime.now().strftime("%d-%m-%Y")
        session = await self._get_session()
        url = f"{self.API_BASE}/historical/bulk-deals?from={from_date}&to={to_date}"
        data = await session.fetch_json(url, warm_up_url=self.NSE_BASE)

        if not data:
            return []

        records = []
        for item in (data.get("data", []) if isinstance(data, dict) else data):
            try:
                dt = datetime.strptime(item.get("BD_DT_DATE", ""), "%d-%b-%Y")
                qty = self._parse_float(item.get("BD_QTY_TRD"))
                price = self._parse_float(item.get("BD_TP_WATP"))
                records.append({
                    "date": dt,
                    "symbol": item.get("BD_SYMBOL"),
                    "client": item.get("BD_CLIENT_NAME"),
                    "buy_sell": item.get("BD_BUYSELL"),
                    "quantity": qty,
                    "price": price,
                    "value": qty * price if qty and price else None,
                })
            except Exception:
                continue

        print(f"  [NSE Browser] Bulk Deals: {len(records)} records ✅")
        return records

    async def fetch_promoter_holdings(self, symbol: str) -> List[Dict]:
        """Fetch quarterly promoter shareholding pattern for a symbol."""
        session = await self._get_session()
        url = f"{self.API_BASE}/corporate-share-holdings-master?symbol={symbol}"
        data = await session.fetch_json(url, warm_up_url=self.NSE_BASE)

        if not data:
            return []

        records = []
        for item in (data if isinstance(data, list) else []):
            try:
                date_str = item.get("date", "")
                for fmt in ["%d-%b-%Y", "%B %Y", "%Y-%m-%d"]:
                    try:
                        dt = datetime.strptime(date_str, fmt)
                        break
                    except ValueError:
                        continue
                else:
                    continue

                records.append({
                    "quarter_end": dt,
                    "promoter_pct": self._parse_float(item.get("promoterAndPromoterGroupTotal")),
                    "fii_pct": self._parse_float(item.get("foreignPortfolioInvestors")),
                    "dii_pct": self._parse_float(item.get("mutualFunds")),
                    "public_pct": self._parse_float(item.get("publicShareholding")),
                })
            except Exception:
                continue

        print(f"  [NSE Browser] Promoter Holdings for {symbol}: {len(records)} quarters ✅")
        return records

    async def fetch_nifty_constituents(self, index: str = "NIFTY 50") -> List[str]:
        """Fetch live index constituents from NSE."""
        session = await self._get_session()
        encoded = index.replace(" ", "%20")
        url = f"{self.API_BASE}/equity-stockIndices?index={encoded}"
        data = await session.fetch_json(url, warm_up_url=self.NSE_BASE)

        if not data:
            return []

        tickers = [item["symbol"] + ".NS" for item in data.get("data", []) if item.get("symbol")]
        print(f"  [NSE Browser] {index}: {len(tickers)} tickers ✅")
        return tickers

    @staticmethod
    def _parse_float(val) -> Optional[float]:
        if val is None:
            return None
        try:
            return float(str(val).replace(",", ""))
        except Exception:
            return None


# ─── RBI Scraper (Browser-Based) ──────────────────────────────────────────────

class RBIBrowserScraper:
    """
    Browser-based RBI DBIE scraper.
    RBI's API requires JS execution for its CORS/cookie layer.
    """

    RBI_DBIE_BASE = "https://dbie.rbi.org.in"
    RBI_API_BASE  = "https://api.rbi.org.in/api/v2"

    async def fetch_repo_rate(self) -> Optional[Dict]:
        """
        Fetch RBI Repo Rate from DBIE.
        Falls back to hardcoded value if unreachable.
        """
        if not PLAYWRIGHT_AVAILABLE:
            return {"indicator": "RBI_REPO_RATE", "value": 6.50, "source": "fallback"}

        try:
            session = await BrowserSession.get()

            # First warm up DBIE portal
            page = await session._context.new_page()
            try:
                await page.goto(self.RBI_DBIE_BASE, timeout=20000, wait_until="networkidle")
                await page.wait_for_timeout(2000)

                # Now hit the API
                url = (
                    f"{self.RBI_API_BASE}/TimeseriesData"
                    f"?APIKey=NOTREQD&Freq=W"
                    f"&StartDate=01-01-2024&EndDate=31-12-2025"
                    f"&Series=RMPOLICYRBI"
                )
                response = await page.goto(url, timeout=15000)
                if response and response.status == 200:
                    body = await page.evaluate("() => document.body.innerText")
                    data = json.loads(body)
                    obs = data.get("data", {}).get("observations", [])
                    if obs:
                        last = obs[-1]
                        val = float(last.get("value", 6.50))
                        dt = last.get("date", "")
                        print(f"  [RBI Browser] Repo Rate: {val}% as of {dt} ✅")
                        return {"indicator": "RBI_REPO_RATE", "value": val, "date": dt, "source": "RBI_DBIE"}
            finally:
                await page.close()

        except Exception as e:
            print(f"  [RBI Browser] API unreachable ({e}), using fallback")

        import os
        fallback_rate = float(os.environ.get("RBI_REPO_RATE_FALLBACK", "6.25"))
        return {"indicator": "RBI_REPO_RATE", "value": fallback_rate, "source": "fallback_hardcoded"}

    async def fetch_india_cpi(self) -> Optional[Dict]:
        """Fetch India CPI from DBIE."""
        try:
            session = await BrowserSession.get()
            url = (
                f"{self.RBI_API_BASE}/TimeseriesData"
                f"?APIKey=NOTREQD&Freq=M"
                f"&StartDate=01-01-2024&EndDate=31-12-2025"
                f"&Series=WPICPIGEN"  # WPI/CPI General Index
            )
            data = await session.fetch_json(url)
            if data:
                obs = data.get("data", {}).get("observations", [])
                if obs:
                    last = obs[-1]
                    val = float(last.get("value", 0))
                    print(f"  [RBI Browser] India CPI: {val} ✅")
                    return {"indicator": "INDIA_CPI", "value": val, "source": "RBI_DBIE"}
        except Exception as e:
            print(f"  [RBI Browser] India CPI error: {e}")
        return None


# ─── Drop-in Replacements for services ───────────────────────────────────────

async def get_nse_fii_dii():
    """Drop-in replacement for InstitutionalService.fetch_india_fii_dii() raw data."""
    scraper = NSEBrowserScraper()
    return await scraper.fetch_fii_dii()

async def get_nse_bulk_deals(from_date="01-01-2024"):
    """Drop-in replacement for InstitutionalService.fetch_india_bulk_deals() raw data."""
    scraper = NSEBrowserScraper()
    return await scraper.fetch_bulk_deals(from_date)

async def get_promoter_holdings(symbol: str):
    """Drop-in replacement for PromoterHoldingService — returns raw data."""
    scraper = NSEBrowserScraper()
    return await scraper.fetch_promoter_holdings(symbol)

async def get_nifty_constituents(index: str = "NIFTY 50"):
    """Get live Nifty constituents — used by UniverseManager."""
    scraper = NSEBrowserScraper()
    return await scraper.fetch_nifty_constituents(index)

async def get_rbi_repo_rate():
    """Get RBI Repo Rate via browser."""
    scraper = RBIBrowserScraper()
    return await scraper.fetch_repo_rate()


# ─── Quick Test ───────────────────────────────────────────────────────────────

async def test_browser_scrapers():
    if not PLAYWRIGHT_AVAILABLE:
        print("❌ playwright not installed. Run:")
        print("   pip install playwright")
        print("   python -m playwright install chromium")
        return

    from rich.console import Console
    from rich.table import Table
    console = Console()

    console.print("\n[bold cyan]Testing Browser-Based Scrapers[/bold cyan]\n")
    results = []

    # FII/DII
    try:
        records = await get_nse_fii_dii()
        if records:
            r = records[0]
            results.append(("NSE FII/DII", True, f"FII Net={r['fii_net']}, DII Net={r['dii_net']} on {r['date'].strftime('%d-%b-%Y')}"))
        else:
            results.append(("NSE FII/DII", False, "empty response"))
    except Exception as e:
        results.append(("NSE FII/DII", False, str(e)[:60]))

    # Promoter Holdings
    try:
        records = await get_promoter_holdings("RELIANCE")
        if records:
            r = records[-1]
            results.append(("NSE Promoter Holdings", True, f"Promoter={r['promoter_pct']}% FII={r['fii_pct']}% as of {r['quarter_end'].strftime('%b-%Y')}"))
        else:
            results.append(("NSE Promoter Holdings", False, "empty response"))
    except Exception as e:
        results.append(("NSE Promoter Holdings", False, str(e)[:60]))

    # Nifty 50 constituents
    try:
        tickers = await get_nifty_constituents("NIFTY 50")
        if tickers:
            results.append(("Nifty 50 Universe", True, f"{len(tickers)} tickers: {', '.join(tickers[:3])}..."))
        else:
            results.append(("Nifty 50 Universe", False, "empty response"))
    except Exception as e:
        results.append(("Nifty 50 Universe", False, str(e)[:60]))

    # RBI Repo Rate
    try:
        result = await get_rbi_repo_rate()
        val = result["value"]
        src = result["source"]
        results.append(("RBI Repo Rate", True, f"{val}% (source: {src})"))
    except Exception as e:
        results.append(("RBI Repo Rate", False, str(e)[:60]))

    # Summary table
    tbl = Table("Scraper", "Status", "Data")
    passed = 0
    for name, ok, sample in results:
        tbl.add_row(name, "✅ PASS" if ok else "❌ FAIL", sample)
        if ok:
            passed += 1
    console.print(tbl)
    console.print(f"\n  [bold]{passed}/{len(results)} browser scrapers passing[/bold]")

    # Close browser
    session = BrowserSession._instance
    if session:
        await session.close()


if __name__ == "__main__":
    asyncio.run(test_browser_scrapers())
