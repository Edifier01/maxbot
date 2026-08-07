"""One-shot: extract worker block from main.py -> app/campaign_worker.py."""
from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
main_path = ROOT / "main.py"
lines = main_path.read_text(encoding="utf-8").splitlines()

# Block A: lifecycle + telegram; B: claim/loops/scheduler/watchdog; C: start/stop
ranges = [(2754, 2979), (3264, 3677), (3700, 3817)]
block: list[str] = []
for start, end in ranges:
    block.extend(lines[start - 1 : end])

out = []
for line in block:
    line = re.sub(r"^async def _(\w+)", r"async def \1", line)
    line = re.sub(r"^def _(\w+)", r"def \1", line)
    out.append(line)

header = '''"""Campaign worker orchestration (extracted from main.py)."""

from __future__ import annotations

import asyncio
import json
import random
import sqlite3
import time
from datetime import datetime, timezone
from typing import Any
from urllib.request import Request, urlopen

from app.campaign_runtime import REGISTRY, RUNTIME


def _m():
    import main as m

    return m


'''

LOCAL = [
    "worker_shutdown",
    "campaign_config_snapshot",
    "begin_campaign",
    "finish_campaign",
    "http_post_json",
    "telegram_credentials",
    "alert_institution_label",
    "schedule_telegram",
    "telegram_notify",
    "notify_campaign_end",
    "claim_next_job",
    "pool_worker_loop",
    "worker_loop",
    "pool_supervisor",
    "scheduler_tenant_ids",
    "scheduler_tick",
    "scheduler_loop",
    "watchdog_loop",
    "start_worker",
    "stop_worker",
    "stop_all_workers",
]

body = "\n".join(out)
for name in LOCAL:
    body = body.replace(f"_{name}", name)

MAIN_SYMBOLS = [
    "append_log",
    "_conn",
    "get_setting",
    "load_message_pool",
    "_metric_inc",
    "_pool_size",
    "_touch_worker_activity",
    "_wait_if_outside_send_window",
    "_maybe_idle_presence",
    "_reset_daily_counts",
    "_campaign_goal",
    "_message_pick_mode",
    "_ensure_message_bag",
    "_active_groups",
    "_active_profiles_for_group",
    "_has_active_profiles",
    "next_index",
    "_is_circuit_open",
    "_can_send_in_group",
    "_preflight_group_proxies",
    "_pick_next_message",
    "_send_with_retry",
    "_return_to_message_bag",
    "_sleep_send_delay",
    "_has_sendable_profile",
    "_seconds_until_any_human_break_ends",
    "_setting_int",
    "_require_vault_unlocked",
    "_is_server_mode",
    "_parse_iso_datetime",
    "_try_auto_resume",
    "_reset_queue_progress",
    "_rebuild_message_bag",
    "_get_message_bag",
    "_set_message_bag",
    "APP_VERSION",
    "_tg_notify_at",
    "_TG_DEDUPE_SEC",
    "_claim_lock",
    "WORKER_TIMEOUT",
    "ROOT",
]
for sym in MAIN_SYMBOLS:
    body = re.sub(rf"(?<!m\.)(?<!\w){re.escape(sym)}(?!\w)", f"m.{sym}", body)
body = body.replace("m.m.", "m.")
body = body.replace("m.REGISTRY", "REGISTRY").replace("m.RUNTIME", "RUNTIME")

fixed_lines: list[str] = []
pending_def = False
for line in body.splitlines():
    if re.match(r"^(async )?def \w+", line):
        fixed_lines.append(line)
        if not line.startswith((" ", "\t")):
            if line.rstrip().endswith(":"):
                fixed_lines.append("    m = _m()")
                pending_def = False
            else:
                pending_def = True
        continue
    if pending_def:
        fixed_lines.append(line)
        if re.match(r"^\)\s*(->[^:]*)?:\s*$", line.lstrip()):
            fixed_lines.append("    m = _m()")
            pending_def = False
        continue
    fixed_lines.append(line)
body = "\n".join(fixed_lines)

(ROOT / "app" / "campaign_worker.py").write_text(header + body + "\n", encoding="utf-8")
print(f"Wrote campaign_worker.py ({len(body.splitlines())} lines)")
