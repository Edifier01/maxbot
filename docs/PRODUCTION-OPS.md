# Production ops — deploy, Celery, backup

Runbook для VPS после `bootstrap-vps.sh` и первого `deploy.sh`.

> Статус на 2026-09-24: пользователь подтвердил наличие MAX-разрешений.
> **NO-GO** сохраняется до exact-SHA CI/review, staging/DR и release evidence.
> Текущие блокеры и порядок закрытия описаны в
> [аудите](audit/PROJECT-AUDIT-2026-09-24.md) и
> [плане запуска](PRODUCTION-LAUNCH-PLAN-2026-09-24.md). Примеры ниже —
> целевые процедуры после исправлений и проверки на изолированном стенде.

## D-1 — Deploy verify

### Platform authorization record

Compose sets `MAX_PLATFORM_AUTHORIZATION_FILE` to
`/app/authorization/platform-authorization.json` and mounts the host directory
`MAX_PLATFORM_AUTHORIZATION_DIR` read-only. The runtime fails closed when the
record is missing, malformed, expired, or does not include the requested action.
The JSON contains only a non-secret approval reference, declared transport,
action scope, and validity window; it is not proof that the underlying contract
or permission exists. A reviewer must verify that underlying authorization
separately. Runtime validation only applies the record's declared scope and
expiry, and does not create or renew authorization.

### Recovery hold

Server mode keeps `/app/control/recovery-hold.json` in the separate
`max_server_control` volume. It is not part of the restored `max_server_data`
archive. While the file exists, scheduler, manual start/test, and every
guarded MAX adapter call are held; the health response reports
`max_external_actions: held` and `recovery_hold: true`. This hold is not
automatically removed by startup, health checks, or restore completion.

Release is a separate operator action after the restored revision and
platform authorization have been reviewed. `release-recovery-hold.py` is
copied into the app image, and deploy prepares `/app/control` ownership for
UID 10001. Staging must still exercise the expected/mismatched revision path
and evidence write; do not remove the hold manually.

Both `scripts/deploy.sh` and the GitHub deploy workflow now create
`deploy-<40-char-SHA>` in `max_server_control` before backup or stopping
services. Hold creation is atomic and refuses to overwrite an existing hold;
the deployment leaves it active. After the release record and canary target
are approved, release only the exact revision and retain a non-secret change
reference in evidence:

```bash
docker compose exec -T app python /app/scripts/release-recovery-hold.py \
  --expected-revision "deploy-<40-char-SHA>" \
  --authorization-reference "<change-id>"
REQUIRE_MAX_ACTIONS=1 bash scripts/verify_deploy.sh
```

The runtime readiness state now checks both the recovery hold and the
authorization record's send scope, user-session transport and expiry.
`REQUIRE_MAX_ACTIONS=1 bash scripts/verify_deploy.sh` fails if either the hold
is active or MAX actions are not authorized. Run this final check only after
the operator has explicitly released the reviewed hold; ordinary deploy
verification can complete with the hold active.

### PyMax 2.4.1 lifecycle boundary

The application is pinned to `maxapi-python==2.4.1`. Before any client network
call, the encrypted session is restored, its identity is checked or migrated
offline once, and the runtime uses `Client.connect()` with the persisted device
ID, instance ID, and user-agent. Runtime catalog resolution is local-only;
`VersionCatalog(remote=True)` is not part of the production path. The effective
TCP target is `api2.oneme.ru:443`; reconnect, relogin, and telemetry remain
disabled while session persistence remains enabled.

Before a deploy, stop the campaign owner, create the ordinary encrypted-volume
backup, and enable the S03 recovery hold. Rollback uses the previous complete
image/commit with the dependency lifecycle pinned by that image rather than
replacing only the wheel inside the new code. The nullable `user_agent` session
column remains backward-readable for that rollback and is not removed.

After deploy, run offline/session-schema checks first and then local fake smoke
checks. A real canary login or send is outside this task and requires a separate
bounded runbook with explicitly approved account, group, action scope, and stop
conditions.

### Pre-deploy checklist

- [ ] CI зелёный (`server-smoke`, `compose-config`, `server-e2e`)
- [ ] `.env` без `change-me*`
- [ ] `bash scripts/backup-volumes.sh` (перед каждым prod deploy)
- [ ] recovery hold включён до restore/deploy; release остаётся отдельным шагом
- [ ] кодовые исправления A02–A07/A09–A12 прошли exact-SHA CI/review; release gates A08/A13 закрыты
- [ ] DNS A-запись → IP VPS

### Deploy

```bash
bash scripts/deploy.sh          # build + up + health
bash scripts/verify_deploy.sh   # полная проверка
```

The deploy command enables a recovery hold before taking the backup; the
revision is `deploy-$(git rev-parse HEAD)`. The GitHub workflow uses the exact
selected `CANDIDATE_SHA`. In both paths, review and explicitly release that
hold only after production readiness and canary scope are documented.

Образ запускает приложение как UID/GID `10001`. `deploy.sh` после сборки
однократно выравнивает ownership существующих `max_server_data` и
`max_server_control` volumes через короткий root-контейнер и затем запускает
постоянные сервисы без root.

`verify_deploy.sh` проверяет:

1. `docker compose config -q`
2. Статус сервисов (`docker compose ps`)
3. `/api/health` внутри `app` (`db_ok: true`)
4. HTTPS через Caddy (если `DOMAIN` не example.com)
5. Celery worker ping (если `USE_CELERY=1`)

`REQUIRE_MAX_ACTIONS=1` requires
`max_external_actions: authorized` and `recovery_hold: false`; the health state
also checks the configured authorization record. This is a technical gate and
does not establish the underlying platform permission.

Переменные:

| Var | Default | Описание |
|-----|---------|----------|
| `CHECK_HTTPS` | `1` | `0` — пропустить curl к DOMAIN |

### Rollback

Проверьте совместимость предыдущего образа с текущей схемой и сохранёнными
сессиями. Если нужно восстановить данные, используйте согласованный бэкап
PostgreSQL и `max_server_data` с recovery hold по процедуре ниже.

```bash
cd /opt/maxsender
git checkout <prev-commit>
docker compose up --build -d
bash scripts/verify_deploy.sh
# при сбое данных:
bash scripts/restore-volumes.sh ./backups/<stamp>
```

### GitHub Actions deploy

Workflow `.github/workflows/deploy.yml` запускается только вручную
(`workflow_dispatch`). Workflow теперь передаёт `CANDIDATE_SHA` через
`appleboy/ssh-action.with.envs`; перед production всё ещё нужен staging прогон,
подтверждающий checkout именно выбранного SHA, backup, Compose и health.
Deploy chown-ит `/app/control` для app UID 10001. Локальная правка workflow не
является свидетельством успешного VPS deploy.

---

## D-2 — Celery profile

In-process worker pool is the campaign runtime (`USE_CELERY=0` by default). Celery is **trigger-only**: the worker HTTP-POSTs `/api/campaign/start` with `INTERNAL_SERVICE_TOKEN` + `X-Tenant-Id` into **one** in-process `app`. The campaign runtime registry is process-local. Multiple campaign-owning `app` replicas are **not** supported.

При server startup приложение берёт POSIX lock `/app/data/.app-instance.lock`.
Второй `app`, подключённый к тому же `max_server_data`, завершится с ошибкой до
инициализации кампаний. Это технически защищает Compose/VPS от случайного
`--scale app=2`; для нескольких хостов всё равно нужен отдельный distributed
campaign coordinator.

Deploy with `--profile celery` only as a trigger worker, still one `app` replica. Do not scale campaigns across machines via extra app replicas.

### Включение

```bash
# .env
USE_CELERY=1

docker compose --profile celery up --build -d
bash scripts/verify_deploy.sh
```

### Smoke (без MAX client)

```bash
docker compose exec -T celery-worker celery -A celery_worker.app inspect ping
docker compose exec -T celery-worker python -c "
from celery_worker import ping
assert ping()['ok']
print('celery ping OK')
"
```

Unit-тесты: `tests/test_celery_worker.py`.

Задача `max_sender.enqueue_campaign_start` вызывает `POST /api/campaign/start` с `INTERNAL_SERVICE_TOKEN` — тот же токен, что в `.env` и middleware.

---

## D-3 — Backup / restore

### Что бэкапить

| Объект | Содержимое | Volume / путь |
|--------|------------|---------------|
| `max_server_data` | SQLite tenant DB, sessions, vault salt/key | compose volume |
| `max_server_pg` | users, tenants, JWT revoke | PostgreSQL 16 |
| `max_server_redis` | опционально | Celery broker state |
| `max_server_control` | recovery hold, auth epoch, release evidence | отдельный compose volume; backup переносит только минимальный `auth-state.json` с epoch, не переносит hold/release evidence |

Backup сохраняет auth epoch в `auth-state.json`, проверяет data tree и готовый
архив на plaintext `session.db` и прекращает операцию при его обнаружении.
Restore сравнивает epoch snapshot с целевым control volume, продвигает его и
создаёт recovery hold до замены данных; hold не снимается автоматически.
Cross-host backup/restore rehearsal остаётся обязательным перед эксплуатацией.
Все backup-каталоги секретны: они содержат vault key и зашифрованные сессии.

**Критично:** `max_server_data` — ключ шифрования сессий. Без него сессии не расшифровать.

**Vault в server mode:** сессии шифруются автоматически ключом `.app_key` в data-dir tenant/global. Пароль vault в UI не используется — admin и пользователи работают без разблокировки.

### PostgreSQL migrations

Fresh install: `initdb.d` монтирует только `schema_pg.sql` (таблица `schema_migrations`). Все SQL из `migrations/*.sql` применяет Python runner (`db_pg._apply_pending_migrations`) при старте приложения. Новые миграции добавляйте только в `migrations/` — **не** в `docker-entrypoint-initdb.d`.

Для существующих SQLite tenant DB перед обновлением проверьте копию базы. Новая
версия автоматически чинит устаревшее состояние `destination_verified=0` при
непустом `max_chat_id`; эта комбинация не создаётся текущим UI/API. Старый
`groups.proxy=''` с прокси у связанных профилей может быть как прерванным
legacy backfill, так и намеренно очищенным значением, поэтому просмотрите
кандидаты вручную и сохраните решение владельца:

```sql
SELECT id, name, max_chat_id
FROM groups
WHERE destination_verified=0 AND TRIM(COALESCE(max_chat_id, '')) <> '';

SELECT g.id, g.name, p.id AS profile_id, p.proxy
FROM groups g
JOIN group_profiles gp ON gp.group_id=g.id AND gp.is_enabled=1
JOIN profiles p ON p.id=gp.profile_id
WHERE TRIM(COALESCE(g.proxy, ''))=''
  AND TRIM(COALESCE(p.proxy, '')) <> ''
ORDER BY g.id, gp.order_index, p.id;
```

### Создание бэкапа

```bash
bash scripts/backup-volumes.sh
# → ./backups/YYYYMMDD-HHMMSS/{pg.dump,data.tar.gz,auth-state.json,README.txt}
```

Backup uses a short maintenance window: it records which app/celery services are running, stops writers, creates the PostgreSQL dump, checkpoints every SQLite WAL, saves the JWT auth epoch, archives `max_server_data`, rejects plaintext sessions and validates both archives, then restarts only the services that were running. An EXIT/INT/TERM trap also attempts restart after failure. This makes PostgreSQL + SQLite consistent relative to application writes. The script sets `umask 077` and `chmod 700` on the destination. Treat backup directories as secret (vault material).

Cron (ежедневно, 03:00):

```cron
0 3 * * * cd /opt/maxsender && bash scripts/backup-volumes.sh /var/backups/maxsender/$(date +\%Y\%m\%d) >> /var/log/maxsender-backup.log 2>&1
```

Копируйте каталог бэкапа off-site (`rsync`, S3, другой сервер).

### Восстановление

```bash
bash scripts/restore-volumes.sh ./backups/20260729-030000
# Автоматизированный DR (подтверждение принято вызывающей системой):
bash scripts/restore-volumes.sh --yes ./backups/20260729-030000
```

Скрипт останавливает `app`/`celery-worker`, перед data swap атомарно создаёт
recovery hold в отдельном control volume, затем делает extract+verify+swap data
volume (live children → `.outgoing-restore`, **without** deleting that dir yet)
и выполняет `pg_restore --exit-on-error --single-transaction`. If PG restore
fails, live data is swapped back from `.outgoing-restore` and the script exits
non-zero — a failed PG restore rolls the data volume back. The hold remains
active on success, failure, or health-check completion. The attempted restore
stays in leftover `.outgoing-restore` (inspect/remove before retry). On
success, `.outgoing-restore` is removed, the stack is started, and
`verify_deploy.sh` runs. An interrupted swap also leaves `.outgoing-restore` —
retry will not proceed while that directory exists.

### Восстановление одного хранилища

Отдельные PG-only и data-only команды исключены из runbook: данные PostgreSQL
и SQLite связаны, а ручная подмена тома обходит создание recovery hold. Для
рабочего восстановления используйте только `scripts/restore-volumes.sh` и
проверяйте результат по процедуре выше. Исключения требуют отдельного плана
восстановления и проверки согласованности данных.

---

## Мониторинг после деплоя (15 мин)

```bash
docker compose logs -f app
curl -s https://$DOMAIN/api/health | python3 -m json.tool
curl -s -H "Authorization: Bearer $INTERNAL_SERVICE_TOKEN" https://$DOMAIN/metrics | head
```

Алерты: `TELEGRAM_BOT_TOKEN` + `TELEGRAM_CHAT_ID` в `.env` (если настроены в приложении).

---

## D-4 — Ops alerts и subscription lifecycle

### Health (расширенный)

`GET /api/health` дополнительно:

| Поле | Описание |
|------|----------|
| `pg_latency_ms` | RTT PostgreSQL |
| `redis_ok` | `true`/`false`/`null` (null если Redis не настроен) |
| `subscriptions_expiring_7d` | Подписки, истекающие в 7 дней |
| `uptime_seconds` | Uptime процесса |

### Metrics

`GET /metrics` — gauges: `max_sender_pg_up`, `max_sender_redis_up`, `max_sender_subscriptions_expiring_7d`, `max_sender_uptime_seconds`.

**Auth:** только `Authorization: Bearer <INTERNAL_SERVICE_TOKEN>`. User JWT не принимается. Prometheus/scrape — передать service token в заголовке.

### WebSocket status

`WS /ws/status` — server mode: same-origin handshake с cookie `max_token` и
первое сообщение `{"type":"auth"}`; JSON-поле `token` не используется.
Локальный режим: первое сообщение `{"type":"auth","pin":"..."}`.
Query `?token=` не используется.

### Telegram ops (server mode)

При заданных `TELEGRAM_BOT_TOKEN` + `TELEGRAM_CHAT_ID`:

- PG недоступен
- Redis недоступен (если `REDIS_URL` задан)
- Circuit breaker ≥ `OPS_CIRCUIT_ALERT_THRESHOLD` (default 10)
- Подписка истекает через 7 / 1 день
- Подписка истекла → worker tenant остановлен

Dedupe: 15 мин на тип алерта.

### Auth rate limit (multi-replica)

| Var | Default | Описание |
|-----|---------|----------|
| `AUTH_RATE_LIMIT` | 10 | Попыток login/register |
| `AUTH_RATE_WINDOW_SEC` | 900 | Окно (сек) |
| `REDIS_URL` | — | Если задан — INCR в Redis; иначе in-memory |

### Campaign webhook

`webhook_url` accepts only HTTPS hosts explicitly listed in `WEBHOOK_ALLOWED_HOSTS` in `.env`, separated by commas. Leave it empty to disable webhooks. URLs outside that allowlist are rejected on save and skipped at runtime.

### Self-registration (`REGISTRATION_OPEN`)

Compose and `.env.example` default to `0` (closed; admin-created accounts only). Set `1` explicitly to enable self-registration for new institutions.

If the var is **unset in the app process**, `POST /api/auth/register` returns **403**. Compose `${REGISTRATION_OPEN:-0}` follows the same fail-closed policy. An existing production `.env` with `REGISTRATION_OPEN=1` stays open until the operator changes it.

При старте server также разбирает crash-leftovers `{tenant_id}.deleting`: если tenant ещё существует в PostgreSQL, каталог возвращается на место; если tenant уже удалён — quarantine очищается. Конфликт, когда существуют оба каталога, не удаляется автоматически и требует ручной проверки.

### Admin API

`GET /api/admin/subscriptions/expiring?days=7` — список истекающих подписок.

### Admin bootstrap and password recovery

`scripts/ensure-admin.sh` only repairs the role/tenant placement of the
configured admin; it does not change a password. For a separately authorized
password recovery, run the interactive command on the VPS:

```bash
bash scripts/recover-admin.sh
```

The operator must enter a non-secret authorization reference and the new
password twice. The password is sent only through stdin to a one-shot app
container and is never placed in command arguments, logs, `.env` or Git. The
command updates the selected admin in PostgreSQL, atomically records the
non-secret reference in the separate control volume, and invalidates all JWTs
issued before the recovery epoch; this is intentionally broader than only the
admin cookie. A failed database update leaves the conservative re-login gate
in place. Do not run this command without an approved change/reference.

### Register rollback

При ошибке `init_tenant_db` после register — PG tenant/user удаляются, `data/tenants/{id}/` очищается.

### Проверка после deploy

```bash
curl -s https://$DOMAIN/api/health | python3 -m json.tool
curl -s https://$DOMAIN/metrics | rg 'max_sender_(pg_up|redis_up|subscriptions)'
# Admin panel uses HttpOnly cookie max_token (not Bearer).
curl -s -b "max_token=$ADMIN_JWT" \
  "https://$DOMAIN/api/admin/subscriptions/expiring?days=7" | python3 -m json.tool
```
