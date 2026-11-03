"""Distributed and in-process rate limiting primitives."""

from __future__ import annotations

import logging
import threading
import time
from collections import deque
from typing import Protocol

import redis

logger = logging.getLogger(__name__)


class RateLimiter(Protocol):
    """Rate limiter interface."""

    def check(self, key: tuple[str, str], limit: int, window: float) -> tuple[bool, int]:
        """Check if request is allowed. Returns (allowed, retry_after_seconds)."""
        ...


class MemorySlidingWindowLimiter:
    """Thread-safe, process-local sliding-window limiter.

    Maintains in-memory deques of timestamps per key. Suitable for single-process
    deployments and test environments.
    """

    def __init__(self) -> None:
        self._hits: dict[tuple[str, str], deque[float]] = {}
        self._lock = threading.Lock()

    def check(self, key: tuple[str, str], limit: int, window: float) -> tuple[bool, int]:
        now = time.time()
        with self._lock:
            bucket = self._hits.setdefault(key, deque())
            while bucket and bucket[0] <= now - window:
                bucket.popleft()
            if len(bucket) >= limit:
                retry_after = int(max(1, window - (now - bucket[0])))
                return False, retry_after
            bucket.append(now)
            return True, 0

    def clear(self) -> None:
        with self._lock:
            self._hits.clear()


class RedisSlidingWindowLimiter:
    """Distributed sliding-window rate limiter backed by Redis sorted sets.

    Coordinates rate limits across multiple uvicorn workers and API replicas.
    Falls back to an in-memory limiter if Redis becomes temporarily unreachable,
    preventing infrastructure outages from cascading to API availability.
    """

    def __init__(
        self,
        redis_url: str,
        fallback: RateLimiter | None = None,
        key_prefix: str = "ratelimit",
    ) -> None:
        self.redis_url = redis_url
        self.fallback = fallback or MemorySlidingWindowLimiter()
        self.key_prefix = key_prefix
        self._client: redis.Redis | None = None
        self._lock = threading.Lock()

    @property
    def client(self) -> redis.Redis:
        if self._client is None:
            with self._lock:
                if self._client is None:
                    self._client = redis.from_url(
                        self.redis_url,
                        decode_responses=True,
                        socket_timeout=1.0,
                        socket_connect_timeout=1.0,
                    )
        return self._client

    def _redis_key(self, key: tuple[str, str]) -> str:
        # key: (client_ip_or_id, endpoint_action)
        return f"{self.key_prefix}:{key[0]}:{key[1]}"

    def check(self, key: tuple[str, str], limit: int, window: float) -> tuple[bool, int]:
        now = time.time()
        redis_key = self._redis_key(key)
        try:
            client = self.client
            pipe = client.pipeline()
            # 1. Prune timestamps outside current window
            pipe.zremrangebyscore(redis_key, "-inf", now - window)
            # 2. Count remaining hits in window
            pipe.zcard(redis_key)
            # 3. Retrieve oldest hit timestamp for retry_after calculation
            pipe.zrange(redis_key, 0, 0, withscores=True)
            results = pipe.execute()

            count: int = results[1]
            oldest_entries = results[2]

            if count >= limit:
                oldest_score = oldest_entries[0][1] if oldest_entries else (now - window)
                retry_after = int(max(1, window - (now - oldest_score)))
                return False, retry_after

            # Under limit: record current hit with score=now, member=f"{now}:{uuid/nonce}"
            nonce = f"{now:.6f}"
            pipe = client.pipeline()
            pipe.zadd(redis_key, {nonce: now})
            pipe.expire(redis_key, int(window) + 1)
            pipe.execute()
            return True, 0
        except Exception as exc:
            logger.warning(
                "redis_rate_limiter_unavailable",
                extra={"extra_fields": {"reason": str(exc), "fallback": "memory"}},
            )
            return self.fallback.check(key, limit, window)


def build_rate_limiter(
    backend: str = "memory",
    redis_url: str = "redis://localhost:6379/0",
) -> RateLimiter:
    """Build rate limiter based on configuration."""
    if backend == "redis":
        return RedisSlidingWindowLimiter(redis_url=redis_url)
    if backend == "auto":
        try:
            client = redis.from_url(redis_url, socket_timeout=0.5, socket_connect_timeout=0.5)
            client.ping()
            return RedisSlidingWindowLimiter(redis_url=redis_url)
        except Exception:
            logger.info("redis_not_available_using_memory_limiter")
            return MemorySlidingWindowLimiter()
    return MemorySlidingWindowLimiter()
