# PostgreSQL migrations (server mode)

## Fresh install

1. Docker Compose монтирует только `schema_pg.sql` в `/docker-entrypoint-initdb.d/` для bootstrap `schema_migrations`.
2. При старте приложения Python runner применяет неучтённые `migrations/*.sql`, включая `001_saas_core.sql`.

При старте app `db_pg.init_schema()` применяет bootstrap и все неучтённые `*.sql` из этой папки.
Для применённых миграций сохраняется SHA-256; изменение уже применённого SQL
останавливает запуск с ошибкой checksum mismatch. Исправления оформляйте новой миграцией.

## Новая миграция

1. Создайте `00N_short_name.sql` (лексикographic sort).
2. Используйте `CREATE TABLE IF NOT EXISTS` / `ALTER TABLE` — идempotent где возможно.
3. На prod: бэкап volume → `docker compose exec postgres pg_dump ...` → deploy → проверка.

## Rollback

Откат только вручную через SQL + restore из бэкапа. Авто-down миграций нет (ponytail).
