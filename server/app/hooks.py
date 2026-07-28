"""Точки расширения для серверной логики."""

from __future__ import annotations


def before_start() -> None:
    from server.app.config import is_server_mode

    if not is_server_mode():
        return

    from server.app import auth, db_pg
    from server.app.config import ADMIN_EMAIL, ADMIN_PASSWORD
    from server.app.tenant_init import init_global_db

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
    from server.app.config import is_server_mode

    if not is_server_mode():
        return
    from server.app import db_pg

    db_pg.close()
