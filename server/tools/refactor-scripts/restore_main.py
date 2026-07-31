"""One-shot: restore modern main.py from monolithic revert + transcript patches."""
from __future__ import annotations

import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MAIN = ROOT / "main.py"
PATCHES = ROOT / "scripts" / "main_patches.json"


def _replace(text: str, old: str, new: str, label: str) -> str:
    if old not in text:
        print(f"SKIP (not found): {label}")
        return text
    text = text.replace(old, new, 1)
    print(f"OK: {label}")
    return text


def _global_to_runtime(text: str) -> str:
    """Monolithic globals -> REGISTRY/RUNTIME."""
    if "from app.campaign_runtime import REGISTRY, RUNTIME" not in text:
        text = text.replace(
            "import antiban_core\n",
            "import antiban_core\n\nfrom app.campaign_runtime import REGISTRY, RUNTIME\n",
            1,
        )

    text = text.replace(
        "        from server.app.config import is_server_mode\n",
        "        from app.config import is_server_mode\n",
    )
    text = text.replace(
        "        from server.app.tenant import get_effective_data_dir\n",
        "        from app.tenant import get_effective_data_dir\n",
    )

    # Remove global worker state block
    old_globals = """_worker_task: asyncio.Task | None = None
_watchdog_task: asyncio.Task | None = None
_scheduler_task: asyncio.Task | None = None
_backup_task: asyncio.Task | None = None
_pool_tasks: list[asyncio.Task] = []
_worker_lock = asyncio.Lock()
_claim_lock = threading.Lock()
_worker_last_activity: float = 0.0
_current_campaign_id: int | None = None
_pool_done_announced = False
"""
    new_globals = """_claim_lock = threading.Lock()
_app_started_at: float | None = None
"""
    text = _replace(text, old_globals, new_globals, "worker globals")

    text = text.replace(
        "_shutting_down = False\n_consecutive_errors: dict[int, int] = {}\n"
        "_circuit_opened_at: dict[int, float] = {}\n_fernet: Fernet | None = None\n"
        "_vault_unlocked = False\n"
        "# Phase C: серия отправок и «перерыв» по аккаунту (in-memory)\n"
        "_human_burst_count: dict[int, int] = {}\n_human_break_until: dict[int, datetime] = {}\n",
        "_fernet: Fernet | None = None\n_vault_unlocked = False\n",
    )

    text = text.replace("_settings_cache: dict[str, str] = {}", "_settings_cache: dict = {}")

    reset_old = '''def reset_test_runtime() -> None:
    """Сброс in-memory состояния между pytest-тестами (MAX_TEST=1)."""
    global _db_conn, _fernet, _vault_unlocked, _worker_task, _watchdog_task
    global _scheduler_task, _backup_task, _pool_tasks, _current_campaign_id
    global _pool_done_announced, _shutting_down, _worker_last_activity
    with _db_lock:
        if _db_conn is not None:
            with contextlib.suppress(Exception):
                _db_conn.close()
            _db_conn = None
    _fernet = None
    _vault_unlocked = False
    _worker_task = None
    _watchdog_task = None
    _scheduler_task = None
    _backup_task = None
    _pool_tasks = []
    _current_campaign_id = None
    _pool_done_announced = False
    _shutting_down = False
    _worker_last_activity = 0.0
    with _settings_cache_lock:
        _settings_cache.clear()
    with _log_lock:
        _log.clear()
    _auth_sessions.clear()
    _login_tasks.clear()
    _rate_counters.clear()
    _consecutive_errors.clear()
    _circuit_opened_at.clear()
    _human_burst_count.clear()
    _human_break_until.clear()
    _metrics.update(
        {
            "messages_sent_total": 0,
            "messages_failed_total": 0,
            "campaigns_started_total": 0,
            "campaigns_finished_total": 0,
            "worker_restarts_total": 0,
            "backups_total": 0,
        }
    )'''

    reset_new = '''def reset_test_runtime() -> None:
    """Сброс in-memory состояния между pytest-тестами (MAX_TEST=1)."""
    global _db_conn, _fernet, _vault_unlocked
    with _db_lock:
        for conn in list(_tenant_db_conns.values()):
            with contextlib.suppress(Exception):
                conn.close()
        _tenant_db_conns.clear()
        if _db_conn is not None:
            with contextlib.suppress(Exception):
                _db_conn.close()
            _db_conn = None
    _fernet = None
    _vault_unlocked = False
    REGISTRY.reset_test()
    with _settings_cache_lock:
        _settings_cache.clear()
    with _log_lock:
        _log.clear()
    _auth_sessions.clear()
    _login_tasks.clear()
    _rate_counters.clear()
    _metrics.update(
        {
            "messages_sent_total": 0,
            "messages_failed_total": 0,
            "campaigns_started_total": 0,
            "campaigns_finished_total": 0,
            "worker_restarts_total": 0,
            "backups_total": 0,
        }
    )'''
    text = _replace(text, reset_old, reset_new, "reset_test_runtime")

    conn_old = """    if _is_server_mode():
        _refresh_data_paths()
        key = str(_resolve_data_dir())"""
    conn_new = """    if _is_server_mode():
        key = str(_resolve_data_dir())"""
    text = _replace(text, conn_old, conn_new, "_conn refresh removal")

    helpers = '''

def _db_path() -> Path:
    return DB_PATH


def _messages_file() -> Path:
    if _is_server_mode():
        from app.tenant import use_global_data

        if use_global_data():
            return ROOT / "data" / "global" / "messages" / "active.txt"
        return _resolve_data_dir() / "messages" / "active.txt"
    return MESSAGES_FILE
'''
    if "def _db_path()" not in text:
        text = text.replace(
            "def parse_messages_text(raw: str) -> list[str]:",
            helpers + "\ndef parse_messages_text(raw: str) -> list[str]:",
            1,
        )

    # Runtime field references (skip inner function name in _start_worker — handled by patches)
    repl = [
        ("global _current_campaign_id", ""),
        ("_current_campaign_id = int(cur.lastrowid)", "RUNTIME.current_campaign_id = int(cur.lastrowid)"),
        ('append_log(f"Кампания #{_current_campaign_id} запущена', 'append_log(f"Кампания #{RUNTIME.current_campaign_id} запущена'),
        ("return _current_campaign_id", "return RUNTIME.current_campaign_id or 0"),
        ("global _current_campaign_id\n    cid = _current_campaign_id", "cid = RUNTIME.current_campaign_id"),
        ("_current_campaign_id = None", "RUNTIME.current_campaign_id = None"),
        ("global _pool_tasks, _pool_done_announced", ""),
        ("_pool_done_announced = False", "RUNTIME.pool_done_announced = False"),
        ("_pool_tasks = [asyncio.create_task", "RUNTIME.pool_tasks = [asyncio.create_task"),
        ("await asyncio.gather(*_pool_tasks)", "await asyncio.gather(*RUNTIME.pool_tasks)"),
        ("for t in _pool_tasks:", "for t in RUNTIME.pool_tasks:"),
        ("await asyncio.gather(*_pool_tasks, return_exceptions=True)", "await asyncio.gather(*RUNTIME.pool_tasks, return_exceptions=True)"),
        ("_pool_tasks = []", "RUNTIME.pool_tasks = []"),
        ("global _worker_last_activity\n    _worker_last_activity = time.monotonic()", "RUNTIME.touch_activity()"),
        ("_worker_last_activity = time.monotonic()", "RUNTIME.touch_activity()"),
        ("global _human_burst_count, _human_break_until, _consecutive_errors, _circuit_opened_at", ""),
        ("_human_burst_count[pid] = burst", "RUNTIME.human_burst_count[pid] = burst"),
        ("_human_break_until[pid] = until", "RUNTIME.human_break_until[pid] = until"),
        ("_consecutive_errors[pid] = errs", "RUNTIME.consecutive_errors[pid] = errs"),
        ("_circuit_opened_at[pid] = opened_f", "RUNTIME.circuit_opened_at[pid] = opened_f"),
        ("_consecutive_errors.pop(pid, None)", "RUNTIME.consecutive_errors.pop(pid, None)"),
        ("burst = _human_burst_count.get(profile_id, 0)", "burst = RUNTIME.human_burst_count.get(profile_id, 0)"),
        ("until = _human_break_until.get(profile_id)", "until = RUNTIME.human_break_until.get(profile_id)"),
        ("errs = _consecutive_errors.get(profile_id, 0)", "errs = RUNTIME.consecutive_errors.get(profile_id, 0)"),
        ("opened = _circuit_opened_at.get(profile_id)", "opened = RUNTIME.circuit_opened_at.get(profile_id)"),
        ("_consecutive_errors.pop(profile_id, None)", "RUNTIME.consecutive_errors.pop(profile_id, None)"),
        ("_circuit_opened_at.pop(profile_id, None)", "RUNTIME.circuit_opened_at.pop(profile_id, None)"),
        ("n = _consecutive_errors.get(profile_id, 0) + 1", "n = RUNTIME.consecutive_errors.get(profile_id, 0) + 1"),
        ("_consecutive_errors[profile_id] = n", "RUNTIME.consecutive_errors[profile_id] = n"),
        ("_circuit_opened_at.setdefault(profile_id, time.time())", "RUNTIME.circuit_opened_at.setdefault(profile_id, time.time())"),
        ("count = _consecutive_errors.get(profile_id, 0)", "count = RUNTIME.consecutive_errors.get(profile_id, 0)"),
        ("opened = _circuit_opened_at.get(profile_id, 0.0)", "opened = RUNTIME.circuit_opened_at.get(profile_id, 0.0)"),
        ("if _worker_task and not _worker_task.done():", "if RUNTIME.worker_busy():"),
        ("bool(_worker_task and not _worker_task.done())", "RUNTIME.worker_busy()"),
        ("if _shutting_down:", "if RUNTIME.shutting_down:"),
        ("global _watchdog_task, _scheduler_task, _backup_task, _shutting_down", ""),
        ("_watchdog_task = asyncio.create_task(_watchdog_loop())", "RUNTIME.watchdog_task = asyncio.create_task(_watchdog_loop())"),
        ("_scheduler_task = asyncio.create_task(_scheduler_loop())", "RUNTIME.scheduler_task = asyncio.create_task(_scheduler_loop())"),
        ("_backup_task = asyncio.create_task(_backup_loop())", "RUNTIME.backup_task = asyncio.create_task(_backup_loop())"),
        ('"role_active_min": get_setting("role_active_min"),', '"role_active_percent": get_setting("role_active_percent"),\n            "role_quiet_percent": get_setting("role_quiet_percent"),\n            "role_active_min": get_setting("role_active_min"),'),
    ]
    for old, new in repl:
        if old in text:
            text = text.replace(old, new)

    circuit_old = '''def _circuit_open_count() -> int:
    return sum(1 for pid in list(_consecutive_errors) if _is_circuit_open(pid))'''
    circuit_new = '''def _circuit_open_count() -> int:
    total = 0
    for _, rt in REGISTRY.worker_items():
        total += sum(
            1 for pid in list(rt.consecutive_errors) if _is_circuit_open_for(pid, rt)
        )
    if not REGISTRY.worker_items():
        total += sum(
            1 for pid in list(RUNTIME.consecutive_errors) if _is_circuit_open(pid)
        )
    return total


def _is_circuit_open_for(profile_id: int, rt) -> bool:
    count = rt.consecutive_errors.get(profile_id, 0)
    if count < MAX_CONSECUTIVE_ERRORS:
        return False
    opened = rt.circuit_opened_at.get(profile_id, 0.0)
    mins = max(1.0, _setting_float("circuit_break_minutes", float(CIRCUIT_BREAK_MINUTES)))
    return time.time() - opened <= mins * 60'''
    if circuit_old in text:
        text = text.replace(circuit_old, circuit_new, 1)

    auto_old = '''async def _try_auto_resume(*, log_prefix: str = "Автовозобновление") -> bool:
    if not _auto_run_enabled():
        return False
    if RUNTIME.worker_busy():
        return False'''
    if "if _worker_task and not _worker_task.done():" in text:
        text = text.replace(
            "    if _worker_task and not _worker_task.done():\n        return False",
            "    if RUNTIME.worker_busy():\n        return False",
            1,
        )

    return text


def _apply_json_patches(text: str) -> str:
    patches = json.loads(PATCHES.read_text(encoding="utf-8"))
    for i, p in enumerate(patches):
        old, new = p["old_string"], p["new_string"]
        if old == new:
            continue
        if old not in text:
            print(f"PATCH {i+1} skip")
            continue
        text = text.replace(old, new, 1)
        print(f"PATCH {i+1} applied")
    return text


def _apply_worker_patches_from_globals(text: str) -> str:
    """Worker/scheduler blocks if JSON patches missed (globals baseline)."""
    patches = json.loads(PATCHES.read_text(encoding="utf-8"))

    # Replace watchdog+scheduler helpers block through scheduler_loop
    wd_start = text.find("async def _watchdog_loop()")
    backup_start = text.find("async def _backup_loop()")
    if wd_start >= 0 and backup_start > wd_start:
        text = text[:wd_start] + patches[2]["new_string"] + "\n\n" + text[backup_start:]

    sch_start = text.find("async def _scheduler_loop()")
    backup_start = text.find("async def _backup_loop()")
    if sch_start >= 0 and backup_start > sch_start:
        text = text[:sch_start] + patches[3]["new_string"] + "\n\n" + text[backup_start:]

    # start/stop/all workers before RateLimitMiddleware
    sw_start = text.find("async def _start_worker(")
    mw_start = text.find("class RateLimitMiddleware(BaseHTTPMiddleware):")
    if sw_start >= 0 and mw_start > sw_start:
        text = text[:sw_start] + patches[4]["new_string"] + "\n\n" + text[mw_start:]

    return text


def _strip_routes(text: str) -> str:
    lines = text.splitlines()
    try:
        start_models = next(
            i for i, l in enumerate(lines) if l.strip().startswith("# --- API models")
        )
        end_models = next(
            i
            for i, l in enumerate(lines)
            if l.strip() == "class RateLimitMiddleware(BaseHTTPMiddleware):"
        )
        start_routes = next(
            i for i, l in enumerate(lines) if '@app.get("/api/profiles")' in l
        )
        end_routes = next(
            i
            for i, l in enumerate(lines)
            if l.strip().startswith("try:")
            and i + 1 < len(lines)
            and "register_server" in lines[i + 1]
        )
        out = lines[:start_models] + lines[end_models:start_routes] + lines[end_routes:]
        text = "\n".join(out) + "\n"
        print(
            f"Stripped models {end_models - start_models} lines, "
            f"routes {end_routes - start_routes} lines"
        )
    except StopIteration:
        # fallback: strip from first @app route to register_server try
        try:
            start_routes = next(i for i, l in enumerate(lines) if l.strip().startswith("@app."))
            end_routes = next(
                i
                for i, l in enumerate(lines)
                if l.strip().startswith("try:")
                and i + 1 < len(lines)
                and "register_server" in lines[i + 1]
            )
            app_idx = next(
                i for i, l in enumerate(lines) if l.strip() == "app = FastAPI(title=\"MAX Sender\", lifespan=lifespan)"
            )
            out = lines[: app_idx + 4] + lines[end_routes:]
            text = "\n".join(out) + "\n"
            print(f"Fallback strip routes {end_routes - start_routes} lines")
        except StopIteration as e:
            print(f"Strip skip: {e}")
    return text


def _fix_lifespan_m5(text: str) -> str:
    old = '''@asynccontextmanager
async def lifespan(_app: FastAPI):
    global _watchdog_task, _scheduler_task, _backup_task, _shutting_down
    init_db()
    _load_log_from_db()
    _load_antiban_state()
    _try_legacy_unlock()
    _reset_auth_on_startup()
    if not _is_test_mode():
        RUNTIME.watchdog_task = asyncio.create_task(_watchdog_loop())
        RUNTIME.scheduler_task = asyncio.create_task(_scheduler_loop())
        RUNTIME.backup_task = asyncio.create_task(_backup_loop())

        async def _startup_auto_resume() -> None:
            await asyncio.sleep(2)
            await _try_auto_resume(log_prefix="Автозапуск")

        asyncio.create_task(_startup_auto_resume())
    try:
        yield
    finally:
        REGISTRY.app.shutting_down = True
        if not _is_test_mode():
            for task in (RUNTIME.watchdog_task, RUNTIME.scheduler_task, RUNTIME.backup_task):
                if task:
                    task.cancel()
                    with contextlib.suppress(asyncio.CancelledError):
                        await task
            RUNTIME.watchdog_task = RUNTIME.scheduler_task = RUNTIME.backup_task = None
        await _stop_all_workers(finish_status="stopped", reason="Остановка сервера")
        _encrypt_all_sessions()'''

    new = '''@asynccontextmanager
async def lifespan(_app: FastAPI):
    global _app_started_at
    init_db()
    _load_log_from_db()
    _load_antiban_state()
    _try_legacy_unlock()
    _reset_auth_on_startup()
    _app_started_at = time.time()
    if not _is_test_mode():
        RUNTIME.watchdog_task = asyncio.create_task(_watchdog_loop())
        RUNTIME.scheduler_task = asyncio.create_task(_scheduler_loop())
        RUNTIME.backup_task = asyncio.create_task(_backup_loop())
        if _is_server_mode():
            from app.ops_monitor import ops_alert_loop
            from app.subscription_jobs import subscription_lifecycle_loop

            RUNTIME.ops_alert_task = asyncio.create_task(ops_alert_loop())
            RUNTIME.subscription_task = asyncio.create_task(subscription_lifecycle_loop())

        async def _startup_auto_resume() -> None:
            await asyncio.sleep(2)
            await _try_auto_resume(log_prefix="Автозапуск")

        asyncio.create_task(_startup_auto_resume())
    try:
        yield
    finally:
        REGISTRY.app.shutting_down = True
        if not _is_test_mode():
            for task in (
                RUNTIME.watchdog_task,
                RUNTIME.scheduler_task,
                RUNTIME.backup_task,
                RUNTIME.ops_alert_task,
                RUNTIME.subscription_task,
            ):
                if task:
                    task.cancel()
                    with contextlib.suppress(asyncio.CancelledError):
                        await task
            RUNTIME.watchdog_task = RUNTIME.scheduler_task = RUNTIME.backup_task = None
            RUNTIME.ops_alert_task = RUNTIME.subscription_task = None
        await _stop_all_workers(finish_status="stopped", reason="Остановка сервера")
        _encrypt_all_sessions()'''

    if old in text:
        text = text.replace(old, new, 1)
        print("OK: lifespan M5")
    else:
        print("SKIP: lifespan M5 — manual fix may be needed")

    # Fix register import
    text = text.replace(
        "    from server.app.register import register_server\n\n    register_server(app)",
        "    from app.register import register_server\n\n    register_server(app)",
    )
    text = text.replace(
        'from server.app.db_pg import db_pg',
        'from app import db_pg',
    )
    return text


def _clean_imports(text: str) -> str:
    text = re.sub(
        r"from fastapi import FastAPI, File, HTTPException, Request, UploadFile, WebSocket, WebSocketDisconnect\n",
        "from fastapi import FastAPI, HTTPException, Request\n",
        text,
    )
    text = re.sub(
        r"from fastapi.responses import FileResponse, JSONResponse, PlainTextResponse, Response\n",
        "from fastapi.responses import JSONResponse\n",
        text,
    )
    text = re.sub(r"from pydantic import BaseModel, model_validator\n", "", text)
    return text


def main() -> None:
    text = MAIN.read_text(encoding="utf-8")
    print(f"Start: {len(text.splitlines())} lines")
    text = _global_to_runtime(text)
    text = _apply_json_patches(text)
    text = _apply_worker_patches_from_globals(text)
    text = _strip_routes(text)
    text = _fix_lifespan_m5(text)
    text = _clean_imports(text)
    MAIN.write_text(text, encoding="utf-8")
    print(f"Done: {len(text.splitlines())} lines")


if __name__ == "__main__":
    main()
