# MAX Sender / MAXBOT

Репозиторий содержит единое приложение: корневой `main.py`, пакет `app/`,
статические страницы и SQLite/PostgreSQL runtime. Каталогов `desktop/` и
`server/` в поддерживаемой структуре нет.

Карта рабочих инструкций и исторических материалов: [`docs/README.md`](docs/README.md).

## Локальный запуск без MAX-действий

Установите зависимости для Python 3.12 из корня проекта:

```bash
python -m pip install -r requirements.lock -r requirements-server.lock
python -m app.main --no-browser
```

На Windows используйте `py -3.12` вместо `python`, если так настроен Python
Launcher. Если создано локальное виртуальное окружение, запускайте команды
через `.venv\Scripts\python.exe` в PowerShell. `run.bat` запускает Docker
Compose, для которого нужен заполненный `.env`. Автоматические тесты
используют только фиктивные данные и fake/mocked boundaries; они не выполняют
SMS, login, send, join,
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

Для исправления роли существующего администратора используется
`bash scripts/ensure-admin.sh`. Смена пароля — отдельная авторизованная
операция `bash scripts/recover-admin.sh`; она не выполняется автоматически и
отзывает ранее выданные JWT.

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
python -m pytest tests/ -q
python -m compileall -q main.py antiban_core.py celery_worker.py app tests static
```

Для pytest установите также `requirements-dev.txt`. Основной suite запускайте
с `MAX_TEST=1`, `MAX_SERVER_MODE=1` и тестовым `JWT_SECRET`, без `DATABASE_URL`;
PostgreSQL-модули запускаются отдельным процессом с тестовой базой. Для
проверки Compose нужны тестовые обязательные переменные из
`.github/workflows/ci.yml`. Браузерный fixture и команда
`npm run browser:e2e` также описаны в CI. Эти локальные проверки не являются
подтверждением готовности production-развёртывания.
