"""
ingestion/institutional/fo_chain.py
=====================================
FoChainService — NSE F&O option chain snapshots for Nifty and BankNifty.

Data source: NSE public API (no auth required, needs browser-like headers).
Endpoint: https://www.nseindia.com/api/option-chain-indices?symbol=NIFTY

Captures every 15 minutes during NSE session (09:15–15:30 IST / 03:45–10:00 UTC).

Max pain calculation: strike with minimum aggregate P&L for all option writers.
"""
import logging
from datetime import datetime, timezone
from typing import Optional

import httpx
from sqlalchemy.dialects.postgresql import insert as pg_insert

from app.db.session import AsyncSessionLocal
from app.models.market_data import FoChainSnapshot

logger = logging.getLogger(__name__)

NSE_OPTION_CHAIN_URL = "https://www.nseindia.com/api/option-chain-indices?symbol={symbol}"
NSE_HEADERS = {
    "User-Agent":      "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
    "Accept":          "application/json, text/plain, */*",
    "Accept-Language": "en-US,en;q=0.9",
    "Referer":         "https://www.nseindia.com/option-chain",
}

SYMBOLS = ["NIFTY", "BANKNIFTY"]


def _calculate_max_pain(records: list[dict], expiry: str) -> Optional[float]:
    """
    Max pain = strike where total option writer losses are minimised.
    For each candidate strike, sum intrinsic value of all calls below it
    and all puts above it weighted by OI.
    """
    strikes_data: dict[float, dict] = {}
    for r in records:
        if r.get("expiry") != expiry:
            continue
        s = r["strike"]
        if s not in strikes_data:
            strikes_data[s] = {"ce_oi": 0.0, "pe_oi": 0.0}
        if r["option_type"] == "CE":
            strikes_data[s]["ce_oi"] += r.get("oi") or 0
        else:
            strikes_data[s]["pe_oi"] += r.get("oi") or 0

    if not strikes_data:
        return None

    all_strikes = sorted(strikes_data.keys())

    min_loss = float("inf")
    max_pain_strike = None

    for candidate in all_strikes:
        total_loss = 0.0
        for s, d in strikes_data.items():
            # Call writers lose when spot > strike (spot assumed = candidate)
            if candidate > s:
                total_loss += (candidate - s) * d["ce_oi"]
            # Put writers lose when spot < strike
            if candidate < s:
                total_loss += (s - candidate) * d["pe_oi"]
        if total_loss < min_loss:
            min_loss = total_loss
            max_pain_strike = candidate

    return max_pain_strike


class FoChainService:
    """Fetches and stores NSE option chain data."""

    async def fetch_and_store(self, symbol: str = "NIFTY") -> dict:
        """
        Fetch option chain for a given index symbol and store to DB.
        Returns: {"rows": int, "symbol": str, "error": str|None}
        """
        try:
            data = await self._fetch_chain(symbol)
            if not data:
                return {"rows": 0, "symbol": symbol, "error": "No data from NSE"}
        except Exception as e:
            logger.warning("FoChainService fetch failed for %s: %s", symbol, e)
            return {"rows": 0, "symbol": symbol, "error": str(e)}

        snapshot_time = datetime.now(timezone.utc)
        records = self._parse_chain(data, symbol, snapshot_time)

        if not records:
            return {"rows": 0, "symbol": symbol, "error": "Empty parsed records"}

        # Calculate max pain per expiry
        expiries = list({r["expiry"] for r in records})
        for expiry in expiries:
            mp = _calculate_max_pain(records, expiry)
            if mp is not None:
                for r in records:
                    if r["expiry"] == expiry:
                        r["max_pain"] = mp

        await self._upsert(records)
        return {"rows": len(records), "symbol": symbol, "error": None}

    async def run_all(self) -> dict:
        """Fetch all configured symbols."""
        results = {}
        for symbol in SYMBOLS:
            results[symbol] = await self.fetch_and_store(symbol)
        return results

    async def _fetch_chain(self, symbol: str) -> Optional[dict]:
        url = NSE_OPTION_CHAIN_URL.format(symbol=symbol)
        # NSE requires a session cookie — first hit the homepage
        async with httpx.AsyncClient(headers=NSE_HEADERS, timeout=30.0, follow_redirects=True) as client:
            # Warm up the session
            try:
                await client.get("https://www.nseindia.com/", timeout=10.0)
            except Exception:
                pass
            resp = await client.get(url)
            resp.raise_for_status()
            return resp.json()

    def _parse_chain(self, data: dict, symbol: str, snapshot_time: datetime) -> list[dict]:
        records = []
        try:
            filtered = data.get("filtered", {})
            records_raw = filtered.get("data", [])
            expiry_dates = data.get("records", {}).get("expiryDates", [])
            # Use near-term expiry (first 2 only to limit volume)
            near_expiries = set(expiry_dates[:2]) if expiry_dates else set()

            for item in records_raw:
                expiry_str = item.get("expiryDate", "")
                if near_expiries and expiry_str not in near_expiries:
                    continue

                try:
                    expiry_date = datetime.strptime(expiry_str, "%d-%b-%Y").date()
                except ValueError:
                    continue

                strike = float(item.get("strikePrice", 0))

                for opt_type, key in [("CE", "CE"), ("PE", "PE")]:
                    opt_data = item.get(key)
                    if not opt_data:
                        continue
                    records.append({
                        "symbol":        symbol,
                        "snapshot_time": snapshot_time,
                        "expiry":        expiry_date,
                        "strike":        strike,
                        "option_type":   opt_type,
                        "oi":            float(opt_data.get("openInterest") or 0),
                        "change_oi":     float(opt_data.get("changeinOpenInterest") or 0),
                        "volume":        float(opt_data.get("totalTradedVolume") or 0),
                        "ltp":           float(opt_data.get("lastPrice") or 0),
                        "iv":            float(opt_data.get("impliedVolatility") or 0),
                        "max_pain":      None,
                    })
        except Exception as e:
            logger.error("FoChainService parse error for %s: %s", symbol, e)

        return records

    async def _upsert(self, records: list[dict]) -> None:
        async with AsyncSessionLocal() as db:
            stmt = pg_insert(FoChainSnapshot).values(records)
            stmt = stmt.on_conflict_do_update(
                constraint="uq_fo_chain",
                set_={
                    "oi":       stmt.excluded.oi,
                    "change_oi": stmt.excluded.change_oi,
                    "volume":   stmt.excluded.volume,
                    "ltp":      stmt.excluded.ltp,
                    "iv":       stmt.excluded.iv,
                    "max_pain": stmt.excluded.max_pain,
                },
            )
            await db.execute(stmt)
            await db.commit()
