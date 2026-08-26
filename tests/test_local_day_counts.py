from __future__ import annotations

import asyncio
from datetime import date


def test_send_counts_use_configured_local_day(tmp_path, monkeypatch):
    monkeypatch.setenv("MAX_TEST", "1")
    monkeypatch.setenv("MAX_SERVER_MODE", "0")

    import main as m
    from app.routes_dashboard import dashboard

    monkeypatch.setattr(m, "ROOT", tmp_path)
    m.reset_test_runtime()
    m._refresh_data_paths()
    m.init_db()
    m.set_setting("timezone_offset_hours", "3")
    monkeypatch.setattr(m, "_local_today", lambda: date(2026, 8, 26))

    with m._conn() as c:
        gid = c.execute("INSERT INTO groups (name) VALUES ('G')").lastrowid
        pid = c.execute(
            "INSERT INTO profiles (phone, status) VALUES ('+79000000001', ?)",
            (m.ProfileStatus.ACTIVE,),
        ).lastrowid
        c.execute(
            "INSERT INTO group_profiles (group_id, profile_id, order_index) VALUES (?, ?, 0)",
            (gid, pid),
        )
        for sent_at in (
            "2026-08-25 20:59:59",
            "2026-08-25 21:00:00",
            "2026-08-25 22:00:00",
            "2026-08-26 20:59:59",
            "2026-08-26 21:00:00",
        ):
            c.execute(
                "INSERT INTO send_log (profile_id, group_id, message_idx, status, sent_at) "
                "VALUES (?, ?, 0, 'sent', ?)",
                (pid, gid, sent_at),
            )
        for sent_at in (
            "2026-08-25 21:00:00",
            "2026-08-25 22:00:00",
            "2026-08-26 21:00:00",
        ):
            c.execute(
                "INSERT INTO send_log (profile_id, group_id, message_idx, status, sent_at) "
                "VALUES (?, ?, 0, 'failed', ?)",
                (pid, gid, sent_at),
            )

    assert m._group_sends_today(int(pid), int(gid)) == 3
    result = asyncio.run(dashboard())
    assert result["sent_today"] == 3
    assert result["failed_today"] == 2
