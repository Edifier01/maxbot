"""Fix extracted routes: prefix main symbols and inject import."""
from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1] / "app"

MAIN_SYMBOLS = [
    "MAX_UPLOAD_BYTES",
    "DEFAULTS",
    "ProfileStatus",
    "_conn",
    "_profile_auth_view",
    "_login_tasks",
    "_clear_session",
    "_ensure_auth_session",
    "_drain_queue",
    "_set_auth_step",
    "_require_vault_unlocked",
    "_login_max",
    "_clear_cooldown",
    "_auth_sessions",
    "_normalize_phone",
    "_is_server_mode",
    "_delete_profile_if_orphan",
    "load_message_pool",
    "_messages_file",
    "save_messages_file",
    "get_setting",
    "_pin_is_set",
    "vault_status",
    "_hash_pin",
    "set_setting",
    "_message_pick_mode",
    "_rebuild_message_bag",
    "backup_database",
    "_backups_dir",
    "_log",
    "_campaign_goal",
    "_daily_capacity_progress",
    "_is_circuit_open",
    "_auto_run_enabled",
    "_circuit_open_count",
    "append_log",
]


def prefix_main(code: str) -> str:
    for sym in sorted(MAIN_SYMBOLS, key=len, reverse=True):
        code = re.sub(rf"(?<![.\w]){re.escape(sym)}(?!\w)", f"m.{sym}", code)
    code = re.sub(r"\bm\.m\.", "m.", code)
    return code


for path in ROOT.glob("routes_*.py"):
    if path.name in ("routes_auth.py", "routes_admin.py", "routes_models.py"):
        continue
    text = path.read_text(encoding="utf-8")
    text = re.sub(r"\n\ndef _m\(\):.*?return m\n\n", "\n\n", text, flags=re.S)
    text = re.sub(r'from server\.app\.routes_models import ""\n\n', "", text)
    # split on async def, prefix body
    parts = re.split(r"(async def \w+\([^)]*\):)", text)
    out = [parts[0]]
    for i in range(1, len(parts), 2):
        header = parts[i]
        body = parts[i + 1] if i + 1 < len(parts) else ""
        if 'import main as m' not in body.split("\n", 3)[0:3]:
            body = "\n    import main as m\n" + body
        body = prefix_main(body)
        out.append(header)
        out.append(body)
    path.write_text("".join(out), encoding="utf-8")
    print("fixed", path.name)
