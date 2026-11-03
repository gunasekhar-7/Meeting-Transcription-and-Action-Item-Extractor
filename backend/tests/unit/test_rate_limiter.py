from __future__ import annotations

import time
from unittest.mock import MagicMock

from app.core.rate_limiter import (
    MemorySlidingWindowLimiter,
    RedisSlidingWindowLimiter,
    build_rate_limiter,
)


def test_memory_limiter_under_and_over_limit() -> None:
    limiter = MemorySlidingWindowLimiter()
    key = ("127.0.0.1", "test_endpoint")

    for _ in range(5):
        allowed, retry_after = limiter.check(key, limit=5, window=60.0)
        assert allowed is True
        assert retry_after == 0

    # 6th request must be rejected
    allowed, retry_after = limiter.check(key, limit=5, window=60.0)
    assert allowed is False
    assert 1 <= retry_after <= 60


def test_memory_limiter_window_slide() -> None:
    limiter = MemorySlidingWindowLimiter()
    key = ("127.0.0.1", "slide")

    allowed, _ = limiter.check(key, limit=1, window=0.1)
    assert allowed is True

    allowed, retry_after = limiter.check(key, limit=1, window=0.1)
    assert allowed is False

    time.sleep(0.12)
    allowed, retry_after = limiter.check(key, limit=1, window=0.1)
    assert allowed is True
    assert retry_after == 0


def test_redis_limiter_under_limit() -> None:
    mock_redis = MagicMock()
    pipe = MagicMock()
    # pipeline returns [removed_count, current_count, oldest_entries]
    pipe.execute.side_effect = [
        [0, 2, [("123.456", 123.456)]],  # first pipeline: zrem, zcard, zrange
        [True, True],                     # second pipeline: zadd, expire
    ]
    mock_redis.pipeline.return_value = pipe

    limiter = RedisSlidingWindowLimiter(redis_url="redis://localhost:6379/0")
    limiter._client = mock_redis

    allowed, retry_after = limiter.check(("client_a", "login"), limit=5, window=60.0)
    assert allowed is True
    assert retry_after == 0
    assert pipe.zremrangebyscore.called
    assert pipe.zcard.called
    assert pipe.zadd.called
    assert pipe.expire.called


def test_redis_limiter_over_limit() -> None:
    mock_redis = MagicMock()
    pipe = MagicMock()
    now = time.time()
    pipe.execute.return_value = [0, 5, [("first_hit", now - 20)]]
    mock_redis.pipeline.return_value = pipe

    limiter = RedisSlidingWindowLimiter(redis_url="redis://localhost:6379/0")
    limiter._client = mock_redis

    allowed, retry_after = limiter.check(("client_b", "audio"), limit=5, window=60.0)
    assert allowed is False
    assert 1 <= retry_after <= 60


def test_redis_limiter_falls_back_to_memory_on_error() -> None:
    mock_redis = MagicMock()
    mock_redis.pipeline.side_effect = ConnectionError("Redis down")

    fallback = MemorySlidingWindowLimiter()
    limiter = RedisSlidingWindowLimiter(redis_url="redis://localhost:6379/0", fallback=fallback)
    limiter._client = mock_redis

    # Should not raise; should use in-memory fallback smoothly
    allowed, retry_after = limiter.check(("client_c", "login"), limit=2, window=60.0)
    assert allowed is True
    assert retry_after == 0

    allowed, _ = limiter.check(("client_c", "login"), limit=2, window=60.0)
    assert allowed is True

    allowed, retry_after = limiter.check(("client_c", "login"), limit=2, window=60.0)
    assert allowed is False
    assert retry_after > 0


def test_build_rate_limiter() -> None:
    mem = build_rate_limiter(backend="memory")
    assert isinstance(mem, MemorySlidingWindowLimiter)

    red = build_rate_limiter(backend="redis", redis_url="redis://localhost:6379/0")
    assert isinstance(red, RedisSlidingWindowLimiter)
