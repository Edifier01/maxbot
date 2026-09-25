from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

import pytest
from cryptography.fernet import Fernet
from fastapi import HTTPException
from types import SimpleNamespace

from app.repositories.onboarding import OnboardingRepository, token_hash


def _db(tmp_path: Path):
    import sqlite3

    conn = sqlite3.connect(tmp_path / "tenant.db", check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.executescript(
        """
        CREATE TABLE groups (id INTEGER PRIMARY KEY, name TEXT, invite_link TEXT,
          max_chat_id TEXT, destination_verified INTEGER, is_active INTEGER,
          destination_revision INTEGER DEFAULT 1, proxy TEXT DEFAULT '');
        CREATE TABLE profiles (id INTEGER PRIMARY KEY, phone TEXT, label TEXT,
          status TEXT DEFAULT 'active');
        CREATE TABLE group_profiles (group_id INTEGER, profile_id INTEGER,
          order_index INTEGER, is_enabled INTEGER DEFAULT 1,
          UNIQUE(group_id, profile_id));
        INSERT INTO groups VALUES (1, 'Тест', 'https://max.ru/invite', 'chat-1', 1, 1, 1, '');
        """
    )
    OnboardingRepository(conn).ensure_schema()
    return conn


def test_public_join_session_uses_signed_cookie_and_token_locator(monkeypatch, tmp_path):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from app import db_pg
    from app.middleware import ServerAuthMiddleware
    from app.routes_onboarding import router
    from app.tenant_sqlite import tenant_conn

    conn = _db(tmp_path)
    token = "a" * 43
    digest = token_hash(token)
    expiry = datetime.now(timezone.utc).replace(microsecond=0)
    repo = OnboardingRepository(conn)
    repo.create_invite(1, digest, "ciphertext", expiry.isoformat(),
                       (expiry.replace(day=min(expiry.day + 7, 28))).isoformat(), None)
    monkeypatch.setattr(db_pg, "get_onboarding_invite_tenant", lambda _hash: 44)
    monkeypatch.setattr("app.routes_onboarding.tenant_conn", lambda tid: _conn_context(conn)(tid))
    monkeypatch.setattr("app.routes_onboarding.JWT_SECRET", "x" * 48)
    monkeypatch.setattr("app.routes_onboarding.is_server_mode", lambda: True)
    monkeypatch.setattr("app.auth_rate_limit.check_auth_rate_limit", lambda *_args: True)

    app = FastAPI()
    app.include_router(router)
    app.add_middleware(ServerAuthMiddleware)
    client = TestClient(app, base_url="https://example.test")
    response = client.get(f"/join/{token}", follow_redirects=False)
    assert response.status_code == 303
    assert response.headers["location"] == "/join"
    assert "HttpOnly" in response.headers["set-cookie"]
    assert "Secure" in response.headers["set-cookie"]
    assert token not in response.headers["set-cookie"]
    status = client.get("/api/public/onboarding/status")
    assert status.status_code == 200
    assert status.json()["state"] == "created"
    assert "no-store" in status.headers["cache-control"].lower()


def test_public_invite_exchange_is_rate_limited_by_ip(monkeypatch):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from app.middleware import ServerAuthMiddleware
    from app.routes_onboarding import router

    monkeypatch.setattr("app.routes_onboarding.is_server_mode", lambda: True)
    monkeypatch.setattr("app.auth_rate_limit.check_auth_rate_limit", lambda *_args: False)
    app = FastAPI()
    app.include_router(router)
    app.add_middleware(ServerAuthMiddleware)
    response = TestClient(app, base_url="https://example.test").get(f"/join/{'b' * 43}")
    assert response.status_code == 429


def test_expired_sessions_are_deleted_with_temporary_identity_data(monkeypatch, tmp_path):
    from contextlib import contextmanager
    from app import routes_onboarding as onboarding

    conn = _db(tmp_path)
    repo = OnboardingRepository(conn)
    invite_id = repo.create_invite(1, "hash", "cipher", "2026-09-01T00:00:00+00:00", "2026-09-02T00:00:00+00:00", None)
    conn.execute(
        "INSERT INTO onboarding_sessions (id, session_token_hash, invite_id, phone, full_name, consent_at, state, created_at, updated_at, expires_at, max_user_id) "
        "VALUES ('expired-session', 'session-hash', ?, '+79991234567', 'Иван Иванов', '2026-09-01', 'waiting_membership', '2026-09-01', '2026-09-01', '2026-09-02T00:00:00+00:00', '123')",
        (invite_id,),
    )
    conn.commit()
    data_root = tmp_path / "data"
    session_dir = data_root / "tenants" / "44" / "sessions" / "onboarding" / "expired-session"
    session_dir.mkdir(parents=True)

    @contextmanager
    def conn_context():
        yield conn

    monkeypatch.setattr(onboarding.m, "_resolve_data_root", lambda: data_root)
    monkeypatch.setattr(onboarding.m, "_conn", conn_context)
    onboarding.recover_and_cleanup_onboarding()
    assert conn.execute("SELECT 1 FROM onboarding_sessions WHERE id='expired-session'").fetchone() is None
    assert not session_dir.exists()


def test_runtime_cleanup_drops_expired_session_state(monkeypatch, tmp_path):
    import asyncio
    from contextlib import contextmanager
    from app import routes_onboarding as onboarding

    conn = _db(tmp_path)
    repo = OnboardingRepository(conn)
    invite_id = repo.create_invite(1, "hash", "cipher", "2026-09-01T00:00:00+00:00", "2026-09-02T00:00:00+00:00", None)
    conn.execute(
        "INSERT INTO onboarding_sessions (id, session_token_hash, invite_id, state, created_at, updated_at, expires_at) "
        "VALUES ('stale-runtime', 'session-hash', ?, 'expired', '2026-09-01', '2026-09-01', '2026-09-02T00:00:00+00:00')",
        (invite_id,),
    )
    conn.commit()

    @contextmanager
    def conn_context():
        yield conn

    monkeypatch.setattr(onboarding.m, "_conn", conn_context)
    onboarding._AUTH_RUNTIME["stale-runtime"] = {"tenant_id": 44}
    onboarding._ONBOARDING_LOCKS["stale-runtime"] = asyncio.Lock()
    try:
        asyncio.run(onboarding._prune_onboarding_runtime())
        assert "stale-runtime" not in onboarding._AUTH_RUNTIME
        assert "stale-runtime" not in onboarding._ONBOARDING_LOCKS
    finally:
        onboarding._AUTH_RUNTIME.pop("stale-runtime", None)
        onboarding._AUTH_TASKS.pop("stale-runtime", None)
        onboarding._ONBOARDING_LOCKS.pop("stale-runtime", None)


def _conn_context(conn):
    from contextlib import contextmanager

    @contextmanager
    def context(_tenant_id):
        yield conn

    return context


def test_new_max_account_is_never_registered_automatically(monkeypatch):
    import asyncio
    from app import routes_onboarding as onboarding

    calls = []
    class Gateway:
        def _require(self, action):
            calls.append(str(action))

    class Auth:
        async def request_code(self, phone):
            assert phone == "+79991234567"
            return SimpleNamespace(token="opaque")

        async def send_code(self, _token, code):
            assert code == "12345"
            return SimpleNamespace(login_token=None, password_challenge=None, register_token="register-token")

        async def confirm_registration(self, **_kwargs):
            raise AssertionError("onboarding must not register accounts")

    app = SimpleNamespace(config=SimpleNamespace(phone="+79991234567"), api=SimpleNamespace(auth=Auth()))
    runtime = {"tenant_id": 2, "codes": asyncio.Queue(), "passwords": asyncio.Queue()}
    runtime["codes"].put_nowait("12345")
    monkeypatch.setattr(onboarding.m, "_max_gateway", lambda _app: Gateway())
    monkeypatch.setattr(onboarding, "_runtime_state", lambda *_args, **_kwargs: None)

    async def run():
        flow = onboarding._OnboardingSmsAuthFlow("session", runtime)
        with pytest.raises(RuntimeError, match="MAX_ACCOUNT_REGISTRATION_REQUIRED"):
            await flow.authenticate(app)

    asyncio.run(run())
    assert "request_otp" in calls
    assert "verify_auth" in calls


def test_onboarding_auth_uses_group_proxy(monkeypatch, tmp_path):
    import asyncio
    from app import routes_onboarding as onboarding

    conn = _db(tmp_path)
    conn.execute("UPDATE groups SET proxy='socks5://proxy.example:1080' WHERE id=1")
    invite_id = OnboardingRepository(conn).create_invite(
        1, "proxy-test-hash", "cipher", "2026-09-25T00:00:00+00:00",
        "2026-10-01T00:00:00+00:00", None,
    )
    conn.execute(
        "INSERT INTO onboarding_sessions (id, session_token_hash, invite_id, phone, state, created_at, updated_at, expires_at) "
        "VALUES ('proxy-test', 'secret-hash', ?, '+79991234567', 'requesting_code', '2026-09-25', '2026-09-25', '2026-10-01')",
        (invite_id,),
    )
    conn.commit()
    monkeypatch.setattr(onboarding, "tenant_conn", _conn_context(conn))
    monkeypatch.setattr(onboarding, "_onboarding_dir", lambda *_args: tmp_path)
    monkeypatch.setattr(onboarding.m, "_ensure_vault_unlocked", lambda: None)
    captured = []

    def build_client(**kwargs):
        captured.append(kwargs)
        raise RuntimeError("stop before network")

    monkeypatch.setattr(onboarding.m, "_build_pymax_client", build_client)
    onboarding._AUTH_RUNTIME["proxy-test"] = {"tenant_id": 44, "codes": asyncio.Queue(), "passwords": asyncio.Queue()}
    try:
        asyncio.run(onboarding._run_onboarding_auth(44, "proxy-test", "+79991234567"))
    finally:
        onboarding._AUTH_RUNTIME.pop("proxy-test", None)
    assert captured[0]["proxy"] == "socks5://proxy.example:1080"


def test_onboarding_keeps_proxy_after_creating_profile(monkeypatch, tmp_path):
    from app import routes_onboarding as onboarding
    from app.repositories.weekly_schedule import WeeklyScheduleRepository

    conn = _db(tmp_path)
    conn.execute(
        "UPDATE groups SET proxy='socks5://first.example:1080;socks5://second.example:1080' WHERE id=1"
    )
    invite_id = OnboardingRepository(conn).create_invite(
        1, "stable-proxy-hash", "cipher", "2026-09-25T00:00:00+00:00",
        "2026-10-01T00:00:00+00:00", None,
    )
    conn.execute(
        "INSERT INTO onboarding_sessions (id, session_token_hash, invite_id, phone, state, created_at, updated_at, expires_at) "
        "VALUES ('stable-proxy', 'secret-hash', ?, '+79991234567', 'waiting_membership', '2026-09-25', '2026-09-25', '2026-10-01')",
        (invite_id,),
    )
    schedule = WeeklyScheduleRepository(conn)
    schedule.ensure_schema()
    conn.execute("INSERT INTO profiles (id, phone, label) VALUES (99, '+79990000099', 'other')")
    conn.commit()
    schedule.assign_profile(99, 1)
    monkeypatch.setattr(onboarding, "tenant_conn", _conn_context(conn))

    first_route = onboarding._onboarding_proxy(44, "stable-proxy", "+79991234567")
    conn.execute("INSERT INTO profiles (id, phone, label) VALUES (100, '+79991234567', 'new')")
    conn.commit()
    saved_route = onboarding._onboarding_proxy(44, "stable-proxy", "+79991234567")

    assert first_route == "socks5://first.example:1080"
    assert saved_route == first_route
    assert schedule.assigned_proxy_url(100, 1) == first_route


def test_onboarding_reports_actionable_auth_failure_codes():
    from app import routes_onboarding as onboarding
    from app.platform_policy import PlatformAuthorizationHold
    from app.recovery_hold import RecoveryHoldActive

    assert onboarding._onboarding_failure_code(RuntimeError("PROXY_ASSIGNMENT_REQUIRED")) == "PROXY_ASSIGNMENT_REQUIRED"
    assert onboarding._onboarding_failure_code(PlatformAuthorizationHold("record_missing")) == "MAX_AUTH_UNAVAILABLE"
    assert onboarding._onboarding_failure_code(RecoveryHoldActive("recovery_hold_active")) == "MAX_AUTH_UNAVAILABLE"
    assert onboarding._onboarding_failure_code(RuntimeError("unknown private detail")) == "MAX_AUTH_FAILED"


def test_membership_proof_fails_closed_without_status_and_join_time():
    from app.routes_onboarding import _member_proof

    assert not _member_proof(SimpleNamespace(id=77, status="member", join_time=0), "77")
    assert not _member_proof(SimpleNamespace(id=77, status="pending", join_time=123), "77")
    assert not _member_proof(SimpleNamespace(id=78, status="member", join_time=123), "77")
    assert _member_proof(SimpleNamespace(id=77, status="member", join_time=123), "77")


def test_invite_token_is_redacted_from_access_log_path():
    import logging
    from app.middleware import UvicornInvitePathRedactor, _safe_log_path

    assert _safe_log_path("/join/super-secret-token") == "/join/[redacted]"
    record = logging.LogRecord("uvicorn.access", logging.INFO, "", 0, "%s %s %s %s %s", ("127.0.0.1", "GET", "/join/super-secret-token", "1.1", 303), None)
    assert UvicornInvitePathRedactor().filter(record)
    assert "super-secret-token" not in record.getMessage()


def test_owner_invite_mutations_require_origin(monkeypatch):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from app.middleware import ServerAuthMiddleware

    monkeypatch.setattr("app.middleware.is_server_mode", lambda: True)
    app = FastAPI()
    app.add_middleware(ServerAuthMiddleware)
    client = TestClient(app, base_url="https://example.test")
    response = client.post("/api/groups/1/onboarding-invite", json={"expires_days": 7})
    assert response.status_code == 403
    response = client.post(
        "/api/groups/1/onboarding-invite", json={"expires_days": 7},
        headers={"Origin": "https://attacker.test"},
    )
    assert response.status_code == 403


def test_owner_can_issue_rotate_and_revoke_encrypted_invite(monkeypatch, tmp_path):
    import asyncio
    from contextlib import contextmanager
    from app import db_pg
    from app import routes_onboarding as onboarding
    from app.tenant import tenant_scope
    from cryptography.fernet import Fernet

    conn = _db(tmp_path)

    @contextmanager
    def conn_context():
        yield conn

    monkeypatch.setattr(onboarding.m, "_conn", conn_context)
    monkeypatch.setattr(onboarding.m, "_resolve_data_dir", lambda: tmp_path)
    fernet = Fernet(Fernet.generate_key())
    monkeypatch.setattr(onboarding.vault, "get_fernet", lambda _path: fernet)
    monkeypatch.setattr(onboarding, "is_server_mode", lambda: True)
    monkeypatch.setenv("PUBLIC_BASE_URL", "https://example.test")
    registered = []
    deleted = []
    monkeypatch.setattr(db_pg, "register_onboarding_invite", lambda *args: registered.append(args))
    monkeypatch.setattr(db_pg, "delete_onboarding_invite_locator", lambda digest: deleted.append(digest) or True)

    async def run():
        with tenant_scope(tenant_id=44, role="admin"):
            created = await onboarding.create_onboarding_invite(1, onboarding.InviteCreateIn(expires_days=3, max_uses=2))
            assert created["active"] and created["max_uses"] == 2
            stored = OnboardingRepository(conn).get_active_invite(1)
            assert stored["token_hash"] not in created["url"]
            assert created["url"].split("/")[-1] not in str(dict(stored))
            assert fernet.decrypt(stored["token_ciphertext"].encode()).decode() == created["url"].split("/")[-1]
            view = await onboarding.get_onboarding_invite(1)
            assert view["url"] == created["url"]
            deleted_result = await onboarding.delete_onboarding_invite(1)
            assert deleted_result["revoked"] is True
        assert len(registered) == 1
        assert len(deleted) == 1

    asyncio.run(run())


def test_group_panel_exposes_self_service_onboarding_link():
    panel_js = (Path(__file__).parents[1] / "static" / "js" / "index.js").read_text(encoding="utf-8")
    join_page = (Path(__file__).parents[1] / "static" / "join.html").read_text(encoding="utf-8")
    join_js = (Path(__file__).parents[1] / "static" / "js" / "join.js").read_text(encoding="utf-8")

    assert "Приглашение пользователей" in panel_js
    assert "Ссылка для подключения аккаунтов" in panel_js
    assert "onboarding-invite-copy" in panel_js
    assert "Открыть приглашение MAX" in join_page
    assert "Разрешаю commentbot отправлять сообщения от имени моего MAX-аккаунта" in join_page
    assert "назначенный мне день недели" in join_js
    assert "отозвать согласие, отключив аккаунт" in join_js
    assert "state.group_name" in join_js


def test_changing_max_invite_link_revokes_self_service_onboarding_invite(monkeypatch, tmp_path):
    from contextlib import contextmanager
    from app import db_pg, routes_groups
    from app.routes_models import GroupPatchIn

    conn = _db(tmp_path)
    onboarding = OnboardingRepository(conn)
    onboarding.create_invite(
        1, "invite-hash", "encrypted-token", "2026-09-24T00:00:00+00:00",
        "2026-10-01T00:00:00+00:00", None,
    )
    deleted = []

    @contextmanager
    def conn_context():
        yield conn

    monkeypatch.setattr(routes_groups.m, "_conn", conn_context)
    monkeypatch.setattr(routes_groups.m, "_require_worker_idle", lambda: None)
    monkeypatch.setattr(routes_groups, "is_server_mode", lambda: True, raising=False)
    monkeypatch.setattr(routes_groups, "is_cabinet_user", lambda: False)
    monkeypatch.setattr(db_pg, "delete_onboarding_invite_locator", lambda digest: deleted.append(digest))

    import asyncio

    asyncio.run(routes_groups.patch_group(1, GroupPatchIn(invite_link="https://max.ru/join/new")))

    assert OnboardingRepository(conn).get_active_invite(1) is None
    assert deleted == ["invite-hash"]


@pytest.mark.parametrize("mutation", ["destination", "disable"])
def test_destination_change_or_group_disable_revokes_onboarding_invite(
    monkeypatch, tmp_path, mutation
):
    from contextlib import contextmanager
    from app import db_pg, routes_groups
    from app.routes_models import DestinationVerifyIn, GroupPatchIn

    conn = _db(tmp_path)
    onboarding = OnboardingRepository(conn)
    onboarding.create_invite(
        1, "invite-hash", "encrypted-token", "2026-09-24T00:00:00+00:00",
        "2026-10-01T00:00:00+00:00", None,
    )
    deleted = []

    @contextmanager
    def conn_context():
        yield conn

    monkeypatch.setattr(routes_groups.m, "_conn", conn_context)
    monkeypatch.setattr(routes_groups.m, "_require_worker_idle", lambda: None)
    monkeypatch.setattr(routes_groups, "is_server_mode", lambda: True, raising=False)
    monkeypatch.setattr(routes_groups, "is_cabinet_user", lambda: False)
    monkeypatch.setattr(db_pg, "delete_onboarding_invite_locator", lambda digest: deleted.append(digest))

    import asyncio

    if mutation == "destination":
        asyncio.run(
            routes_groups.verify_group_destination(
                1, DestinationVerifyIn(chat_id="chat-2", revision=1)
            )
        )
    else:
        asyncio.run(routes_groups.patch_group(1, GroupPatchIn(is_active=0)))

    assert OnboardingRepository(conn).get_active_invite(1) is None
    assert deleted == ["invite-hash"]
