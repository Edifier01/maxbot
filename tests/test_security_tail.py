"""FIX-007/008/009: security tail — metrics, token_version, WS auth."""

from __future__ import annotations

import asyncio
import json
import sys
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


@pytest.fixture
def auth_mw(monkeypatch):
    monkeypatch.setenv("INTERNAL_SERVICE_TOKEN", "metrics-svc-token")
    monkeypatch.setattr("app.middleware.is_server_mode", lambda: True)
    monkeypatch.setattr("app.middleware.INTERNAL_SERVICE_TOKEN", "metrics-svc-token")

    fake_main = MagicMock()
    fake_main._try_legacy_unlock = MagicMock()
    monkeypatch.setitem(sys.modules, "main", fake_main)

    from app import auth
    from app.middleware import ServerAuthMiddleware

    auth.clear_session_cache()
    return ServerAuthMiddleware(app=MagicMock())


def _request(
    path: str,
    token: str = "",
    method: str = "GET",
    *,
    cookie: str = "",
) -> MagicMock:
    req = MagicMock()
    req.method = method
    req.url.path = path
    headers = {}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    req.headers = headers
    req.cookies = {"max_token": cookie} if cookie else {}
    req.client = MagicMock()
    req.client.host = "10.0.0.1"
    return req


def test_metrics_requires_service_token(auth_mw):
    async def run():
        call_next = AsyncMock(return_value="metrics-body")
        resp = await auth_mw.dispatch(_request("/metrics"), call_next)
        assert resp.status_code == 401
        call_next.assert_not_awaited()

    asyncio.run(run())


def test_metrics_rejects_user_jwt(auth_mw):
    payload = {"sub": "1", "role": "admin", "tenant_id": None, "jti": "x", "tv": 0}

    async def run():
        call_next = AsyncMock(return_value="metrics-body")
        with patch("app.middleware.decode_token", return_value=payload):
            resp = await auth_mw.dispatch(
                _request("/metrics", token="user-jwt"), call_next
            )
        assert resp.status_code == 401
        call_next.assert_not_awaited()

    asyncio.run(run())


def test_metrics_allows_internal_service_token(auth_mw):
    async def run():
        call_next = AsyncMock(return_value="metrics-body")
        resp = await auth_mw.dispatch(
            _request("/metrics", token="metrics-svc-token"), call_next
        )
        assert resp == "metrics-body"
        call_next.assert_awaited_once()

    asyncio.run(run())


def test_token_version_mismatch_rejected(auth_mw):
    payload = {"sub": "1", "role": "user", "tenant_id": 2, "jti": "x", "tv": 0}
    user = {"id": 1, "role": "user", "tenant_id": 2}
    tenant = {"id": 2, "token_version": 1}

    async def run():
        call_next = AsyncMock(return_value="ok")
        with patch("app.middleware.decode_token", return_value=payload), patch(
            "app.middleware.db_pg.get_user_by_id", return_value=user
        ), patch("app.middleware.db_pg.get_tenant", return_value=tenant), patch(
            "app.middleware.db_pg.is_token_revoked", return_value=False
        ), patch(
            "app.middleware.db_pg.subscription_active", return_value=True
        ):
            resp = await auth_mw.dispatch(
                _request("/api/status", cookie="jwt"), call_next
            )
            assert resp.status_code == 401
            assert "отозвана" in resp.body.decode()
            call_next.assert_not_awaited()

    asyncio.run(run())


def test_create_token_includes_tv(monkeypatch):
    monkeypatch.setattr(
        "app.auth.db_pg.get_tenant_token_version", lambda tid: 3 if tid == 5 else 0
    )
    from app import auth

    token = auth.create_token(1, tenant_id=5, role="user")
    payload = auth.decode_token(token)
    assert payload["tv"] == 3


def test_bump_tenant_token_version_increments():
    from app import db_pg

    cur = MagicMock()
    cur.fetchone.return_value = {"token_version": 2}
    ctx = MagicMock()
    ctx.__enter__ = MagicMock(return_value=cur)
    ctx.__exit__ = MagicMock(return_value=False)

    with patch.object(db_pg, "_cursor", return_value=ctx):
        assert db_pg.bump_tenant_token_version(1) == 2


def test_ws_auth_rejects_missing_type():
    from app.routes_monitor import _authenticate_ws

    ws = AsyncMock()
    ws.cookies = {}
    ws.receive_text = AsyncMock(return_value=json.dumps({"token": "x"}))

    async def run():
        ok = await _authenticate_ws(ws)
        assert ok is False

    asyncio.run(run())


def test_ws_auth_accepts_valid_cookie(monkeypatch):
    from app.routes_monitor import _authenticate_ws

    monkeypatch.setattr("app.config.is_server_mode", lambda: True)
    payload = {"sub": "1", "role": "user", "tenant_id": 2, "jti": "j", "tv": 0}

    ws = AsyncMock()
    ws.cookies = {"max_token": "good-jwt"}
    ws.receive_text = AsyncMock(return_value=json.dumps({"type": "auth"}))

    fake_main = MagicMock()
    fake_main._try_legacy_unlock = MagicMock()
    monkeypatch.setitem(sys.modules, "main", fake_main)

    async def run():
        with patch("app.auth.decode_token", return_value=payload) as dec, patch(
            "app.auth.cached_validate_token_session", return_value=None
        ), patch("app.tenant.set_context") as set_ctx:
            ok = await _authenticate_ws(ws)
            assert ok is True
            dec.assert_called_once_with("good-jwt")
            set_ctx.assert_called_once()

    asyncio.run(run())


def test_ws_auth_cookie_wins_over_json_token(monkeypatch):
    from app.routes_monitor import _authenticate_ws

    monkeypatch.setattr("app.config.is_server_mode", lambda: True)
    payload = {"sub": "1", "role": "user", "tenant_id": 2, "jti": "j", "tv": 0}

    async def json_only_fails():
        ws = AsyncMock()
        ws.cookies = {}
        ws.receive_text = AsyncMock(
            return_value=json.dumps({"type": "auth", "token": "json-jwt"})
        )
        with patch("app.auth.decode_token") as dec:
            ok = await _authenticate_ws(ws)
            assert ok is False
            dec.assert_not_called()

    async def cookie_still_works():
        ws = AsyncMock()
        ws.cookies = {"max_token": "cookie-jwt"}
        ws.receive_text = AsyncMock(
            return_value=json.dumps({"type": "auth", "token": "json-jwt"})
        )
        with patch("app.auth.decode_token", return_value=payload) as dec, patch(
            "app.auth.cached_validate_token_session", return_value=None
        ), patch("app.tenant.set_context"):
            ok = await _authenticate_ws(ws)
            assert ok is True
            dec.assert_called_once_with("cookie-jwt")

    asyncio.run(json_only_fails())
    asyncio.run(cookie_still_works())


def test_ws_auth_rejects_server_without_cookie_or_token(monkeypatch):
    from app.routes_monitor import _authenticate_ws

    monkeypatch.setattr("app.config.is_server_mode", lambda: True)
    ws = AsyncMock()
    ws.cookies = {}
    ws.receive_text = AsyncMock(return_value=json.dumps({"type": "auth"}))

    async def run():
        ok = await _authenticate_ws(ws)
        assert ok is False

    asyncio.run(run())


def test_ws_cookie_session_ok_valid(monkeypatch):
    from app.routes_monitor import _ws_cookie_session_ok

    monkeypatch.setattr("app.config.is_server_mode", lambda: True)
    ws = MagicMock()
    ws.cookies = {"max_token": "good-jwt"}
    payload = {"sub": "1", "role": "user", "tenant_id": 2, "jti": "j", "tv": 0}
    with patch("app.auth.decode_token", return_value=payload) as dec, patch(
        "app.auth.cached_validate_token_session", return_value=None
    ) as val:
        assert _ws_cookie_session_ok(ws) is True
        dec.assert_called_once_with("good-jwt")
        val.assert_called_once_with(payload)


def test_ws_cookie_session_ok_revoked_or_missing(monkeypatch):
    from app.routes_monitor import _ws_cookie_session_ok

    monkeypatch.setattr("app.config.is_server_mode", lambda: True)
    ws = MagicMock()
    ws.cookies = {"max_token": "stale-jwt"}
    payload = {"sub": "1", "jti": "j"}
    with patch("app.auth.decode_token", return_value=payload), patch(
        "app.auth.cached_validate_token_session", return_value="Сессия отозвана"
    ):
        assert _ws_cookie_session_ok(ws) is False

    ws.cookies = {}
    assert _ws_cookie_session_ok(ws) is False

    import jwt

    ws.cookies = {"max_token": "bad"}
    with patch("app.auth.decode_token", side_effect=jwt.InvalidTokenError("x")):
        assert _ws_cookie_session_ok(ws) is False


def test_ws_cookie_session_ok_desktop_skips(monkeypatch):
    from app.routes_monitor import _ws_cookie_session_ok

    monkeypatch.setattr("app.config.is_server_mode", lambda: False)
    ws = MagicMock()
    ws.cookies = {}
    assert _ws_cookie_session_ok(ws) is True


def _health_request(*, authorization: str = "", cookie: str = "") -> MagicMock:
    req = MagicMock()
    headers = {}
    if authorization:
        headers["Authorization"] = authorization
    req.headers = headers
    req.cookies = {"max_token": cookie} if cookie else {}
    return req


def _patch_health_runtime(monkeypatch):
    fake = MagicMock()
    fake._is_server_mode.return_value = True
    fake.vault_status.return_value = {
        "unlocked": True,
        "needs_setup": False,
        "legacy": False,
    }
    fake.RUNTIME.worker_busy.return_value = True
    fake._pool_size.return_value = 1
    fake.DB_BACKEND = "pg"
    fake.REDIS_URL = ""
    fake.USE_CELERY = False
    fake._app_started_at = None
    fake.APP_VERSION = "test"
    fake._circuit_open_count.return_value = 0
    monkeypatch.setattr("app.routes_monitor.m", fake)
    return fake


def test_health_junk_authorization_stays_thin(monkeypatch):
    from app.routes_monitor import health

    _patch_health_runtime(monkeypatch)

    async def run():
        with patch("app.db_pg.ping", return_value=True):
            body = await health(_health_request(authorization="x"))
        assert body["ok"] is True
        assert body["db_ok"] is True
        assert "server_mode" in body
        assert "worker_running" not in body

    asyncio.run(run())


def test_health_missing_token_stays_thin(monkeypatch):
    from app.routes_monitor import health

    _patch_health_runtime(monkeypatch)

    async def run():
        with patch("app.db_pg.ping", return_value=True):
            body = await health(_health_request())
        assert "worker_running" not in body
        assert set(body) == {"ok", "db_ok", "server_mode"}

    asyncio.run(run())


def test_health_valid_cookie_or_service_token_gets_extras(monkeypatch):
    from app.routes_monitor import health

    _patch_health_runtime(monkeypatch)
    monkeypatch.setattr("app.config.INTERNAL_SERVICE_TOKEN", "health-svc-token")
    payload = {"sub": "1", "role": "user", "tenant_id": 2, "jti": "j", "tv": 0}

    async def run():
        with patch("app.db_pg.ping", return_value=True), patch(
            "app.db_pg.ping_latency_ms", return_value=1.0
        ), patch("app.db_pg.count_subscriptions_expiring", return_value=0):
            svc = await health(
                _health_request(authorization="Bearer health-svc-token")
            )
            assert svc["worker_running"] is True

            with patch("app.auth.decode_token", return_value=payload), patch(
                "app.auth.cached_validate_token_session", return_value=None
            ):
                cookie = await health(_health_request(cookie="good-jwt"))
            assert cookie["worker_running"] is True

            junk_cookie = await health(_health_request(cookie="junk"))
            assert "worker_running" not in junk_cookie

    asyncio.run(run())


def test_require_production_secrets_rejects_change_me(monkeypatch):
    monkeypatch.delenv("MAX_TEST", raising=False)
    monkeypatch.setenv("JWT_SECRET", "change-me-random-64-chars-xxxxxxxxxxx")
    monkeypatch.setenv("ADMIN_PASSWORD", "AdminPass123!")
    monkeypatch.setenv("INTERNAL_SERVICE_TOKEN", "real-service-token")
    monkeypatch.setattr("app.config.is_server_mode", lambda: True)
    from app.config import require_production_secrets

    with pytest.raises(RuntimeError, match="JWT_SECRET"):
        require_production_secrets()


def test_require_production_secrets_skipped_when_max_test(monkeypatch):
    monkeypatch.setenv("MAX_TEST", "1")
    monkeypatch.setenv("JWT_SECRET", "change-me-random-64-chars-xxxxxxxxxxx")
    monkeypatch.setenv("ADMIN_PASSWORD", "change-me-admin")
    monkeypatch.setenv("INTERNAL_SERVICE_TOKEN", "change-me-svc")
    monkeypatch.setattr("app.config.is_server_mode", lambda: True)
    from app.config import require_production_secrets

    require_production_secrets()


def test_user_jwt_bearer_without_cookie_401(auth_mw):
    async def run():
        call_next = AsyncMock(return_value="ok")
        resp = await auth_mw.dispatch(_request("/api/status", token="user-jwt"), call_next)
        assert resp.status_code == 401
        call_next.assert_not_awaited()

    asyncio.run(run())


def test_user_jwt_cookie_used_not_bearer(auth_mw):
    payload = {"sub": "1", "role": "user", "tenant_id": 2, "jti": "x", "tv": 0}

    async def run():
        call_next = AsyncMock(return_value="ok")
        with patch("app.middleware.decode_token", return_value=payload) as dec, patch(
            "app.middleware.cached_validate_token_session", return_value=None
        ):
            resp = await auth_mw.dispatch(
                _request("/api/status", token="attacker-jwt", cookie="cookie-jwt"),
                call_next,
            )
            assert resp == "ok"
            dec.assert_called_once_with("cookie-jwt")

    asyncio.run(run())
