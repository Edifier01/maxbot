# MAX Sender / MAXBOT

Репозиторий содержит единое приложение: корневой `main.py`, пакет `app/`,
статические страницы и SQLite/PostgreSQL runtime. Каталогов `desktop/` и
`server/` в поддерживаемой структуре нет.

## Локальный запуск без MAX-действий

Для Python 3.12 используйте из корня проекта:

```bash
.venv/bin/python -m app.main --no-browser
```

На Windows локальный launcher `run.bat` запускает Docker Compose, а не
production MAX-квалификацию. Автоматические тесты используют только фиктивные
данные и fake/mocked boundaries; они не выполняют SMS, login, send, join,
probe, history, read или reaction.

## Docker Compose server mode

`Dockerfile` и `docker-compose.yml` собирают server mode с одним владельцем
кампании `app`; Celery остаётся trigger-only профилем. Образы и Python
зависимости зафиксированы в manifests/lock-файлах. Для операционного запуска
оператор создаёт защищённый `.env` из `.env.example`, заполняет секреты и
запускает только на тестовом или отдельно авторизованном окружении:

```bash
cp .env.example .env
bash scripts/deploy.sh
bash scripts/verify_deploy.sh
```

`.env` не создаётся автоматическими проверками и не должен попадать в Git.
`verify_deploy.sh` считает readiness успешным только после валидного ответа
health с `db_ok: true`; неуспешные попытки завершаются ненулевым кодом.

## Поддерживаемые границы

- `maxapi-python` закреплён строго на `2.4.1`; transport и session identity
  проверяются отдельным runtime adapter.
- Внешние MAX-действия fail-closed при отсутствии authorization record или
  recovery release. Локальная готовность не является production proof.
- Schema changes additive/idempotent; до migration/deploy нужен согласованный
  backup и restore rehearsal. См. `docs/audit/migrations.md` и
  `docs/PRODUCTION-OPS.md`.
- Frozen EXE/PyInstaller build в текущем HEAD отсутствует и не поддерживается;
  Windows launcher/поддержка ограничены описанным локальным Python/Docker
  workflow до отдельной проверки.

## Проверки

```bash
.venv/bin/python -m pytest tests/ -q
.venv/bin/python -m compileall -q main.py antiban_core.py celery_worker.py app tests static
docker compose config -q
```

Полный suite, Docker daemon, PostgreSQL/Redis, rendered browser и production
verification должны быть отмечены фактическими exit-кодами и не заменяются
документом о готовности.
