# Production ops — deploy, Celery, backup

Runbook для VPS после `bootstrap-vps.sh` и первого `deploy.sh`.

## D-1 — Deploy verify

### Pre-deploy checklist

- [ ] CI зелёный (`server-smoke`, `compose-config`, `server-e2e`)
- [ ] `.env` без `change-me*`
- [ ] `bash scripts/backup-volumes.sh` (перед каждым prod deploy)
- [ ] DNS A-запись → IP VPS

### Deploy

```bash
bash scripts/deploy.sh          # build + up + health
bash scripts/verify_deploy.sh   # полная проверка
```

`verify_deploy.sh` проверяет:

1. `docker compose config -q`
2. Статус сервисов (`docker compose ps`)
3. `/api/health` внутри `app` (`db_ok: true`)
4. HTTPS через Caddy (если `DOMAIN` не example.com)
5. Celery worker ping (если `USE_CELERY=1`)

Переменные:

| Var | Default | Описание |
|-----|---------|----------|
| `CHECK_HTTPS` | `1` | `0` — пропустить curl к DOMAIN |

### Rollback

```bash
cd /opt/maxsender
git checkout <prev-commit>
docker compose up --build -d
bash scripts/verify_deploy.sh
# при сбое данных:
bash scripts/restore-volumes.sh ./backups/<stamp>
```

### GitHub Actions deploy

Workflow `.github/workflows/deploy.yml` — после успешного CI, SSH на VPS, `git reset --hard`, `docker compose up -d`, health с `db_ok`.

---

## D-2 — Celery profile

In-process worker pool достаточен по умолчанию (`USE_CELERY=0`). Celery — для горизонтального масштаба с общим Redis и volume.

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

**Критично:** `max_server_data` — ключ шифрования сессий. Без него сессии не расшифровать.

**Vault в server mode:** сессии шифруются автоматически ключом `.app_key` в data-dir tenant/global. Пароль vault в UI не используется — admin и пользователи работают без разблокировки.

### PostgreSQL migrations

Fresh install: `initdb.d` монтирует только `schema_pg.sql` (таблица `schema_migrations`). Все SQL из `migrations/*.sql` применяет Python runner (`db_pg._apply_pending_migrations`) при старте приложения. Новые миграции добавляйте только в `migrations/` — **не** в `docker-entrypoint-initdb.d`.

### Создание бэкапа

```bash
bash scripts/backup-volumes.sh
# → ./backups/YYYYMMDD-HHMMSS/{pg.dump,data.tar.gz,README.txt}
```

Cron (ежедневно, 03:00):

```cron
0 3 * * * cd /opt/maxsender && bash scripts/backup-volumes.sh /var/backups/maxsender/$(date +\%Y\%m\%d) >> /var/log/maxsender-backup.log 2>&1
```

Копируйте каталог бэкапа off-site (`rsync`, S3, другой сервер).

### Восстановление

```bash
bash scripts/restore-volumes.sh ./backups/20260729-030000
```

Скрипт останавливает `app`/`celery-worker`, восстанавливает PG и data volume, поднимает стек и вызывает `verify_deploy.sh`.

### Ручной PG-only restore

```bash
docker compose exec -T postgres pg_restore -U maxsender -d maxsender --clean --if-exists \
  < backups/<stamp>/pg.dump
```

### Ручной data-only restore

```bash
docker compose stop app celery-worker
docker compose run --rm --no-deps \
  -v max_server_data:/data \
  -v "$(pwd)/backups/<stamp>:/backup:ro" \
  alpine sh -c 'find /data -mindepth 1 -delete && tar xzf /backup/data.tar.gz -C /data'
docker compose up -d
```

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

`WS /ws/status` — auth первым сообщением после connect: `{"type":"auth","token":"<JWT>"}` (server) или `{"type":"auth","pin":"..."}` (desktop). Query `?token=` больше не используется.

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

### Admin API

`GET /api/admin/subscriptions/expiring?days=7` — список истекающих подписок.

### Register rollback

При ошибке `init_tenant_db` после register — PG tenant/user удаляются, `data/tenants/{id}/` очищается.

### Проверка после deploy

```bash
curl -s https://$DOMAIN/api/health | python3 -m json.tool
curl -s https://$DOMAIN/metrics | rg 'max_sender_(pg_up|redis_up|subscriptions)'
curl -s -H "Authorization: Bearer $ADMIN_JWT" \
  "https://$DOMAIN/api/admin/subscriptions/expiring?days=7" | python3 -m json.tool
```
