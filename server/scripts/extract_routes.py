"""Extract remaining panel routes from main.py into router modules."""
from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
lines = (ROOT / "main.py").read_text(encoding="utf-8").splitlines()

# --- models ---
model_start = next(i for i, l in enumerate(lines) if l.strip() == "class ProfileIn(BaseModel):")
model_end = next(
    i for i, l in enumerate(lines) if l.strip() == "class RateLimitMiddleware(BaseHTTPMiddleware):"
)
models_body = "\n".join(lines[model_start:model_end])
models_body = models_body.replace(
    "if not _parse_send_windows(s):",
    'if not __import__("main")._parse_send_windows(s):',
)
(ROOT / "app" / "routes_models.py").write_text(
    '"""Pydantic models for panel API routes."""\n\n'
    "from __future__ import annotations\n\n"
    "from pydantic import BaseModel, model_validator\n\n\n"
    + models_body
    + "\n",
    encoding="utf-8",
)

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

MODEL_IMPORTS = {
    "routes_profiles.py": "CodeIn, ProfilePatchIn",
    "routes_groups.py": "BulkProfilesIn, GroupIn, GroupPatchIn, ProfileIn",
    "routes_settings.py": "SettingsIn",
}

BLOCKS = [
    ("routes_profiles.py", 'profiles', '@app.get("/api/profiles")', '@app.get("/api/groups")'),
    ("routes_groups.py", "groups", '@app.get("/api/groups")', '@app.get("/api/messages")'),
    ("routes_messages.py", "messages", '@app.get("/api/messages")', '@app.get("/api/settings")'),
    ("routes_settings.py", "settings", '@app.get("/api/settings")', '@app.post("/api/backup")'),
    ("routes_dashboard.py", "dashboard", '@app.post("/api/backup")', "try:"),
]


def prefix_main(code: str) -> str:
    for sym in sorted(MAIN_SYMBOLS, key=len, reverse=True):
        code = re.sub(rf"(?<![.\w]){re.escape(sym)}(?!\w)", f"m.{sym}", code)
    return code


for fname, tag, start_m, end_m in BLOCKS:
    s = next(i for i, l in enumerate(lines) if l.strip() == start_m)
    if end_m == "try:":
        e = next(i for i, l in enumerate(lines) if l.strip().startswith("try:") and "register_server" in lines[i + 1])
    else:
        e = next(i for i, l in enumerate(lines) if l.strip() == end_m)
    chunk = lines[s:e]
    out = []
    for line in chunk:
        if line.startswith("@app."):
            out.append(line.replace("@app.", "@router.", 1))
        else:
            out.append(line)
    body = prefix_main("\n".join(out))

    hdr = f'"""Panel API — {tag}."""\n\nfrom __future__ import annotations\n\n'
    hdr += "import asyncio\nimport contextlib\nfrom datetime import datetime\nfrom typing import Any\n\n"
    hdr += "from fastapi import APIRouter, File, HTTPException, UploadFile\n\n"
    if fname in MODEL_IMPORTS:
        hdr += f"from app.routes_models import {MODEL_IMPORTS[fname]}\n\n"
    hdr += f'router = APIRouter(tags=["{tag}"])\n\n\n'

    # inject import main at start of each route function
    body = re.sub(
        r"(async def \w+\([^)]*\):)\n",
        r"\1\n    import main as m\n\n",
        body,
    )
    (ROOT / "app" / fname).write_text(hdr + body + "\n", encoding="utf-8")
    print("wrote", fname, e - s, "lines")

print("models ok")
