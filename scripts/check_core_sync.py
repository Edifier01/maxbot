#!/usr/bin/env python3
"""Compare shared core between desktop/ and server/ copies.

Usage (from maxserverapp/):
  python scripts/check_core_sync.py
  python scripts/check_core_sync.py --strict   # exit 1 on unexpected drift

Intentional server-only symbols and extracted modules are ignored.
"""

from __future__ import annotations

import argparse
import ast
import hashlib
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DESKTOP_MAIN = ROOT / "desktop" / "main.py"
SERVER_MAIN = ROOT / "server" / "main.py"
DESKTOP_ANTIBAN = ROOT / "desktop" / "antiban_core.py"
SERVER_ANTIBAN = ROOT / "server" / "antiban_core.py"

SERVER_ONLY = {
    "_data_dir",
    "_sessions_root",
    "_messages_file",
    "_db_path",
    "_app_key_path",
    "_app_salt_path",
    "_app_vault_path",
    "_backups_dir",
    "_vault_clear_all",
}

VAULT_DESKTOP_ONLY = {"_derive_fernet", "_reencrypt_all_sessions"}

# Refactored on server — bodies differ by design (modules / thin wrappers)
KNOWN_DIVERGENT = {
    "_begin_campaign",
    "_campaign_config_snapshot",
    "_circuit_open_count",
    "_decrypt_session",
    "_encrypt_all_sessions",
    "_encrypt_session",
    "_finish_campaign",
    "_get_fernet",
    "_is_circuit_open",
    "_is_in_human_break",
    "_load_antiban_state",
    "_note_human_burst",
    "_on_error",
    "_on_success",
    "_persist_antiban_profile",
    "_refresh_data_paths",
    "_seconds_until_any_human_break_ends",
    "_session_dir",
    "_touch_worker_activity",
    "_try_legacy_unlock",
    "_vault_ready_for_send",
    "lock_vault",
    "reset_test_runtime",
    "setup_vault",
    "unlock_vault",
    "vault_status",
    "lifespan",
    # P0 path helpers / tenant conn (server uses _data_dir() not globals refresh)
    "_conn",
    "init_db",
    "save_messages_file",
    "backup_database",
    # worker loops use RUNTIME on server
    "_backup_loop",
    "_claim_next_job",
    "_delete_profile_if_orphan",
    "_pool_supervisor",
    "_scheduler_loop",
    "_start_worker",
    "_stop_worker",
    "_try_auto_resume",
    "_watchdog_loop",
}

ROUTE_DECORATORS = {"get", "post", "put", "patch", "delete", "websocket", "head", "options"}


def _is_route_handler(node: ast.AST) -> bool:
    for dec in getattr(node, "decorator_list", ()):
        target = dec
        if isinstance(dec, ast.Call):
            target = dec.func
        if isinstance(target, ast.Attribute) and target.attr in ROUTE_DECORATORS:
            return True
        if isinstance(target, ast.Name) and target.id in ROUTE_DECORATORS:
            return True
    return False


def _collect_defs(path: Path) -> dict[str, ast.AST]:
    src = path.read_text(encoding="utf-8")
    tree = ast.parse(src)
    lines = src.splitlines()
    out: dict[str, ast.AST] = {}
    for node in tree.body:
        if isinstance(node, ast.ClassDef) and node.name.endswith("In"):
            continue
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            if _is_route_handler(node):
                continue
            out[node.name] = node
            node._sync_src = "\n".join(lines[node.lineno - 1 : node.end_lineno])  # type: ignore[attr-defined]
    return out


def _core_names(defs: dict[str, ast.AST], *, side: str) -> set[str]:
    names = set(defs)
    if side == "server":
        names -= SERVER_ONLY
    return names


def _body_hash(node: ast.AST) -> str:
    src = getattr(node, "_sync_src", "")
    normalized = "\n".join(line.rstrip() for line in src.splitlines()).strip()
    return hashlib.sha256(normalized.encode()).hexdigest()[:16]


def _file_hash(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()[:16]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--strict", action="store_true", help="exit 1 on unexpected drift")
    args = parser.parse_args()

    issues: list[str] = []
    print("MAX Sender — core sync check\n")

    if _file_hash(DESKTOP_ANTIBAN) != _file_hash(SERVER_ANTIBAN):
        issues.append("antiban_core.py differs between desktop/ and server/")
        print("FAIL  antiban_core.py  (desktop != server)")
    else:
        print("OK    antiban_core.py")

    desktop = _collect_defs(DESKTOP_MAIN)
    server = _collect_defs(SERVER_MAIN)
    d_core = _core_names(desktop, side="desktop")
    s_core = _core_names(server, side="server")

    only_desktop = sorted(d_core - s_core - VAULT_DESKTOP_ONLY)
    only_server = sorted(s_core - d_core)

    if only_desktop:
        print(f"\nCore symbols only in desktop/main.py ({len(only_desktop)}):")
        for n in only_desktop[:20]:
            print(f"  + {n}")
        if len(only_desktop) > 20:
            print(f"  ... and {len(only_desktop) - 20} more")
        issues.append(f"{len(only_desktop)} core symbol(s) missing in server/main.py")

    if only_server:
        print(f"\nCore symbols only in server/main.py ({len(only_server)}):")
        for n in only_server:
            print(f"  + {n}")
        issues.append(f"{len(only_server)} core symbol(s) missing in desktop/main.py")

    shared = sorted((d_core & s_core) - SERVER_ONLY - KNOWN_DIVERGENT)
    mismatched: list[str] = []
    for name in shared:
        if _body_hash(desktop[name]) != _body_hash(server[name]):
            mismatched.append(name)

    if mismatched:
        print(f"\nUnexpected body drift ({len(mismatched)}):")
        for n in mismatched[:30]:
            print(f"  ~ {n}")
        if len(mismatched) > 30:
            print(f"  ... and {len(mismatched) - 30} more")
        issues.append(f"{len(mismatched)} shared symbol(s) differ unexpectedly")

    ref_count = len(KNOWN_DIVERGENT & (d_core & s_core))
    if ref_count:
        print(f"\nInfo  {ref_count} symbol(s) skipped (known server refactor: vault/campaign/paths)")

    print("\n---")
    if not issues:
        print("No blocking drift detected.")
        return 0

    print("Issues:")
    for i in issues:
        print(f"  - {i}")
    print("\nSee docs/CORE-SYNC.md for the mirror checklist.")
    strict_issues = [i for i in issues if "differ unexpectedly" not in i]
    return 1 if args.strict and strict_issues else 0


if __name__ == "__main__":
    sys.exit(main())
