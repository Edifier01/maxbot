def init_global_db(main_module) -> None:
    from app.tenant import tenant_scope

    ensure_global_data(main_module.ROOT)
    with tenant_scope(use_global_data=True, role="admin"):
        # Always init/migrate: empty file from early _global_conn() has no tables.
        main_module.init_db()
        main_module._try_legacy_unlock()
