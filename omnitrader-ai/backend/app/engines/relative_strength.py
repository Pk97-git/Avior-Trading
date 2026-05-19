"""
engines/relative_strength.py
============================
IBD-style Relative Strength (RS) Rating engine.

RS Rating (1-99) = percentile rank of a stock's weighted 12-month price
performance across all stocks in the universe.

Weighting (IBD-style):
  Q1  most recent 3 months  → 40%
  Q2  months 4–6 ago        → 20%
  Q3  months 7–9 ago        → 20%
  Q4  months 10–12 ago      → 20%
"""
import logging
from datetime import datetime, timedelta, timezone
from typing import Optional

import numpy as np
import pandas as pd
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.market_data import Stock, StockPrice  # noqa: F401 — used via text() queries

logger = logging.getLogger(__name__)

# Quarter boundary offsets (trading-day approximations via calendar days)
_Q_OFFSETS = [
    (0,   63),    # Q1: 0  – ~3 months ago
    (63,  126),   # Q2: ~3 – ~6 months ago
    (126, 189),   # Q3: ~6 – ~9 months ago
    (189, 252),   # Q4: ~9 – ~12 months ago
]
_Q_WEIGHTS = [0.40, 0.20, 0.20, 0.20]


def _quarterly_return(closes: pd.Series, start_idx: int, end_idx: int) -> Optional[float]:
    """
    Return the % change between the close at end_idx and start_idx positions
    within a sorted (oldest→newest) Series.  Returns None if indices out of range.
    """
    n = len(closes)
    # Translate from "bars from the end" to actual positional indices
    new_pos = n - 1 - start_idx
    old_pos = n - 1 - end_idx
    if new_pos < 0 or old_pos < 0 or old_pos >= n or new_pos >= n:
        return None
    old_price = closes.iloc[old_pos]
    new_price = closes.iloc[new_pos]
    if pd.isna(old_price) or pd.isna(new_price) or old_price == 0:
        return None
    return (new_price / old_price - 1) * 100


class RelativeStrengthEngine:
    """Compute IBD-style RS Ratings for all stocks in the universe."""

    def __init__(self, db: AsyncSession):
        self.db = db

    # ── Internal helpers ───────────────────────────────────────────────────────

    async def _fetch_stocks(self, country: str) -> list[dict]:
        """Return [{ticker, name, sector, country}] filtered by country."""
        if country == "ALL":
            result = await self.db.execute(
                text("SELECT ticker, name, sector, country FROM stocks ORDER BY ticker")
            )
        else:
            result = await self.db.execute(
                text("SELECT ticker, name, sector, country FROM stocks WHERE country = :c ORDER BY ticker"),
                {"c": country.upper()},
            )
        return [
            {"ticker": r.ticker, "name": r.name, "sector": r.sector, "country": r.country}
            for r in result.fetchall()
        ]

    async def _fetch_all_prices(self) -> pd.DataFrame:
        """
        Bulk-fetch 13 months of daily closes for all tickers.
        Returns a DataFrame with columns [ticker, time, close], sorted by ticker + time.
        """
        price_q = text("""
            SELECT ticker, time, close
            FROM stock_prices
            WHERE time >= NOW() - INTERVAL '13 months'
              AND close IS NOT NULL
            ORDER BY ticker, time
        """)
        result = await self.db.execute(price_q)
        rows = result.fetchall()
        if not rows:
            return pd.DataFrame(columns=["ticker", "time", "close"])
        df = pd.DataFrame(rows, columns=["ticker", "time", "close"])
        df["close"] = pd.to_numeric(df["close"], errors="coerce")
        return df

    def _compute_composite(
        self, closes: pd.Series
    ) -> tuple[Optional[float], Optional[float], Optional[float], Optional[float], Optional[float]]:
        """
        Given a sorted (oldest→newest) close series, compute:
          (composite_return, q1, q2, q3, q4)
        Returns (None, None, None, None, None) if insufficient data.
        """
        if len(closes) < 20:
            return None, None, None, None, None

        q_returns = []
        for start_idx, end_idx in _Q_OFFSETS:
            q_ret = _quarterly_return(closes, start_idx, end_idx)
            q_returns.append(q_ret)

        # Need at least Q1 to compute a composite
        if q_returns[0] is None:
            return None, None, None, None, None

        composite = 0.0
        total_weight = 0.0
        for ret, w in zip(q_returns, _Q_WEIGHTS):
            if ret is not None:
                composite += ret * w
                total_weight += w

        if total_weight == 0:
            return None, *q_returns

        composite = composite / total_weight * sum(_Q_WEIGHTS)  # rescale to full-weight basis
        return round(composite, 4), *[round(q, 4) if q is not None else None for q in q_returns]

    # ── Public API ─────────────────────────────────────────────────────────────

    async def compute_rs_ratings(self, country: str = "ALL") -> list[dict]:
        """
        Compute RS Rating (1-99) for all tickers with sufficient price history.

        RS Rating is the percentile rank of each stock's composite weighted return
        versus the entire universe (or country subset).

        Returns a list of dicts sorted by rs_rating desc.
        """
        stocks = await self._fetch_stocks(country)
        if not stocks:
            return []

        stock_map = {s["ticker"]: s for s in stocks}
        all_tickers = set(stock_map.keys())

        prices_df = await self._fetch_all_prices()
        if prices_df.empty:
            return []

        # Filter to requested universe only
        prices_df = prices_df[prices_df["ticker"].isin(all_tickers)]
        if prices_df.empty:
            return []

        # Pivot: columns = tickers, rows = dates (sorted oldest→newest)
        prices_df["time"] = pd.to_datetime(prices_df["time"], utc=True)
        pivot = (
            prices_df.pivot_table(index="time", columns="ticker", values="close", aggfunc="last")
            .sort_index()
        )

        # Compute composite returns for each ticker
        composites: dict[str, tuple] = {}
        for ticker in pivot.columns:
            closes = pivot[ticker].dropna()
            composites[ticker] = self._compute_composite(closes)

        # Build records with valid composite returns
        records = []
        for ticker, (comp, q1, q2, q3, q4) in composites.items():
            if comp is None:
                continue
            s = stock_map.get(ticker, {})
            records.append({
                "ticker":           ticker,
                "name":             s.get("name"),
                "sector":           s.get("sector"),
                "country":          s.get("country"),
                "composite_return": comp,
                "return_1q":        q1,
                "return_2q":        q2,
                "return_3q":        q3,
                "return_4q":        q4,
            })

        if not records:
            return []

        # Percentile rank composite returns → RS Rating 1-99
        comp_values = np.array([r["composite_return"] for r in records], dtype=float)
        total = len(comp_values)
        # argsort twice gives rank (0-based); convert to 1-99 percentile
        rank_0based = np.argsort(np.argsort(comp_values))  # 0 = lowest
        rs_ratings  = np.clip(np.round((rank_0based / (total - 1)) * 98 + 1).astype(int), 1, 99) \
                      if total > 1 else np.full(total, 50, dtype=int)

        # Compute RS-4w-ago to determine trend (we re-use the 4W-ago price point)
        # Simple proxy: compare Q1 return vs (Q1+Q2)/2 — rising if Q1 > avg older quarters
        for i, r in enumerate(records):
            r["rs_rating"] = int(rs_ratings[i])
            r["rank"]      = int(total - rank_0based[i])   # rank 1 = best
            r["total_tickers"] = total

            q1 = r["return_1q"]
            q2 = r["return_2q"]
            q3 = r["return_3q"]
            older = [v for v in [q2, q3] if v is not None]
            if q1 is not None and older:
                avg_older = sum(older) / len(older)
                if q1 > avg_older + 2:
                    r["trend"] = "RISING"
                elif q1 < avg_older - 2:
                    r["trend"] = "FALLING"
                else:
                    r["trend"] = "NEUTRAL"
            else:
                r["trend"] = "NEUTRAL"

        # Sort by RS rating descending
        records.sort(key=lambda x: x["rs_rating"], reverse=True)
        return records

    async def get_sector_rs(self, country: str = "US") -> list[dict]:
        """
        Compute average RS rating per sector.

        Returns list of {sector, avg_rs, median_rs, top_stock, top_stock_rs, stock_count}
        sorted by avg_rs desc.
        """
        all_ratings = await self.compute_rs_ratings(country=country)
        if not all_ratings:
            return []

        from collections import defaultdict
        sector_groups: dict[str, list[dict]] = defaultdict(list)
        for r in all_ratings:
            sector = r.get("sector") or "Unknown"
            sector_groups[sector].append(r)

        results = []
        for sector, members in sector_groups.items():
            rs_vals = [m["rs_rating"] for m in members]
            top     = max(members, key=lambda x: x["rs_rating"])
            results.append({
                "sector":       sector,
                "avg_rs":       round(float(np.mean(rs_vals)), 1),
                "median_rs":    round(float(np.median(rs_vals)), 1),
                "top_stock":    top["ticker"],
                "top_stock_rs": top["rs_rating"],
                "stock_count":  len(members),
            })

        results.sort(key=lambda x: x["avg_rs"], reverse=True)
        return results

    async def get_ticker_rs(self, ticker: str) -> dict:
        """
        Get RS rating for a single ticker with its return breakdown.

        Computes the full universe first (needed to produce a percentile),
        then filters down to the requested ticker.
        """
        ticker = ticker.upper()

        # Determine country for this ticker
        stock_result = await self.db.execute(
            text("SELECT country FROM stocks WHERE ticker = :t"),
            {"t": ticker},
        )
        stock_row = stock_result.fetchone()
        country = stock_row.country if stock_row else "ALL"

        all_ratings = await self.compute_rs_ratings(country=country)
        if not all_ratings:
            raise ValueError(f"No RS data available for universe (country={country})")

        matched = next((r for r in all_ratings if r["ticker"] == ticker), None)
        if matched is None:
            raise ValueError(f"Ticker {ticker} not found or insufficient price history")

        return {
            "ticker":           matched["ticker"],
            "rs_rating":        matched["rs_rating"],
            "percentile":       matched["rs_rating"],   # RS rating IS the percentile (1-99)
            "rank":             matched["rank"],
            "total_tickers":    matched["total_tickers"],
            "return_composite": matched["composite_return"],
            "return_1q":        matched["return_1q"],
            "return_2q":        matched["return_2q"],
            "return_3q":        matched["return_3q"],
            "return_4q":        matched["return_4q"],
            "trend":            matched["trend"],
        }
