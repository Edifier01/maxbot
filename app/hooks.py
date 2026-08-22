"""Точки расширения для серверной логики."""

from __future__ import annotations

from app.config import is_server_mode
from app.runtime import main as app_main


def before_start() -> None:
    if not is_server_mode():
        return

    from app import auth, db_pg, instance_lock
    from app.config import (
        ADMIN_EMAIL,
        ADMIN_PASSWORD,
        require_jwt_secret,
        require_production_secrets,
    )
    from app.tenant_init import init_global_db, reconcile_tenant_quarantines

    require_jwt_secret()
    require_production_secrets()
    instance_lock.acquire(app_main.ROOT)
    try:
        db_pg.init_schema()
        reconciled = reconcile_tenant_quarantines(
            app_main.ROOT, lambda tenant_id: db_pg.get_tenant(tenant_id) is not None
        )
        if any(reconciled.values()):
            app_main.append_log(f"Tenant quarantine reconciliation: {reconciled}")
        init_global_db(app_main)

        if ADMIN_EMAIL and ADMIN_PASSWORD and not db_pg.admin_exists():
            db_pg.create_user(
                ADMIN_EMAIL,
                auth.hash_password(ADMIN_PASSWORD),
                tenant_id=None,
                role="admin",
            )
    except BaseException:
        instance_lock.release()
        raise


def after_shutdown() -> None:
    from app.config import is_server_mode

    if not is_server_mode():
        return
    from app import db_pg, instance_lock

    try:
        db_pg.close()
    finally:
        instance_lock.release()
