"""Redis-backed auth rate limit with in-memory fallback."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from app import auth_rate_limit


def test_redis_rate_limit_blocks(monkeypatch):
    auth_rate_limit.reset_for_tests()
    monkeypatch.setenv("REDIS_URL", "redis://127.0.0.1:6379/0")

    mock_r = MagicMock()
    mock_r.incr.side_effect = [1, 2, 3, 4]
    mock_r.expire.return_value = True

    with patch.object(auth_rate_limit, "_get_redis", return_value=mock_r):
        assert auth_rate_limit.check_auth_rate_limit("k", 3, 60.0) is True
        assert auth_rate_limit.check_auth_rate_limit("k", 3, 60.0) is True
        assert auth_rate_limit.check_auth_rate_limit("k", 3, 60.0) is True
        assert auth_rate_limit.check_auth_rate_limit("k", 3, 60.0) is False


def test_memory_fallback_when_no_redis(monkeypatch):
    auth_rate_limit.reset_for_tests()
    monkeypatch.delenv("REDIS_URL", raising=False)
    with patch.object(auth_rate_limit, "_get_redis", return_value=None):
        assert auth_rate_limit.check_auth_rate_limit("mem:k", 2, 60.0) is True
        assert auth_rate_limit.check_auth_rate_limit("mem:k", 2, 60.0) is True
        assert auth_rate_limit.check_auth_rate_limit("mem:k", 2, 60.0) is False
