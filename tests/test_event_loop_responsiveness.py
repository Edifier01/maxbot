"""T20 bounded-cache and cancellation-safe local checks."""

from __future__ import annotations

import asyncio
from contextlib import contextmanager
import threading
import tracemalloc
from pathlib import Path
from types import SimpleNamespace
from collections.abc import Iterator
from unittest.mock import patch

from app import auth, auth_rate_limit


ROOT = Path(__file__).resolve().parents[1]


@contextmanager
def _isolated_to_thread() -> Iterator[None]:
    """Use joinable threads when the restricted runner cannot join asyncio's pool."""

    async def run_in_executor(func, /, *args, **kwargs):
        result = []
        error = []

        def worker() -> None:
            try:
                result.append(func(*args, **kwargs))
            except BaseException as exc:  # pragma: no cover - fixture propagation
                error.append(exc)

        thread = threading.Thread(target=worker, name="maxbot-test", daemon=False)
        thread.start()
        while thread.is_alive():
            await asyncio.sleep(0.001)
        thread.join()
        if error:
            raise error[0]
        return result[0]

    with patch("asyncio.to_thread", new=run_in_executor):
        yield


def test_session_and_rate_limit_caches_have_explicit_bounds() -> None:
    assert auth.SESSION_CACHE_MAX > 0
    assert auth_rate_limit.MEMORY_MAX_KEYS > 0
    auth.clear_session_cache()
    auth_rate_limit.reset_for_tests()
    assert auth.session_cache_size() == 0
    assert auth_rate_limit.memory_bucket_count() == 0


def test_memory_rate_limit_buckets_are_evicted_at_bound() -> None:
    auth_rate_limit.reset_for_tests()
    limit = auth_rate_limit.MEMORY_MAX_KEYS
    for index in range(limit + 10):
        auth_rate_limit.check_auth_rate_limit(f"fixture:{index}", 1, 900)
    assert auth_rate_limit.memory_bucket_count() <= limit


def test_backup_entrypoints_use_executor_boundary() -> None:
    dashboard = (ROOT / "app/routes_dashboard.py").read_text(encoding="utf-8")
    main = (ROOT / "main.py").read_text(encoding="utf-8")
    assert "path = await asyncio.to_thread(m.backup_database)" in dashboard
    assert main.count("await asyncio.to_thread(_run_scheduled_backups)") == 2


def test_status_and_backup_executor_boundaries_keep_loop_responsive() -> None:
    from app import routes_dashboard, routes_monitor

    async def scenario() -> None:
        with _isolated_to_thread():
            entered = threading.Event()
            release = threading.Event()
            ticks = 0

            def blocking_result():
                entered.set()
                if not release.wait(timeout=2):
                    raise AssertionError("fixture worker was not released")
                return {"ok": True}

            async def ticker() -> None:
                nonlocal ticks
                while not release.is_set():
                    ticks += 1
                    await asyncio.sleep(0.005)

            ticker_task = asyncio.create_task(ticker())
            try:
                with patch.object(
                    routes_monitor.m,
                    "_build_status_payload",
                    side_effect=blocking_result,
                ):
                    status_task = asyncio.create_task(routes_monitor.status())
                    for _ in range(100):
                        if entered.is_set():
                            break
                        await asyncio.sleep(0.005)
                    assert entered.is_set()
                    await asyncio.sleep(0.04)
                    assert ticks >= 3
                    release.set()
                    assert await asyncio.wait_for(status_task, timeout=2) == {"ok": True}

                entered.clear()
                release.clear()

                def blocking_backup_result():
                    entered.set()
                    if not release.wait(timeout=2):
                        raise AssertionError("backup fixture worker was not released")
                    return Path("app-fixture.db")

                with patch.object(
                    routes_dashboard.m,
                    "backup_database",
                    side_effect=blocking_backup_result,
                ):
                    backup_task = asyncio.create_task(routes_dashboard.api_backup_now())
                    for _ in range(100):
                        if entered.is_set():
                            break
                        await asyncio.sleep(0.005)
                    assert entered.is_set()
                    release.set()
                    assert await asyncio.wait_for(backup_task, timeout=2) == {
                        "ok": True,
                        "file": "app-fixture.db",
                    }
            finally:
                release.set()
                ticker_task.cancel()
                await asyncio.gather(ticker_task, return_exceptions=True)

    asyncio.run(scenario())


def test_one_hundred_ws_auth_cycles_keep_runtime_memory_bounded() -> None:
    from app import routes_monitor

    class FixtureWebSocket:
        def __init__(self, token: str) -> None:
            self.cookies = {"max_token": token}

        async def receive_text(self) -> str:
            return '{"type":"auth"}'

    async def scenario() -> tuple[int, int, int]:
        with _isolated_to_thread():
            async def cycle(index: int) -> None:
                token = f"fixture-token-{index}"
                payload = {
                    "sub": "1",
                    "role": "user",
                    "tenant_id": 2,
                    "jti": token,
                    "tv": 0,
                }
                assert await routes_monitor._authenticate_ws(FixtureWebSocket(token)) is True
                auth.invalidate_session_cache(payload["jti"])

            for index in range(20):
                await cycle(index)
            tracemalloc.reset_peak()
            before, _peak = tracemalloc.get_traced_memory()
            for index in range(20, 120):
                await cycle(index)
            after, peak = tracemalloc.get_traced_memory()
            return before, after, peak

    auth.clear_session_cache()
    tracemalloc.start()
    try:
        with patch("app.config.is_server_mode", new=lambda: True), patch(
            "app.auth.decode_token",
            new=lambda token: {
                "sub": "1",
                "role": "user",
                "tenant_id": 2,
                "jti": token,
                "tv": 0,
            },
        ), patch("app.auth.validate_token_session", new=lambda _payload: None), patch.object(
            routes_monitor.m, "_try_legacy_unlock", new=lambda: None
        ):
            before, after, peak = asyncio.run(scenario())
    finally:
        tracemalloc.stop()
        auth.clear_session_cache()

    assert after - before < 128 * 1024
    assert peak - before < 256 * 1024
    assert auth.session_cache_size() == 0


def test_campaign_stop_offloads_slow_persistence_from_event_loop() -> None:
    from app import routes_campaign

    async def scenario() -> None:
        with _isolated_to_thread():
            entered = threading.Event()
            release = threading.Event()
            coordinator_started = threading.Event()
            coordinator_released = threading.Event()
            completion_started = threading.Event()
            completion_released = threading.Event()
            ticks = 0

            class FixtureCoordinator:
                def stop(self, _command_id: str):
                    coordinator_started.set()
                    if not coordinator_released.wait(timeout=2):
                        raise AssertionError("stop coordinator fixture was not released")
                    return SimpleNamespace(state="stopping", generation=4)

                def complete_stop(self, _command_id: str, *, state: str = "stopped"):
                    completion_started.set()
                    if not completion_released.wait(timeout=2):
                        raise AssertionError("stop completion fixture was not released")
                    return SimpleNamespace(state=state, generation=4)

            def slow_set_setting(_key: str, _value: str) -> None:
                entered.set()
                if not release.wait(timeout=2):
                    raise AssertionError("stop persistence fixture was not released")

            async def ticker() -> None:
                nonlocal ticks
                while not completion_released.is_set():
                    ticks += 1
                    await asyncio.sleep(0.005)

            ticker_task = asyncio.create_task(ticker())
            try:
                with patch.object(
                    routes_campaign, "_coordinator", return_value=FixtureCoordinator()
                ), patch.object(
                    routes_campaign.m, "set_setting", side_effect=slow_set_setting
                ), patch.object(
                    routes_campaign.m, "_stop_worker", return_value=None
                ) as stop_worker:
                    stop_task = asyncio.create_task(
                        routes_campaign.campaign_stop(request_id="stop-slow")
                    )
                    for _ in range(100):
                        if coordinator_started.is_set():
                            break
                        await asyncio.sleep(0.005)
                    assert coordinator_started.is_set()
                    await asyncio.sleep(0.04)
                    assert ticks >= 3
                    coordinator_released.set()
                    for _ in range(100):
                        if entered.is_set():
                            break
                        await asyncio.sleep(0.005)
                    assert entered.is_set()
                    await asyncio.sleep(0.04)
                    assert ticks >= 6
                    release.set()
                    for _ in range(100):
                        if completion_started.is_set():
                            break
                        await asyncio.sleep(0.005)
                    assert completion_started.is_set()
                    await asyncio.sleep(0.04)
                    assert ticks >= 9
                    completion_released.set()
                    assert await asyncio.wait_for(stop_task, timeout=2) == {
                        "ok": True,
                        "state": "stopped",
                        "generation": 4,
                    }
                    stop_worker.assert_awaited_once_with(
                        finish_status="stopped", reason="Остановлено пользователем"
                    )
            finally:
                release.set()
                coordinator_released.set()
                completion_released.set()
                ticker_task.cancel()
                await asyncio.gather(ticker_task, return_exceptions=True)

    asyncio.run(scenario())


def test_admin_user_creation_offloads_slow_password_registration() -> None:
    from app import routes_admin, tenant_init

    async def scenario() -> None:
        with _isolated_to_thread():
            entered = threading.Event()
            release = threading.Event()
            ticks = 0

            def slow_register(_institution: str, _login: str, _password: str):
                entered.set()
                if not release.wait(timeout=2):
                    raise AssertionError("registration fixture was not released")
                return {"tenant_id": 17, "user_id": 19}

            async def ticker() -> None:
                nonlocal ticks
                while not release.is_set():
                    ticks += 1
                    await asyncio.sleep(0.005)

            ticker_task = asyncio.create_task(ticker())
            try:
                with patch.object(routes_admin, "_require_admin", return_value=1), patch.object(
                    routes_admin.auth, "register_user", side_effect=slow_register
                ), patch.object(tenant_init, "init_tenant_db", return_value=None):
                    create_task = asyncio.create_task(
                        routes_admin.create_user(
                            routes_admin.CreateUserIn(
                                institution_name="Fixture institution",
                                login="fixture@example.com",
                                password="fixture-password",
                            )
                        )
                    )
                    for _ in range(100):
                        if entered.is_set():
                            break
                        await asyncio.sleep(0.005)
                    assert entered.is_set()
                    await asyncio.sleep(0.04)
                    assert ticks >= 3
                    release.set()
                    assert await asyncio.wait_for(create_task, timeout=2) == {
                        "ok": True,
                        "tenant_id": 17,
                        "user_id": 19,
                    }
            finally:
                release.set()
                ticker_task.cancel()
                await asyncio.gather(ticker_task, return_exceptions=True)

    asyncio.run(scenario())


def test_blocking_auth_status_and_cleanup_boundaries_are_explicit() -> None:
    middleware = (ROOT / "app/middleware.py").read_text(encoding="utf-8-sig")
    monitor = (ROOT / "app/routes_monitor.py").read_text(encoding="utf-8-sig")
    routes_auth = (ROOT / "app/routes_auth.py").read_text(encoding="utf-8-sig")
    routes_admin = (ROOT / "app/routes_admin.py").read_text(encoding="utf-8-sig")
    assert "await asyncio.to_thread(cached_validate_token_session, payload)" in middleware
    assert "await asyncio.to_thread(\n                auth_rate_limit.check_auth_rate_limit" in middleware
    assert "return await asyncio.to_thread(m._build_status_payload)" in monitor
    assert "await asyncio.to_thread(auth.authenticate, body.login, body.password)" in routes_auth
    assert "await asyncio.to_thread(_token_response, user)" in routes_auth
    assert "await asyncio.to_thread(" in routes_admin
    assert "auth.register_user, body.institution_name, body.login, body.password" in routes_admin
    assert "auth_rate_limit.clear_tenant_rate_limit_keys" in routes_admin
    assert "deleted = await asyncio.to_thread(db_pg.delete_tenant, tenant_id)" in routes_admin
    routes_campaign = (ROOT / "app/routes_campaign.py").read_text(encoding="utf-8-sig")
    assert 'await asyncio.to_thread(m.set_setting, "auto_run", "0")' in routes_campaign
    assert 'await asyncio.to_thread(m.append_log, "Рассылка на паузе")' in routes_campaign


def test_one_hundred_auth_cache_cycles_are_retired() -> None:
    auth.clear_session_cache()
    with patch("app.auth.validate_token_session", return_value=None):
        for index in range(100):
            payload = {"jti": f"cycle-{index}", "sub": "1"}
            auth.cached_validate_token_session(payload)
            auth.invalidate_session_cache(payload["jti"])
    assert auth.session_cache_size() == 0
