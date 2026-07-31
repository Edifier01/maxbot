"""PostgreSQL: пользователи, tenant, подписки."""

from __future__ import annotations

import contextlib
import threading
from datetime import datetime, timezone
from typing import Any, Iterator

from app.config import require_database_url

_pool = None
_pool_lock = threading.Lock()


def _get_pool():
    global _pool
    if _pool is None:
        with _pool_lock:
            if _pool is None:
                from psycopg.rows import dict_row
                from psycopg_pool import ConnectionPool

                _pool = ConnectionPool(
                    require_database_url(),
                    kwargs={"row_factory": dict_row},
                    min_size=1,
                    max_size=10,
                    timeout=30.0,
                    max_waiting=50,
                    open=True,
                )
    return _pool


@contextlib.contextmanager
def _cursor(*, transaction: bool = False) -> Iterator[Any]:
    with _get_pool().connection() as conn:
        if transaction:
            with conn.transaction():
                with conn.cursor() as cur:
                    yield cur
        else:
            with conn.cursor() as cur:
                yield cur


def register_tenant_user(
    institution_name: str,
    email: str,
    password_hash: str,
) -> dict[str, Any]:
    """Атомарно: tenant + user в одной транзакции."""
    email_norm = email.strip().lower()
    with _cursor(transaction=True) as cur:
        cur.execute("SELECT 1 FROM users WHERE email = %s", (email_norm,))
        if cur.fetchone():
            raise ValueError("Email уже зарегистрирован")
        cur.execute(
            "INSERT INTO tenants (institution_name) VALUES (%s) RETURNING id",
            (institution_name.strip(),),
        )
        tenant_row = cur.fetchone()
        if tenant_row is None:
            raise RuntimeError("register_tenant_user: tenant INSERT не вернул id")
        tenant_id = int(tenant_row["id"])
        cur.execute(
            """
            INSERT INTO users (tenant_id, email, password_hash, role)
            VALUES (%s, %s, %s, 'user') RETURNING id
            """,
            (tenant_id, email_norm, password_hash),
        )
        user_row = cur.fetchone()
        if user_row is None:
            raise RuntimeError("register_tenant_user: user INSERT не вернул id")
        user_id = int(user_row["id"])
    return {
        "user_id": user_id,
        "tenant_id": tenant_id,
        "email": email_norm,
        "role": "user",
    }


def _schema_dir():
    from pathlib import Path

    return Path(__file__).resolve().parents[1]


def ping() -> bool:
    try:
        with _cursor() as cur:
            cur.execute("SELECT 1")
        return True
    except Exception:
        return False


def _migration_done(cur, version: str) -> bool:
    cur.execute("SELECT 1 FROM schema_migrations WHERE version = %s", (version,))
    return cur.fetchone() is not None


def _apply_pending_migrations() -> None:
    migrations_dir = _schema_dir() / "migrations"
    if not migrations_dir.is_dir():
        return
    for path in sorted(migrations_dir.glob("*.sql")):
        version = path.stem
        sql = path.read_text(encoding="utf-8")
        with _cursor(transaction=True) as cur:
            cur.execute("SELECT pg_advisory_xact_lock(%s)", (12345,))
            if _migration_done(cur, version):
                continue
            cur.execute(sql)
            cur.execute(
                "INSERT INTO schema_migrations (version) VALUES (%s) ON CONFLICT DO NOTHING",
                (version,),
            )


def init_schema() -> None:
    bootstrap = _schema_dir() / "schema_pg.sql"
    if bootstrap.exists():
        with _cursor(transaction=True) as cur:
            cur.execute(bootstrap.read_text(encoding="utf-8"))
    _apply_pending_migrations()


def _now() -> datetime:
    return datetime.now(timezone.utc)


def create_tenant(institution_name: str) -> int:
    with _cursor() as cur:
        cur.execute(
            "INSERT INTO tenants (institution_name) VALUES (%s) RETURNING id",
            (institution_name.strip(),),
        )
        row = cur.fetchone()
        if row is None:
            raise RuntimeError("create_tenant: INSERT не вернул id")
        return int(row["id"])


def create_user(
    email: str,
    password_hash: str,
    *,
    tenant_id: int | None,
    role: str = "user",
) -> int:
    with _cursor() as cur:
        cur.execute(
            """
            INSERT INTO users (tenant_id, email, password_hash, role)
            VALUES (%s, %s, %s, %s) RETURNING id
            """,
            (tenant_id, email.strip().lower(), password_hash, role),
        )
        row = cur.fetchone()
        if row is None:
            raise RuntimeError("create_user: INSERT не вернул id")
        return int(row["id"])


def get_user_by_email(email: str) -> dict[str, Any] | None:
    with _cursor() as cur:
        cur.execute("SELECT * FROM users WHERE email = %s", (email.strip().lower(),))
        return cur.fetchone()


def get_user_by_id(user_id: int) -> dict[str, Any] | None:
    with _cursor() as cur:
        cur.execute("SELECT * FROM users WHERE id = %s", (user_id,))
        return cur.fetchone()


def get_tenant(tenant_id: int) -> dict[str, Any] | None:
    with _cursor() as cur:
        cur.execute("SELECT * FROM tenants WHERE id = %s", (tenant_id,))
        return cur.fetchone()


def get_tenant_token_version(tenant_id: int) -> int:
    tenant = get_tenant(tenant_id)
    if not tenant:
        return 0
    return int(tenant.get("token_version") or 0)


def bump_tenant_token_version(tenant_id: int) -> int:
    """Increment token_version — all outstanding JWTs for tenant become invalid."""
    with _cursor() as cur:
        cur.execute(
            """
            UPDATE tenants SET token_version = token_version + 1
            WHERE id = %s
            RETURNING token_version
            """,
            (tenant_id,),
        )
        row = cur.fetchone()
        if row is None:
            raise ValueError(f"tenant {tenant_id} not found")
        return int(row["token_version"])


def list_tenants_with_users() -> list[dict[str, Any]]:
    with _cursor() as cur:
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
    with _cursor() as cur:
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
    with _cursor() as cur:
        cur.execute(
            """
            SELECT 1 FROM subscriptions
            WHERE tenant_id = %s AND expires_at > %s
            LIMIT 1
            """,
            (tenant_id, _now()),
        )
        return cur.fetchone() is not None


def subscription_info_from_expires(expires_at: Any) -> dict[str, Any]:
    if expires_at is None:
        return {"active": False, "expires_at": None}
    if expires_at <= _now():
        return {"active": False, "expires_at": None}
    return {
        "active": True,
        "expires_at": expires_at.isoformat()
        if hasattr(expires_at, "isoformat")
        else str(expires_at),
    }


def subscription_info(tenant_id: int | None) -> dict[str, Any]:
    if tenant_id is None:
        return {"active": True, "expires_at": None}
    with _cursor() as cur:
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


def count_subscriptions_expiring(within_days: int = 7) -> int:
    """Tenants with active sub expiring within N days (not yet expired)."""
    now = _now()
    with _cursor() as cur:
        cur.execute(
            """
            SELECT COUNT(DISTINCT tenant_id) AS n FROM subscriptions
            WHERE expires_at > %s
              AND expires_at <= %s + make_interval(days => %s)
            """,
            (now, now, within_days),
        )
        row = cur.fetchone()
    return int(row["n"] if row else 0)


def list_expiring_subscriptions(within_days: int = 7) -> list[dict[str, Any]]:
    """Active subscriptions expiring within N days, with tenant info."""
    now = _now()
    with _cursor() as cur:
        cur.execute(
            """
            SELECT t.id AS tenant_id, t.institution_name, u.email,
                   s.expires_at,
                   EXTRACT(day FROM s.expires_at - %s)::int AS days_left
            FROM subscriptions s
            JOIN tenants t ON t.id = s.tenant_id
            JOIN users u ON u.tenant_id = t.id AND u.role = 'user'
            WHERE s.expires_at > %s
              AND s.expires_at <= %s + make_interval(days => %s)
              AND s.expires_at = (
                  SELECT MAX(s2.expires_at) FROM subscriptions s2
                  WHERE s2.tenant_id = t.id AND s2.expires_at > %s
              )
            ORDER BY s.expires_at ASC
            """,
            (now, now, now, within_days, now),
        )
        return list(cur.fetchall())


def tenants_recently_expired(since_hours: int = 24) -> list[dict[str, Any]]:
    """Tenants whose latest subscription expired within the last N hours."""
    now = _now()
    with _cursor() as cur:
        cur.execute(
            """
            SELECT t.id AS tenant_id, t.institution_name, u.email,
                   MAX(s.expires_at) AS expired_at
            FROM subscriptions s
            JOIN tenants t ON t.id = s.tenant_id
            JOIN users u ON u.tenant_id = t.id AND u.role = 'user'
            GROUP BY t.id, t.institution_name, u.email
            HAVING MAX(s.expires_at) <= %s
               AND MAX(s.expires_at) > %s - make_interval(hours => %s)
            ORDER BY expired_at DESC
            """,
            (now, now, since_hours),
        )
        return list(cur.fetchall())


def ping_latency_ms() -> float | None:
    """PostgreSQL round-trip latency in ms, or None on failure."""
    import time

    t0 = time.perf_counter()
    try:
        if not ping():
            return None
        return (time.perf_counter() - t0) * 1000.0
    except Exception:
        return None


def log_impersonation(admin_user_id: int, target_tenant_id: int) -> None:
    with _cursor() as cur:
        cur.execute(
            """
            INSERT INTO impersonation_log (admin_user_id, target_tenant_id)
            VALUES (%s, %s)
            """,
            (admin_user_id, target_tenant_id),
        )


def admin_exists() -> bool:
    with _cursor() as cur:
        cur.execute("SELECT 1 FROM users WHERE role = 'admin' LIMIT 1")
        return cur.fetchone() is not None


def get_tenant_user(tenant_id: int) -> dict[str, Any] | None:
    with _cursor() as cur:
        cur.execute(
            "SELECT * FROM users WHERE tenant_id = %s AND role = 'user' LIMIT 1",
            (tenant_id,),
        )
        return cur.fetchone()


def delete_tenant(tenant_id: int) -> bool:
    with _cursor() as cur:
        cur.execute(
            "DELETE FROM impersonation_log WHERE target_tenant_id = %s",
            (tenant_id,),
        )
        cur.execute("DELETE FROM tenants WHERE id = %s", (tenant_id,))
        return cur.rowcount > 0


def revoke_token(jti: str, expires_at: datetime) -> None:
    with _cursor() as cur:
        cur.execute(
            """
            INSERT INTO revoked_tokens (jti, expires_at)
            VALUES (%s, %s) ON CONFLICT (jti) DO NOTHING
            """,
            (jti, expires_at),
        )


def is_token_revoked(jti: str) -> bool:
    with _cursor() as cur:
        cur.execute(
            """
            SELECT 1 FROM revoked_tokens
            WHERE jti = %s AND expires_at > %s
            LIMIT 1
            """,
            (jti, _now()),
        )
        return cur.fetchone() is not None


def cleanup_revoked_tokens() -> int:
    """Delete expired rows from revoked_tokens. Returns deleted count."""
    with _cursor() as cur:
        cur.execute("DELETE FROM revoked_tokens WHERE expires_at < %s", (_now(),))
        return cur.rowcount or 0


def close() -> None:
    global _pool
    if _pool is not None:
        with contextlib.suppress(Exception):
            _pool.close()
        _pool = None


def _self_check() -> None:
    """ponytail: smoke без реального PG — только импорт pool API."""
    assert _pool is None
