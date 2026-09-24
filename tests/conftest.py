"""Pytest: project root on import path (standalone server)."""

from __future__ import annotations

import asyncio
import contextvars
import os
import sys
import threading
from collections.abc import Iterator
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def postgres_ready() -> bool:
    if not os.environ.get("DATABASE_URL", "").strip():
        return False
    try:
        import psycopg  # noqa: F401
        import psycopg_pool  # noqa: F401
        return True
    except ImportError:
        return False


requires_postgres = pytest.mark.skipif(
    not postgres_ready(),
    reason="DATABASE_URL and psycopg required (PostgreSQL)",
)


def _enable_testclient_uvloop_compat() -> None:
    """Avoid the restricted runner's broken default asyncio portal wake-up."""
    if os.environ.get("MAXBOT_TESTCLIENT_UVLOOP", "").strip() != "1":
        return
    try:
        import uvloop  # noqa: F401
        from starlette.testclient import TestClient
    except ImportError:
        return

    if getattr(TestClient, "_maxbot_uvloop_compat", False):
        return

    original_init = TestClient.__init__

    def init_with_uvloop(self, *args, **kwargs):
        if kwargs.get("backend", "asyncio") == "asyncio" and kwargs.get(
            "backend_options"
        ) is None:
            kwargs["backend_options"] = {"use_uvloop": True}
        original_init(self, *args, **kwargs)

    TestClient.__init__ = init_with_uvloop
    TestClient._maxbot_uvloop_compat = True


_enable_testclient_uvloop_compat()


@pytest.fixture(autouse=True)
def optional_joinable_to_thread(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    """Opt-in workaround for the restricted runner's default executor shutdown."""
    if os.environ.get("MAXBOT_TEST_THREAD_SHIM", "").strip() != "1":
        yield
        return

    async def run_in_thread(func, /, *args, **kwargs):
        result = []
        error = []
        context = contextvars.copy_context()

        def worker() -> None:
            try:
                result.append(context.run(func, *args, **kwargs))
            except BaseException as exc:  # pragma: no cover - fixture propagation
                error.append(exc)

        thread = threading.Thread(target=worker, name="maxbot-test", daemon=True)
        thread.start()
        while thread.is_alive():
            await asyncio.sleep(0.001)
        thread.join()
        if error:
            raise error[0]
        return result[0]

    monkeypatch.setattr(asyncio, "to_thread", run_in_thread)
    yield
