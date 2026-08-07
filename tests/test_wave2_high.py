"""Wave 2 (H-1..H-4): rate limit cleanup, session cache, proxy validation."""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from pydantic import ValidationError

import antiban_core
from app import auth


def test_ip_rate_limit_drops_empty_keys():
    import time

    import main as m
    from main import RATE_WINDOW, RateLimitMiddleware

    m._rate_counters.clear()
    ip = "203.0.113.55"
    mw = RateLimitMiddleware(app=MagicMock())
    stale = time.monotonic() - RATE_WINDOW - 1

    async def run():
        req = MagicMock()
        req.url.path = "/api/status"
        req.client = MagicMock()
        req.client.host = ip
        m._rate_counters[ip] = [stale]
        await mw.dispatch(req, AsyncMock(return_value="ok"))
        assert ip not in m._rate_counters

    asyncio.run(run())


def test_normalize_proxy_field():
    assert antiban_core.normalize_proxy_field("") == ""
    assert antiban_core.normalize_proxy_field("  ") == ""
    with pytest.raises(ValueError, match="proxy"):
        antiban_core.normalize_proxy_field("bad-value")


def test_proxy_in_rejects_invalid():
    from app.routes_admin import ProxyIn

    ProxyIn(proxy="")
    with pytest.raises(ValidationError):
        ProxyIn(proxy="bad-value")


def test_cached_validate_uses_cache():
    auth.clear_session_cache()
    payload = {"jti": "j1", "sub": "1", "tenant_id": 1, "tv": 0}
    with patch("app.auth.validate_token_session", return_value=None) as validate:
        assert auth.cached_validate_token_session(payload) is None
        assert auth.cached_validate_token_session(payload) is None
        validate.assert_called_once()


def test_invalidate_session_cache_forces_revalidate():
    auth.clear_session_cache()
    payload = {"jti": "j2", "sub": "1"}
    with patch("app.auth.validate_token_session", return_value=None) as validate:
        auth.cached_validate_token_session(payload)
        auth.invalidate_session_cache("j2")
        auth.cached_validate_token_session(payload)
        assert validate.call_count == 2


def test_clear_session_cache():
    auth.clear_session_cache()
    payload = {"jti": "j3", "sub": "1"}
    with patch("app.auth.validate_token_session", return_value=None) as validate:
        auth.cached_validate_token_session(payload)
        auth.clear_session_cache()
        auth.cached_validate_token_session(payload)
        assert validate.call_count == 2
