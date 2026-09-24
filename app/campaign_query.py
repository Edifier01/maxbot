"""Active campaign groups and accounts."""

from __future__ import annotations

import sqlite3


def _main():
    import main as m

    return m


def _active_profiles_for_group(group_id: int) -> list[sqlite3.Row]:
    m = _main()
    with m._conn() as connection:
        return connection.execute(
            "SELECT p.* FROM profiles p JOIN group_profiles gp "
            "ON gp.profile_id=p.id WHERE gp.group_id=? AND gp.is_enabled=1 "
            "AND p.status=? ORDER BY gp.order_index, p.id",
            (int(group_id), m.ProfileStatus.ACTIVE),
        ).fetchall()


def _active_groups() -> list[sqlite3.Row]:
    m = _main()
    with m._conn() as connection:
        return connection.execute(
            "SELECT * FROM groups WHERE is_active=1 ORDER BY id"
        ).fetchall()
