"""
api/options.py
==============
Unusual options activity scanner and options chain endpoints.

GET /options/unusual            — scan HIGH-tier tickers for unusual options flow
GET /options/put-call/{ticker}  — put/call ratio and market sentiment signal
GET /options/chain/{ticker}     — full options chain for a ticker
"""
import asyncio
import logging
from typing import Optional

import yfinance as yf
import pandas as pd
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from app.db.session import get_db
from app.models.market_data import Stock, StockPrice

router = APIRouter()
logger = logging.getLogger(__name__)


# ── Options Flow Scanner ───────────────────────────────────────────────────────

class OptionsFlowScanner:

    @staticmethod
    def _moneyness(strike: float, current_price: float) -> str:
        if current_price <= 0:
            return "OTM"
        ratio = strike / current_price
        if ratio < 0.97:
            return "OTM"
        if ratio > 1.03:
            return "OTM"
        return "ATM" if 0.97 <= ratio <= 1.03 else "ITM"

    @staticmethod
    def _moneyness_call(strike: float, current_price: float) -> str:
        """ITM for calls: strike < current_price."""
        if current_price <= 0:
            return "OTM"
        ratio = strike / current_price
        if abs(ratio - 1.0) <= 0.03:
            return "ATM"
        return "ITM" if strike < current_price else "OTM"

    @staticmethod
    def _moneyness_put(strike: float, current_price: float) -> str:
        """ITM for puts: strike > current_price."""
        if current_price <= 0:
            return "OTM"
        ratio = strike / current_price
        if abs(ratio - 1.0) <= 0.03:
            return "ATM"
        return "ITM" if strike > current_price else "OTM"

    @staticmethod
    def _urgency_score(vol_oi_ratio: float, volume: int) -> float:
        return min(100.0, round(vol_oi_ratio * 50 + (volume / 1000) * 10, 2))

    @staticmethod
    def _chain_to_records(df: pd.DataFrame, option_type: str, current_price: float) -> list[dict]:
        """Convert a calls or puts DataFrame to a list of dicts."""
        records = []
        for _, row in df.iterrows():
            try:
                oi = int(row.get("openInterest") or 0)
                vol = int(row.get("volume") or 0)
                strike = float(row.get("strike") or 0)
                iv = float(row.get("impliedVolatility") or 0)
                last_price = float(row.get("lastPrice") or 0)
                bid = float(row.get("bid") or 0)
                ask = float(row.get("ask") or 0)

                moneyness = (
                    OptionsFlowScanner._moneyness_call(strike, current_price)
                    if option_type == "CALL"
                    else OptionsFlowScanner._moneyness_put(strike, current_price)
                )

                records.append({
                    "contractSymbol": row.get("contractSymbol", ""),
                    "strike": strike,
                    "lastPrice": last_price,
                    "bid": bid,
                    "ask": ask,
                    "volume": vol,
                    "openInterest": oi,
                    "impliedVolatility": round(iv, 4),
                    "option_type": option_type,
                    "moneyness": moneyness,
                })
            except Exception:
                continue
        return records

    async def scan_unusual_activity(
        self, tickers: list[str], min_oi: int = 500
    ) -> list[dict]:
        """
        Scan a list of tickers for unusual options activity.
        Unusual = volume > openInterest * 0.5 AND volume > min_oi AND volume > 100.
        Returns up to 50 contracts sorted by urgency_score desc.
        """
        unusual: list[dict] = []

        async def _fetch_one(ticker: str) -> list[dict]:
            try:
                def _yf_work():
                    t = yf.Ticker(ticker)
                    expiries = t.options  # tuple of date strings
                    if not expiries:
                        return [], 0.0
                    current_price = 0.0
                    try:
                        hist = t.history(period="2d", auto_adjust=True)
                        if not hist.empty:
                            current_price = float(hist["Close"].iloc[-1])
                    except Exception:
                        pass
                    target_expiries = expiries[:2]
                    chains = []
                    for exp in target_expiries:
                        try:
                            chain = t.option_chain(exp)
                            chains.append((exp, chain.calls, chain.puts))
                        except Exception:
                            continue
                    return chains, current_price

                chains, current_price = await asyncio.to_thread(_yf_work)
                contracts: list[dict] = []

                for expiry, calls_df, puts_df in chains:
                    for df, option_type in ((calls_df, "CALL"), (puts_df, "PUT")):
                        if df is None or df.empty:
                            continue
                        for _, row in df.iterrows():
                            try:
                                oi = int(row.get("openInterest") or 0)
                                vol = int(row.get("volume") or 0)
                                if not (vol > oi * 0.5 and vol > min_oi and vol > 100):
                                    continue
                                strike = float(row.get("strike") or 0)
                                iv = float(row.get("impliedVolatility") or 0)
                                last_price = float(row.get("lastPrice") or 0)
                                vol_oi_ratio = round(vol / oi, 4) if oi > 0 else float(vol)
                                moneyness = (
                                    self._moneyness_call(strike, current_price)
                                    if option_type == "CALL"
                                    else self._moneyness_put(strike, current_price)
                                )
                                urgency = self._urgency_score(vol_oi_ratio, vol)
                                contracts.append({
                                    "ticker": ticker,
                                    "expiry": expiry,
                                    "strike": strike,
                                    "option_type": option_type,
                                    "volume": vol,
                                    "open_interest": oi,
                                    "vol_oi_ratio": vol_oi_ratio,
                                    "implied_volatility": round(iv, 4),
                                    "last_price": last_price,
                                    "moneyness": moneyness,
                                    "current_price": round(current_price, 4),
                                    "urgency_score": urgency,
                                })
                            except Exception:
                                continue
                return contracts

            except Exception as exc:
                logger.debug("Options scan failed for %s: %s", ticker, exc)
                return []

        task_results = await asyncio.gather(*[_fetch_one(t) for t in tickers])
        for contracts in task_results:
            unusual.extend(contracts)

        unusual.sort(key=lambda x: x["urgency_score"], reverse=True)
        return unusual[:50]

    async def get_put_call_ratio(self, ticker: str) -> dict:
        """
        Compute aggregate put/call volume ratio across the nearest 3 expiries.
        """
        def _yf_work():
            t = yf.Ticker(ticker)
            expiries = t.options
            if not expiries:
                return 0, 0
            total_calls = 0
            total_puts = 0
            for exp in expiries[:3]:
                try:
                    chain = t.option_chain(exp)
                    total_calls += int(chain.calls["volume"].fillna(0).sum())
                    total_puts += int(chain.puts["volume"].fillna(0).sum())
                except Exception:
                    continue
            return total_calls, total_puts

        try:
            total_calls, total_puts = await asyncio.to_thread(_yf_work)
        except Exception as exc:
            logger.warning("get_put_call_ratio failed for %s: %s", ticker, exc)
            total_calls, total_puts = 0, 0

        if total_calls == 0:
            put_call_ratio = None
            signal = "NEUTRAL"
            interpretation = "Insufficient call volume to compute ratio."
        else:
            put_call_ratio = round(total_puts / total_calls, 4)
            if put_call_ratio < 0.7:
                signal = "BULLISH"
                interpretation = (
                    f"Put/call ratio of {put_call_ratio:.2f} is below 0.7, indicating "
                    "elevated call buying relative to puts — typically a bullish signal."
                )
            elif put_call_ratio > 1.3:
                signal = "BEARISH"
                interpretation = (
                    f"Put/call ratio of {put_call_ratio:.2f} is above 1.3, indicating "
                    "elevated put buying relative to calls — typically a bearish/hedging signal."
                )
            else:
                signal = "NEUTRAL"
                interpretation = (
                    f"Put/call ratio of {put_call_ratio:.2f} is in the neutral range (0.7–1.3), "
                    "suggesting balanced options activity."
                )

        return {
            "ticker": ticker,
            "put_call_ratio": put_call_ratio,
            "total_call_volume": total_calls,
            "total_put_volume": total_puts,
            "signal": signal,
            "interpretation": interpretation,
        }


_scanner = OptionsFlowScanner()


# ── /unusual ──────────────────────────────────────────────────────────────────

@router.get("/unusual")
async def get_unusual_options(
    country: Optional[str] = Query("US", description="Filter tickers by country: US, IN, or ALL"),
    min_oi: int = Query(500, ge=0, description="Minimum open interest for unusual flag"),
    min_score: float = Query(30.0, ge=0, le=100, description="Minimum urgency score"),
    db: AsyncSession = Depends(get_db),
):
    """
    Scan top tickers for unusual options activity.
    Returns contracts sorted by urgency_score descending.
    """
    stmt = select(Stock.ticker)
    if country and country.upper() != "ALL":
        stmt = stmt.where(Stock.country == country.upper())
    # Limit to 50 tickers per scan to keep latency reasonable
    stmt = stmt.limit(50)
    result = await db.execute(stmt)
    tickers = [row[0] for row in result.fetchall()]

    if not tickers:
        return []

    unusual = await _scanner.scan_unusual_activity(tickers, min_oi=min_oi)
    return [c for c in unusual if c["urgency_score"] >= min_score]


# ── /put-call/{ticker} ────────────────────────────────────────────────────────

@router.get("/put-call/{ticker}")
async def get_put_call_ratio(ticker: str):
    """
    Put/call ratio and directional signal for a single ticker.
    """
    return await _scanner.get_put_call_ratio(ticker.upper())


# ── /chain/{ticker} ───────────────────────────────────────────────────────────

@router.get("/chain/{ticker}")
async def get_options_chain(
    ticker: str,
    expiry: Optional[str] = Query(None, description="Expiry date string e.g. 2025-06-20; uses nearest if omitted"),
    db: AsyncSession = Depends(get_db),
):
    """
    Return the full options chain (calls + puts) for a ticker.
    Optionally specify an expiry date; defaults to the nearest available.
    """
    ticker = ticker.upper()

    def _yf_work():
        t = yf.Ticker(ticker)
        available_expiries = t.options
        if not available_expiries:
            return None, None, None, 0.0

        selected = expiry if (expiry and expiry in available_expiries) else available_expiries[0]
        chain = t.option_chain(selected)

        current_price = 0.0
        try:
            hist = t.history(period="2d", auto_adjust=True)
            if not hist.empty:
                current_price = float(hist["Close"].iloc[-1])
        except Exception:
            pass

        return selected, chain.calls, chain.puts, current_price

    try:
        selected_expiry, calls_df, puts_df, current_price = await asyncio.to_thread(_yf_work)
    except Exception as exc:
        logger.warning("get_options_chain failed for %s: %s", ticker, exc)
        raise HTTPException(status_code=502, detail=f"Could not fetch options chain for {ticker}: {exc}")

    if selected_expiry is None:
        raise HTTPException(status_code=404, detail=f"No options data available for {ticker}")

    calls_records = OptionsFlowScanner._chain_to_records(calls_df, "CALL", current_price)
    puts_records = OptionsFlowScanner._chain_to_records(puts_df, "PUT", current_price)

    return {
        "ticker": ticker,
        "expiry": selected_expiry,
        "current_price": round(current_price, 4),
        "calls": calls_records,
        "puts": puts_records,
    }
