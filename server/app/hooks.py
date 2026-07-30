"""Точки расширения для серверной логики."""

from __future__ import annotations


def before_start() -> None:
    from app.config import is_server_mode

    if not is_server_mode():
        return

    from app import auth, db_pg
    from app.config import ADMIN_EMAIL, ADMIN_PASSWORD, require_jwt_secret
    from app.tenant_init import init_global_db

    require_jwt_secret()
    db_pg.init_schema()

    import main as app_main

    init_global_db(app_main)

    if ADMIN_EMAIL and ADMIN_PASSWORD and not db_pg.admin_exists():
        db_pg.create_user(
            ADMIN_EMAIL,
            auth.hash_password(ADMIN_PASSWORD),
            tenant_id=None,
            role="admin",
        )


def after_shutdown() -> None:
    from app.config import is_server_mode

    if not is_server_mode():
        return
    from app import db_pg

    db_pg.close()
