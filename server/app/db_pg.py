"""PostgreSQL: пользователи, tenant, подписки."""

from __future__ import annotations

import contextlib
from datetime import datetime, timezone
from typing import Any

from server.app.config import require_database_url

_conn = None


def _get_conn():
    global _conn
    if _conn is None:
        import psycopg
        from psycopg.rows import dict_row

        _conn = psycopg.connect(require_database_url(), row_factory=dict_row, autocommit=True)
    return _conn


def init_schema() -> None:
    from pathlib import Path

    schema_path = Path(__file__).resolve().parents[2] / "schema_pg.sql"
    sql = schema_path.read_text(encoding="utf-8")
    with _get_conn().cursor() as cur:
        cur.execute(sql)


def _now() -> datetime:
    return datetime.now(timezone.utc)


def create_tenant(institution_name: str) -> int:
    with _get_conn().cursor() as cur:
        cur.execute(
            "INSERT INTO tenants (institution_name) VALUES (%s) RETURNING id",
            (institution_name.strip(),),
        )
        row = cur.fetchone()
        assert row
        return int(row["id"])


def create_user(
    email: str,
    password_hash: str,
    *,
    tenant_id: int | None,
    role: str = "user",
) -> int:
    with _get_conn().cursor() as cur:
        cur.execute(
            """
            INSERT INTO users (tenant_id, email, password_hash, role)
            VALUES (%s, %s, %s, %s) RETURNING id
            """,
            (tenant_id, email.strip().lower(), password_hash, role),
        )
        row = cur.fetchone()
        assert row
        return int(row["id"])


def get_user_by_email(email: str) -> dict[str, Any] | None:
    with _get_conn().cursor() as cur:
        cur.execute("SELECT * FROM users WHERE email = %s", (email.strip().lower(),))
        return cur.fetchone()


def get_user_by_id(user_id: int) -> dict[str, Any] | None:
    with _get_conn().cursor() as cur:
        cur.execute("SELECT * FROM users WHERE id = %s", (user_id,))
        return cur.fetchone()


def get_tenant(tenant_id: int) -> dict[str, Any] | None:
    with _get_conn().cursor() as cur:
        cur.execute("SELECT * FROM tenants WHERE id = %s", (tenant_id,))
        return cur.fetchone()


def list_tenants_with_users() -> list[dict[str, Any]]:
    with _get_conn().cursor() as cur:
        cur.execute(
            """
            SELECT t.id AS tenant_id, t.institution_name, t.created_at,
                   u.id AS user_id, u.email,
                   (SELECT MAX(s.expires_at) FROM subscriptions s
                    WHERE s.tenant_id = t.id) AS subscription_expires
            FROM tenants t
            JOIN users u ON u.tenant_id = t.id AND u.role = 'user'
            ORDER BY t.institution_name
            """
        )
        return list(cur.fetchall())


def grant_subscription(
    tenant_id: int,
    expires_at: datetime,
    granted_by: int,
) -> None:
    with _get_conn().cursor() as cur:
        cur.execute(
            """
            INSERT INTO subscriptions (tenant_id, expires_at, granted_by)
            VALUES (%s, %s, %s)
            """,
            (tenant_id, expires_at, granted_by),
        )


def subscription_active(tenant_id: int | None) -> bool:
    if tenant_id is None:
        return True
    with _get_conn().cursor() as cur:
        cur.execute(
            """
            SELECT 1 FROM subscriptions
            WHERE tenant_id = %s AND expires_at > %s
            LIMIT 1
            """,
            (tenant_id, _now()),
        )
        return cur.fetchone() is not None


def subscription_info(tenant_id: int | None) -> dict[str, Any]:
    if tenant_id is None:
        return {"active": True, "expires_at": None}
    with _get_conn().cursor() as cur:
        cur.execute(
            """
            SELECT expires_at FROM subscriptions
            WHERE tenant_id = %s AND expires_at > %s
            ORDER BY expires_at DESC LIMIT 1
            """,
            (tenant_id, _now()),
        )
        row = cur.fetchone()
    if not row:
        return {"active": False, "expires_at": None}
    exp = row["expires_at"]
    return {
        "active": True,
        "expires_at": exp.isoformat() if hasattr(exp, "isoformat") else str(exp),
    }


def log_impersonation(admin_user_id: int, target_tenant_id: int) -> None:
    with _get_conn().cursor() as cur:
        cur.execute(
            """
            INSERT INTO impersonation_log (admin_user_id, target_tenant_id)
            VALUES (%s, %s)
            """,
            (admin_user_id, target_tenant_id),
        )


def admin_exists() -> bool:
    with _get_conn().cursor() as cur:
        cur.execute("SELECT 1 FROM users WHERE role = 'admin' LIMIT 1")
        return cur.fetchone() is not None


def close() -> None:
    global _conn
    if _conn is not None:
        with contextlib.suppress(Exception):
            _conn.close()
        _conn = None
