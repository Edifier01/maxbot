"""T07 canonical auth endpoints and session-preservation boundaries."""

from __future__ import annotations

import asyncio
from contextlib import closing
import importlib
import random
import sqlite3
import ssl
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import pytest


def _setup_db(tmp_path, monkeypatch):
    monkeypatch.setenv("MAX_TEST", "1")
    monkeypatch.setenv("MAX_SERVER_MODE", "0")
    import app.config as cfg
    import app.sqlite_backend as sqlite_backend

    importlib.reload(cfg)
    import main as m

    importlib.reload(m)
    sqlite_backend.reset_connections()
    monkeypatch.setattr(m, "ROOT", tmp_path)
    m._refresh_data_paths()
    m.reset_test_runtime()
    m.init_db()
    with m._conn() as connection:
        connection.execute(
            "INSERT INTO profiles (phone, label, status) VALUES (?, ?, ?)",
            ("+79990015551", "auth", m.ProfileStatus.PENDING),
        )
        profile_id = connection.execute(
            "SELECT id FROM profiles WHERE phone=?", ("+79990015551",)
        ).fetchone()["id"]
    return m, int(profile_id)


def _cleanup(m, monkeypatch) -> None:
    from app import sqlite_backend

    sqlite_backend.reset_connections()
    monkeypatch.undo()
    import app.config as cfg

    importlib.reload(cfg)
    importlib.reload(m)


def _attach_test_proxy(m, profile_id: int, group_id: int = 10) -> None:
    with m._conn() as connection:
        connection.execute(
            "INSERT INTO groups (id, name, proxy) VALUES (?, 'fixture', ?)",
            (group_id, "socks5://proxy.example:1080"),
        )
        connection.execute(
            "INSERT INTO group_profiles (group_id, profile_id) VALUES (?, ?)",
            (group_id, profile_id),
        )
        from app.repositories.weekly_schedule import WeeklyScheduleRepository

        WeeklyScheduleRepository(connection).assign_profile(profile_id, group_id)


def test_canonical_attempt_code_and_password_endpoints_are_guarded(
    tmp_path, monkeypatch
):
    m, profile_id = _setup_db(tmp_path, monkeypatch)
    try:
        from app.routes_models import AuthCodeIn, AuthPasswordIn
        from app.routes_profiles import (
            get_auth_attempt,
            submit_auth_attempt_code,
            submit_auth_attempt_password,
        )

        attempt, _ = m._start_auth_attempt(
            profile_id, group_id=None, fresh=False, request_id="canonical-start"
        )
        waiting_code = m._auth_attempts().waiting_code(
            "local", profile_id, attempt_id=attempt.attempt_id
        )
        m._persist_auth_attempt(waiting_code)
        m._sync_auth_attempt_view(waiting_code)

        code_result = asyncio.run(
            submit_auth_attempt_code(
                profile_id,
                attempt.attempt_id,
                AuthCodeIn(
                    code="123456",
                    revision=waiting_code.revision,
                    request_id="canonical-code",
                ),
            )
        )
        assert code_result["auth_step"] == "verifying_sms"
        assert m._auth_sessions[m._auth_session_key(profile_id)]["sms_q"].get_nowait() == (
            "123456"
        )

        waiting_password = m._auth_attempts().waiting_password(
            "local", profile_id, attempt_id=attempt.attempt_id, hint="hint"
        )
        m._persist_auth_attempt(waiting_password)
        m._sync_auth_attempt_view(waiting_password)
        password_result = asyncio.run(
            submit_auth_attempt_password(
                profile_id,
                attempt.attempt_id,
                AuthPasswordIn(
                    password="  exact password  ",
                    revision=waiting_password.revision,
                    request_id="canonical-password",
                ),
            )
        )
        assert password_result["auth_step"] == "verifying_password"
        assert m._auth_sessions[m._auth_session_key(profile_id)]["pwd_q"].get_nowait() == (
            "  exact password  "
        )

        safe = asyncio.run(get_auth_attempt(profile_id, attempt.attempt_id))
        assert "exact password" not in repr(safe)
        assert "123456" not in repr(safe)
    finally:
        _cleanup(m, monkeypatch)


def test_expired_attempt_input_cannot_enter_new_stage_and_password_receipt_is_safe(
    tmp_path, monkeypatch
):
    m, profile_id = _setup_db(tmp_path, monkeypatch)
    try:
        from fastapi import HTTPException
        from app.routes_models import AuthCodeIn, AuthPasswordIn
        from app.routes_profiles import (
            submit_auth_attempt_code,
            submit_auth_attempt_password,
        )
        from app.services.auth_attempts import AuthAttemptStore

        now = [datetime(2026, 9, 23, 10, 0, tzinfo=UTC)]
        store = AuthAttemptStore(clock=lambda: now[0])
        monkeypatch.setattr(m, "_auth_attempts", lambda: store)
        m._ensure_auth_session(profile_id)

        old, _ = m._start_auth_attempt(
            profile_id, group_id=None, fresh=True, request_id="old-attempt-start"
        )
        old_waiting_code = m._mark_auth_waiting_code(profile_id)
        assert old_waiting_code is not None
        now[0] = old_waiting_code.stage_deadline_at + timedelta(seconds=1)

        current, _ = m._start_auth_attempt(
            profile_id, group_id=None, fresh=True, request_id="new-attempt-start"
        )
        current_waiting_code = m._mark_auth_waiting_code(profile_id)
        assert current_waiting_code is not None
        current_verifying_code = asyncio.run(
            submit_auth_attempt_code(
                profile_id,
                current.attempt_id,
                AuthCodeIn(
                    code="654321",
                    revision=current_waiting_code.revision,
                    request_id="new-attempt-code",
                ),
            )
        )
        current_waiting_password = m._mark_auth_waiting_password(
            profile_id, "fixture-password-challenge"
        )
        assert current_verifying_code["auth_stage"] == "verifying_code"
        assert current_waiting_password is not None
        assert current_waiting_password.stage == "waiting_password"

        with pytest.raises(HTTPException) as stale:
            asyncio.run(
                submit_auth_attempt_code(
                    profile_id,
                    old.attempt_id,
                    AuthCodeIn(
                        code="123456",
                        revision=old_waiting_code.revision,
                        request_id="old-attempt-code",
                    ),
                )
            )
        assert stale.value.status_code == 410
        auth_session = m._auth_sessions[m._auth_session_key(profile_id)]
        assert auth_session["sms_q"].get_nowait() == "654321"
        assert auth_session["sms_q"].empty()

        password = AuthPasswordIn(
            password="  exact cloud password  ",
            revision=current_waiting_password.revision,
            request_id="new-attempt-password",
        )
        first_password = asyncio.run(
            submit_auth_attempt_password(
                profile_id, current.attempt_id, password
            )
        )
        repeated_password = asyncio.run(
            submit_auth_attempt_password(
                profile_id, current.attempt_id, password
            )
        )
        assert first_password == repeated_password
        assert first_password["auth_stage"] == "verifying_password"
        assert auth_session["pwd_q"].get_nowait() == "  exact cloud password  "
        assert auth_session["pwd_q"].empty()

        with m._conn() as connection:
            persisted = tuple(
                connection.execute(
                    "SELECT stage, auth_step, error_code FROM auth_attempts "
                    "WHERE attempt_id=?",
                    (current.attempt_id,),
                ).fetchone()
            )
            all_attempt_rows = repr(
                [tuple(row) for row in connection.execute("SELECT * FROM auth_attempts")]
            )
        assert persisted == ("verifying_password", "verifying_password", None)
        assert "exact cloud password" not in all_attempt_rows
        assert "123456" not in all_attempt_rows
        assert "654321" not in all_attempt_rows
    finally:
        _cleanup(m, monkeypatch)


def test_login_reset_preserves_session_and_explicit_delete_requires_confirmation(
    tmp_path, monkeypatch
):
    m, profile_id = _setup_db(tmp_path, monkeypatch)
    try:
        from fastapi import HTTPException
        from app.routes_models import SessionDeleteIn
        from app.routes_profiles import delete_profile_session, reset_login

        session_dir = m._session_dir(profile_id)
        retained = session_dir / "session.db.enc"
        retained.write_bytes(b"encrypted-session-fixture")

        reset_result = asyncio.run(reset_login(profile_id))
        assert reset_result["session_preserved"] is True
        assert retained.read_bytes() == b"encrypted-session-fixture"

        with pytest.raises(HTTPException):
            asyncio.run(delete_profile_session(profile_id, object()))
        assert retained.exists()

        deleted = asyncio.run(
            delete_profile_session(
                profile_id, SessionDeleteIn(confirm="DELETE_SESSION")
            )
        )
        assert deleted["session_deleted"] is True
        assert not session_dir.exists()
    finally:
        _cleanup(m, monkeypatch)


def test_fresh_login_restores_old_session_when_new_attempt_fails(tmp_path, monkeypatch):
    m, profile_id = _setup_db(tmp_path, monkeypatch)
    try:
        retained = m._session_dir(profile_id) / "session.db.enc"
        retained.write_bytes(b"old-encrypted-session")

        async def failed_client(*_args, **_kwargs):
            raise TimeoutError("fixture timeout")

        monkeypatch.setattr(m, "_with_client", failed_client)
        with pytest.raises(TimeoutError):
            asyncio.run(
                m._login_max(profile_id, "+79990015551", fresh=True)
            )
        assert retained.read_bytes() == b"old-encrypted-session"
        assert not list(retained.parent.glob("*.reauth-previous"))
    finally:
        _cleanup(m, monkeypatch)


def test_needs_reauth_starts_a_new_attempt_and_reaches_code_stage(
    tmp_path, monkeypatch
):
    m, profile_id = _setup_db(tmp_path, monkeypatch)
    try:
        from app.routes_profiles import login_profile

        with m._conn() as connection:
            connection.execute(
                "UPDATE profiles SET status=?, last_error=? WHERE id=?",
                (m.ProfileStatus.NEEDS_REAUTH, "previous login failed", profile_id),
            )
            connection.execute(
                "INSERT INTO groups (id, name, proxy, is_active) "
                "VALUES (10, 'fixture', 'socks5://proxy.example:1080', 1)"
            )
            connection.execute(
                "INSERT INTO group_profiles (group_id, profile_id, is_enabled) "
                "VALUES (10, ?, 1)",
                (profile_id,),
            )
            connection.execute(
                "INSERT INTO profile_automation_scope "
                "(profile_id, automation_group_id, consent_state, revision) "
                "VALUES (?, 10, 'active', 1)",
                (profile_id,),
            )
            from app.repositories.weekly_schedule import WeeklyScheduleRepository

            WeeklyScheduleRepository(connection).assign_profile(profile_id, 10)

        release = asyncio.Event()

        async def fake_login(profile, phone, *, fresh, group_id):
            assert profile == profile_id
            assert phone == "+79990015551"
            assert fresh is False
            assert group_id == 10
            waiting = m._mark_auth_waiting_code(profile_id)
            assert waiting is not None
            await release.wait()
            return 1001

        monkeypatch.setattr(m, "_login_max", fake_login)
        started_attempt_id = ""

        async def run() -> None:
            nonlocal started_attempt_id
            started = await login_profile(
                profile_id, fresh=False, group_id=10, request_id="needs-reauth-retry"
            )
            assert started["auth_step"] == "connecting"
            assert started["attempt_id"]
            started_attempt_id = str(started["attempt_id"])

            task = m._login_tasks[m._auth_session_key(profile_id)]
            await asyncio.sleep(0)
            current = m._current_auth_attempt(profile_id)
            assert current is not None
            assert current.attempt_id == started["attempt_id"]
            assert current.stage == "waiting_code"
            assert current.auth_step == "waiting_sms"
            with m._conn() as connection:
                row = connection.execute(
                    "SELECT status, last_error FROM profiles WHERE id=?",
                    (profile_id,),
                ).fetchone()
            assert tuple(row) == (m.ProfileStatus.NEEDS_REAUTH, "previous login failed")

            release.set()
            await task

        asyncio.run(run())
        with m._conn() as connection:
            row = connection.execute(
                "SELECT status, last_error FROM profiles WHERE id=?", (profile_id,)
            ).fetchone()
            attempt = connection.execute(
                "SELECT stage, terminal FROM auth_attempts WHERE attempt_id=?",
                (started_attempt_id,),
            ).fetchone()
        assert tuple(row) == (m.ProfileStatus.ACTIVE, "")
        assert tuple(attempt) == ("succeeded", 1)
    finally:
        _cleanup(m, monkeypatch)


def test_saved_login_failure_preserves_session_without_reauth_staging(
    tmp_path, monkeypatch
):
    m, profile_id = _setup_db(tmp_path, monkeypatch)
    try:
        retained = m._session_dir(profile_id) / "session.db.enc"
        retained.write_bytes(b"saved-session-byte-for-byte")

        async def failed_client(*_args, **_kwargs):
            raise TimeoutError("saved session transport timeout")

        monkeypatch.setattr(m, "_with_client", failed_client)
        with pytest.raises(TimeoutError, match="saved session transport timeout"):
            asyncio.run(m._login_max(profile_id, "+79990015551", fresh=False))

        assert retained.read_bytes() == b"saved-session-byte-for-byte"
        assert not list(retained.parent.glob("*.reauth-previous"))
    finally:
        _cleanup(m, monkeypatch)


@pytest.mark.parametrize(
    "failure_kind",
    ["timeout", "proxy", "tls", "local_db"],
)
def test_ordinary_login_faults_reseal_same_saved_session_without_sms_or_fresh_login(
    tmp_path, monkeypatch, failure_kind
):
    """Timeout/transport/storage faults must not replace a valid saved identity."""
    m, profile_id = _setup_db(tmp_path, monkeypatch)
    try:
        _attach_test_proxy(m, profile_id)
        from app.platform_policy import AuthorizationRecord, MaxAction, MaxTransport

        session_dir = m._session_dir(profile_id)
        session_dir.mkdir(parents=True, exist_ok=True)
        session_db = session_dir / "session.db"
        with closing(sqlite3.connect(session_db)) as connection, connection:
            connection.execute(
                "CREATE TABLE sessions ("
                "token TEXT NOT NULL PRIMARY KEY, device_id TEXT NOT NULL, "
                "phone TEXT NOT NULL, mt_instance_id TEXT NOT NULL DEFAULT '', "
                "chats_sync INTEGER NOT NULL DEFAULT -1, "
                "contacts_sync INTEGER NOT NULL DEFAULT -1, "
                "drafts_sync INTEGER NOT NULL DEFAULT -1, "
                "presence_sync INTEGER NOT NULL DEFAULT -1, "
                "config_hash TEXT NOT NULL DEFAULT '')"
            )
            connection.execute(
                "INSERT INTO sessions (token, device_id, phone, mt_instance_id) "
                "VALUES (?, ?, ?, ?)",
                ("fixture-auth-token", "device-stable-01", "+79990015551", "instance-stable-01"),
            )
        m._ensure_vault_unlocked()
        asyncio.run(m._ensure_session_identity(session_dir, "session.db"))
        m._encrypt_session(profile_id)
        encrypted = session_dir / "session.db.enc"
        assert encrypted.is_file()

        def session_identity() -> tuple[object, ...]:
            m._decrypt_session(profile_id)
            try:
                with closing(sqlite3.connect(session_db)) as connection, connection:
                    return connection.execute(
                        "SELECT token, device_id, phone, mt_instance_id, "
                        "user_agent FROM sessions"
                    ).fetchone()
            finally:
                m._encrypt_session(profile_id)

        expected_identity = session_identity()
        monkeypatch.setattr(
            m,
            "_platform_authorization_record",
            lambda: AuthorizationRecord(
                schema_version=1,
                reference="local-fault-fixture",
                transport=MaxTransport.AUTHORIZED_USER_SESSION,
                allowed_actions=frozenset({MaxAction.CONNECT}),
                valid_from=datetime.now(UTC) - timedelta(minutes=1),
                valid_until=datetime.now(UTC) + timedelta(minutes=5),
            ),
        )
        client_configs: list[dict[str, object]] = []
        staged_sessions: list[int] = []
        original_stage = m._stage_session_for_reauth

        def observe_staged_session(staged_profile_id: int):
            staged_sessions.append(int(staged_profile_id))
            return original_stage(staged_profile_id)

        monkeypatch.setattr(m, "_stage_session_for_reauth", observe_staged_session)

        class FixtureClient:
            me = SimpleNamespace(contact=SimpleNamespace(id=2001))

            async def connect(self):
                if failure_kind == "timeout":
                    raise TimeoutError("fixture connect timeout")
                if failure_kind == "proxy":
                    raise ConnectionError("fixture proxy connection refused")
                if failure_kind == "tls":
                    raise ssl.SSLError("fixture TLS handshake failure")

            async def stop(self):
                return None

        def build_client(**kwargs):
            client_configs.append(kwargs)
            return FixtureClient()

        monkeypatch.setattr(m, "_build_pymax_client", build_client)
        if failure_kind == "local_db":
            def fail_identity_read(*_args, **_kwargs):
                raise sqlite3.OperationalError("fixture session database read failed")

            monkeypatch.setattr(m, "_ensure_session_identity", fail_identity_read)

        failure = {
            "timeout": TimeoutError,
            "proxy": ConnectionError,
            "tls": ssl.SSLError,
            "local_db": sqlite3.OperationalError,
        }[failure_kind]
        with pytest.raises(failure):
            asyncio.run(
                m._login_max(profile_id, "+79990015551", fresh=False, group_id=10)
            )

        assert session_identity() == expected_identity
        assert encrypted.is_file()
        assert not list(session_dir.glob("*.reauth-previous"))
        assert staged_sessions == []
        assert m._auth_sessions[m._auth_session_key(profile_id)]["sms_q"].empty()
        if failure_kind == "local_db":
            assert client_configs == []
        else:
            assert len(client_configs) == 1
            assert client_configs[0]["identity"].device_id == "device-stable-01"
    finally:
        _cleanup(m, monkeypatch)


def test_ordinary_login_tolerates_benign_tls_disconnect_and_reseals_session(
    tmp_path, monkeypatch
):
    m, profile_id = _setup_db(tmp_path, monkeypatch)
    try:
        _attach_test_proxy(m, profile_id)
        from app.platform_policy import AuthorizationRecord, MaxAction, MaxTransport

        session_dir = m._session_dir(profile_id)
        session_dir.mkdir(parents=True, exist_ok=True)
        session_db = session_dir / "session.db"
        with closing(sqlite3.connect(session_db)) as connection, connection:
            connection.execute(
                "CREATE TABLE sessions (token TEXT NOT NULL PRIMARY KEY, "
                "device_id TEXT NOT NULL, phone TEXT NOT NULL, "
                "mt_instance_id TEXT NOT NULL DEFAULT '', "
                "chats_sync INTEGER NOT NULL DEFAULT -1, "
                "contacts_sync INTEGER NOT NULL DEFAULT -1, "
                "drafts_sync INTEGER NOT NULL DEFAULT -1, "
                "presence_sync INTEGER NOT NULL DEFAULT -1, "
                "config_hash TEXT NOT NULL DEFAULT '')"
            )
            connection.execute(
                "INSERT INTO sessions (token, device_id, phone, mt_instance_id) "
                "VALUES (?, ?, ?, ?)",
                ("fixture-auth-token", "device-stable-02", "+79990015551", "instance-stable-02"),
            )
        m._ensure_vault_unlocked()
        asyncio.run(m._ensure_session_identity(session_dir, "session.db"))
        m._encrypt_session(profile_id)

        monkeypatch.setattr(
            m,
            "_platform_authorization_record",
            lambda: AuthorizationRecord(
                schema_version=1,
                reference="local-benign-disconnect-fixture",
                transport=MaxTransport.AUTHORIZED_USER_SESSION,
                allowed_actions=frozenset({MaxAction.CONNECT}),
                valid_from=datetime.now(UTC) - timedelta(minutes=1),
                valid_until=datetime.now(UTC) + timedelta(minutes=5),
            ),
        )

        class FixtureClient:
            me = SimpleNamespace(contact=SimpleNamespace(id=2002))

            async def connect(self):
                return None

            async def stop(self):
                raise ssl.SSLError("close_notify")

        monkeypatch.setattr(m, "_build_pymax_client", lambda **_kwargs: FixtureClient())
        assert asyncio.run(
            m._login_max(profile_id, "+79990015551", fresh=False, group_id=10)
        ) == 2002

        encrypted = session_dir / "session.db.enc"
        assert encrypted.is_file()
        m._decrypt_session(profile_id)
        try:
            with closing(sqlite3.connect(session_db)) as connection, connection:
                identity = connection.execute(
                    "SELECT token, device_id, phone, mt_instance_id "
                    "FROM sessions"
                ).fetchone()
        finally:
            m._encrypt_session(profile_id)
        assert identity == (
            "fixture-auth-token",
            "device-stable-02",
            "+79990015551",
            "instance-stable-02",
        )
    finally:
        _cleanup(m, monkeypatch)


def test_runtime_delete_cancels_owned_client_before_session_rmtree(tmp_path, monkeypatch):
    m, profile_id = _setup_db(tmp_path, monkeypatch)
    try:
        session_dir = m._session_dir(profile_id)
        session_dir.mkdir(parents=True, exist_ok=True)
        marker = session_dir / "runtime-marker"
        marker.write_text("fixture", encoding="utf-8")

        class Client:
            def __init__(self):
                self.stopped = False

            async def stop(self):
                self.stopped = True

        async def _run():
            manager = m._client_manager_instance()
            client = Client()
            lease = await manager.acquire(
                "local", profile_id, {"fixture": True}, "login", lambda: client
            )
            hold = asyncio.Event()

            async def owner():
                try:
                    await hold.wait()
                finally:
                    await m._release_client_lease(manager, lease)

            task = asyncio.create_task(owner())
            m._login_tasks[m._auth_session_key(profile_id)] = task
            await asyncio.sleep(0)
            await m._delete_profile_runtime(profile_id)
            assert client.stopped is True
            assert manager.active("local", profile_id) is False

        asyncio.run(_run())
        assert not marker.exists()
        assert not session_dir.exists()
    finally:
        _cleanup(m, monkeypatch)


def test_login_is_fenced_while_profile_runtime_is_deleting(tmp_path, monkeypatch):
    m, profile_id = _setup_db(tmp_path, monkeypatch)
    try:
        from fastapi import HTTPException
        from app.routes_profiles import login_profile

        m._client_manager_instance()._deleting.add(("local", profile_id))
        with pytest.raises(HTTPException) as caught:
            asyncio.run(login_profile(profile_id))
        assert caught.value.status_code == 409
        assert caught.value.detail == "PROFILE_RUNTIME_CLEANUP_IN_PROGRESS"
        assert not m._login_tasks
    finally:
        _cleanup(m, monkeypatch)


def test_login_rejects_nonselected_work_group_before_sdk(tmp_path, monkeypatch):
    m, profile_id = _setup_db(tmp_path, monkeypatch)
    try:
        from fastapi import HTTPException
        from app.routes_profiles import login_profile

        with m._conn() as connection:
            connection.execute(
                "INSERT INTO groups (id, name, invite_link) VALUES (?, ?, ?), (?, ?, ?)",
                (10, "A", "https://max.example/a", 20, "B", "https://max.example/b"),
            )
            connection.execute(
                "INSERT INTO group_profiles (group_id, profile_id) VALUES (?, ?), (?, ?)",
                (10, profile_id, 20, profile_id),
            )
            connection.execute(
                "CREATE TABLE IF NOT EXISTS profile_automation_scope ("
                "profile_id INTEGER PRIMARY KEY, automation_group_id INTEGER, "
                "consent_state TEXT NOT NULL, revision INTEGER NOT NULL)"
            )
            connection.execute(
                "INSERT INTO profile_automation_scope "
                "(profile_id, automation_group_id, consent_state, revision) "
                "VALUES (?, ?, 'active', 1)",
                (profile_id, 10),
            )

        monkeypatch.setattr(m, "_require_vault_unlocked", lambda: None)
        async def unexpected_login(*_args, **_kwargs):
            raise AssertionError("SDK login must not be reached")

        monkeypatch.setattr(m, "_login_max", unexpected_login)
        with pytest.raises(HTTPException) as caught:
            asyncio.run(login_profile(profile_id, group_id=20))
        assert caught.value.status_code == 409
        assert caught.value.detail == "WORK_GROUP_SELECTION_REQUIRED"
        assert not m._login_tasks
    finally:
        _cleanup(m, monkeypatch)


def test_explicit_work_group_selection_preserves_session_and_fences_other_group(
    tmp_path, monkeypatch
):
    m, profile_id = _setup_db(tmp_path, monkeypatch)
    try:
        from app.routes_models import AutomationScopeIn
        from app.routes_profiles import select_automation_scope

        with m._conn() as connection:
            connection.execute(
                "INSERT INTO groups (id, name, invite_link) VALUES (?, ?, ?), (?, ?, ?)",
                (30, "A", "https://max.example/a", 40, "B", "https://max.example/b"),
            )
            connection.execute(
                "INSERT INTO group_profiles (group_id, profile_id) VALUES (?, ?), (?, ?)",
                (30, profile_id, 40, profile_id),
            )
        retained = m._session_dir(profile_id) / "session.db.enc"
        retained.parent.mkdir(parents=True, exist_ok=True)
        retained.write_bytes(b"encrypted-session-fixture")

        assert m._automation_scope_allows_external_action(profile_id, 30) is False
        selected = asyncio.run(
            select_automation_scope(profile_id, AutomationScopeIn(group_id=40))
        )
        assert selected["automation_group_id"] == 40
        assert selected["session_preserved"] is True
        assert retained.read_bytes() == b"encrypted-session-fixture"
        assert m._automation_scope_allows_external_action(profile_id, 30) is False
        assert m._automation_scope_allows_external_action(profile_id, 40) is True
    finally:
        _cleanup(m, monkeypatch)


def test_unlinking_selected_group_unselects_scope_and_cancels_queued_slots(
    tmp_path, monkeypatch
):
    m, profile_id = _setup_db(tmp_path, monkeypatch)
    try:
        from app.repositories.automation_scope import AutomationScopeRepository
        from app.repositories.daily_plans import DailyPlanRepository
        from app.routes_groups import remove_group_profile
        from app.services.daily_plans import DailyPlanService, LibraryItem

        with m._conn() as connection:
            connection.execute(
                "INSERT INTO groups (id, name, invite_link) VALUES (?, ?, ?), (?, ?, ?)",
                (50, "A", "https://max.example/a", 60, "B", "https://max.example/b"),
            )
            connection.execute(
                "INSERT INTO group_profiles (group_id, profile_id) VALUES (?, ?), (?, ?)",
                (50, profile_id, 60, profile_id),
            )
            scope = AutomationScopeRepository(connection)
            scope.select_work_group(profile_id, 50)
            DailyPlanService(DailyPlanRepository(connection)).materialize_day(
                "local",
                profile_id,
                "2026-09-23",
                sampled_limit=1,
                role="active",
                quiet_limit=1,
                work_group_id=50,
                library_items=(LibraryItem("item-1", "text", "v1"),),
                rng=random.Random(1),
            )
        retained = m._session_dir(profile_id) / "session.db.enc"
        retained.parent.mkdir(parents=True, exist_ok=True)
        retained.write_bytes(b"encrypted-session-fixture")

        result = asyncio.run(remove_group_profile(50, profile_id))
        assert result["ok"] is True
        assert retained.read_bytes() == b"encrypted-session-fixture"
        with m._conn() as connection:
            scope_row = connection.execute(
                "SELECT automation_group_id, consent_state FROM profile_automation_scope "
                "WHERE profile_id=?",
                (profile_id,),
            ).fetchone()
            remaining = connection.execute(
                "SELECT group_id FROM group_profiles WHERE profile_id=? ORDER BY group_id",
                (profile_id,),
            ).fetchall()
            slot = connection.execute(
                "SELECT status, failure_reason FROM profile_message_slots"
            ).fetchone()
        assert tuple(scope_row) == (None, "unselected")
        assert [int(row["group_id"]) for row in remaining] == [60]
        assert tuple(slot) == ("cancelled", "WORK_GROUP_UNLINKED")
    finally:
        _cleanup(m, monkeypatch)


def test_startup_marks_persisted_auth_attempt_interrupted(tmp_path, monkeypatch):
    m, profile_id = _setup_db(tmp_path, monkeypatch)
    try:
        attempt, _ = m._start_auth_attempt(
            profile_id, group_id=None, fresh=False, request_id="restart-start"
        )
        m._reset_auth_on_startup()
        with m._conn() as connection:
            row = connection.execute(
                "SELECT stage, terminal, error_code FROM auth_attempts WHERE attempt_id=?",
                (attempt.attempt_id,),
            ).fetchone()
        assert tuple(row) == ("interrupted", 1, "ATTEMPT_INTERRUPTED")
    finally:
        _cleanup(m, monkeypatch)
