"""Routes are registered via register_panel."""

from __future__ import annotations

import asyncio
import importlib
from io import BytesIO

import pytest


def test_panel_routes_registered():
    import main as m

    importlib.reload(m)
    paths = set(m.app.openapi().get("paths", {}))
    for path in (
        "/api/health",
        "/api/vault/status",
        "/api/campaign/start",
        "/api/profiles",
        "/api/groups",
        "/api/messages",
        "/api/settings",
        "/api/dashboard",
        "/",
    ):
        assert path in paths, path


def test_messages_upload(tmp_path, monkeypatch):
    monkeypatch.setenv("MAX_TEST", "1")
    monkeypatch.setenv("MAX_SERVER_MODE", "0")

    import importlib

    import app.config as cfg

    importlib.reload(cfg)

    import main as m

    importlib.reload(m)
    monkeypatch.setattr(m, "ROOT", tmp_path)
    m._refresh_data_paths()
    m.init_db()

    from starlette.testclient import TestClient

    with TestClient(m.app) as client:
        r = client.post(
            "/api/messages/upload",
            files={"file": ("t.txt", b"hello\nworld\n", "text/plain")},
        )
    assert r.status_code == 200, r.text
    assert r.json()["count"] == 2


def test_messages_upload_rejects_over_limit_before_publishing(monkeypatch):
    import main as m
    from fastapi import HTTPException, UploadFile

    from app.campaign_runtime import REGISTRY
    from app.routes_messages import upload_messages

    monkeypatch.setattr(m, "MAX_UPLOAD_BYTES", 8)
    monkeypatch.setattr(REGISTRY, "any_worker_busy", lambda: False)
    monkeypatch.setattr(
        m,
        "save_messages_file",
        lambda _content: pytest.fail("oversized message file must not be published"),
    )

    class InMemoryFile(BytesIO):
        _rolled = False

    upload = UploadFile(filename="oversized.txt", file=InMemoryFile(b"123456789"))

    with pytest.raises(HTTPException) as caught:
        asyncio.run(upload_messages(upload))

    assert caught.value.status_code == 413
    assert upload.file.tell() == 9


def test_messages_upload_rejects_active_worker_before_write(tmp_path, monkeypatch):
    monkeypatch.setenv("MAX_TEST", "1")
    monkeypatch.setenv("MAX_SERVER_MODE", "0")

    import app.config as cfg

    importlib.reload(cfg)

    import main as m

    importlib.reload(m)
    monkeypatch.setattr(m, "ROOT", tmp_path)
    m._refresh_data_paths()
    m.reset_test_runtime()
    m.init_db()

    from fastapi import HTTPException, UploadFile

    from app.campaign_runtime import REGISTRY
    from app.routes_messages import upload_messages

    class UnfinishedTask:
        @staticmethod
        def done():
            return False

    try:
        upload = UploadFile(filename="t.txt", file=BytesIO(b"hello\nworld\n"))
        REGISTRY.worker_for(42).worker_task = UnfinishedTask()
        with pytest.raises(HTTPException) as exc:
            asyncio.run(upload_messages(upload))
        assert exc.value.status_code == 409
        assert upload.file.tell() == 0
        assert not m._messages_file().exists()
    finally:
        m.reset_test_runtime()


def test_messages_upload_waits_for_message_pool_lock_before_read(tmp_path, monkeypatch):
    monkeypatch.setenv("MAX_TEST", "1")
    monkeypatch.setenv("MAX_SERVER_MODE", "0")

    import app.config as cfg

    importlib.reload(cfg)

    import main as m

    importlib.reload(m)
    monkeypatch.setattr(m, "ROOT", tmp_path)
    m._refresh_data_paths()
    m.reset_test_runtime()
    m.init_db()

    from fastapi import UploadFile

    from app.campaign_runtime import REGISTRY
    from app.routes_messages import upload_messages

    class InMemoryFile(BytesIO):
        _rolled = False

    async def scenario():
        upload = UploadFile(filename="t.txt", file=InMemoryFile(b"hello\nworld\n"))
        lock = REGISTRY.app.message_pool_lock
        await lock.acquire()
        task = asyncio.create_task(upload_messages(upload))
        try:
            await asyncio.sleep(0)
            assert not task.done()
            assert upload.file.tell() == 0
        finally:
            lock.release()
            await asyncio.gather(task, return_exceptions=True)
        assert task.result() == {"count": 2}

    try:
        asyncio.run(scenario())
    finally:
        m.reset_test_runtime()


def test_start_worker_waits_for_message_pool_lock_before_worker_check():
    from app.campaign_runtime import REGISTRY
    from app.campaign_worker import start_worker

    class UnfinishedTask:
        checked = 0

        def done(self):
            self.checked += 1
            return False

    async def scenario():
        REGISTRY.reset_test()
        worker = UnfinishedTask()
        REGISTRY.worker_for(None).worker_task = worker
        lock = REGISTRY.app.message_pool_lock
        await lock.acquire()
        task = asyncio.create_task(start_worker(record_campaign=False))
        try:
            await asyncio.sleep(0)
            assert not task.done()
            assert worker.checked == 0
        finally:
            lock.release()
            await asyncio.gather(task, return_exceptions=True)
        assert task.result() is False
        assert worker.checked == 1

    try:
        asyncio.run(scenario())
    finally:
        REGISTRY.reset_test()


def test_list_backups(tmp_path, monkeypatch):
    monkeypatch.setenv("MAX_TEST", "1")
    monkeypatch.setenv("MAX_SERVER_MODE", "0")

    import importlib

    import app.config as cfg

    importlib.reload(cfg)

    import main as m

    importlib.reload(m)
    monkeypatch.setattr(m, "ROOT", tmp_path)
    m._refresh_data_paths()
    m.init_db()
    backups = m._backups_dir()
    backups.mkdir(parents=True, exist_ok=True)
    (backups / "app-test.db").write_bytes(b"x")

    from starlette.testclient import TestClient

    with TestClient(m.app) as client:
        r = client.get("/api/backups")
    assert r.status_code == 200, r.text
    names = [item["file"] for item in r.json()["items"]]
    assert "app-test.db" in names


def test_backup_database_uses_tenant_backups_dir(tmp_path, monkeypatch):
    monkeypatch.setenv("MAX_TEST", "1")
    monkeypatch.setenv("MAX_SERVER_MODE", "1")

    import importlib

    import app.config as cfg

    importlib.reload(cfg)

    import main as m

    importlib.reload(m)
    monkeypatch.setattr(m, "ROOT", tmp_path)
    m._refresh_data_paths()
    m.reset_test_runtime()

    from app.tenant import tenant_scope

    with tenant_scope(tenant_id=42, role="user"):
        m.init_db()
        dest = m.backup_database()

    assert dest is not None
    tenant_backups = tmp_path / "data" / "tenants" / "42" / "backups"
    assert dest.parent == tenant_backups
    assert dest.is_file()
    global_backups = tmp_path / "data" / "backups"
    assert not list(global_backups.glob("app-*.db")) if global_backups.exists() else True
