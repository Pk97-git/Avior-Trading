"""
ingestion/core/us_options.py
==============================
UsOptionsService — fetches US equity options chain via yfinance.

Captures the nearest 4 expiry dates for each ticker:
  - bid, ask, last, volume, OI, IV per strike (calls + puts)
  - Stored daily — overwrites same-day snapshot

Run daily after US close for HIGH-tier equities.
"""
import asyncio
import logging
from datetime import date
from typing import Optional

import yfinance as yf
import pandas as pd
from sqlalchemy.dialects.postgresql import insert as pg_insert

from app.db.session import AsyncSessionLocal
from app.models.market_data import UsOptionsSnapshot

logger = logging.getLogger(__name__)

# Limit to front 3 expiries to control row volume (each expiry = ~100-200 rows/ticker)
MAX_EXPIRIES = 3


class UsOptionsService:
    async def run_batch(self, tickers: list[str]) -> dict:
        """Fetch today's options chain for each ticker."""
        stored_total = 0
        failed = []
        today = date.today()

        for ticker in tickers:
            if "." in ticker or ticker.startswith("^"):
                continue
            try:
                rows = await self._fetch_and_store(ticker, today)
                stored_total += rows
            except Exception as e:
                logger.warning("US options failed for %s: %s", ticker, e)
                failed.append(ticker)

        logger.info("UsOptionsService: %d rows stored, %d failed", stored_total, len(failed))
        return {"stored": stored_total, "failed": failed}

    async def _fetch_and_store(self, ticker: str, today: date) -> int:
        loop = asyncio.get_event_loop()
        records = await loop.run_in_executor(None, self._fetch_chain, ticker, today)
        if not records:
            return 0

        async with AsyncSessionLocal() as db:
            stmt = pg_insert(UsOptionsSnapshot).values(records)
            stmt = stmt.on_conflict_do_update(
                constraint="uq_us_options",
                set_={
                    "bid":          stmt.excluded.bid,
                    "ask":          stmt.excluded.ask,
                    "last_price":   stmt.excluded.last_price,
                    "volume":       stmt.excluded.volume,
                    "open_interest": stmt.excluded.open_interest,
                    "implied_vol":  stmt.excluded.implied_vol,
                    "delta":        stmt.excluded.delta,
                    "gamma":        stmt.excluded.gamma,
                    "theta":        stmt.excluded.theta,
                    "vega":         stmt.excluded.vega,
                    "in_the_money": stmt.excluded.in_the_money,
                },
            )
            await db.execute(stmt)
            await db.commit()

        return len(records)

    def _fetch_chain(self, ticker: str, today: date) -> list[dict]:
        records = []
        try:
            t = yf.Ticker(ticker)
            expiries = t.options
            if not expiries:
                return []

            for expiry_str in expiries[:MAX_EXPIRIES]:
                try:
                    chain = t.option_chain(expiry_str)
                    expiry_date = date.fromisoformat(expiry_str)

                    for opt_type, df in [("call", chain.calls), ("put", chain.puts)]:
                        if df is None or df.empty:
                            continue
                        for _, row in df.iterrows():
                            def _f(val):
                                if val is None or (isinstance(val, float) and pd.isna(val)):
                                    return None
                                return float(val)

                            records.append({
                                "ticker":        ticker,
                                "snapshot_date": today,
                                "expiry":        expiry_date,
                                "strike":        float(row.get("strike", 0)),
                                "option_type":   opt_type,
                                "bid":           _f(row.get("bid")),
                                "ask":           _f(row.get("ask")),
                                "last_price":    _f(row.get("lastPrice")),
                                "volume":        _f(row.get("volume")),
                                "open_interest": _f(row.get("openInterest")),
                                "implied_vol":   _f(row.get("impliedVolatility")),
                                "delta":         _f(row.get("delta")),
                                "gamma":         _f(row.get("gamma")),
                                "theta":         _f(row.get("theta")),
                                "vega":          _f(row.get("vega")),
                                "in_the_money":  bool(row.get("inTheMoney")) if row.get("inTheMoney") is not None else None,
                            })
                except Exception as e:
                    logger.debug("Options chain parse error %s / %s: %s", ticker, expiry_str, e)
                    continue

        except Exception as e:
            logger.warning("yfinance options %s: %s", ticker, e)

        return records
