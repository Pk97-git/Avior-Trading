"""
Universe Manager
=================
Fetches and maintains full index constituents dynamically.

PRD Section 9 requires:
  US:   S&P 500, Nasdaq 100, Russell 2000 (optional)
  India: Nifty 50, Nifty 500, Midcap index

Sources:
  US  → Wikipedia (free, no auth, updated regularly)
  India → NSE India API
"""
import requests
import pandas as pd
from typing import List, Dict
import json
import os

CACHE_FILE = "/tmp/omnitrader_universe_cache.json"


# ─── US Universe ─────────────────────────────────────────────────────────────

def fetch_sp500() -> List[str]:
    """Fetches S&P 500 tickers from Wikipedia."""
    try:
        url = "https://en.wikipedia.org/wiki/List_of_S%26P_500_companies"
        headers = {
            "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
        }
        response = requests.get(url, headers=headers, timeout=10)
        response.raise_for_status()
        
        from io import StringIO
        tables = pd.read_html(StringIO(response.text))
        df = tables[0]
        tickers = df["Symbol"].str.replace(".", "-", regex=False).tolist()
        print(f"  S&P 500: {len(tickers)} tickers fetched")
        return tickers
    except Exception as e:
        print(f"  [ERROR] S&P 500 fetch: {e}")
        # Minimal fallback — top 20 by market cap
        return [
            "AAPL", "MSFT", "NVDA", "AMZN", "GOOGL", "META", "BRK-B",
            "LLY", "AVGO", "TSLA", "WMT", "JPM", "V", "UNH", "XOM",
            "ORCL", "MA", "HD", "PG", "COST",
        ]


def fetch_nasdaq100() -> List[str]:
    """Fetches Nasdaq 100 tickers from Wikipedia."""
    try:
        url = "https://en.wikipedia.org/wiki/Nasdaq-100"
        headers = {
            "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
        }
        response = requests.get(url, headers=headers, timeout=10)
        response.raise_for_status()
        
        from io import StringIO
        tables = pd.read_html(StringIO(response.text))
        # Find the table with a 'Ticker' or 'Symbol' column
        for tbl in tables:
            if "Ticker" in tbl.columns:
                return tbl["Ticker"].tolist()
            if "Symbol" in tbl.columns:
                return tbl["Symbol"].tolist()
        raise ValueError("No ticker column found")
    except Exception as e:
        print(f"  [ERROR] Nasdaq 100 fetch: {e}")
        # Minimal fallback — top 20 Nasdaq 100 by market cap
        return [
            "AAPL", "MSFT", "NVDA", "AMZN", "META", "GOOGL", "GOOG", "TSLA",
            "AVGO", "COST", "NFLX", "ASML", "AMD", "ADBE", "PEP", "QCOM",
            "INTC", "CSCO", "INTU", "CMCSA",
        ]


def fetch_russell2000_sample() -> List[str]:
    """
    Russell 2000 full fetch is expensive. Returns the iShares ETF (IWM)
    as a proxy, with an optional future expansion hook.
    """
    return ["IWM"]  # ETF proxy — full list requires paid data


# ─── India Universe ───────────────────────────────────────────────────────────

def fetch_nifty50() -> List[str]:
    """Fetches Nifty 50 constituents from NSE API."""
    try:
        headers = {
            "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7)",
            "Accept": "application/json",
            "Referer": "https://www.nseindia.com/",
        }
        session = requests.Session()
        session.get("https://www.nseindia.com", headers=headers, timeout=10)
        url = "https://www.nseindia.com/api/equity-stockIndices?index=NIFTY%2050"
        response = session.get(url, headers=headers, timeout=15)
        data = response.json().get("data", [])
        tickers = [item["symbol"] + ".NS" for item in data if item.get("symbol")]
        print(f"  Nifty 50: {len(tickers)} tickers fetched")
        return tickers
    except Exception as e:
        print(f"  [ERROR] Nifty 50 fetch: {e}")
        return [
            "RELIANCE.NS", "TCS.NS", "HDFCBANK.NS", "INFY.NS", "ICICIBANK.NS",
            "HINDUNILVR.NS", "ITC.NS", "KOTAKBANK.NS", "LT.NS", "SBIN.NS",
            "AXISBANK.NS", "BAJFINANCE.NS", "BHARTIARTL.NS", "ASIANPAINT.NS",
            "MARUTI.NS", "HCLTECH.NS", "TITAN.NS", "SUNPHARMA.NS", "WIPRO.NS",
            "ULTRACEMCO.NS", "NESTLEIND.NS", "TATAMOTORS.NS", "NTPC.NS",
            "POWERGRID.NS", "ADANIENT.NS", "ADANIPORTS.NS", "COALINDIA.NS",
            "JSWSTEEL.NS", "TATASTEEL.NS", "TECHM.NS", "BAJAJFINSV.NS",
            "ONGC.NS", "BPCL.NS", "DIVISLAB.NS", "CIPLA.NS", "DRREDDY.NS",
            "GRASIM.NS", "EICHERMOT.NS", "HEROMOTOCO.NS", "M&M.NS",
            "INDUSINDBK.NS", "APOLLOHOSP.NS", "BRITANNIA.NS", "SBILIFE.NS",
            "HDFCLIFE.NS", "BAJAJ-AUTO.NS", "TATACONSUM.NS", "UPL.NS",
            "LTIM.NS", "HINDALCO.NS",
        ]


def fetch_nifty500() -> List[str]:
    """Fetches Nifty 500 constituents from NSE API."""
    try:
        headers = {
            "User-Agent": "Mozilla/5.0",
            "Accept": "application/json",
            "Referer": "https://www.nseindia.com/",
        }
        session = requests.Session()
        session.get("https://www.nseindia.com", headers=headers, timeout=10)
        url = "https://www.nseindia.com/api/equity-stockIndices?index=NIFTY%20500"
        response = session.get(url, headers=headers, timeout=20)
        data = response.json().get("data", [])
        tickers = [item["symbol"] + ".NS" for item in data if item.get("symbol")]
        print(f"  Nifty 500: {len(tickers)} tickers fetched")
        return tickers
    except Exception as e:
        print(f"  [ERROR] Nifty 500 fetch: {e}")
        return fetch_nifty50()  # Fallback to Nifty 50


def fetch_nifty_midcap() -> List[str]:
    """Fetches Nifty Midcap 100 constituents from NSE."""
    try:
        headers = {
            "User-Agent": "Mozilla/5.0",
            "Accept": "application/json",
            "Referer": "https://www.nseindia.com/",
        }
        session = requests.Session()
        session.get("https://www.nseindia.com", headers=headers, timeout=10)
        url = "https://www.nseindia.com/api/equity-stockIndices?index=NIFTY%20MIDCAP%20100"
        response = session.get(url, headers=headers, timeout=15)
        data = response.json().get("data", [])
        tickers = [item["symbol"] + ".NS" for item in data if item.get("symbol")]
        print(f"  Nifty Midcap 100: {len(tickers)} tickers fetched")
        return tickers
    except Exception as e:
        print(f"  [ERROR] Nifty Midcap fetch: {e}")
        # Minimal fallback — top 30 Nifty Midcap 100 stocks by market cap
        return [
            "PERSISTENT.NS", "MPHASIS.NS", "COFORGE.NS", "LTTS.NS", "TATAELXSI.NS",
            "PIIND.NS", "ALKEM.NS", "TORNTPHARM.NS", "AUROPHARMA.NS", "LALPATHLAB.NS",
            "METROPOLIS.NS", "DMART.NS", "NYKAA.NS", "POLICYBZR.NS", "ZOMATO.NS",
            "PAYTM.NS", "INDIAMART.NS", "IRCTC.NS", "RAILVIKAS.NS", "RVNL.NS",
            "FEDERALBNK.NS", "BANDHANBNK.NS", "IDFCFIRSTB.NS", "RBLBANK.NS",
            "CANBK.NS", "BANKBARODA.NS", "UNIONBANK.NS", "PNBHOUSING.NS",
            "CHOLAFIN.NS", "MUTHOOTFIN.NS",
        ]


# ─── Crypto & Macro ───────────────────────────────────────────────────────────

CRYPTO_UNIVERSE = ["BTC-USD", "ETH-USD", "BNB-USD", "SOL-USD"]

INDEX_UNIVERSE = ["^GSPC", "^IXIC", "^NSEI", "^BSESN", "^RUT", "^DJI"]

MACRO_UNIVERSE = [
    "GC=F",    # Gold Futures
    "CL=F",    # Crude Oil WTI
    "BZ=F",    # Brent Crude
    "SI=F",    # Silver
    "DX-Y.NYB",# US Dollar Index
    "^VIX",    # CBOE VIX
    "INDIAVIX.NS", # India VIX
]


# ─── Universe Manager ─────────────────────────────────────────────────────────

class UniverseManager:
    """
    Manages the full tradeable universe with caching.
    Priority tiers:
      HIGH   — active candidates (top 50 US + Nifty 50)
      MEDIUM — watchlist (S&P 500 + Nifty 500)
      LOW    — background (full universe, updated weekly)
    """

    def __init__(self, use_cache: bool = True, cache_ttl_hours: int = 24):
        self.use_cache = use_cache
        self.cache_ttl_hours = cache_ttl_hours
        self._cache: Dict = {}

    def _load_cache(self) -> bool:
        if not self.use_cache or not os.path.exists(CACHE_FILE):
            return False
        try:
            import time
            mtime = os.path.getmtime(CACHE_FILE)
            age_hours = (time.time() - mtime) / 3600
            if age_hours > self.cache_ttl_hours:
                return False
            with open(CACHE_FILE) as f:
                self._cache = json.load(f)
            print(f"  Universe loaded from cache ({age_hours:.1f}h old)")
            return True
        except Exception:
            return False

    def _save_cache(self):
        try:
            with open(CACHE_FILE, "w") as f:
                json.dump(self._cache, f)
        except Exception as e:
            print(f"  [WARN] Cache save failed: {e}")

    def build(self, tier: str = "MEDIUM") -> Dict[str, List[str]]:
        """
        Build the universe for a given tier.
        Returns dict of {universe_name: [tickers]}
        """
        if self._load_cache() and tier in self._cache:
            return self._cache[tier]

        print(f"  Building {tier} universe...")
        result = {}

        if tier == "HIGH":
            result = {
                "US_TOP50": fetch_sp500()[:50],
                "INDIA_NIFTY50": fetch_nifty50(),
                "CRYPTO": CRYPTO_UNIVERSE,
                "INDICES": INDEX_UNIVERSE,
                "MACRO": MACRO_UNIVERSE,
            }

        elif tier == "MEDIUM":
            result = {
                "US_SP500": fetch_sp500(),
                "US_NASDAQ100": fetch_nasdaq100(),
                "INDIA_NIFTY50": fetch_nifty50(),
                "INDIA_NIFTY500": fetch_nifty500(),
                "CRYPTO": CRYPTO_UNIVERSE,
                "INDICES": INDEX_UNIVERSE,
                "MACRO": MACRO_UNIVERSE,
            }

        elif tier == "LOW":
            result = {
                "US_SP500": fetch_sp500(),
                "US_NASDAQ100": fetch_nasdaq100(),
                "US_RUSSELL2000": fetch_russell2000_sample(),
                "INDIA_NIFTY500": fetch_nifty500(),
                "INDIA_MIDCAP": fetch_nifty_midcap(),
                "CRYPTO": CRYPTO_UNIVERSE,
                "INDICES": INDEX_UNIVERSE,
                "MACRO": MACRO_UNIVERSE,
            }

        self._cache[tier] = result
        self._save_cache()
        return result

    def get_all_tickers(self, tier: str = "MEDIUM") -> List[str]:
        """Returns a flat deduplicated list of all tickers for a tier."""
        universe = self.build(tier)
        seen = set()
        tickers = []
        for group_tickers in universe.values():
            for t in group_tickers:
                if t not in seen:
                    seen.add(t)
                    tickers.append(t)
        return tickers

    def get_priority_groups(self) -> Dict[str, List[str]]:
        """
        Returns tickers grouped by ingestion priority tier.
        Used by the rate limiter to schedule fetches.
        """
        return {
            "HIGH": self.get_all_tickers("HIGH"),
            "MEDIUM": [t for t in self.get_all_tickers("MEDIUM")
                       if t not in self.get_all_tickers("HIGH")],
            "LOW": [t for t in self.get_all_tickers("LOW")
                    if t not in self.get_all_tickers("MEDIUM")],
        }


# ─── Quick standalone test ────────────────────────────────────────────────────

if __name__ == "__main__":
    mgr = UniverseManager()
    groups = mgr.get_priority_groups()
    for tier, tickers in groups.items():
        print(f"{tier}: {len(tickers)} tickers")
