"""Redis-backed auth rate limit with in-memory fallback."""

from __future__ import annotations

import sys
from concurrent.futures import ThreadPoolExecutor
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from app import auth_rate_limit


def test_redis_rate_limit_blocks(monkeypatch):
    auth_rate_limit.reset_for_tests()
    monkeypatch.setenv("REDIS_URL", "redis://127.0.0.1:6379/0")

    mock_r = MagicMock()
    mock_r.eval.side_effect = [1, 2, 3, 4]

    with patch.object(auth_rate_limit, "_get_redis", return_value=mock_r):
        assert auth_rate_limit.check_auth_rate_limit("k", 3, 60.0) is True
        assert auth_rate_limit.check_auth_rate_limit("k", 3, 60.0) is True
        assert auth_rate_limit.check_auth_rate_limit("k", 3, 60.0) is True
        assert auth_rate_limit.check_auth_rate_limit("k", 3, 60.0) is False

    assert mock_r.incr.call_count == 0
    assert mock_r.expire.call_count == 0
    assert mock_r.eval.call_count == 4
    script, key_count, key, ttl = mock_r.eval.call_args.args
    assert "INCR" in script
    assert "EXPIRE" in script
    assert "rate_limit_expiry_failed" in script
    assert key_count == 1
    assert key == "k"
    assert ttl == 60


def test_memory_fallback_when_no_redis(monkeypatch):
    auth_rate_limit.reset_for_tests()
    monkeypatch.delenv("REDIS_URL", raising=False)
    with patch.object(auth_rate_limit, "_get_redis", return_value=None):
        assert auth_rate_limit.check_auth_rate_limit("mem:k", 2, 60.0) is True
        assert auth_rate_limit.check_auth_rate_limit("mem:k", 2, 60.0) is True
        assert auth_rate_limit.check_auth_rate_limit("mem:k", 2, 60.0) is False


def test_memory_fallback_serializes_concurrent_bucket_updates():
    auth_rate_limit.reset_for_tests()
    with patch.object(auth_rate_limit, "_get_redis", return_value=None):
        with ThreadPoolExecutor(max_workers=8) as pool:
            results = list(
                pool.map(
                    lambda _index: auth_rate_limit.check_auth_rate_limit(
                        "concurrent", 1, 60.0
                    ),
                    range(32),
                )
            )
    assert sum(results) == 1


def test_atomic_script_repairs_existing_no_ttl_bucket(monkeypatch):
    auth_rate_limit.reset_for_tests()
    monkeypatch.setenv("REDIS_URL", "redis://127.0.0.1:6379/0")

    class AtomicRedis:
        def __init__(self) -> None:
            self.count = 2
            self.ttl = -1

        def eval(self, _script, _key_count, _key, ttl):
            self.count += 1
            if self.ttl < 0:
                self.ttl = ttl
            return self.count

    redis = AtomicRedis()
    with patch.object(auth_rate_limit, "_get_redis", return_value=redis):
        assert auth_rate_limit.check_auth_rate_limit("orphan", 2, 60.0) is False
    assert redis.ttl == 60


def test_tenant_cleanup_removes_memory_and_redis_scoped_buckets(monkeypatch):
    auth_rate_limit.reset_for_tests()
    tenant_key = auth_rate_limit.user_rate_limit_key(77, 12, bucket=1)
    other_tenant_key = auth_rate_limit.user_rate_limit_key(77, 13, bucket=1)
    legacy_key = "user_rl:77:1"
    with patch.object(auth_rate_limit, "_get_redis", return_value=None):
        assert auth_rate_limit.check_auth_rate_limit(tenant_key, 5, 60.0) is True
        assert auth_rate_limit.check_auth_rate_limit(other_tenant_key, 5, 60.0) is True
        assert auth_rate_limit.check_auth_rate_limit(legacy_key, 5, 60.0) is True
        removed = auth_rate_limit.clear_tenant_rate_limit_keys(12, 77)

    assert removed == 2
    assert tenant_key not in auth_rate_limit._memory
    assert legacy_key not in auth_rate_limit._memory
    assert other_tenant_key in auth_rate_limit._memory


def test_redis_cleanup_deletes_only_requested_tenant_patterns():
    auth_rate_limit.reset_for_tests()

    class CleanupRedis:
        def __init__(self) -> None:
            self.deleted: list[str] = []

        def scan_iter(self, *, match, count):
            assert count == 100
            if match == "user_rl:tenant:12:*":
                return iter(["user_rl:tenant:12:77:1"])
            if match == "user_rl:77:*":
                return iter(["user_rl:77:1"])
            return iter([])

        def delete(self, *keys):
            self.deleted.extend(keys)
            return len(keys)

    redis = CleanupRedis()
    with patch.object(auth_rate_limit, "_get_redis", return_value=redis):
        assert auth_rate_limit.clear_tenant_rate_limit_keys(12, 77) == 2
    assert redis.deleted == ["user_rl:tenant:12:77:1", "user_rl:77:1"]


def test_redis_client_has_bounded_network_timeouts(monkeypatch):
    auth_rate_limit.reset_for_tests()
    monkeypatch.setenv("REDIS_URL", "redis://127.0.0.1:6379/0")
    client = MagicMock()
    redis_module = SimpleNamespace(from_url=MagicMock(return_value=client))
    with patch.dict(sys.modules, {"redis": redis_module}):
        assert auth_rate_limit._get_redis() is client
    redis_module.from_url.assert_called_once_with(
        "redis://127.0.0.1:6379/0",
        decode_responses=True,
        socket_connect_timeout=2.0,
        socket_timeout=2.0,
    )
    auth_rate_limit.reset_for_tests()
