"""Ordered three-day rotation of weighted role segments."""

from __future__ import annotations

from datetime import date, timedelta

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
    assert [
        [antiban_core.role_rotation_for_part(day, part) for part in range(3)]
        for day in range(3)
    ] == [
        ["active", "quiet", "skip"],
        ["quiet", "skip", "active"],
        ["skip", "active", "quiet"],
    ]


def test_assign_rotation_roles_day1():
    ids = [101, 102, 103, 104, 105, 106, 107, 108, 109]
    roles = antiban_core.assign_rotation_roles(ids, 0)
    assert roles[101] == "active"
    assert roles[102] == "active"
    assert roles[103] == "active"
    assert roles[104] == "quiet"
    assert roles[107] == "skip"

    for cycle_day in range(3):
        counts = antiban_core.assign_rotation_roles(list(range(10)), cycle_day)
        assert sum(role == "active" for role in counts.values()) == 3
        assert sum(role == "quiet" for role in counts.values()) == 3
        assert sum(role == "skip" for role in counts.values()) == 4


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
    m.set_setting("day_skip_percent", "40")
    m.set_setting("role_active_percent", "30")
    m.set_setting("role_quiet_percent", "30")
    m.set_setting("role_cycle_anchor", "2026-07-01")
    monkeypatch.setattr(m, "_local_today", lambda: date(2026, 7, 1))
    monkeypatch.setattr(m, "_role_cycle_day", lambda: 0)

    suffix = uuid.uuid4().hex[:8]
    with m._conn() as c:
        c.execute("INSERT INTO groups (name, is_active) VALUES ('G', 1)")
        gid = c.execute("SELECT last_insert_rowid()").fetchone()[0]
        pids: list[int] = []
        for i in range(10):
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
    assert len(roles_by_name["active"]) == 3
    assert len(roles_by_name["quiet"]) == 3
    assert len(roles_by_name["skip"]) == 4
    assert set(roles_by_name["active"]) == set(pids[:3])
    assert set(roles_by_name["quiet"]) == set(pids[3:6])
    assert set(roles_by_name["skip"]) == set(pids[6:])
