"""Human activity lines from tenant send_log for the status payload."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Mapping

ACTIVITY_LIMIT = 50
ERROR_MAX_LEN = 80

_FALLBACK_GROUP = "группа"
_FALLBACK_PHONE = "номер"
INFO_OUTSIDE_WINDOW = "рассылка на паузе до рабочего окна"


def _as_str(value: Any) -> str:
    if value is None:
        return ""
    return str(value).strip()


def _row_get(row: Mapping[str, Any] | Any, key: str, default: Any = None) -> Any:
    try:
        val = row[key]
    except (KeyError, IndexError, TypeError):
        return default
    return default if val is None else val


def _group_label(name: Any) -> str:
    return _as_str(name) or _FALLBACK_GROUP


def _phone_label(phone: Any) -> str:
    return _as_str(phone) or _FALLBACK_PHONE


def is_auth_reauth_error(error: str) -> bool:
    low = (error or "").lower()
    return "auth" in low or "reauth" in low or "повторн" in low


def short_error(error: str) -> str:
    text = (error or "").replace("\r", "\n")
    lines = [ln.strip() for ln in text.split("\n") if ln.strip()]
    if not lines:
        return ""
    first = lines[0]
    if first.lower().startswith("traceback"):
        first = lines[-1]
    if len(first) > ERROR_MAX_LEN:
        return first[:ERROR_MAX_LEN].rstrip()
    return first


def humanize_send_row(
    row: Mapping[str, Any] | Any, *, now_iso: str
) -> dict[str, str] | None:
    status = _as_str(_row_get(row, "status")).lower()
    group = _group_label(_row_get(row, "group_name"))
    phone = _phone_label(_row_get(row, "phone"))
    ts = _as_str(_row_get(row, "sent_at")) or now_iso
    if status == "sent":
        return {
            "ts": ts,
            "kind": "sent",
            "text": f"отправлено в «{group}» с номера {phone}",
        }
    if status == "failed":
        err = _as_str(_row_get(row, "error"))
        if is_auth_reauth_error(err):
            detail = "нужен повторный вход"
        else:
            detail = short_error(err) or "ошибка"
        return {
            "ts": ts,
            "kind": "failed",
            "text": f"не отправилось в «{group}»: {detail}",
        }
    return None


def fetch_activity(
    conn: Any,
    *,
    running: bool = False,
    outside_window: bool = False,
    now_iso: str | None = None,
    limit: int = ACTIVITY_LIMIT,
) -> list[dict[str, str]]:
    now_iso = now_iso or datetime.now().isoformat(timespec="seconds")
    rows = conn.execute(
        """
        SELECT sl.status, sl.error, sl.sent_at, p.phone, g.name AS group_name
        FROM send_log sl
        LEFT JOIN profiles p ON p.id = sl.profile_id
        LEFT JOIN groups g ON g.id = sl.group_id
        ORDER BY sl.id DESC
        LIMIT ?
        """,
        (limit,),
    ).fetchall()
    items: list[dict[str, str]] = []
    for row in reversed(rows):
        item = humanize_send_row(row, now_iso=now_iso)
        if item:
            items.append(item)
    if running and outside_window:
        items.append(
            {
                "ts": now_iso,
                "kind": "info",
                "text": INFO_OUTSIDE_WINDOW,
            }
        )
    return items
