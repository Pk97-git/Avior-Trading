
import asyncio
import time
import logging
from typing import Callable, Any
from functools import wraps

# Constants
YAHOO_RATE = 40       # Limit to 40 requests...
YAHOO_PERIOD = 60.0   # ...per 60 seconds (Safe threshold to avoid 2024 Yahoo IP bans)

logger = logging.getLogger(__name__)

class RateLimiter:
    """
    Async Sliding Window Log Rate Limiter.
    Thread-safe and async-friendly.
    """
    def __init__(self, max_calls: int, period: float):
        self.max_calls = max_calls
        self.period = period
        self.calls = []
        self._lock = asyncio.Lock()

    async def acquire(self):
        """
        Wait until a slot is available.
        """
        while True:
            sleep_needed = 0
            async with self._lock:
                now = time.monotonic()
                # Prune old timestamps
                self.calls = [t for t in self.calls if now - t < self.period]
                
                if len(self.calls) < self.max_calls:
                    self.calls.append(now)
                    return # Acquired!
                
                # If full, calculate wait time
                # Wait until the oldest call expires
                if self.calls:
                    expiry = self.calls[0] + self.period
                    sleep_needed = expiry - now
                else:
                    sleep_needed = 0.1 # Should not happen if full
            
            if sleep_needed > 0:
                # Add small buffer
                await asyncio.sleep(sleep_needed + 0.05)

# Global Instance for Yahoo Finance
yahoo_limiter = RateLimiter(max_calls=YAHOO_RATE, period=YAHOO_PERIOD)

def rate_limit(limiter: RateLimiter):
    """Decorator to apply rate limiting to an async function."""
    def decorator(func: Callable):
        @wraps(func)
        async def wrapper(*args, **kwargs):
            await limiter.acquire()
            return await func(*args, **kwargs)
        return wrapper
    return decorator
