"""
Rate Limiter & Priority Queue
================================
PRD Section 8 Requirements:
  - Token bucket system
  - Queue-based ingestion
  - Priority tiers: HIGH (active candidates), MEDIUM (watchlist), LOW (background)
  - Staggered fetch across 24 hours

Architecture:
  - TokenBucket: controls per-source API call rate
  - PriorityIngestionQueue: asyncio priority queue with 3 tiers
  - IngestionScheduler: distributes work across 24h staggered windows
"""

import asyncio
import time
import heapq
from dataclasses import dataclass, field
from typing import List, Callable, Awaitable, Any, Dict, Optional
from enum import IntEnum
from datetime import datetime, timedelta


# ─── Priority Tiers ───────────────────────────────────────────────────────────

class Priority(IntEnum):
    HIGH = 0    # Active candidates — fetched every run
    MEDIUM = 1  # Watchlist — fetched daily
    LOW = 2     # Background universe — fetched weekly


# ─── Token Bucket ─────────────────────────────────────────────────────────────

class TokenBucket:
    """
    Classic token bucket rate limiter.
    
    Controls: max requests per source per minute/hour.
    
    yfinance limits:  ~2000 req/hour from same IP
    NSE limits:       ~60 req/min (be conservative)
    FRED limits:      ~120 req/min (free tier)
    SEC EDGAR:        10 req/sec max
    """

    DEFAULT_RATES = {
        "yfinance": {"rate": 40, "per_seconds": 60},    # 40 req/min (Safe threshold for 2024 Yahoo scraping defenses)
        "nse":      {"rate": 20, "per_seconds": 60},    # 20 req/min
        "fred":     {"rate": 60, "per_seconds": 60},    # 60 req/min
        "sec_edgar":{"rate": 8,  "per_seconds": 1},     # 8 req/sec
        "reddit":   {"rate": 10, "per_seconds": 60},    # 10 req/min
        "default":  {"rate": 10, "per_seconds": 60},    # fallback
    }

    def __init__(self, source: str):
        config = self.DEFAULT_RATES.get(source, self.DEFAULT_RATES["default"])
        self.capacity = config["rate"]
        self.refill_rate = config["rate"] / config["per_seconds"]  # tokens/second
        self.tokens = float(self.capacity)
        self.last_refill = time.monotonic()
        self.source = source
        self._lock = asyncio.Lock()

    def _refill(self):
        now = time.monotonic()
        elapsed = now - self.last_refill
        self.tokens = min(self.capacity, self.tokens + elapsed * self.refill_rate)
        self.last_refill = now

    async def acquire(self, tokens: int = 1) -> float:
        """
        Acquires tokens from the bucket.
        Returns wait time in seconds (0.0 if no wait needed).
        Blocks until tokens are available.
        """
        async with self._lock:
            self._refill()
            if self.tokens >= tokens:
                self.tokens -= tokens
                return 0.0

            # Calculate wait time needed to refill
            deficit = tokens - self.tokens
            wait_time = deficit / self.refill_rate
            await asyncio.sleep(wait_time)
            self._refill()
            self.tokens -= tokens
            return wait_time

    async def __aenter__(self):
        await self.acquire()
        return self

    async def __aexit__(self, *args):
        pass


# ─── Rate Limiter Registry ────────────────────────────────────────────────────

class RateLimiterRegistry:
    """Global singleton registry of rate limiters per source."""
    _buckets: Dict[str, TokenBucket] = {}

    @classmethod
    def get(cls, source: str) -> TokenBucket:
        if source not in cls._buckets:
            cls._buckets[source] = TokenBucket(source)
        return cls._buckets[source]

    @classmethod
    async def acquire(cls, source: str):
        """Acquire a rate limit token for a given source."""
        bucket = cls.get(source)
        wait = await bucket.acquire()
        if wait > 0.5: # only log substantial waits to avoid console spam
            print(f"  [RateLimit] {source}: waited {wait:.1f}s")


# ─── Ingestion Job ────────────────────────────────────────────────────────────

@dataclass(order=True)
class IngestionJob:
    """A single ingestion work item with priority."""
    priority: int                     # Lower = higher priority
    ticker: str = field(compare=False)
    source: str = field(compare=False)
    task_fn: Callable = field(compare=False, repr=False)
    kwargs: dict = field(default_factory=dict, compare=False)
    scheduled_at: float = field(default_factory=time.monotonic, compare=False)


# ─── Priority Queue ───────────────────────────────────────────────────────────

class PriorityIngestionQueue:
    """
    Async priority queue for ingestion jobs.
    
    Priority order: HIGH → MEDIUM → LOW
    Workers pull jobs and apply rate limiting per source.
    """

    def __init__(self, n_workers: int = 4):
        self._heap: List[IngestionJob] = []
        self._lock = asyncio.Lock()
        self._event = asyncio.Event()
        self.n_workers = n_workers
        self._stats = {"completed": 0, "failed": 0, "rate_limited": 0}

    async def push(self, job: IngestionJob):
        async with self._lock:
            heapq.heappush(self._heap, job)
        self._event.set()

    async def push_batch(self, jobs: List[IngestionJob]):
        async with self._lock:
            for job in jobs:
                heapq.heappush(self._heap, job)
        self._event.set()

    async def _pop(self) -> Optional[IngestionJob]:
        async with self._lock:
            if self._heap:
                return heapq.heappop(self._heap)
        return None

    async def _worker(self, worker_id: int):
        while True:
            job = await self._pop()
            if job is None:
                # Wait for new work
                self._event.clear()
                await self._event.wait()
                continue

            try:
                # Apply rate limiting for this source
                await RateLimiterRegistry.acquire(job.source)
                # Execute the ingestion task
                await job.task_fn(**job.kwargs)
                self._stats["completed"] += 1
            except Exception as e:
                self._stats["failed"] += 1
                print(f"  [Worker-{worker_id}] ERROR for {job.ticker}: {e}")

    async def run(self):
        """Start all workers and process the queue until empty."""
        workers = [asyncio.create_task(self._worker(i)) for i in range(self.n_workers)]
        # Wait until queue is drained
        while True:
            await asyncio.sleep(2)
            async with self._lock:
                if not self._heap:
                    break
        for w in workers:
            w.cancel()
        print(f"  Queue complete — {self._stats}")


# ─── Ingestion Scheduler ──────────────────────────────────────────────────────

class IngestionScheduler:
    """
    Distributes ingestion across a 24-hour window by staggering fetches.
    
    PRD Section 8:
    HIGH priority  → Fetched immediately at run start
    MEDIUM priority → Spread across first 8 hours
    LOW priority   → Spread across remaining 16 hours
    """

    def __init__(self, queue: PriorityIngestionQueue):
        self.queue = queue

    def _stagger_delay(self, priority: Priority, index: int, total: int) -> float:
        """
        Returns a sleep delay in seconds to stagger requests.
        HIGH: no delay
        MEDIUM: spread across a fast 2-hour window (7200s) to prevent hammering
        LOW: spread across a 4-hour window (14400s)
        """
        if priority == Priority.HIGH:
            return 0.0
        elif priority == Priority.MEDIUM:
            window_secs = 2 * 3600
        else:
            window_secs = 4 * 3600

        if total <= 1:
            return 0.0
        return (index / total) * window_secs

    async def schedule(
        self,
        ticker_groups: Dict[str, List[str]],  # {"HIGH": [...], "MEDIUM": [...], "LOW": [...]}
        task_fn: Callable,
        source: str = "yfinance",
    ):
        """
        Schedule all tickers into the priority queue with staggered timing.
        """
        priority_map = {"HIGH": Priority.HIGH, "MEDIUM": Priority.MEDIUM, "LOW": Priority.LOW}
        jobs = []

        for tier_name, tickers in ticker_groups.items():
            priority = priority_map.get(tier_name, Priority.LOW)
            total = len(tickers)

            for i, ticker in enumerate(tickers):
                delay = self._stagger_delay(priority, i, total)
                jobs.append(IngestionJob(
                    priority=int(priority),
                    ticker=ticker,
                    source=source,
                    task_fn=self._delayed_task,
                    kwargs={
                        "delay": delay,
                        "inner_fn": task_fn,
                        "ticker": ticker,
                    },
                ))

        await self.queue.push_batch(jobs)
        print(f"  Scheduled {len(jobs)} jobs across priority tiers")

    @staticmethod
    async def _delayed_task(delay: float, inner_fn: Callable, ticker: str, **kwargs):
        """Wraps a task with an optional delay for staggering."""
        if delay > 0:
            await asyncio.sleep(delay)
        await inner_fn(ticker)


# ─── Convenience: Rate-Limited Fetch Wrapper ─────────────────────────────────

async def rate_limited_fetch(source: str, fetch_fn: Callable, *args, **kwargs) -> Any:
    """
    Generic wrapper to apply rate limiting around any fetch function.
    
    Usage:
        result = await rate_limited_fetch("yfinance", some_async_fn, ticker, period="2d")
    """
    await RateLimiterRegistry.acquire(source)
    return await fetch_fn(*args, **kwargs)


# ─── Quick Test ───────────────────────────────────────────────────────────────

async def _demo():
    queue = PriorityIngestionQueue(n_workers=2)

    async def mock_fetch(ticker: str):
        print(f"  Fetching {ticker}")

    scheduler = IngestionScheduler(queue)
    await scheduler.schedule(
        ticker_groups={
            "HIGH": ["AAPL", "MSFT"],
            "MEDIUM": ["GOOGL", "AMZN"],
            "LOW": ["META", "TSLA"],
        },
        task_fn=mock_fetch,
        source="yfinance",
    )
    await queue.run()


if __name__ == "__main__":
    asyncio.run(_demo())
