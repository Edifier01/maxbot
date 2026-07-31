"""Active groups/profiles queries and role plan (ADR 003 phase 3)."""

from __future__ import annotations

import sqlite3

import antiban_core


def _main():
    import main as m

    return m


def _ensure_group_role_plan(group_id: int) -> None:
    m = _main()
    if not m._role_plan_enabled():
        return
    today = m._local_today().isoformat()
    cycle_day = m._role_cycle_day()
    with m._conn() as c:
        rows = c.execute(
            """
            SELECT gp.profile_id, gp.role_day, gp.is_enabled, p.status
            FROM group_profiles gp
            JOIN profiles p ON p.id = gp.profile_id
            WHERE gp.group_id=? AND gp.is_enabled=1 AND p.status=?
            ORDER BY gp.order_index, p.id
            """,
            (group_id, m.ProfileStatus.ACTIVE),
        ).fetchall()
        if not rows:
            return
        if all(r["role_day"] == today for r in rows):
            return

        ids = [int(r["profile_id"]) for r in rows]
        role_map = antiban_core.assign_rotation_roles(ids, cycle_day)
        order_map = {pid: idx for idx, pid in enumerate(ids)}

        active_n = quiet_n = skip_n = 0
        for pid in ids:
            role = role_map[pid]
            if role == "active":
                active_n += 1
            elif role == "quiet":
                quiet_n += 1
            else:
                skip_n += 1
            c.execute(
                "UPDATE group_profiles SET role_day=?, day_role=?, day_order=? "
                "WHERE group_id=? AND profile_id=?",
                (today, role, order_map.get(pid, 0), group_id, pid),
            )

        g = c.execute("SELECT name FROM groups WHERE id=?", (group_id,)).fetchone()
        gname = g["name"] if g else str(group_id)
    m.append_log(
        f"Роли дня «{gname}»: активных={active_n} тихих={quiet_n} "
        f"пропуск={skip_n} (ротация день {cycle_day + 1}/3)"
    )


def _active_profiles_for_group(group_id: int) -> list[sqlite3.Row]:
    m = _main()
    if m._role_plan_enabled():
        _ensure_group_role_plan(group_id)
    with m._conn() as c:
        if m._role_plan_enabled():
            return c.execute(
                """
                SELECT p.*, gp.day_role, gp.day_order FROM profiles p
                JOIN group_profiles gp ON gp.profile_id = p.id
                WHERE gp.group_id=? AND gp.is_enabled=1 AND p.status=?
                  AND COALESCE(gp.day_role, '') != 'skip'
                ORDER BY COALESCE(gp.day_order, gp.order_index), p.id
                """,
                (group_id, m.ProfileStatus.ACTIVE),
            ).fetchall()
        return c.execute(
            """
            SELECT p.* FROM profiles p
            JOIN group_profiles gp ON gp.profile_id = p.id
            WHERE gp.group_id=? AND gp.is_enabled=1 AND p.status=?
            ORDER BY gp.order_index, p.id
            """,
            (group_id, m.ProfileStatus.ACTIVE),
        ).fetchall()


def _active_groups() -> list[sqlite3.Row]:
    m = _main()
    with m._conn() as c:
        return c.execute(
            "SELECT * FROM groups WHERE is_active=1 ORDER BY id"
        ).fetchall()
