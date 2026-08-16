"""Cabinet activity: human send_log lines on status payload."""

from __future__ import annotations

import importlib

from app.activity_log import fetch_activity, humanize_send_row
from app.tenant import tenant_scope


def test_humanize_sent_failed_reauth():
    now = "2026-08-16T12:00:00"
    sent = humanize_send_row(
        {
            "status": "sent",
            "sent_at": "2026-08-16T11:00:00",
            "group_name": "Отдел продаж",
            "phone": "+79991112233",
            "sent_text": "SECRET-BODY-MUST-NOT-LEAK",
        },
        now_iso=now,
    )
    assert sent == {
        "ts": "2026-08-16T11:00:00",
        "kind": "sent",
        "text": "отправлено в «Отдел продаж» с номера +79991112233",
    }
    assert "SECRET" not in sent["text"]

    failed = humanize_send_row(
        {
            "status": "failed",
            "sent_at": "2026-08-16T11:01:00",
            "group_name": "Чат А",
            "phone": "+7000",
            "error": "FloodWait: wait 32 seconds",
        },
        now_iso=now,
    )
    assert failed["kind"] == "failed"
    assert failed["text"] == "не отправилось в «Чат А»: FloodWait: wait 32 seconds"

    reauth = humanize_send_row(
        {
            "status": "failed",
            "sent_at": "2026-08-16T11:02:00",
            "group_name": "Чат Б",
            "phone": "+7111",
            "error": "Auth error — требуется повторный вход",
        },
        now_iso=now,
    )
    assert reauth["kind"] == "failed"
    assert reauth["text"] == "не отправилось в «Чат Б»: нужен повторный вход"


def test_humanize_fallbacks_and_no_sent_text_key():
    now = "2026-08-16T12:00:00"
    item = humanize_send_row(
        {"status": "sent", "sent_text": "leak-me", "error": ""},
        now_iso=now,
    )
    assert item["ts"] == now
    assert item["text"] == "отправлено в «группа» с номера номер"
    assert set(item) == {"ts", "kind", "text"}
    assert "sent_text" not in item
    assert "leak-me" not in item["text"]

    long_err = "x" * 200 + "\nTraceback (most recent call last):\n  File foo.py"
    failed = humanize_send_row(
        {"status": "failed", "error": long_err, "group_name": "", "phone": None},
        now_iso=now,
    )
    assert failed["text"].startswith("не отправилось в «группа»: ")
    assert "Traceback" not in failed["text"]
    assert len(failed["text"].split(": ", 1)[1]) <= 80


def _setup_server_main(tmp_path, monkeypatch):
    monkeypatch.setenv("MAX_SERVER_MODE", "1")
    monkeypatch.setenv("MAX_TEST", "1")
    monkeypatch.setenv("JWT_SECRET", "test-jwt-secret-min-32-characters-long")

    import app.config as cfg

    importlib.reload(cfg)
    import main as m

    importlib.reload(m)
    monkeypatch.setattr(m, "ROOT", tmp_path)
    m._refresh_data_paths()
    m.reset_test_runtime()
    return m


def _init_tenant(m, tenant_id: int) -> None:
    from app.tenant_init import init_tenant_db

    init_tenant_db(m, tenant_id)


def _seed_send(m, *, phone: str, group: str, status: str, error: str = "", sent_text: str = ""):
    with m._conn() as c:
        c.execute(
            "INSERT INTO profiles (phone, label, status) VALUES (?, '', 'ready')",
            (phone,),
        )
        pid = c.execute("SELECT id FROM profiles WHERE phone=?", (phone,)).fetchone()["id"]
        c.execute("INSERT INTO groups (name) VALUES (?)", (group,))
        gid = c.execute("SELECT id FROM groups WHERE name=?", (group,)).fetchone()["id"]
        c.execute(
            "INSERT INTO send_log (profile_id, group_id, message_idx, status, error, sent_text) "
            "VALUES (?, ?, 0, ?, ?, ?)",
            (pid, gid, status, error, sent_text),
        )


def test_status_payload_activity_from_tenant_sqlite(tmp_path, monkeypatch):
    m = _setup_server_main(tmp_path, monkeypatch)
    _init_tenant(m, 7)

    with tenant_scope(tenant_id=7, role="user"):
        m._refresh_data_paths()
        _seed_send(
            m,
            phone="+79990001111",
            group="Маркетинг",
            status="sent",
            sent_text="TXT-BODY-SECRET",
        )
        _seed_send(
            m,
            phone="+79990002222",
            group="Поддержка",
            status="failed",
            error="timeout from peer",
            sent_text="SHOULD-NOT-APPEAR",
        )
        payload = m._build_status_payload()

    assert "log" in payload
    activity = payload["activity"]
    assert [a["kind"] for a in activity] == ["sent", "failed"]
    assert activity[0]["text"] == "отправлено в «Маркетинг» с номера +79990001111"
    assert activity[1]["text"] == "не отправилось в «Поддержка»: timeout from peer"
    blob = " ".join(a["text"] for a in activity)
    assert "TXT-BODY-SECRET" not in blob
    assert "SHOULD-NOT-APPEAR" not in blob
    assert all(set(a) == {"ts", "kind", "text"} for a in activity)


def test_activity_cross_tenant_isolated(tmp_path, monkeypatch):
    m = _setup_server_main(tmp_path, monkeypatch)
    _init_tenant(m, 1)
    _init_tenant(m, 2)

    with tenant_scope(tenant_id=1, role="user"):
        m._refresh_data_paths()
        _seed_send(m, phone="+7111", group="Секрет А", status="sent", sent_text="A-BODY")

    with tenant_scope(tenant_id=2, role="user"):
        m._refresh_data_paths()
        _seed_send(m, phone="+7222", group="Чат Б", status="sent", sent_text="B-BODY")
        payload = m._build_status_payload()
        texts = [a["text"] for a in payload["activity"]]
        assert any("Чат Б" in t and "+7222" in t for t in texts)
        assert all("Секрет А" not in t and "+7111" not in t for t in texts)
        assert all("A-BODY" not in t for t in texts)


def test_info_line_when_running_outside_window():
    class _FakeConn:
        def execute(self, *_a, **_k):
            class _R:
                def fetchall(self):
                    return []

            return _R()

    items = fetch_activity(
        _FakeConn(),
        running=True,
        outside_window=True,
        now_iso="2026-08-16T03:00:00",
    )
    assert items == [
        {
            "ts": "2026-08-16T03:00:00",
            "kind": "info",
            "text": "рассылка на паузе до рабочего окна",
        }
    ]
    idle = fetch_activity(_FakeConn(), running=False, outside_window=True)
    assert idle == []
