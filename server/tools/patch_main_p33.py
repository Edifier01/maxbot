"""One-shot: remove P3-3 extracted symbols from main.py and add re-exports."""
from __future__ import annotations

import re
from pathlib import Path

path = Path(__file__).resolve().parents[1] / "main.py"
lines = path.read_text(encoding="utf-8").splitlines(keepends=True)

skip_ranges = [
    (299, 621),
    (947, 1058),
    (1848, 2086),
]
skip: set[int] = set()
for start, end in skip_ranges:
    for i in range(start - 1, end):
        skip.add(i)
for i in (251, 252, 253):
    skip.add(i)

out = [line for i, line in enumerate(lines) if i not in skip]
text = "".join(out)

old = """    global _db_conn, _fernet, _vault_unlocked
    with _db_lock:
        for conn in list(_tenant_db_conns.values()):
            with contextlib.suppress(Exception):
                conn.close()
        _tenant_db_conns.clear()
        if _db_conn is not None:
            with contextlib.suppress(Exception):
                _db_conn.close()
            _db_conn = None
    _fernet = None"""

new = """    global _fernet, _vault_unlocked
    from app import sqlite_backend

    sqlite_backend.reset_connections()
    _fernet = None"""

if old not in text:
    raise SystemExit("reset_test_runtime block not found")
text = text.replace(old, new, 1)

imports = """
from app.sqlite_backend import (
    _conn,
    _db_path,
    _global_conn,
    _global_db_path,
    _reset_db_conn,
    init_db,
)
from app.campaign_queue import (
    _ensure_message_bag,
    _get_message_bag,
    _pick_next_message,
    _rebuild_message_bag,
    _return_to_message_bag,
    _set_message_bag,
)
from app.campaign_query import (
    _active_groups,
    _active_profiles_for_group,
    _ensure_group_role_plan,
)

"""
marker = "from app.campaign_worker import ("
if marker not in text:
    raise SystemExit("campaign_worker import not found")
text = text.replace(marker, imports + marker, 1)

text = re.sub(
    r"\ndef _db_path\(\) -> Path:\n    return _resolve_data_dir\(\) / \"app\.db\"\n\n",
    "\n",
    text,
    count=1,
)

path.write_text(text, encoding="utf-8")
print(f"patched main.py ({len(text.splitlines())} lines)")
