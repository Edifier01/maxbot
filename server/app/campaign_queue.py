"""Campaign message bag and pick logic (ADR 003 phase 3)."""

from __future__ import annotations

import json
import random
import sqlite3


def _main():
    import main as m

    return m


def _get_message_bag(c: sqlite3.Connection) -> list[int]:
    row = c.execute("SELECT message_bag FROM queue_state WHERE id=1").fetchone()
    raw = (row["message_bag"] if row else None) or "[]"
    try:
        data = json.loads(raw)
        if isinstance(data, list):
            return [int(x) for x in data]
    except (TypeError, ValueError, json.JSONDecodeError):
        pass
    return []


def _set_message_bag(c: sqlite3.Connection, bag: list[int]) -> None:
    c.execute(
        "UPDATE queue_state SET message_bag=? WHERE id=1",
        (json.dumps(bag),),
    )


def _rebuild_message_bag(n: int | None = None) -> list[int]:
    m = _main()
    if n is None:
        n = len(m.load_message_pool())
    with m._conn() as c:
        if m._message_pick_mode() != "random_norepeat" or n <= 0:
            _set_message_bag(c, [])
            return []
        bag = list(range(n))
        random.shuffle(bag)
        _set_message_bag(c, bag)
        return bag


def _return_to_message_bag(pool_idx: int) -> None:
    m = _main()
    if m._message_pick_mode() != "random_norepeat":
        return
    with m._conn() as c:
        bag = _get_message_bag(c)
        if pool_idx in bag:
            return
        bag.append(pool_idx)
        random.shuffle(bag)
        _set_message_bag(c, bag)
        qs = c.execute("SELECT message_idx FROM queue_state WHERE id=1").fetchone()
        mi = max(0, int(qs["message_idx"] if qs else 0) - 1)
        c.execute("UPDATE queue_state SET message_idx=? WHERE id=1", (mi,))


def _ensure_message_bag(c: sqlite3.Connection, n: int) -> list[int]:
    m = _main()
    if m._message_pick_mode() != "random_norepeat":
        return []
    if n <= 0:
        return []
    bag = _get_message_bag(c)
    if bag:
        return bag
    goal = m._campaign_goal()
    qs = c.execute("SELECT message_idx FROM queue_state WHERE id=1").fetchone()
    mi = int(qs["message_idx"] if qs else 0)
    if goal == "message_pool":
        if mi >= n:
            return []
        if mi == 0:
            bag = list(range(n))
        else:
            bag = list(range(mi, n))
    else:
        bag = list(range(n))
    random.shuffle(bag)
    _set_message_bag(c, bag)
    if goal == "daily_limits" and mi > 0:
        m.append_log(f"Колода сообщений перемешана заново ({n} шт.)")
    return bag


def _pick_next_message(
    c: sqlite3.Connection, messages: list[str], mi: int
) -> tuple[str, int, int, bool] | None:
    m = _main()
    n = len(messages)
    if n == 0:
        return None
    qs = c.execute("SELECT message_idx FROM queue_state WHERE id=1").fetchone()
    cur = int(qs["message_idx"] if qs else mi)
    if m._message_pick_mode() == "random_norepeat":
        bag = _ensure_message_bag(c, n)
        if not bag:
            return None
        pos = random.randrange(len(bag))
        pool_idx = bag.pop(pos)
        _set_message_bag(c, bag)
        progress_next = cur + 1
        c.execute(
            "UPDATE queue_state SET message_idx=? WHERE id=1",
            (progress_next,),
        )
        return messages[pool_idx], pool_idx, progress_next, True
    if m._campaign_goal() == "message_pool" and mi >= n:
        return None
    pool_idx = mi % n
    progress_next = cur + 1
    return messages[pool_idx], pool_idx, progress_next, False
