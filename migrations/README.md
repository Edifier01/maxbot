# PostgreSQL migrations (server mode)

## Fresh install

1. `schema_pg.sql` — bootstrap (`schema_migrations`).
2. `001_saas_core.sql` — SaaS-таблицы.

При старте app `db_pg.init_schema()` применяет bootstrap и все неучтённые `*.sql` из этой папки.
Для применённых миграций сохраняется SHA-256; изменение уже применённого SQL
останавливает запуск с ошибкой checksum mismatch. Исправления оформляйте новой миграцией.

Docker Postgres (initdb) монтирует те же файлы в `/docker-entrypoint-initdb.d/`.

## Новая миграция

1. Создайте `00N_short_name.sql` (лексикographic sort).
2. Используйте `CREATE TABLE IF NOT EXISTS` / `ALTER TABLE` — идempotent где возможно.
3. На prod: бэкап volume → `docker compose exec postgres pg_dump ...` → deploy → проверка.

## Rollback

Откат только вручную через SQL + restore из бэкапа. Авто-down миграций нет (ponytail).
