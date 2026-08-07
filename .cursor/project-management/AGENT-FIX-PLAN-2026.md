# Agent Fix Plan — MAX Sender Server (2026-08-07)

Источник: полное ревью кодовой базы от 2026-08-07.  
Предыдущий план (`SERVER-REVIEW-FIX-PLAN.md`) — выполнен полностью.  
Этот документ — следующая волна исправлений.

---

## Контекст

**Zone:** `server`  
**Entry:** `AGENTS.md`  
**Стек:** FastAPI · PostgreSQL (psycopg3 pool) · per-tenant SQLite · Fernet · Redis · Docker Compose · Caddy

Перед любой задачей:
1. Прочитать нужный skill из `.cursor/skills/`.
2. Запустить тесты: `MAX_TEST=1 MAX_SERVER_MODE=1 python -m pytest tests/ -q`
3. Проверить compose: `docker compose config -q`
4. Не коммитить `.env`, vault-материал, секреты.

---

## Волна 1 — CRITICAL (исправить первыми)

### C-1. `threading.Lock` блокирует event loop в async worker

**Файл:** `main.py` (строка `_claim_lock = threading.Lock()`)  
**Файл:** `app/campaign_worker.py` (`claim_next_job` → `with main._claim_lock:`)

**Проблема:**  
`claim_next_job()` — синхронная функция, вызывается напрямую из `async def poolworker_loop`.
`threading.Lock.acquire()` блокирует event loop. При `WORKER_POOL_SIZE > 1` воркеры
выполняются последовательно вместо параллельного.

**Решение:**
1. Заменить `_claim_lock = threading.Lock()` → `_claim_lock = asyncio.Lock()`.
2. Сделать `claim_next_job` асинхронной функцией: `async def claim_next_job()`.
3. Все SQLite-операции внутри (через `main._conn()`) обернуть в `asyncio.to_thread(...)`.
4. В `poolworker_loop` изменить вызов: `job = await claim_next_job()`.
5. В `worker_loop` (single-worker path) — также `await claim_next_job()`.

**Тест:** `tests/test_campaign_modules.py` — убедиться что тесты проходят.  
**Понтэйл:** минимальная правка — только lock + async/await, никакой реструктуризации.

---

### C-2. ContextVar может утечь в asyncio background tasks

**Файл:** `main.py` lifespan, `app/campaign_worker.py` `start_worker`

**Проблема:**  
`asyncio.create_task()` копирует context момента создания. Задачи созданные в lifespan
(`_startup_auto_resume`, `ops_alert_loop`, `subscription_lifecycle_loop`) не имеют tenant
context — это нормально. Но `scheduler_loop` итерирует тенанты через `tenant_scope`,
и если там создаётся вложенная задача — контекст утечёт.

**Решение:**
1. В `scheduler_loop` убедиться что `asyncio.create_task(...)` не создаётся внутри
   `with tenant_scope(...)` — только прямые `await` вызовы.
2. Добавить явный `assert get_tenant_id() is None` перед созданием любого
   background task из lifespan (документирует намерение, ловит будущие регрессии).
3. Проверить `ops_monitor.py` и `subscription_jobs.py` — не создают ли они задачи
   внутри tenant-scope.

**Тест:** `tests/test_worker_tenant_runtime.py`, `tests/test_phase3_tenant_scope.py`

---

### C-3. Redis container без healthcheck

**Файл:** `docker-compose.yml`

**Проблема:**  
Redis используется `condition: service_started` (не healthy). Если Redis поднимается
медленно — app стартует с недоступным Redis, rate-limit и Celery молча ломаются.

**Решение:**
```yaml
# В секции redis:
healthcheck:
  test: ["CMD", "redis-cli", "-a", "${REDIS_PASSWORD}", "ping"]
  interval: 5s
  timeout: 3s
  retries: 10

# В секции app → depends_on → redis:
  condition: service_healthy
```

**Проверка:** `docker compose config -q`

---

### C-4. delete_tenant без atomic rollback

**Файл:** `app/routes_admin.py` → `delete_user`

**Проблема:**  
Последовательность: stop_worker → bump_token_version → `db_pg.delete_tenant` → `_drop_tenant_sqlite`.
Если `_drop_tenant_sqlite` падает, PG-запись уже удалена → tenant исчез из БД, но SQLite-файлы
остались. При следующем запросе с тем же tenant_id — ошибки.

**Решение:**
1. Сначала `_drop_tenant_sqlite` (если падает — PG не тронут, можно retry).
2. Затем `db_pg.delete_tenant`.
3. Если нужно атомарность в обратную сторону — обернуть в try/except с лог-записью
   о неполном удалении, чтобы не потерять ошибку.

```python
# Правильный порядок:
await stop_worker(...)
db_pg.bump_tenant_token_version(tenant_id)
_drop_tenant_sqlite(tenant_id)          # сначала локальные файлы
if not db_pg.delete_tenant(tenant_id):  # потом PG
    raise HTTPException(404, "...")
```

**Тест:** `tests/test_cross_tenant_api.py`

---

## Волна 2 — HIGH

### H-1. Memory leak: `_rate_counters` не очищает мёртвые ключи

**Файл:** `main.py` → `RateLimitMiddleware.dispatch`

**Проблема:**  
`_rate_counters[ip]` — defaultdict, ключи добавляются при первом запросе и **никогда**
не удаляются, даже если IP больше не приходит. Список timestamps очищается, но
сам ключ остаётся.

**Решение** (одна строка):
```python
# После очистки старых timestamps:
_rate_counters[ip] = [t for t in window if now - t < RATE_WINDOW]
if not _rate_counters[ip]:          # ← добавить
    del _rate_counters[ip]          # ← добавить
if len(_rate_counters[ip]) >= RATE_LIMIT:
    ...
```

**Тест:** `tests/test_auth_rate_limit.py`

---

### H-2. validate_token_session — 3-4 PG запроса на каждый HTTP-запрос

**Файлы:** `app/auth.py` → `validate_token_session`, `app/middleware.py` → `ServerAuthMiddleware`

**Проблема:**  
На каждый authenticated запрос: `is_token_revoked` (PG) + `get_user_by_id` (PG) + `get_tenant` (PG)
+ повторный `is_token_revoked` в middleware = 4 запроса к PostgreSQL.

**Решение:**  
Добавить in-process TTL-кэш с коротким временем жизни (30 сек):

```python
# app/auth.py — добавить после импортов
import functools, time as _time
_session_cache: dict[str, tuple[float, str | None]] = {}  # jti → (exp_mono, error|None)
_SESSION_CACHE_TTL = 30.0

def _cached_validate(payload: dict) -> str | None:
    jti = payload.get("jti")
    if jti:
        hit = _session_cache.get(jti)
        if hit and _time.monotonic() < hit[0]:
            return hit[1]
    result = validate_token_session(payload)
    if jti:
        _session_cache[jti] = (_time.monotonic() + _SESSION_CACHE_TTL, result)
    return result
```

Использовать `_cached_validate` в middleware вместо двойного вызова.  
При revoke-токена (`logout`) — явно удалять ключ из `_session_cache`.

**Ограничения:** Отозванный токен будет "живым" до 30 сек после logout. Это стандартный
trade-off. Документировать в комментарии.

**Понтэйл:** не вводить сторонних кэш-библиотек, простой dict+TTL.

---

### H-3. Нет Security Headers (CSP, X-Frame-Options)

**Файл:** `caddy/Caddyfile`

**Проблема:**  
HTML-панели отдаются без `Content-Security-Policy`. JWT в localStorage уязвим к XSS.

**Решение:**  
Добавить в Caddyfile глобальный блок header:

```caddyfile
{$DOMAIN} {
    header {
        X-Frame-Options "DENY"
        X-Content-Type-Options "nosniff"
        Referrer-Policy "strict-origin-when-cross-origin"
        Content-Security-Policy "default-src 'self'; script-src 'self' 'unsafe-inline'; style-src 'self' 'unsafe-inline'; font-src 'self';"
    }
    reverse_proxy app:8765
}
```

**Проверка:** `curl -I https://domain` после deploy, проверить заголовки.

---

### H-4. Proxy URL не валидируется при сохранении

**Файл:** `app/routes_admin.py` → `set_group_proxy`

**Проблема:**  
`ProxyIn.proxy = Field(max_length=500)` — без проверки формата.
Некорректный proxy сохранится и вызовет ошибки при соединении.

**Решение:**  
Добавить validator в Pydantic-модель:

```python
from pydantic import field_validator
import antiban_core

class ProxyIn(BaseModel):
    proxy: str = Field(max_length=500)

    @field_validator("proxy")
    @classmethod
    def validate_proxy(cls, v: str) -> str:
        v = v.strip()
        if v and not antiban_core.parse_proxy_list(v):
            raise ValueError("Некорректный формат proxy URL")
        return v
```

---

## Волна 3 — MEDIUM

### M-1. Нет rate limit на mutation endpoint-ы для авторизованных пользователей

**Файл:** `app/middleware.py` → `ServerAuthMiddleware`

**Проблема:**  
`/api/campaign/start`, `/api/profiles`, `/api/groups` не имеют per-user rate limit.
Пользователь может спамить запуски кампаний.

**Решение:**  
Добавить в `ServerAuthMiddleware.dispatch` после декода токена:

```python
# Лёгкий per-user лимит на mutation ops
MUTATION_RATE = 60  # req/min per user
if request.method in ("POST", "PUT", "DELETE", "PATCH"):
    user_key = f"user_rl:{user_id}:{int(time.monotonic() // 60)}"
    # использовать тот же auth_rate_limit._memory
    if not auth_rate_limit.check_auth_rate_limit(user_key, MUTATION_RATE, 60):
        return JSONResponse(429, {"detail": "Слишком много запросов"})
```

---

### M-2. Структурированный logging в stdout

**Файл:** `main.py` → `append_log`

**Проблема:**  
Логи идут только в in-memory list + SQLite. `docker logs` не видит application-level события.

**Решение:**  
В `append_log` добавить `print` на stdout:

```python
def append_log(msg: str) -> None:
    line = f"[{date.today()}] {msg}"
    if _is_server_mode():
        print(line, flush=True)   # ← добавить — docker logs подхватит
    with _log_lock:
        ...
```

**Понтэйл:** одна строка, никаких новых зависимостей.

---

### M-3. Удалить dev-инструменты из репозитория

**Файлы:** `tools/refactor-scripts/`, `tools/patch_main_p33.py`

**Проблема:**  
Скрипты для патчинга `main.py` — технический долг, сигнализируют о незавершённом рефакторинге.
`patch_main_p33.py` — инструмент одноразового применения, уже не нужен.

**Решение:**
```bash
git rm -r tools/
git commit -m "remove: dev refactoring scripts (one-time tools, no longer needed)"
```

---

### M-4. `pg_advisory_xact_lock(12345)` — хардкожен magic number

**Файл:** `app/db_pg.py` → `_apply_pending_migrations`

**Решение:**
```python
# Заменить magic number на hash имени приложения
import hashlib
_MIGRATION_LOCK_ID = int(hashlib.md5(b"maxsender-migrations").hexdigest()[:8], 16) % (2**31)

# В _apply_pending_migrations:
cur.execute("SELECT pg_advisory_xact_lock(%s)", (_MIGRATION_LOCK_ID,))
```

---

### M-5. Синхронные SQLite-операции в async route handlers

**Файлы:** `app/routes_admin.py`, `app/routes_dashboard.py`, `app/routes_monitor.py` и др.

**Проблема:**  
Прямые `_conn()` вызовы в async handlers блокируют event loop.
Критично при 10+ concurrent пользователях.

**Решение:**  
Обернуть тяжёлые SQLite-вызовы в `asyncio.to_thread`:

```python
# Было:
profiles = c.execute("SELECT COUNT(*) AS n FROM profiles").fetchone()["n"]

# Стало (внутри async def tenant_stats):
def _get_stats():
    with tenant_conn(tenant_id) as c:
        ...
    return {...}
result = await asyncio.to_thread(_get_stats)
```

**Приоритет:** начать с `routes_admin.py` (admin-only, критичнее по данным).

---

## Волна 4 — LOW

### L-1. Lockfile для зависимостей

**Файлы:** `requirements.txt`, `requirements-server.txt`

```bash
pip install pip-tools
pip-compile requirements.txt -o requirements.lock
pip-compile requirements-server.txt -o requirements-server.lock
# Dockerfile: использовать *.lock файлы
```

---

### L-2. Docker base image с digest

**Файл:** `Dockerfile`

```dockerfile
# Было:
FROM python:3.12-slim

# Стало (обновлять раз в квартал):
FROM python:3.12-slim@sha256:<актуальный_digest>
```

Получить digest: `docker pull python:3.12-slim && docker inspect python:3.12-slim --format '{{index .RepoDigests 0}}'`

---

### L-3. Документировать timezone_offset_hours в .env.example

**Файл:** `.env.example`

```bash
# Часовой пояс для расписания кампаний (UTC смещение, например 3 = UTC+3 Москва, 0 = UTC)
TIMEZONE_OFFSET_HOURS=3
```

---

## Порядок выполнения агентом

```
Волна 1 (C-1..C-4)  →  Тесты  →  Волна 2 (H-1..H-4)  →  Тесты  →  Волна 3 (M-1..M-5)  →  Тесты
```

После каждой волны:
```bash
MAX_TEST=1 MAX_SERVER_MODE=1 python -m pytest tests/ -q
docker compose config -q
```

---

## Механические команды

```bash
# Тесты
MAX_TEST=1 MAX_SERVER_MODE=1 python -m pytest tests/ -q

# E2E (требует запущенного PG)
MAX_TEST=1 MAX_SERVER_MODE=1 python -m pytest tests/test_e2e_server.py -q

# Compose валидация
docker compose config -q

# Deploy verify
bash scripts/verify_deploy.sh
```

---

## Ограничения (что НЕ делать)

- **Не** трогать anti-ban параметры (`antiban_core.py`, `campaign_pacing.py`) без approval.
- **Не** менять tenant isolation flow без skill `tenant-isolation-max`.
- **Не** переносить `main.py` в другую структуру — God Object декомпозиция вне скоупа этого плана.
- **Не** вводить новые зависимости без одобрения.
- **Не** коммитить `.env`, vault-материал, session files.
- **Не** ослаблять subscription guard на `/api/campaign/start`.

---

## Статус

| Волна | Задача | Статус |
|-------|--------|--------|
| C-1 | asyncio.Lock в campaign worker | DONE |
| C-2 | ContextVar leak audit | DONE |
| C-3 | Redis healthcheck | DONE |
| C-4 | delete_tenant order | DONE |
| H-1 | _rate_counters cleanup | DONE |
| H-2 | validate_token_session cache | DONE |
| H-3 | Security headers (CSP) | DONE |
| H-4 | Proxy URL validation | DONE |
| M-1 | Per-user mutation rate limit | DONE |
| M-2 | stdout logging | DONE |
| M-3 | Remove tools/ | DONE |
| M-4 | pg_advisory_lock hash | DONE |
| M-5 | asyncio.to_thread для SQLite | DONE |
| L-1 | requirements lockfile | DONE |
| L-2 | Docker digest | DONE |
| L-3 | .env.example timezone | DONE |
