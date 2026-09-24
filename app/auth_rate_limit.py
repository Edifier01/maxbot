"""Auth rate limit: Redis INCR when REDIS_URL set, else in-memory (single replica)."""

from __future__ import annotations

import ipaddress
import os
import threading
import time
from collections import defaultdict
from typing import Any

_redis_client = None
_redis_failed = False
_last_redis_retry: float = 0.0
MEMORY_MAX_KEYS = 4096
_last_memory_prune: float = 0.0
_memory_lock = threading.Lock()


def _trusted_proxy(peer: str) -> bool:
    """Return whether forwarded headers may be trusted for this peer."""
    try:
        peer_ip = ipaddress.ip_address(peer)
    except ValueError:
        return False
    for raw_cidr in os.environ.get("TRUSTED_PROXY_CIDRS", "").split(","):
        try:
            if peer_ip in ipaddress.ip_network(raw_cidr.strip(), strict=False):
                return True
        except ValueError:
            continue
    return False

# Keep the increment and expiry in one Redis-side transaction.  The script
# also repairs a legacy bucket that somehow exists without a TTL; a failed
# expiry deletes that bucket before returning an error, so the caller can
# safely fall back to the bounded in-process limiter.
_REDIS_RATE_LIMIT_SCRIPT = """
local count = redis.call('INCR', KEYS[1])
if redis.call('TTL', KEYS[1]) < 0 then
    local ok, result = pcall(redis.call, 'EXPIRE', KEYS[1], ARGV[1])
    if not ok or result ~= 1 then
        redis.call('DEL', KEYS[1])
        return redis.error_reply('rate_limit_expiry_failed')
    end
end
return count
"""


def client_ip(request: Any) -> str:
    """Peer IP behind explicitly trusted reverse proxies (for example Caddy).

    Leftmost X-Forwarded-For is client-spoofable. The rightmost forwarded
    address is used only when the direct peer belongs to TRUSTED_PROXY_CIDRS;
    otherwise forwarded headers are ignored. App port must stay unpublished.
    """
    peer = getattr(getattr(request, "client", None), "host", None)
    peer = peer if isinstance(peer, str) and peer else "127.0.0.1"
    raw = ""
    headers = getattr(request, "headers", None)
    if headers is not None and _trusted_proxy(peer):
        raw = headers.get("X-Forwarded-For") or headers.get("x-forwarded-for") or ""
    if isinstance(raw, str) and raw.strip():
        token = raw.split(",")[-1].strip()
        try:
            ipaddress.ip_address(token)
            return token
        except ValueError:
            pass
    return peer


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

        _redis_client = redis.from_url(
            url,
            decode_responses=True,
            socket_connect_timeout=2.0,
            socket_timeout=2.0,
        )
        _redis_client.ping()
        _redis_failed = False
        return _redis_client
    except Exception:
        _redis_failed = True
        _redis_client = None
        _last_redis_retry = time.time()
        return None


def user_rate_limit_key(
    user_id: int,
    tenant_id: int | None,
    *,
    bucket: int | None = None,
) -> str:
    """Build a mutation bucket that can be retired with its tenant."""
    scope = f"tenant:{int(tenant_id)}" if tenant_id is not None else "global"
    minute = int(time.monotonic() // 60) if bucket is None else int(bucket)
    return f"user_rl:{scope}:{int(user_id)}:{minute}"


def _mark_redis_failed() -> None:
    global _redis_failed, _last_redis_retry, _redis_client

    _redis_failed = True
    _last_redis_retry = time.time()
    _redis_client = None


def check_auth_rate_limit(key: str, limit: int, window: float) -> bool:
    """Return True if request allowed, False if over cap."""
    r = _get_redis()
    if r is not None:
        try:
            count = r.eval(
                _REDIS_RATE_LIMIT_SCRIPT,
                1,
                key,
                max(1, int(window)),
            )
            return int(count) <= limit
        except Exception:
            _mark_redis_failed()
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
    with _memory_lock:
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
    with _memory_lock:
        _memory.clear()
        _last_memory_prune = 0.0


def memory_bucket_count() -> int:
    with _memory_lock:
        _prune_memory(time.monotonic())
        return len(_memory)


def clear_tenant_rate_limit_keys(tenant_id: int, user_id: int | None = None) -> int:
    """Retire in-process and Redis mutation buckets after tenant deletion.

    IP login buckets are intentionally process/global rather than tenant-owned;
    they have an atomic Redis TTL and bounded local eviction.  Tenant-scoped
    mutation buckets are deleted by scope, while the legacy user-only pattern
    is removed for the affected user during the transition.
    """
    tenant_prefix = f"user_rl:tenant:{int(tenant_id)}:"
    legacy_prefix = f"user_rl:{int(user_id)}:" if user_id is not None else ""
    removed = 0
    with _memory_lock:
        for key in list(_memory):
            if key.startswith(tenant_prefix) or (legacy_prefix and key.startswith(legacy_prefix)):
                _memory.pop(key, None)
                removed += 1

    r = _get_redis()
    if r is None:
        return removed
    patterns = [f"{tenant_prefix}*"]
    if legacy_prefix:
        patterns.append(f"{legacy_prefix}*")
    try:
        for pattern in patterns:
            keys = list(r.scan_iter(match=pattern, count=100))
            if keys:
                removed += int(r.delete(*keys) or 0)
    except Exception:
        _mark_redis_failed()
    return removed


def reset_for_tests() -> None:
    global _redis_client, _redis_failed, _last_redis_retry, _last_memory_prune
    _redis_client = None
    _redis_failed = False
    _last_redis_retry = 0.0
    with _memory_lock:
        _memory.clear()
        _last_memory_prune = 0.0
