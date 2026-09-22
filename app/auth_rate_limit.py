"""Auth rate limit: Redis INCR when REDIS_URL set, else in-memory (single replica)."""

from __future__ import annotations

import ipaddress
import os
import time
from collections import defaultdict
from typing import Any

_redis_client = None
_redis_failed = False
_last_redis_retry: float = 0.0
MEMORY_MAX_KEYS = 4096
_last_memory_prune: float = 0.0


def client_ip(request: Any) -> str:
    """Peer IP behind one trusted reverse proxy (Caddy).

    Leftmost X-Forwarded-For is client-spoofable; Caddy appends the real peer.
    App port must stay unpublished (already true in compose).
    """
    raw = ""
    headers = getattr(request, "headers", None)
    if headers is not None:
        raw = headers.get("X-Forwarded-For") or headers.get("x-forwarded-for") or ""
    if isinstance(raw, str) and raw.strip():
        token = raw.split(",")[-1].strip()
        try:
            ipaddress.ip_address(token)
            return token
        except ValueError:
            pass
    host = getattr(getattr(request, "client", None), "host", None)
    return host if isinstance(host, str) and host else "127.0.0.1"


def auth_rate_limit_config() -> tuple[int, float]:
    try:
        limit = int(os.environ.get("AUTH_RATE_LIMIT", "10") or "10")
    except ValueError:
        limit = 10
    try:
        window = float(os.environ.get("AUTH_RATE_WINDOW_SEC", "900") or "900")
    except ValueError:
        window = 900.0
    return max(1, limit), max(60.0, window)


def _get_redis():
    global _redis_client, _redis_failed, _last_redis_retry
    url = os.environ.get("REDIS_URL", "").strip()
    if not url:
        return None
    if _redis_failed and time.time() - _last_redis_retry < 60:
        return None
    if _redis_client is not None:
        try:
            _redis_client.ping()
            return _redis_client
        except Exception:
            _redis_client = None
            _redis_failed = True
            _last_redis_retry = time.time()
            return None
    try:
        import redis

        _redis_client = redis.from_url(url, decode_responses=True)
        _redis_client.ping()
        _redis_failed = False
        return _redis_client
    except Exception:
        _redis_failed = True
        _redis_client = None
        _last_redis_retry = time.time()
        return None


def check_auth_rate_limit(key: str, limit: int, window: float) -> bool:
    """Return True if request allowed, False if over cap."""
    r = _get_redis()
    if r is not None:
        try:
            count = r.incr(key)
            if count == 1:
                r.expire(key, int(window))
            return count <= limit
        except Exception:
            global _redis_failed, _last_redis_retry, _redis_client
            _redis_failed = True
            _last_redis_retry = time.time()
            _redis_client = None
    return _memory_check(key, limit, window)


_memory: dict[str, list[float]] = defaultdict(list)


def _prune_memory(now: float) -> None:
    global _last_memory_prune
    if now - _last_memory_prune < 1.0 and len(_memory) <= MEMORY_MAX_KEYS:
        return
    _last_memory_prune = now
    expired = [
        key for key, bucket in _memory.items()
        if not bucket or now - bucket[-1] >= auth_rate_limit_config()[1]
    ]
    for key in expired:
        _memory.pop(key, None)
    overflow = len(_memory) - MEMORY_MAX_KEYS
    if overflow > 0:
        oldest = sorted(_memory.items(), key=lambda item: item[1][-1])
        for key, _bucket in oldest[:overflow]:
            _memory.pop(key, None)


def _memory_check(key: str, limit: int, window: float) -> bool:
    now = time.monotonic()
    _prune_memory(now)
    if key not in _memory and len(_memory) >= MEMORY_MAX_KEYS:
        oldest_key = min(_memory, key=lambda item: _memory[item][-1])
        _memory.pop(oldest_key, None)
    bucket = [t for t in _memory.get(key, []) if now - t < window]
    if len(bucket) >= limit:
        _memory[key] = bucket
        return False
    bucket.append(now)
    _memory[key] = bucket
    return True


def reset_memory_limits() -> None:
    global _last_memory_prune
    _memory.clear()
    _last_memory_prune = 0.0


def memory_bucket_count() -> int:
    _prune_memory(time.monotonic())
    return len(_memory)


def reset_for_tests() -> None:
    global _redis_client, _redis_failed, _last_redis_retry, _last_memory_prune
    _redis_client = None
    _redis_failed = False
    _last_redis_retry = 0.0
    _memory.clear()
    _last_memory_prune = 0.0
