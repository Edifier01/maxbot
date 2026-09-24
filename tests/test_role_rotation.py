"""Ordered 3-day role rotation (33/33/33)."""

from __future__ import annotations

from datetime import date, datetime, timedelta

import uuid

import antiban_core
import main as m
from app import campaign_query


def test_split_thirds_remainder_to_first_parts():
    assert antiban_core.split_thirds(30) == (10, 10, 10)
    assert antiban_core.split_thirds(31) == (11, 10, 10)
    assert antiban_core.split_thirds(32) == (11, 11, 10)
    assert antiban_core.split_thirds(10) == (4, 3, 3)
    for n in range(0, 101):
        assert sum(antiban_core.split_thirds(n)) == n


def test_rotation_parts_disjoint_roles_per_day():
    for cycle_day in range(3):
        roles = {antiban_core.role_rotation_for_part(cycle_day, p) for p in range(3)}
        assert roles == {"active", "quiet", "skip"}


def test_assign_rotation_roles_day1():
    ids = [101, 102, 103, 104, 105, 106, 107, 108, 109]
    roles = antiban_core.assign_rotation_roles(ids, 0)
    assert roles[101] == "active"
    assert roles[102] == "active"
    assert roles[103] == "active"
    assert roles[104] == "quiet"
    assert roles[107] == "skip"


def test_role_cycle_day_from_anchor(tmp_path, monkeypatch):
    data = tmp_path / "data"
    data.mkdir()
    monkeypatch.setattr(m, "DATA", data)
    monkeypatch.setattr(m, "DB_PATH", data / "app.db")
    m._settings_cache.clear()
    m.init_db()
    anchor = date(2026, 7, 1)
    m.set_setting("role_cycle_anchor", anchor.isoformat())
    monkeypatch.setattr(m, "_local_today", lambda: anchor + timedelta(days=5))
    assert m._role_cycle_day() == 2


def test_role_cycle_anchor_not_reset_on_second_start(tmp_path, monkeypatch):
    data = tmp_path / "data"
    data.mkdir()
    monkeypatch.setattr(m, "DATA", data)
    monkeypatch.setattr(m, "DB_PATH", data / "app.db")
    m._settings_cache.clear()
    m.init_db()
    first = date(2026, 6, 10)
    m.set_setting("role_cycle_anchor", first.isoformat())
    monkeypatch.setattr(m, "_local_today", lambda: date(2026, 7, 20))
    m._ensure_role_cycle_anchor()
    assert m.get_setting("role_cycle_anchor") == first.isoformat()


def test_ensure_group_role_plan_ordered(tmp_path, monkeypatch):
    data = tmp_path / "data"
    data.mkdir()
    monkeypatch.setattr(m, "DATA", data)
    monkeypatch.setattr(m, "DB_PATH", data / "app.db")
    m._settings_cache.clear()
    m.init_db()
    m.set_setting("human_rhythm_enabled", "1")
    m.set_setting("role_plan_enabled", "1")
    m.set_setting("role_cycle_anchor", "2026-07-01")
    monkeypatch.setattr(m, "_local_today", lambda: date(2026, 7, 1))
    monkeypatch.setattr(m, "_role_cycle_day", lambda: 0)

    suffix = uuid.uuid4().hex[:8]
    with m._conn() as c:
        c.execute("INSERT INTO groups (name, is_active) VALUES ('G', 1)")
        gid = c.execute("SELECT last_insert_rowid()").fetchone()[0]
        pids: list[int] = []
        for i in range(6):
            cur = c.execute(
                "INSERT INTO profiles (phone, status) VALUES (?, ?)",
                (f"+7900{suffix}{i:02d}", m.ProfileStatus.ACTIVE),
            )
            pid = int(cur.lastrowid)
            pids.append(pid)
            c.execute(
                "INSERT INTO group_profiles (group_id, profile_id, order_index, is_enabled) "
                "VALUES (?, ?, ?, 1)",
                (gid, pid, i + 1),
            )

    campaign_query._ensure_group_role_plan(int(gid))
    with m._conn() as c:
        rows = c.execute(
            "SELECT profile_id, day_role FROM group_profiles WHERE group_id=? "
            "ORDER BY order_index, profile_id",
            (gid,),
        ).fetchall()
    roles_by_name = {"active": [], "quiet": [], "skip": []}
    for row in rows:
        roles_by_name[row["day_role"]].append(row["profile_id"])
    assert len(roles_by_name["active"]) == 2
    assert len(roles_by_name["quiet"]) == 2
    assert len(roles_by_name["skip"]) == 2
    assert set(roles_by_name["active"]) == set(pids[:2])
    assert set(roles_by_name["quiet"]) == set(pids[2:4])
    assert set(roles_by_name["skip"]) == set(pids[4:6])


def test_late_member_does_not_reshuffle_pinned_roles(tmp_path, monkeypatch):
    data = tmp_path / "data"
    data.mkdir()
    monkeypatch.setattr(m, "DATA", data)
    monkeypatch.setattr(m, "DB_PATH", data / "app.db")
    m._settings_cache.clear()
    m.init_db()
    m.set_setting("human_rhythm_enabled", "1")
    m.set_setting("role_plan_enabled", "1")
    m.set_setting("role_cycle_anchor", "2026-07-01")
    today = date(2026, 7, 1)
    monkeypatch.setattr(m, "_local_today", lambda: today)
    monkeypatch.setattr(m, "_role_cycle_day", lambda: 0)

    suffix = uuid.uuid4().hex[:8]
    with m._conn() as c:
        c.execute("INSERT INTO groups (name, is_active) VALUES ('G', 1)")
        gid = int(c.execute("SELECT last_insert_rowid()").fetchone()[0])
        pids: list[int] = []
        for i in range(3):
            cur = c.execute(
                "INSERT INTO profiles (phone, status) VALUES (?, ?)",
                (f"+7911{suffix}{i:02d}", m.ProfileStatus.ACTIVE),
            )
            pid = int(cur.lastrowid)
            pids.append(pid)
            c.execute(
                "INSERT INTO group_profiles (group_id, profile_id, order_index, is_enabled) "
                "VALUES (?, ?, ?, 1)",
                (gid, pid, i + 1),
            )

    campaign_query._ensure_group_role_plan(gid)
    with m._conn() as c:
        before = {
            row["profile_id"]: (row["day_role"], row["day_order"])
            for row in c.execute(
                "SELECT profile_id, day_role, day_order FROM group_profiles "
                "WHERE group_id=? ORDER BY profile_id",
                (gid,),
            ).fetchall()
        }
        cur = c.execute(
            "INSERT INTO profiles (phone, status) VALUES (?, ?)",
            (f"+7911{suffix}99", m.ProfileStatus.ACTIVE),
        )
        late_pid = int(cur.lastrowid)
        c.execute(
            "INSERT INTO group_profiles (group_id, profile_id, order_index, is_enabled) "
            "VALUES (?, ?, ?, 1)",
            (gid, late_pid, 99),
        )

    campaign_query._ensure_group_role_plan(gid)
    with m._conn() as c:
        after = {
            row["profile_id"]: (row["day_role"], row["day_order"], row["role_day"])
            for row in c.execute(
                "SELECT profile_id, day_role, day_order, role_day FROM group_profiles "
                "WHERE group_id=? ORDER BY profile_id",
                (gid,),
            ).fetchall()
        }

    for pid, snapshot in before.items():
        assert after[pid][:2] == snapshot
        assert after[pid][2] == today.isoformat()
    assert after[late_pid][0] == "skip"
    assert after[late_pid][2] == today.isoformat()
    assert after[late_pid][1] > max(order for _, order in before.values())


def test_role_rotation_is_independent_from_send_window_switch(tmp_path, monkeypatch):
    data = tmp_path / "data"
    data.mkdir()
    monkeypatch.setattr(m, "DATA", data)
    monkeypatch.setattr(m, "DB_PATH", data / "app.db")
    m._settings_cache.clear()
    m.init_db()
    m.set_setting("human_rhythm_enabled", "0")
    m.set_setting("role_plan_enabled", "0")
    m.set_setting("send_windows_weekday", "09:00-10:00")

    assert m._role_plan_enabled() is True
    assert m._in_send_window(datetime(2026, 7, 1, 12, 0)) is True
