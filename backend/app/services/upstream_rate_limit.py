import asyncio
import time
from dataclasses import dataclass
from typing import Literal
from urllib.parse import urlparse

from app.core.config import get_settings


Venue = Literal["polymarket", "kalshi", "other"]


@dataclass
class BucketSnapshot:
    rate_per_second: float
    burst: int
    available_tokens: float
    acquired: int
    delayed: int
    total_wait_seconds: float
    cooldown_seconds: float


class TokenBucket:
    def __init__(self, rate_per_second: float, burst: int) -> None:
        self.rate_per_second = max(rate_per_second, 0.1)
        self.burst = max(burst, 1)
        self._tokens = float(self.burst)
        self._updated_at = time.monotonic()
        self._lock = asyncio.Lock()
        self._acquired = 0
        self._delayed = 0
        self._total_wait_seconds = 0.0
        self._blocked_until = 0.0

    async def acquire(self) -> None:
        waited = 0.0
        while True:
            async with self._lock:
                now = time.monotonic()
                cooldown_delay = max(self._blocked_until - now, 0.0)
                elapsed = max(now - self._updated_at, 0.0)
                self._tokens = min(
                    float(self.burst),
                    self._tokens + elapsed * self.rate_per_second,
                )
                self._updated_at = now
                if self._tokens >= 1.0 and cooldown_delay <= 0:
                    self._tokens -= 1.0
                    self._acquired += 1
                    if waited > 0:
                        self._delayed += 1
                        self._total_wait_seconds += waited
                    return
                token_delay = max((1.0 - self._tokens) / self.rate_per_second, 0)
                delay = max(token_delay, cooldown_delay)
            await asyncio.sleep(delay)
            waited += delay

    def penalize(self, seconds: float) -> None:
        self._blocked_until = max(
            self._blocked_until,
            time.monotonic() + max(seconds, 0.1),
        )

    def snapshot(self) -> BucketSnapshot:
        elapsed = max(time.monotonic() - self._updated_at, 0.0)
        available = min(
            float(self.burst),
            self._tokens + elapsed * self.rate_per_second,
        )
        return BucketSnapshot(
            rate_per_second=self.rate_per_second,
            burst=self.burst,
            available_tokens=round(available, 2),
            acquired=self._acquired,
            delayed=self._delayed,
            total_wait_seconds=round(self._total_wait_seconds, 3),
            cooldown_seconds=round(
                max(self._blocked_until - time.monotonic(), 0.0),
                3,
            ),
        )


class UpstreamRateLimiter:
    def __init__(self) -> None:
        self._buckets: dict[Venue, TokenBucket] = {}

    def _bucket(self, venue: Venue) -> TokenBucket | None:
        if venue == "other":
            return None
        existing = self._buckets.get(venue)
        if existing is not None:
            return existing

        settings = get_settings()
        if venue == "kalshi":
            rate = settings.kalshi_request_rate_per_second
            burst = settings.kalshi_request_burst
        else:
            rate = settings.polymarket_request_rate_per_second
            burst = settings.polymarket_request_burst
        bucket = TokenBucket(rate, burst)
        self._buckets[venue] = bucket
        return bucket

    async def acquire_url(self, url: str) -> Venue:
        venue = venue_for_url(url)
        bucket = self._bucket(venue)
        if bucket is not None:
            await bucket.acquire()
        return venue

    def penalize_url(self, url: str, seconds: float) -> None:
        bucket = self._bucket(venue_for_url(url))
        if bucket is not None:
            bucket.penalize(seconds)

    def status(self) -> dict[str, dict[str, float | int]]:
        payload: dict[str, dict[str, float | int]] = {}
        for venue in ("polymarket", "kalshi"):
            bucket = self._bucket(venue)
            if bucket is None:
                continue
            snapshot = bucket.snapshot()
            payload[venue] = {
                "ratePerSecond": snapshot.rate_per_second,
                "burst": snapshot.burst,
                "availableTokens": snapshot.available_tokens,
                "acquired": snapshot.acquired,
                "delayed": snapshot.delayed,
                "totalWaitSeconds": snapshot.total_wait_seconds,
                "cooldownSeconds": snapshot.cooldown_seconds,
            }
        return payload

    def reset(self) -> None:
        self._buckets.clear()


def venue_for_url(url: str) -> Venue:
    hostname = (urlparse(url).hostname or "").lower()
    if "kalshi" in hostname:
        return "kalshi"
    if "polymarket" in hostname:
        return "polymarket"
    return "other"


upstream_rate_limiter = UpstreamRateLimiter()
