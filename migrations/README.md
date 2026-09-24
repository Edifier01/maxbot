# PostgreSQL migrations (server mode)

При создании нового PostgreSQL volume Docker Compose монтирует в
`/docker-entrypoint-initdb.d/` только `schema_pg.sql`. Он создаёт bootstrap
схему и `schema_migrations`. Файлы из `migrations/*.sql` туда не монтируются:
при старте приложения их в лексикографическом порядке применяет
`app/db_pg.py`.

Для уже применённых миграций runner хранит SHA-256 и останавливает запуск при
изменении файла. Не редактируйте такие файлы. Для новой схемы добавьте
следующий `00N_short_name.sql`; по возможности делайте изменения добавочными
и повторяемыми.

Перед применением на рабочей базе нужны согласованный бэкап PostgreSQL и
`max_server_data`, проверка восстановления и recovery hold. Порядок описан в
`docs/PRODUCTION-OPS.md` и `docs/audit/migrations.md`. Автоматических down
миграций нет.
