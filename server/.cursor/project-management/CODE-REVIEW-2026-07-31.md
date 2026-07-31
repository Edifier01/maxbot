# Code Review — MAX Sender Server
**Дата:** 2026-07-31  
**Зона:** `server/`  
**Статус предыдущего ревью:** [`SERVER-REVIEW-FIX-PLAN.md`](SERVER-REVIEW-FIX-PLAN.md) — P0–P3 выполнены, P3-3 partial  
**Цель:** свежие баги, логические дыры, оптимизации, мусор — для исправления агентами

---

## КРИТИЧЕСКИЕ БАГИ (P0 — падение в production)

### P0-1 · `middleware.py` — NameError: `role`, `tenant_id`, `impersonating` не извлечены из payload

**Файл:** `app/middleware.py`, строки 147–201  
**Эффект:** каждый аутентифицированный запрос в `MAX_SERVER_MODE=1` падает с `NameError`

После `payload = decode_token(token)` переменные `role`, `tenant_id`, `impersonating` используются в условиях (строки 150, 153, 155–157, 163, 164, 171, 175–176, 182–184, 191–192, 196, 198, 200), но **ни разу не присваиваются** из `payload`.

```python
# СЕЙЧАС (сломано):
user_id = int(payload["sub"])
if path.startswith("/api/admin"):
    if role != "admin":   # NameError: name 'role' is not defined
```

```python
# ИСПРАВЛЕНИЕ — добавить после line 147:
role = payload.get("role", "user")
tenant_id = payload.get("tenant_id")
impersonating = bool(payload.get("imp"))
```

**Почему не поймали тесты:** `if not is_server_mode(): return await call_next(request)` — в local mode блок не достигается. Все тесты, судя по конфигу, запускаются без `MAX_SERVER_MODE=1`.

**Агент:** `backend-engineer`

---

### P0-2 · `ops_monitor.py` — NameError: `threshold` внутри `_tick`

**Файл:** `app/ops_monitor.py`, строка 72  
**Эффект:** `_tick` падает с `NameError` при первой triggered-проверке circuit breaker

```python
# СЕЙЧАС (сломано):
async def _tick(circuit_threshold: int) -> None:
    ...
    if open_n >= circuit_threshold and _should_alert(f"circuit:{open_n // threshold}"):
    #                                                                     ^^^^^^^^
    #                                          NameError: threshold не определён в _tick
```

```python
# ИСПРАВЛЕНИЕ:
    if open_n >= circuit_threshold and _should_alert(f"circuit:{open_n // circuit_threshold}"):
```

**Агент:** `backend-engineer`

---

### P0-3 · `auth_rate_limit.py` — missing `global` в exception handler

**Файл:** `app/auth_rate_limit.py`, строки 66–68  
**Эффект:** при падении Redis внутри `check_auth_rate_limit` состояние `_redis_failed`, `_last_redis_retry`, `_redis_client` **не сбрасывается в модульных глобалах** — создаются локальные переменные. Функция будет снова и снова пытаться использовать неработающий Redis на каждый запрос.

```python
# СЕЙЧАС (сломано):
def check_auth_rate_limit(key: str, limit: int, window: float) -> bool:
    r = _get_redis()
    if r is not None:
        try:
            count = r.incr(key)
            ...
        except Exception:
            _redis_failed = True          # создаёт ЛОКАЛЬНУЮ переменную
            _last_redis_retry = time.time()  # создаёт ЛОКАЛЬНУЮ переменную
            _redis_client = None          # создаёт ЛОКАЛЬНУЮ переменную
```

```python
# ИСПРАВЛЕНИЕ:
        except Exception:
            global _redis_failed, _last_redis_retry, _redis_client
            _redis_failed = True
            _last_redis_retry = time.time()
            _redis_client = None
```

**Агент:** `backend-engineer`

---

## ВЫСОКИЙ ПРИОРИТЕТ (P1 — риск потери данных / некорректного поведения)

### P1-1 · `db_pg.py` — race condition при инициализации пула

**Файл:** `app/db_pg.py`, строки 11–27  
**Эффект:** при двух параллельных запросах оба видят `_pool is None`, создают два `ConnectionPool`. Первый pool утечёт (без `close()`).

```python
# СЕЙЧАС:
_pool = None
def _get_pool():
    global _pool
    if _pool is None:           # не atomic
        _pool = ConnectionPool(...)
    return _pool
```

```python
# ИСПРАВЛЕНИЕ:
import threading
_pool = None
_pool_lock = threading.Lock()

def _get_pool():
    global _pool
    if _pool is None:
        with _pool_lock:
            if _pool is None:   # double-checked locking
                _pool = ConnectionPool(...)
    return _pool
```

**Агент:** `database-engineer`

---

### P1-2 · `tenant_init.py` — `init_tenant_db` устанавливает контекст без restore

**Файл:** `app/tenant_init.py`, строки 32–41  
**Эффект:** если `init_db()` или `_try_legacy_unlock()` бросает исключение, `ContextVar` остаётся с tenant_id=X. Middleware вызывает `clear_context()` в `finally`, но в `init_global_db` этого `finally` нет. Утечка контекста между тестами / запросами.

```python
# СЕЙЧАС:
def init_tenant_db(main_module, tenant_id: int) -> None:
    set_context(tenant_id=tenant_id, role="user")   # нет restore при ошибке
    db_path = main_module._db_path()
    if not db_path.exists():
        main_module.init_db()
    main_module._try_legacy_unlock()
```

```python
# ИСПРАВЛЕНИЕ — использовать tenant_scope:
def init_tenant_db(main_module, tenant_id: int) -> None:
    from app.tenant import tenant_scope
    ensure_tenant_data(main_module.ROOT, tenant_id)
    with tenant_scope(tenant_id=tenant_id, role="user"):
        if not main_module._db_path().exists():
            main_module.init_db()
        main_module._try_legacy_unlock()
```

То же для `init_global_db`.

**Агент:** `backend-engineer`

---

### P1-3 · `tenant_init.py` — новые tenants получают plaintext `.app_key` (weak vault)

**Файл:** `app/tenant_init.py`, строки 10–18; `app/vault.py` `try_legacy_unlock`  
**Эффект:** `ensure_tenant_data` создаёт `.app_key` с raw Fernet-ключом. Это «legacy» vault — сессии «зашифрованы», но ключ лежит в открытом виде рядом. В server mode на VPS любой, кто получил доступ к диску, читает все сессии.

По-хорошему: в server mode при создании tenant выдавать автогенерированный PIN (хранить hash в PG), при первом входе предлагать пользователю сменить. Либо явно документировать ограничение.

**Минимальный fix сейчас:** добавить NOTICE в документацию + `/api/vault/status` ответ `"protected": false` должен отображаться в UI как предупреждение.

**Агент:** `security-engineer`

---

### P1-4 · `campaign_worker.py` — `scheduler_tenant_ids()` сканирует ФС вместо PG

**Файл:** `app/campaign_worker.py`, строки 566–578  
**Эффект:** новые tenants не попадают в расписание пока у них нет `app.db`. Tenant, удалённый из PG, но с оставшейся папкой данных, останется в цикле расписания (→ ошибки в логе).

```python
# ИСПРАВЛЕНИЕ — запрашивать tenant_ids из PG:
def scheduler_tenant_ids() -> list[int | None]:
    if not main._is_server_mode():
        return [None]
    from app import db_pg
    try:
        rows = db_pg.list_tenants_with_users()  # уже есть
        return [int(r["tenant_id"]) for r in rows] or [None]
    except Exception:
        return [None]
```

**Агент:** `backend-engineer`

---

### P1-5 · `docker-compose.yml` — слабый дефолт `POSTGRES_PASSWORD`

**Файл:** `docker-compose.yml`, строка 109  
```yaml
POSTGRES_PASSWORD: "${POSTGRES_PASSWORD:-maxsender}"
```
Если администратор не задаст переменную в `.env`, БД поднимется с паролем `maxsender`. Это не заблокировано ни в Dockerfile, ни в startup-скрипте.

**Fix:** убрать дефолт, как это сделано для `JWT_SECRET`:
```yaml
POSTGRES_PASSWORD: "${POSTGRES_PASSWORD:?задайте POSTGRES_PASSWORD в .env}"
```

**Агент:** `devops-engineer`

---

## СРЕДНИЙ ПРИОРИТЕТ (P2 — некорректное поведение, логические дыры)

### P2-1 · `requirements-scale.txt` — вводящее в заблуждение название

**Файл:** `requirements-scale.txt`  
`bcrypt`, `PyJWT`, `psycopg`, `psycopg-pool` — это не «scale» зависимости, а **обязательные для server mode**. Новый разработчик установит только `requirements.txt` и получит `ImportError`.

**Fix:** переименовать в `requirements-server.txt`. Обновить `Dockerfile`, `README.md`, `.cursor/skills/`.

**Агент:** `devops-engineer`

---

### P2-2 · `db_pg.py` — `ConnectionPool` без timeout на checkout

**Файл:** `app/db_pg.py`, строки 20–26  
```python
_pool = ConnectionPool(
    ...
    min_size=1,
    max_size=10,
    open=True,
)
```
Нет `timeout` параметра. При 10 параллельных запросах, удерживающих соединения, 11-й будет ждать **бесконечно**. В production это выглядит как зависший запрос.

```python
# ИСПРАВЛЕНИЕ:
_pool = ConnectionPool(
    ...,
    timeout=30.0,    # checkout timeout
    max_waiting=50,  # queue depth
)
```

**Агент:** `database-engineer`

---

### P2-3 · `notify_campaign_end` — дублирует Telegram логику вместо `telegram_credentials()`

**Файл:** `app/campaign_worker.py`, строки 221–243  
Функция `notify_campaign_end` читает `telegram_bot_token` и `telegram_chat_id` из SQLite settings напрямую, а `telegram_credentials()` (строки 128–138) читает из env vars и возвращает `("", "")` в server mode. Это создаёт два несогласованных источника конфигурации Telegram.

**Fix:** заменить строки 221–243 на вызов `await telegram_notify(...)` через `telegram_credentials()`. В server mode Telegram должен работать только через env vars.

**Агент:** `backend-engineer`

---

### P2-4 · Docker: schema смонтирована в `initdb.d` И применяется через Python

**Файл:** `docker-compose.yml`, строки 113–115  
```yaml
volumes:
  - ./schema_pg.sql:/docker-entrypoint-initdb.d/01_bootstrap.sql:ro
  - ./migrations/001_saas_core.sql:/docker-entrypoint-initdb.d/02_001_saas_core.sql:ro
  - ./migrations/002_revoked_tokens.sql:/docker-entrypoint-initdb.d/03_002_revoked_tokens.sql:ro
```
Миграции монтируются в `initdb.d` (PG выполняет при первом старте) **и** применяются через `db_pg._apply_pending_migrations()` при старте Python-приложения.

Проблема: `initdb.d` вставляет версии в `schema_migrations`. Python migration runner проверяет `schema_migrations` и пропускает их — это корректно и идемпотентно. Но если добавить `004_*.sql` и **не** смонтировать его в `initdb.d`, на fresh install он применится через Python, а на existing install — тоже через Python. Смешение двух механизмов запутывает.

**Рекомендация:** убрать миграции из `initdb.d`, оставить только bootstrap (создание `schema_migrations`). Всё остальное — через Python runner. В README задокументировать.

**Агент:** `devops-engineer`

---

### P2-5 · `routes_auth.py` — `import os` и `import main` внутри хендлеров

**Файл:** `app/routes_auth.py`, строки 51, 66–69, 79–80  
Многократный `import main as app_main` внутри хендлеров (register, login, impersonate). Python кеширует модуль, но CPython всё равно вызывает `sys.modules` lookup + lock на каждый вызов. Под нагрузкой это ~несколько микросекунд на запрос. Незначительно, но нарушает принцип «imports at top».

Более серьёзно: `import main as app_main` в `routes_auth.py`, `routes_campaign.py`, `middleware.py`, `campaign_worker.py`, `tenant_sqlite.py` — везде. Это coupling через глобальный модуль. При рефакторинге любого из них нужно перепроверять все точки.

**Fix:** постепенно переходить от `import main as m` к dependency injection или хелперам в `campaign_facade.py`. Для P2 минимально — хотя бы `campaign_facade.main` консолидировать в один proxy.

**Агент:** `backend-engineer`

---

### P2-6 · `routes_auth.py` `/me` — дублирует auth логику middleware

**Файл:** `app/routes_auth.py`, строки 138–157  
Если `user_id is None` (контекст не установлен middleware), `/me` сам декодирует токен и устанавливает контекст. Это компенсация для бага P0-1. После исправления P0-1 этот дублирующий блок должен быть упрощён — опираться только на контекст, установленный middleware.

**Агент:** `backend-engineer` (после фикса P0-1)

---

### P2-7 · `subscription_jobs.py` — `_stopped_expired` in-memory set не сбрасывается при возобновлении подписки

**Файл:** `app/subscription_jobs.py`, строка 14  
```python
_stopped_expired: set[int] = set()
```
После остановки воркера при истечении подписки, tenant добавляется в `_stopped_expired`. Если подписка продлевается и воркер нужно запустить снова — `_stopped_expired` препятствует повторной обработке `tenants_recently_expired`. Однако worker restart при новой подписке должен идти через API `/api/campaign/start`, а не через lifecycle loop. Логика корректна, но неочевидна. Нужен комментарий.

**Агент:** `campaign-specialist`

---

## НИЗКИЙ ПРИОРИТЕТ (P3 — качество кода, мусор, мелкие недочёты)

### P3-1 · `db_pg.py` — `tenants_recently_expired` и `list_expiring_subscriptions` вызывают `_now()` многократно

**Файл:** `app/db_pg.py`, строки 302–322, 325–342  
Каждый `%s` с `_now()` — отдельный вызов `datetime.now()`. В `list_expiring_subscriptions` — 5 вызовов `_now()`. Между ними проходят микросекунды, что создаёт незначительный временной дрейф внутри одного запроса. Правильнее создать один `now = _now()` и использовать его.

```python
# ИСПРАВЛЕНИЕ:
def list_expiring_subscriptions(within_days: int = 7):
    now = _now()
    with _cursor() as cur:
        cur.execute("...", (now, now, now, within_days, now))
```

**Агент:** `database-engineer`

---

### P3-2 · `vault.py` — `encrypt_session_file` без `missing_ok=True`

**Файл:** `app/vault.py`, строка 214  
```python
db.unlink()   # FileNotFoundError если удалён между exists() и unlink()
```
Заменить на `db.unlink(missing_ok=True)`.

**Агент:** `backend-engineer`

---

### P3-3 · `main.py` (root) — всё ещё монолит ~3200+ строк

**Файл:** `main.py`  
P3-3 из предыдущего ревью — `PARTIAL`. Вынесены vault, paths, campaign_*, routes_*. Остаются в `main.py`:
- `worker_loop`, `pool_supervisor` (через `campaign_worker.py`) — OK
- `_conn()`, `init_db()`, `init_schema()` (SQLite) — кандидаты для `sqlite_backend.py`
- `_pick_next_message`, `_ensure_message_bag` — кандидаты для `campaign_queue.py`
- `_active_groups`, `_active_profiles_for_group` — кандидаты для `campaign_query.py`
- Desktop-специфичный UI код (`_open_browser_when_ready`) — уже в `app/main.py`

Это не срочно, но затрудняет все следующие рефакторинги.

**Агент:** `backend-engineer` (только планирование, не реализация без отдельного `/start-feature`)

---

### P3-4 · `celery_worker.py` — REDIS_URL дефолт без пароля

**Файл:** `celery_worker.py`, строка 18  
```python
REDIS_URL = os.environ.get("REDIS_URL", "redis://127.0.0.1:6379/0")
```
Если `REDIS_URL` не задан, Celery попытается подключиться к Redis без пароля. В production docker-compose всегда задаёт `REDIS_URL`, но в dev можно запустить `celery_worker.py` напрямую и получить непонятную ошибку auth.

**Fix:** `REDIS_URL = os.environ.get("REDIS_URL") or ""` — если пусто, выдать явное сообщение.

**Агент:** `devops-engineer`

---

### P3-5 · `ops_monitor.py` — Telegram только через env vars, но campaign_worker дублирует через settings

Уже отмечено в P2-3. Дополнительно: `ops_monitor.py` правильно проверяет env vars сразу (строки 48–50). `campaign_worker.py`/`notify_campaign_end` использует settings. Нужна единая функция-источник Telegram-credentials для server mode.

---

### P3-6 · `routes_auth.py` — `REGISTRATION_OPEN` не в `.env.example`

**Файл:** `app/routes_auth.py`, строка 52; `.env.example`  
`REGISTRATION_OPEN` управляет открытием регистрации, но не документирован в `.env.example`. Администратор закроет регистрацию случайно (не установит переменную), или не будет знать что можно закрыть.

**Fix:** добавить в `.env.example`:
```
# REGISTRATION_OPEN=1   # 1=открыта, 0=только через ADMIN_EMAIL/PASSWORD
```

**Агент:** `devops-engineer`

---

### P3-7 · `db_pg.py` — `init_schema()` не идемпотентен при повторных вызовах

**Файл:** `app/db_pg.py`, строки 118–123  
```python
def init_schema() -> None:
    bootstrap = _schema_dir() / "schema_pg.sql"
    if bootstrap.exists():
        with _cursor() as cur:
            cur.execute(bootstrap.read_text(encoding="utf-8"))  # без транзакции!
    _apply_pending_migrations()
```
`schema_pg.sql` создаёт только `schema_migrations` с `IF NOT EXISTS` — повторный запуск идемпотентен. Но функция выполняет bootstrap **без транзакции**, а migration runner работает внутри `transaction=True`. Если bootstrap-запрос упадёт на полпути (маловероятно для одной таблицы) — состояние будет неопределённым.

**Fix:** обернуть bootstrap в `_cursor(transaction=True)`.

**Агент:** `database-engineer`

---

## МУСОР / ТЕХНИЧЕСКИЙ ДОЛГ

### M-1 · `scripts/` — скрипты миграции кода без применения

**Файл:** `scripts/extract_routes.py`, `scripts/extract_worker.py`, `scripts/fix_routes.py`, `scripts/patch_main_worker.py`, `scripts/restore_main.py`, `scripts/strip_main_routes.py`

Это **одноразовые скрипты рефакторинга**, использованные при декомпозиции `main.py`. Они не нужны в production и не должны быть в `COPY . .` в Dockerfile. Создают путаницу.

**Fix:** либо удалить, либо переместить в `tools/` и добавить в `.dockerignore`.

**Агент:** `devops-engineer`

---

### M-2 · `schema_pg_legacy.sql` — мёртвый файл

**Файл:** `schema_pg_legacy.sql`  
Не импортируется, не монтируется в compose, не используется в коде. Оставлен как артефакт P2-3 из предыдущего ревью.

**Fix:** удалить или переместить в `docs/archive/`.

**Агент:** `devops-engineer`

---

### M-3 · `run.bat` — Windows-скрипт в server-only проекте

**Файл:** `run.bat`  
Server работает на Linux/Docker. `run.bat` нужен только для локального тестирования на Windows. Без комментария непонятно его назначение.

**Fix:** добавить комментарий в начало файла или перенести в `tools/`.

---

### M-4 · `rules/` в корне — дублирует `.cursor/rules/`

**Файл:** `rules/` (папка в корне `server/`)  
Содержит то же что `.cursor/rules/`. Вероятно артефакт копирования.

**Fix:** проверить содержимое, удалить если дубли.

---

## АРХИТЕКТУРНЫЕ ЗАМЕЧАНИЯ (не баги, но важно знать)

### A-1 · Dual-write: PG metadata + SQLite per-tenant data

Каждый tenant имеет: PG-запись (users/subscriptions) + SQLite в `data/tenants/{id}/app.db`. Это осознанное решение (tenant data isolation), но создаёт дополнительный инвариант: «tenant существует в PG ↔ имеет SQLite-папку». Инвариант нарушается при ошибках `init_tenant_db` или неполном `rollback_tenant_registration`. Нужен admin API для диагностики.

### A-2 · `CampaignRuntime` на `asyncio.Lock` — проблема в Celery-режиме

`worker_lock: asyncio.Lock` хорошо работает в asyncio-контексте. Но Celery-воркер (`celery_worker.py`) является отдельным **процессом**, не asyncio-тасками. При `USE_CELERY=1` и многопроцессном celery, каждый процесс имеет свой `REGISTRY`. Это означает отсутствие shared state между Celery workers — необходимо явно документировать, что Celery сейчас только thin HTTP-proxy к основному FastAPI, а не замена worker loop.

### A-3 · Token revocation только по JTI (без Redis)

`revoked_tokens` в PG — таблица с TTL cleanup. Каждый запрос делает SELECT из `revoked_tokens`. При большом числе logout-ов и долгих JWT (168h дефолт) таблица растёт. `cleanup_revoked_tokens()` вызывается раз в сутки через `subscription_lifecycle_loop`. Достаточно для малого трафика; при росте нагрузки — перейти на Redis SET с TTL.

---

## ИТОГОВАЯ МАТРИЦА ЗАДАЧ

| # | Файл | Проблема | Приоритет | Агент |
|---|------|----------|-----------|-------|
| P0-1 | `middleware.py` | NameError: role/tenant_id/impersonating | **P0** | backend-engineer |
| P0-2 | `ops_monitor.py` | NameError: threshold в _tick | **P0** | backend-engineer |
| P0-3 | `auth_rate_limit.py` | missing global декларация | **P0** | backend-engineer |
| P1-1 | `db_pg.py` | race condition init pool | P1 | database-engineer |
| P1-2 | `tenant_init.py` | set_context без restore | P1 | backend-engineer |
| P1-3 | `tenant_init.py` | plaintext .app_key в server mode | P1 | security-engineer |
| P1-4 | `campaign_worker.py` | scheduler сканирует ФС, не PG | P1 | backend-engineer |
| P1-5 | `docker-compose.yml` | дефолт POSTGRES_PASSWORD | P1 | devops-engineer |
| P2-1 | `requirements-scale.txt` | вводящее в заблуждение название | P2 | devops-engineer |
| P2-2 | `db_pg.py` | pool без checkout timeout | P2 | database-engineer |
| P2-3 | `campaign_worker.py` | дубль Telegram логики | P2 | backend-engineer |
| P2-4 | `docker-compose.yml` | двойное применение миграций | P2 | devops-engineer |
| P2-5 | множество файлов | `import main as m` в хендлерах | P2 | backend-engineer |
| P2-6 | `routes_auth.py` | /me дублирует middleware auth | P2 | backend-engineer |
| P2-7 | `subscription_jobs.py` | _stopped_expired без документации | P2 | campaign-specialist |
| P3-1 | `db_pg.py` | многократный _now() в запросах | P3 | database-engineer |
| P3-2 | `vault.py` | missing_ok в unlink | P3 | backend-engineer |
| P3-3 | `main.py` | монолит (продолжение P3-3) | P3 | backend-engineer |
| P3-4 | `celery_worker.py` | дефолт REDIS_URL без пароля | P3 | devops-engineer |
| P3-5 | `ops_monitor.py` | дубль Telegram source | P3 | backend-engineer |
| P3-6 | `.env.example` | REGISTRATION_OPEN не задокументирован | P3 | devops-engineer |
| P3-7 | `db_pg.py` | init_schema без транзакции | P3 | database-engineer |
| M-1 | `scripts/` | одноразовые скрипты рефакторинга | мусор | devops-engineer |
| M-2 | `schema_pg_legacy.sql` | мёртвый файл | мусор | devops-engineer |
| M-3 | `run.bat` | без комментария | мусор | — |
| M-4 | `rules/` | дубль `.cursor/rules/` | мусор | — |

---

## Рекомендуемый порядок исправлений

**Wave 1 (P0 — немедленно, один round):**
- backend-engineer: P0-1, P0-2, P0-3 — 3 точечные правки

**Wave 2 (P1 — следующий спринт):**
- backend-engineer: P1-2, P1-4
- database-engineer: P1-1
- security-engineer: P1-3 (документирование + UI warning)
- devops-engineer: P1-5

**Wave 3 (P2 + мусор):**
- devops-engineer: P2-1, P2-4, M-1, M-2, P3-6
- database-engineer: P2-2, P3-1, P3-7
- backend-engineer: P2-3, P2-6, P3-2, P3-5

**Verifier gate:** после каждой волны — `pytest tests/ -q` + smoke в server mode (два tenant, parallel requests).
