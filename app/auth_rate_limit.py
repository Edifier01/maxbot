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


def _memory_check(key: str, limit: int, window: float) -> bool:
    now = time.monotonic()
    bucket = [t for t in _memory[key] if now - t < window]
    if len(bucket) >= limit:
        _memory[key] = bucket
        return False
    bucket.append(now)
    _memory[key] = bucket
    return True


def reset_memory_limits() -> None:
    _memory.clear()


def reset_for_tests() -> None:
    global _redis_client, _redis_failed, _last_redis_retry
    _redis_client = None
    _redis_failed = False
    _last_redis_retry = 0.0
    _memory.clear()
