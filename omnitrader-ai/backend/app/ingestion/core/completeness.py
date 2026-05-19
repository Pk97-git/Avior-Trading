import asyncio
from datetime import datetime, timedelta, timezone
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import text
from typing import List, Dict, Tuple
import logging

from app.ingestion.core.prices import DataIngestionService
from app.ingestion.core.macro_fundamental import FundamentalService
from app.ingestion.infra.rate_limiter import PriorityIngestionQueue, IngestionScheduler, RateLimiterRegistry

logger = logging.getLogger(__name__)

class DataCompletenessMonitor:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def scan_price_gaps(self, tickers: List[str]) -> Tuple[List[str], List[Dict]]:
        """
        Scans the stock_prices table for the provided universe of tickers.
        Returns:
            - missing_entirely: List of tickers with NO price history present. (e.g. IPOs)
            - missing_recent: List of dicts {ticker, start, end} for gaps > 4 days.
        """
        missing_entirely = []
        missing_recent = []

        # Find max date for all given tickers in batch
        # This query is highly optimized since it uses timescaledb indexes or PG groupby
        query = text("""
            SELECT ticker, max(time) as last_date, count(*) as count
            FROM stock_prices
            WHERE ticker = ANY(:tickers)
            GROUP BY ticker
        """)
        
        result = await self.db.execute(query, {"tickers": tickers})
        stats = {row.ticker: {"last_date": row.last_date, "count": row.count} for row in result.all()}
        
        now = datetime.now(timezone.utc)
        
        for ticker in tickers:
            if ticker not in stats or stats[ticker]["count"] == 0:
                missing_entirely.append(ticker)
                continue
                
            last_date = stats[ticker]["last_date"]
            if last_date:
                # Ensure last_date is aware
                if isinstance(last_date, str):
                    last_date = datetime.fromisoformat(last_date.replace("Z", "+00:00"))
                elif last_date.tzinfo is None:
                    last_date = last_date.replace(tzinfo=timezone.utc)
                    
                days_missing = (now - last_date).days
                
                # If we are missing more than 4 days (covers most long weekends/holidays)
                if days_missing > 4:
                    start_str = (last_date - timedelta(days=1)).strftime("%Y-%m-%d")
                    end_str = (now + timedelta(days=1)).strftime("%Y-%m-%d")
                    missing_recent.append({
                        "ticker": ticker,
                        "start": start_str,
                        "end": end_str,
                        "days_missing": days_missing
                    })
                    
        return missing_entirely, missing_recent

    async def run_price_completeness_check(self, tickers: List[str], period: str = "2d"):
        """
        Runs the completeness scan over the provided universe and dynamically
        routes the execution to the high-performance async priority queue.

        period="max"  → initial backfill: fetches full history for ALL tickers
                        (both newly added and those with incomplete history)
        period="2d"   → daily/intraday update: only fills actual gaps
        """
        from app.db.session import AsyncSessionLocal
        missing_entirely, missing_recent = await self.scan_price_gaps(tickers)

        print(f"[Completeness] Scan complete. period={period}. "
              f"{len(missing_entirely)} completely missing. "
              f"{len(missing_recent)} missing recent blocks.")

        # ── Path A: full historical backfill (initial load) ───────────────────
        # When period="max" we re-fetch ALL tickers so that any ticker with only
        # partial history (e.g. 1 year) gets extended to its full available history.
        if period == "max":
            all_to_backfill = list(set(tickers))
            print(f"[Completeness] Full-history mode: scheduling {len(all_to_backfill)} tickers with period=max...")

            async with AsyncSessionLocal() as temp_session:
                svc = DataIngestionService(temp_session)
                await svc.upsert_stock_metadata(all_to_backfill)
                await temp_session.commit()

            queue = PriorityIngestionQueue(n_workers=4)
            scheduler = IngestionScheduler(queue)

            async def fetch_max(ticker: str):
                await RateLimiterRegistry.acquire("yfinance")
                async with AsyncSessionLocal() as session:
                    svc = DataIngestionService(session)
                    await svc.fetch_history(ticker, period="max")

            await scheduler.schedule(
                ticker_groups={"HIGH": all_to_backfill},
                task_fn=fetch_max,
                source="yfinance"
            )
            await queue.run()
            return

        # ── Path B: incremental gap-fill (daily / intraday) ──────────────────

        # 1. Backfill fully missing (IPO or newly added)
        if missing_entirely:
            print(f"[Completeness] Starting Full History Backfill for {len(missing_entirely)} newly added tickers...")
            async with AsyncSessionLocal() as temp_session:
                svc = DataIngestionService(temp_session)
                await svc.upsert_stock_metadata(missing_entirely)
                await temp_session.commit()

            queue = PriorityIngestionQueue(n_workers=4)
            scheduler = IngestionScheduler(queue)

            async def fetch_full(ticker: str):
                await RateLimiterRegistry.acquire("yfinance")
                async with AsyncSessionLocal() as session:
                    svc = DataIngestionService(session)
                    await svc.fetch_history(ticker, period="max")

            await scheduler.schedule(
                ticker_groups={"HIGH": missing_entirely},
                task_fn=fetch_full,
                source="yfinance"
            )
            await queue.run()

        # 2. Backfill delta gaps (missing a few days/weeks)
        if missing_recent:
            print(f"[Completeness] Starting Targeted Date-Range Backfill for {len(missing_recent)} tickers with gaps...")
            tickers_with_gaps = [m["ticker"] for m in missing_recent]

            async with AsyncSessionLocal() as temp_session:
                svc = DataIngestionService(temp_session)
                await svc.upsert_stock_metadata(tickers_with_gaps)
                await temp_session.commit()

            queue = PriorityIngestionQueue(n_workers=5)
            scheduler = IngestionScheduler(queue)

            gap_map = {m["ticker"]: m for m in missing_recent}

            async def fetch_gap(ticker: str):
                params = gap_map[ticker]
                await RateLimiterRegistry.acquire("yfinance")
                async with AsyncSessionLocal() as session:
                    svc = DataIngestionService(session)
                    await svc.fetch_history(ticker, start=params["start"], end=params["end"])
                print(f"  [GAP FILL] {ticker}: {params['start']} to {params['end']} filled.")

            await scheduler.schedule(
                ticker_groups={"HIGH": list(gap_map.keys())},
                task_fn=fetch_gap,
                source="yfinance"
            )
            await queue.run()

    async def scan_fundamental_gaps(self, tickers: List[str]) -> List[str]:
        """
        Scans company_financials for the given tickers.
        Returns a list of tickers that either have NO fundamentals or whose
        latest financial report is more than 6 months (180 days) old.
        """
        missing_or_outdated = []
        
        query = text("""
            SELECT ticker, max(fiscal_date) as last_date, count(*) as count
            FROM company_financials
            WHERE ticker = ANY(:tickers)
            GROUP BY ticker
        """)
        
        result = await self.db.execute(query, {"tickers": tickers})
        stats = {row.ticker: {"last_date": row.last_date, "count": row.count} for row in result.all()}
        
        now = datetime.now(timezone.utc)
        
        for ticker in tickers:
            if ticker not in stats or stats[ticker]["count"] == 0:
                missing_or_outdated.append(ticker)
                continue
                
            last_date = stats[ticker]["last_date"]
            if last_date:
                if isinstance(last_date, str):
                    last_date = datetime.fromisoformat(last_date.replace("Z", "+00:00"))
                elif last_date.tzinfo is None:
                    last_date = last_date.replace(tzinfo=timezone.utc)
                    
                days_missing = (now - last_date).days
                
                # Annual reports might have up to a year gap, but yfinance provides TTM or recent data
                # Flag if older than 180 days to be safe and try to fetch newer data.
                if days_missing > 180:
                    missing_or_outdated.append(ticker)
                    
        return missing_or_outdated

    async def run_fundamental_completeness_check(self, tickers: List[str]):
        """
        Runs completeness scan for fundamentals and triggers backfill.
        """
        needs_fetch = await self.scan_fundamental_gaps(tickers)
        
        print(f"[Completeness] Fundamental scan complete. {len(needs_fetch)} tickers need fundamental data.")
        
        if not needs_fetch:
            return
            
        from app.db.session import AsyncSessionLocal
        print(f"[Completeness] Starting Fundamental Fetch for {len(needs_fetch)} tickers...")
        
        queue = PriorityIngestionQueue(n_workers=3)
        scheduler = IngestionScheduler(queue)
        
        async def fetch_fund(ticker: str):
            await RateLimiterRegistry.acquire("yfinance")
            async with AsyncSessionLocal() as session:
                svc = FundamentalService(session)
                await svc.fetch_financials(ticker)
            
        await scheduler.schedule(
            ticker_groups={"HIGH": needs_fetch},
            task_fn=fetch_fund,
            source="yfinance"
        )
        await queue.run()

    async def get_coverage_stats(self) -> dict:
        """
        Calculates the coverage percentage of price and fundamental data 
        across the entire stock universe.
        """
        # 1. Total Stocks in Universe
        total_stocks_query = text("SELECT count(*) FROM stocks")
        total_res = await self.db.execute(total_stocks_query)
        total_stocks = total_res.scalar() or 0

        if total_stocks == 0:
            return {"total_universe": 0, "price_coverage": 0.0, "fundamental_coverage": 0.0}

        # 2. Stocks with at least 1 price row
        price_query = text("SELECT count(DISTINCT ticker) FROM stock_prices")
        price_res = await self.db.execute(price_query)
        stocks_with_prices = price_res.scalar() or 0

        # 3. Stocks with at least 1 fundamental report
        fund_query = text("SELECT count(DISTINCT ticker) FROM company_financials")
        fund_res = await self.db.execute(fund_query)
        stocks_with_funds = fund_res.scalar() or 0

        return {
            "total_universe": total_stocks,
            "stocks_with_prices": stocks_with_prices,
            "price_coverage_pct": round((stocks_with_prices / total_stocks) * 100, 2),
            "stocks_with_fundamentals": stocks_with_funds,
            "fundamental_coverage_pct": round((stocks_with_funds / total_stocks) * 100, 2)
        }
