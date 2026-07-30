# MAX Sender Server — Agent Review & Fix Plan

**Дата:** 2026-07-30  
**Статус базы:** Worker extraction phase 1 COMPLETED, pytest 44/4  
**Цель документа:** Пошаговое руководство для агентов по исправлению ошибок и улучшению проекта.

---

## Как пользоваться

1. Читать раздел полностью перед началом.
2. Каждый агент берёт один блок задач по своему домену.
3. После выполнения блока — запуск `pytest` + smoke-проверка.
4. Только после `verifier PASSED` — отмечать DONE.
5. Параллельные агенты **не** редактируют один файл в одном round.

---

## Карта доменов → агенты

| Блок | Агент | Приоритет |
|------|-------|-----------|
| P0-CRITICAL: Сломанные пути и изоляция данных | `backend-engineer` | Немедленно |
| P0-CRITICAL: Extraction breakages (NameError, missing imports) | `backend-engineer` | Немедленно |
| P1-HIGH: Security hardening | `security-engineer` | После P0 |
| P1-HIGH: Delete tenant — stop worker + revoke JWT | `backend-engineer` + `security-engineer` | После P0 |
| P2-MEDIUM: Performance (blocking I/O, N+1, indexes) | `backend-engineer` | После P1 |
| P2-MEDIUM: Docker / Caddy hardening | `devops-engineer` | После P0 |
| P3-LOW: Code quality, dead code | `backend-engineer` | Последний |
| Tests: дыры в покрытии | `qa-engineer` | Параллельно с P0 |

---

## БЛОК P0 — CRITICAL BUGS (исправить первыми)

### FIX-001 · `routes_messages.py` — NameError в upload

**Файл:** `app/routes_messages.py`, строки 32–42  
**Симптом:** `POST /api/messages/upload` падает с `NameError: name 'm' is not defined` при любом вызове.  
**Причина:** `upload_messages` использует `m.MAX_UPLOAD_BYTES`, `m.save_messages_file`, `m.append_log` без `import main as m`.  
**Подтверждение:** `get_messages` (строка 17) импортирует инлайн — `upload_messages` не импортирует.

**Исправление:**
```python
@router.post("/api/messages/upload")
async def upload_messages(file: UploadFile = File(...)):
    import main as m           # ← добавить эту строку
    content = await file.read(m.MAX_UPLOAD_BYTES + 1)
    ...
```

**Тест после:** `curl -X POST /api/messages/upload -F file=@test.txt` — должен вернуть `{"count": N}`.

---

### FIX-002 · `campaign_worker.py` — undefined `_pool_done_announced`

**Файл:** `app/campaign_worker.py`, ~строки 270–330  
**Симптом:** При `worker_pool_size > 1` и завершении всех воркеров → `NameError: name '_pool_done_announced' is not defined`. Кампания зависает.  
**Причина:** `claim_next_job` и/или логика завершения пула используют `global _pool_done_announced` (никогда не объявлена на уровне модуля), тогда как правильное место — `RUNTIME.pool_done_announced`.

**Исправление:**
1. Найти все `_pool_done_announced` в `campaign_worker.py`.
2. Заменить на `RUNTIME.pool_done_announced` (поле уже есть в `CampaignRuntime`).
3. Удалить строку `global _pool_done_announced` если есть.

**Проверка:** `grep -n "_pool_done_announced" app/campaign_worker.py app/campaign_runtime.py`

---

### FIX-003 · `campaign_worker.py` — отсутствующие импорты

**Файл:** `app/campaign_worker.py`  
**Симптом:** `NameError` при Telegram-уведомлениях, отмене пула, schedule tick.

**Пропущенные импорты** (добавить в начало файла рядом с остальными):
```python
import os            # нужен для os.environ (Telegram credentials)
import contextlib    # нужен для contextlib.suppress в pool cancel cleanup
from fastapi import HTTPException  # нужен для schedule tick
```

**Проверка:** `python -c "import app.campaign_worker"` — не должно быть ошибок.

---

### FIX-004 · `app/main.py` (Docker entrypoint) — `_shutting_down` не существует

**Файл:** `app/main.py`, строки ~33–36  
**Симптом:** SIGTERM/SIGINT обработчик падает с `AttributeError: module 'main' has no attribute '_shutting_down'` — vault не шифруется при shutdown.  
**Причина:** Флаг `_shutting_down` перенесён в `RUNTIME.shutting_down` / `REGISTRY.app.shutting_down` во время extraction, ссылка в entrypoint не обновлена.

**Исправление:** Найти в `app/main.py`:
```python
app_main._shutting_down = True
```
Заменить на:
```python
from app.campaign_runtime import RUNTIME
RUNTIME.shutting_down = True
```
Убедиться что `CampaignRuntime` имеет атрибут `shutting_down: bool = False`.

---

### FIX-005 · `routes_dashboard.py` — `m._backups_dir()` не существует

**Файл:** `app/routes_dashboard.py`, строка ~29  
**Симптом:** `GET /api/backups` → `AttributeError: module 'main' has no attribute '_backups_dir'`.  
**Причина:** Extraction leftover — функция была удалена или переименована в `main.py`.

**Исправление:**
1. Проверить `main.py` — есть ли там `_backups_dir`, `BACKUPS`, или аналог.
2. Если нет — добавить хелпер в `main.py`:
```python
def _backups_dir() -> Path:
    return _resolve_data_dir() / "backups"
```
3. Убедиться что `BACKUPS` тоже пересчитывается per-tenant (не глобальный).

---

### FIX-006 · Tenant isolation — SQLite и vault шарятся между тенантами

**Файлы:** `main.py` ~342–359, ~841–842, ~250, ~1090–1236  
**Серьёзность:** КРИТИЧЕСКАЯ — нарушение изоляции данных, тенант A видит данные тенанта B.  
**Причина:** `_db_path()` и `_conn()` возвращают глобальный `DB_PATH` (вычисленный при старте), а не `_resolve_data_dir() / "app.db"`. Vault и sessions тоже глобальные.

**Исправление (поэтапно, каждый шаг — отдельный коммит):**

**Шаг А — `_db_path()`:**
```python
# было:
def _db_path() -> Path:
    return DB_PATH  # глобальный

# стало:
def _db_path() -> Path:
    return _resolve_data_dir() / "app.db"
```

**Шаг Б — `_conn()` уже использует `_resolve_data_dir()`?** Проверить:
```python
grep -n "_conn\|_db_path\|DB_PATH\|_resolve_data_dir" main.py | head -40
```
Убедиться что `_conn()` открывает `_db_path()`, а не `DB_PATH`.

**Шаг В — Sessions:**  
`_auth_sessions` — глобальный dict, ключ `profile_id` → коллизия между тенантами.  
Изменить ключ на `(tenant_id, profile_id)`:
```python
# было: _auth_sessions[profile_id]
# стало: _auth_sessions[(tenant_id, profile_id)]
```
Где `tenant_id = get_tenant_id()` из `app.tenant`.

**Шаг Г — Process-global `_log`:**  
`append_log` пишет в один глобальный список. `/api/log` отдаёт всем тенантам.  
Минимальный фикс: скопировать только записи текущего тенанта, если `is_server_mode()`.  
Полный фикс: `_log` → dict keyed by `tenant_id`.

**Тест после:** написать `tests/test_tenant_isolation_sqlite.py`:
```python
# tenant A пишет профиль → tenant B не видит его через _conn()
```

---

## БЛОК P1 — HIGH SEVERITY

### FIX-007 · Delete tenant — не останавливает воркер и не ревокает JWT

**Файл:** `app/routes_admin.py` ~110–121, `app/db_pg.py` ~347–354  
**Серьёзность:** HIGH — активный воркер тенанта продолжает рассылку после удаления; JWT остаются валидными.

**Исправление:**
```python
# В routes_admin.py перед db_pg.delete_tenant(tenant_id):
from app.campaign_runtime import REGISTRY
worker = REGISTRY.get_worker(tenant_id)
if worker and worker.running:
    worker.stop()  # или вызвать эндпоинт /api/stop

# После — ревокация всех токенов тенанта:
# Вариант A (быстрый): добавить поле token_version в tenants,
#                      инкрементировать его, проверять в middleware
# Вариант B (текущий стек): db_pg.revoke_all_tenant_tokens(tenant_id)
#                            (нужна новая функция + индекс)
```

---

### FIX-008 · `/metrics` и `/api/health` не защищены

**Файл:** `app/routes_monitor.py` ~54–101, ~104–166; `app/middleware.py` ~44–48  
**Серьёзность:** HIGH — раскрывает subscription counts, redis/pg статус, vault state, campaign counters.

**Исправление:**
```python
# Вариант A (рекомендован): ограничить в Caddyfile — только с localhost/VPN:
@internal {
    /metrics
    /api/health
}

# Вариант B: добавить Bearer-check с INTERNAL_SERVICE_TOKEN для /metrics
```

**Публичный `/api/health` оставить только:**
```json
{"ok": true, "db_ok": true}
```

---

### FIX-009 · JWT в WebSocket query string

**Файл:** `app/routes_monitor.py` ~24–25, ~176–178  
**Серьёзность:** HIGH — токен попадает в access logs, browser history.

**Исправление — первый WebSocket message auth:**
```python
# После accept():
msg = await ws.receive_text()
payload = json.loads(msg)
token = payload.get("token", "")
# валидировать token, затем продолжить
```

---

### FIX-010 · JWT lifetime 168h, secret не проверяет длину

**Файл:** `app/config.py` ~16–31  
**Серьёзность:** HIGH (security)

**Исправление:**
```python
def require_jwt_secret() -> str:
    secret = os.environ.get("JWT_SECRET", "").strip()
    if len(secret) < 32:  # было: просто not secret
        raise RuntimeError("JWT_SECRET must be at least 32 characters")
    return secret
```
JWT_EXPIRE_HOURS: рассмотреть снижение с 168h до 24h (access token) + отдельный refresh.

---

### FIX-011 · Открытая регистрация без invite/approval

**Файл:** `app/routes_auth.py` ~46–72  
**Серьёзность:** HIGH — кто угодно может создавать тенантов.

**Исправление (минимальное):**
```python
# env var REGISTRATION_OPEN=0 → отклонять запросы
if not os.environ.get("REGISTRATION_OPEN", "1") in ("1", "true"):
    raise HTTPException(403, "Регистрация закрыта. Обратитесь к администратору.")
```
По умолчанию production `.env` должен иметь `REGISTRATION_OPEN=0`.

---

## БЛОК P2 — MEDIUM (Performance + Architecture)

### FIX-012 · Блокирующий I/O в async handlers

**Файлы:** `app/db_pg.py` (sync pool), `main.py` ~2614 (proxy socket checks)  
**Серьёзность:** MEDIUM performance — может подвесить event loop.

**Исправление:**
```python
# Proxy checks в main.py:
result = await asyncio.to_thread(check_proxy, host, port)

# db_pg: psycopg_pool ConnectionPool — уже thread-safe, но вызовы sync.
# Обернуть тяжелые вызовы:
rows = await asyncio.to_thread(db_pg.list_tenants_with_users)
```

---

### FIX-013 · N+1 запрос в admin user list

**Файл:** `app/routes_admin.py` ~57–77  
**Серьёзность:** MEDIUM — `subscription_info(tid)` на каждую строку, `list_tenants_with_users` уже возвращает `subscription_expires`.

**Исправление:** убрать отдельный `subscription_info(tid)`, использовать `subscription_expires` из join-query.

---

### FIX-014 · SQLite без индексов на hot columns

**Файл:** `main.py` ~427–435 (schema `send_log`)  
**Серьёзность:** MEDIUM — full scan на dashboard/stats при большом `send_log`.

**Исправление** — добавить в schema creation:
```sql
CREATE INDEX IF NOT EXISTS idx_send_log_status_sent
    ON send_log(status, sent_at);
CREATE INDEX IF NOT EXISTS idx_send_log_profile_group
    ON send_log(profile_id, group_id, status);
```

---

### FIX-015 · Нет cleanup job для `revoked_tokens`

**Файл:** `app/db_pg.py`, `app/subscription_jobs.py`  
**Серьёзность:** MEDIUM — таблица растёт бесконечно.

**Исправление** — добавить в `subscription_jobs.py` периодическую задачу:
```python
async def _cleanup_revoked_tokens() -> None:
    with db_pg._cursor() as cur:
        cur.execute("DELETE FROM revoked_tokens WHERE expires_at < NOW()")
```
Запускать раз в сутки в существующем scheduler.

---

### FIX-016 · Migration TOCTOU race при параллельном старте

**Файл:** `app/db_pg.py` ~100–115  
**Серьёзность:** MEDIUM — concurrent restart может применить одну миграцию дважды.

**Исправление:**
```python
# Использовать advisory lock:
with _cursor(transaction=True) as cur:
    cur.execute("SELECT pg_advisory_xact_lock(12345)")  # фиксированный lock id
    if _migration_done(cur, version):
        continue
    cur.execute(sql)
    cur.execute("INSERT INTO schema_migrations (version) VALUES (%s) ON CONFLICT DO NOTHING", (version,))
```

---

### FIX-017 · Auth rate-limit fail-open + `_redis_failed` не восстанавливается

**Файл:** `app/auth_rate_limit.py` ~40–57, ~63–71  
**Серьёзность:** MEDIUM security — после падения Redis лимит уходит in-memory (per replica).

**Исправление:**
```python
# Добавить периодическую попытку переподключения:
_last_redis_retry: float = 0.0

def _try_redis(fn):
    global _redis_failed, _last_redis_retry
    if _redis_failed and time.time() - _last_redis_retry < 60:
        return None  # fail-open: in-memory fallback
    try:
        result = fn()
        _redis_failed = False
        return result
    except Exception:
        _redis_failed = True
        _last_redis_retry = time.time()
        return None
```

---

### FIX-018 · bcrypt 72-byte password truncation

**Файл:** `app/auth.py` ~16–24  
**Серьёзность:** LOW/MEDIUM security — bcrypt молча обрезает пароли > 72 байт.

**Исправление:**
```python
def hash_password(password: str) -> str:
    if len(password.encode()) > 72:
        raise ValueError("Пароль слишком длинный (максимум 72 байта)")
    return bcrypt.hashpw(password.encode(), bcrypt.gensalt()).decode()
```

---

## БЛОК P2 — Docker / Caddy (devops-engineer)

### FIX-019 · Caddy — нет security headers

**Файл:** `caddy/Caddyfile`  
**Исправление** — добавить блок headers:
```
header {
    Strict-Transport-Security "max-age=31536000; includeSubDomains"
    X-Content-Type-Options "nosniff"
    X-Frame-Options "DENY"
    Referrer-Policy "strict-origin-when-cross-origin"
    Content-Security-Policy "default-src 'self'; script-src 'self' 'unsafe-inline'; style-src 'self' 'unsafe-inline'"
}
```

### FIX-020 · Redis без пароля в compose

**Файл:** `docker-compose.yml`  
**Исправление:**
```yaml
redis:
  command: ["redis-server", "--requirepass", "${REDIS_PASSWORD}"]
environment:
  - REDIS_PASSWORD=${REDIS_PASSWORD}
```
Добавить `REDIS_PASSWORD` в `.env.example`.

### FIX-021 · Dockerfile — `pip install ... || true` маскирует ошибки

**Файл:** `Dockerfile` ~строка 12  
**Исправление:** Убрать `|| true`, использовать `pip install --no-cache-dir -r requirements-optional.txt` с явным `[celery]` extras.

### FIX-022 · CI deploy без статус-чека

**Файл:** `.github/workflows/deploy.yml` ~17–19  
**Исправление:** Добавить required check на CI перед deploy даже при `workflow_dispatch`.

---

## БЛОК P3 — Code Quality (LOW)

### FIX-023 · Dead imports в extracted modules

**Файлы:**
- `app/routes_messages.py` — `asyncio`, `contextlib`, `datetime` не используются
- `app/campaign_worker.py` — `sqlite3` не используется напрямую

**Исправление:** Удалить неиспользуемые импорты. Проверить: `python -m py_compile app/routes_messages.py`.

### FIX-024 · Circular coupling `main` ↔ `campaign_worker` через `_m()`

**Файл:** `app/campaign_worker.py`  
**Серьёзность:** Architecture/LOW now (phase 2 ADR 003)  
**Действие:** Запланировать `/start-feature` для Phase 2 — вынести send/pacing из `main.py`, убрать `_m()` bridge.

### FIX-025 · `main.py` — 3200 строк монолит

**Действие:** Фиксировать в `docs/adr/003-worker-module-extraction-deferred.md` как следующую фазу. Не делать сейчас без Feature Plan.

---

## БЛОК: Tests — Дыры в покрытии (qa-engineer)

### TEST-001 · Cross-tenant SQLite isolation

**Файл:** создать `tests/test_tenant_isolation_sqlite.py`

```python
"""Tenant A write → Tenant B must NOT see it via _conn()"""
# Проверяет FIX-006. Должен ПАДАТЬ до исправления, ПРОХОДИТЬ после.
```

### TEST-002 · `POST /api/messages/upload`

**Файл:** `tests/test_routes_panel.py` или новый  
Добавить тест загрузки файла — проверяет FIX-001.

### TEST-003 · Pool DONE / `_pool_done_announced`

**Файл:** `tests/test_worker_tenant_runtime.py`  
Добавить тест: инициализировать пул > 1, завершить все воркеры, проверить что `RUNTIME.pool_done_announced = True` без `NameError`.

### TEST-004 · SIGTERM shutdown handler

**Файл:** новый `tests/test_shutdown_handler.py`  
Проверить что `RUNTIME.shutting_down` устанавливается без `AttributeError`.

### TEST-005 · `/api/backups` endpoint

**Файл:** `tests/test_routes_panel.py`  
GET `/api/backups` → 200, список.

### TEST-006 · `/api/health` не требует аутентификации, `/metrics` требует

После FIX-008 добавить тесты что:
- `/api/health` → 200 без токена
- `/metrics` → 401 без токена (или 403 с неверным)

---

## Порядок выполнения (Recommended)

```
Round 1 (backend-engineer):
  FIX-001 → FIX-002 → FIX-003 → FIX-004 → FIX-005
  pytest → все проходят

Round 1 (qa-engineer, параллельно):
  TEST-001 написать (ожидать FAIL до FIX-006)
  TEST-002, TEST-003, TEST-004, TEST-005 написать

Round 2 (backend-engineer):
  FIX-006 (поэтапно: Шаг А → Б → В → Г)
  После каждого шага: pytest

Round 2 (security-engineer, параллельно):
  FIX-007, FIX-008, FIX-009, FIX-010, FIX-011

Round 2 (devops-engineer, параллельно):
  FIX-019, FIX-020, FIX-021, FIX-022

Round 3 (backend-engineer):
  FIX-012, FIX-013, FIX-014, FIX-015, FIX-016, FIX-017, FIX-018

Round 4 (backend-engineer):
  FIX-023, FIX-024 (планирование фазы 2)

Round 4 (verifier):
  Полный прогон pytest
  Smoke: curl все критические endpoints
  docker compose config
  PASSED → можно коммитить
```

---

## Контрольные команды

```powershell
# Проверить отсутствие очевидных import ошибок:
python -c "import app.campaign_worker; import app.routes_messages; print('OK')"

# Полный pytest:
pytest tests/ -v --tb=short

# Smoke критических эндпоинтов (нужен запущенный сервер):
curl http://localhost:8765/api/health
curl -X POST http://localhost:8765/api/messages/upload -F "file=@test.txt"
```

---

## Заметки

- `db_pg.py` использует `psycopg_pool` (sync) — это нормально для текущего масштаба, но обернуть тяжелые вызовы в `asyncio.to_thread` при необходимости.
- `antiban_core.py` не содержит ошибок, не трогать без явной нужды.
- `app/vault.py` + `app/vault_store.py` уже имеют per-tenant логику — после FIX-006 можно переключить `main.py` vault helpers на них.
- Scripts в `scripts/` (extract_routes.py, strip_main_routes.py и др.) — вспомогательные, не часть production. Не удалять.
