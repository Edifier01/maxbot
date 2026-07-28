# Полное ревью проекта MAX Sender (локальная версия)

> **Дата:** 2026-07-28  
> **Версия:** 1.13.0 (`APP_VERSION` в `main.py`)  
> **Фокус:** локальная разработка — `run.bat`, `build.bat`, exe, `127.0.0.1:8765`  
> **Метод:** статический анализ кода + сверка с `AUDIT.md`

---

## Executive Summary

MAX Sender вырос из «MVP на ~1400 строк» до **зрелого локального продукта v1.13** с богатым функционалом: vault для сессий, antiban, worker pool, WebSocket-статус, кампании с паузой/сбросом, расписание, бэкапы, Prometheus-метрики.

**Вердict для локального использования (5–50 аккаунтов):** продукт **готов к ежедневной работе**. Основные P0-проблемы из `AUDIT.md` **исправлены**. Главные ограничения сейчас — **монолит ~4700 строк**, **0 автотестов** и **потолок SQLite** при росте нагрузки.

| Область | Было (AUDIT) | Сейчас | Δ |
|---------|--------------|--------|---|
| Архитектура | 4/10 | 5/10 | +1 — больше фич, но монолит вырос |
| Backend / код | 5/10 | 7/10 | +2 — retry, vault, pool, campaigns |
| UI | 5/10 | 7/10 | +2 — toast, loading, vault UI, tabs |
| UX | 4/10 | 7/10 | +3 — пауза, сброс, WebSocket, модалки |
| Производительность | 5/10 | 7/10 | +2 — singleton SQLite WAL, кеш settings |
| Безопасность (local) | 6/10 | 7/10 | +1 — vault, scrypt PIN; legacy .app_key остаётся |
| Поддерживаемость | 3/10 | 4/10 | +1 — inline migrations; тестов по-прежнему 0 |
| **Локальный продукт** | **4/10** | **7/10** | **+3** |

---

## 1. Локальный deployment

### Что работает хорошо

| Компонент | Путь | Статус |
|-----------|------|--------|
| Запуск из исходников | `run.bat` → `python main.py --no-browser` | ✅ |
| Portable exe | `build.bat` → `dist/MAX-Sender.exe` | ✅ |
| Данные рядом с exe | `data/app.db`, `data/sessions/` | ✅ |
| Авто-venv | `run.bat` / `build.bat` | ✅ |
| Браузер | открывается при прямом запуске; `run.bat` — `--no-browser` | ✅ |

### Замечания

| # | Severity | Finding | Evidence |
|---|----------|---------|----------|
| L-1 | Medium | UI тянет **Google Fonts** — без интернета exe покажет fallback-шрифты | `static/index.html:7-9` |
| L-2 | Low | `run.bat` не открывает браузер — пользователь должен знать URL | `run.bat:7` |
| L-3 | Low | README говорит «браузер откроется сам» — для `run.bat` это не так | `README.md` vs `run.bat` |

**Рекомендация:** встроить шрифты локально или добавить system-ui fallback без блокировки; в README различить `run.bat` и двойной клик по exe.

---

## 2. Backend (`main.py` ~4707 строк)

### Сильные стороны

- **Singleton SQLite + WAL** — исправлена проблема AUDIT P0-6

```232:254:main.py
def _conn() -> sqlite3.Connection:
    """Singleton SQLite connection with WAL mode."""
    ...
            _db_conn.execute("PRAGMA journal_mode=WAL")
            _db_conn.execute("PRAGMA synchronous=NORMAL")
```

- **Retry отправки** (3 попытки, backoff 5/15/60 с) — AUDIT P0-2 ✅
- **Пауза / стоп / сброс прогресса** разделены — AUDIT P0-1 ✅

```3199:3212:main.py
async def _start_worker(...):
    """Запуск воркера / пула без сброса индексов прогресса."""
    ...
            c.execute("UPDATE queue_state SET running=1 WHERE id=1")
```

- **Vault с PBKDF2** + миграция legacy `.app_key` — AUDIT P0-3 ✅
- **Scrypt-хеш API PIN** + авто-миграция plaintext — AUDIT P1-1 ✅
- **Rate limit** 180 req/min — AUDIT P1-3 ✅
- **Upload limit** 5 MB — AUDIT P1-2 ✅
- **Settings cache** — AUDIT P0-7 ✅
- **Persistent log** в `app_log` — AUDIT P0-8 ✅
- **Graceful shutdown** SIGINT/SIGTERM + encrypt sessions — AUDIT P0-5 ✅
- **Health + metrics** — расширенный `/api/health`, `/metrics`
- **Campaigns table**, schedule, retry_failed, test send, dashboard API
- **Worker pool** до 32 воркеров, claim-based job queue
- **Human rhythm**: send windows, role plan, pauses, presence, dedupe

### Открытые проблемы

| # | Severity | Finding | Рекомендация |
|---|----------|---------|--------------|
| B-1 | High | **Монолит ~4707 строк** — сложно сопровождать, высокий риск регрессий | Инкрементальное выделение `api/`, `services/` (см. AUDIT) |
| B-2 | High | **0 автотестов** в репозитории | Smoke: round-robin, settings validator, vault, campaign pause/resume |
| B-3 | Medium | **`ProfileStatus` enum есть, но не везде** — SQL CASE использует строки | Постепенная замена magic strings |
| B-4 | Medium | **`session.db` plaintext на диске** во время работы PyMax | Неизбежно для PyMax; mitigated: `finally: _encrypt_session` в `_with_client:1348-1350` |
| B-5 | Medium | **Legacy `.app_key`** без пароля всё ещё поддерживается | UI предлагает миграцию — OK; предупреждать при первом запуске |
| B-6 | Low | **PostgreSQL runtime не реализован** — только schema | Для локали не критично |
| B-7 | Low | **`_encrypt_session` при shutdown без unlock** молча пропускает | Комментарий в коде осознанный; документировать для оператора |

### API surface (локально)

Полный REST + WebSocket `/ws/status`. Ключевые группы:

- Profiles: login flow (SMS, password), bulk import, proxy
- Groups: CRUD, profiles M2M, group proxy
- Campaign: start/stop/pause/reset/schedule/retry/test
- Vault: setup/unlock/lock/status
- Settings: 40+ antiban параметров с Pydantic-валидацией
- Backup: auto loop + manual `/api/backup/now`

---

## 3. Anti-ban (`antiban_core.py` + логика в `main.py`)

### Реализовано

| Механизм | Статус |
|----------|--------|
| Паузы lognormal + jitter | ✅ |
| Дневные лимиты + warmup | ✅ |
| Cooldown эскалация | ✅ `escalating_cooldown_hours` |
| Circuit breaker | ✅ |
| Send windows (weekday/weekend) | ✅ |
| Role plan (active/quiet/skip) | ✅ |
| Human pauses (short/long) | ✅ |
| Text dedupe / spintax | ✅ |
| Proxy per group / pool rotation | ✅ |
| Human presence (read/react/idle) | ✅ |

### Замечания

| # | Severity | Finding |
|---|----------|---------|
| A-1 | Info | Antiban state частично in-memory (`_human_burst_count`) — теряется при рестарте; часть в `antiban_state` table |
| A-2 | Info | Неофициальный API — риск бана аккаунтов остаётся; документировано в README |

---

## 4. Frontend (`static/index.html` ~2032 строки)

### Сильные стороны (vs AUDIT UX 4/10)

- ✅ **Toast** вместо `alert()` — AUDIT UX fix done
- ✅ **`withLoading`** на кнопках кампании, vault, backup
- ✅ **Пауза / сброс / расписание / retry / test** в UI
- ✅ **Vault UI** — setup, unlock, lock, legacy migration
- ✅ **WebSocket** статус с fallback на polling 2s
- ✅ **Responsive** `@media (max-width: 720px)`
- ✅ Современный dark UI (Manrope, badges, sticky topbar)
- ✅ Bulk import профилей из файла
- ✅ Dashboard, campaigns history, settings audit

### Открытые проблемы

| # | Severity | Finding | Рекомендация |
|---|----------|---------|--------------|
| F-1 | Medium | **~2032 строки в одном HTML** — сложно поддерживать | Разбить на partials или Alpine/HTMX (ADR-005) |
| F-2 | Medium | **Google Fonts CDN** — offline exe | Self-host fonts в `static/` |
| F-3 | Low | Polling fallback каждые 2s при WS disconnect | Приемлемо для локали |
| F-4 | Low | Нет empty-state иллюстраций для нового пользователя | Onboarding hint на первом запуске |
| F-5 | Low | PIN API опционален локально — UI не напоминает установить перед переносом на сервер | Badge «PIN не задан» в settings |

---

## 5. Database (SQLite локально)

### Schema

11+ таблиц с inline `_migrate_schema()` — работает для portable exe без Alembic.

| Таблица | Назначение |
|---------|------------|
| profiles, groups, group_profiles | аккаунты и группы |
| message_pool, queue_state | сообщения и прогресс |
| send_log, app_log, settings_audit | история |
| campaigns, campaign_schedule | кампании |
| antiban_state | persisted antiban |

### Замечания

| # | Severity | Finding |
|---|----------|---------|
| D-1 | Medium | Нет версионированных миграций (Alembic) — `_migrate_schema` ad-hoc |
| D-2 | Medium | SQLite + один процесс ≈ **потолок ~100 аккаунтов** при активной рассылке |
| D-3 | Low | `schema_pg.sql` есть, runtime PG — не для локали |
| D-4 | Low | Backup loop + manual backup — хорошо для локали |

---

## 6. Security (локальный контекст)

| Контроль | Статус | Комментарий |
|----------|--------|-------------|
| Session encryption (Fernet) | ✅ | Vault PBKDF2 + legacy path |
| API PIN (scrypt) | ✅ | Опционален на localhost — **by design** |
| Rate limiting | ✅ | 180/min per IP |
| Upload size limit | ✅ | 5 MB |
| Secrets in git | ✅ | `.gitignore` для `.app_key`, `data/` |
| Settings audit log | ✅ | Маскировка секретов |
| Bind 127.0.0.1 | ✅ | Default `MAX_HOST=127.0.0.1` |

| # | Severity | Finding |
|---|----------|---------|
| S-1 | Medium | Локально PIN не обязателен — любой на машине может управлять рассылкой через localhost |
| S-2 | Low | Legacy `.app_key` plaintext до миграции |
| S-3 | Info | `data/` = полный доступ к аккаунтам MAX — документировано |

**Для локали это приемлемо** — защита = физический доступ к ПК + vault password.

---

## 7. Quality / Testing

| Аспект | Статус |
|--------|--------|
| Unit tests | ❌ 0 файлов в корне проекта |
| Integration tests | ❌ |
| `_self_check_round_robin()` | ✅ runtime self-check при старте |
| Manual test flows | ✅ test send, campaign test API |
| CI | ❌ |
| Linting | ❌ не настроен |

**Критический gap:** без smoke-тестов каждый релиз exe — ручная проверка.

---

## 8. AUDIT.md — сверка (P0/P1)

| ID | Проблема AUDIT | Статус v1.13 |
|----|----------------|--------------|
| P0-1 | Сброс прогресса при Start | ✅ Исправлено |
| P0-2 | Нет retry | ✅ `_send_with_retry` |
| P0-3 | Plaintext `.app_key` | ✅ Vault + migration |
| P0-4 | Session plaintext on crash | 🟡 Mitigated (`finally` encrypt) |
| P0-5 | Graceful shutdown | ✅ SIGINT/SIGTERM |
| P0-6 | New SQLite conn each call | ✅ Singleton WAL |
| P0-7 | get_setting без кеша | ✅ Cache |
| P0-8 | Log только в RAM | ✅ `app_log` table |
| P1-1 | PIN plaintext | ✅ scrypt |
| P1-2 | Upload limit | ✅ 5 MB |
| P1-3 | Rate limit | ✅ 180/min |
| P1-4 | Magic strings status | 🟡 Enum есть, не везде |
| P1-5 | Settings validation | ✅ Extensive Pydantic |
| P1-6 | Health check | ✅ Enhanced |
| UX toast | alert() | ✅ toast() |
| UX loading | нет | ✅ withLoading |
| UX pause | нет | ✅ pause/reset API + UI |

**Вывод:** `AUDIT.md` **существенно устарел** по оценкам (4/10 overall) и размеру кодовой базы. Рекомендуется обновить или заменить этим документом.

---

## 9. Приоритетный backlog (локальная версия)

### P0 — Quick wins (S)

1. Обновить `README.md`: различие `run.bat` vs exe, vault setup, PIN optional
2. Self-host fonts или убрать CDN-зависимость
3. Smoke test script (pytest): health, settings validation, round-robin self-check

### P1 — Качество (M)

4. Выделить `tests/test_campaign_flow.py` — pause/resume не сбрасывает индексы
5. Badge «PIN не задан» / «Legacy vault» в UI settings
6. Onboarding: первый запуск → vault setup wizard

### P2 — Maintainability (L)

7. Инкрементальный refactor `main.py` → modules (по AUDIT structure)
8. Alembic или numbered migrations вместо ad-hoc `_migrate_schema`
9. Разбить `index.html` (если UI продолжит расти)

### P3 — Scale (когда >50 аккаунтов)

10. PostgreSQL runtime
11. Celery profile tuning
12. CI + auto exe build

---

## 10. Рекомендуемые следующие `/start-feature`

```text
/start-feature добавить smoke-тесты для локали: health, vault, campaign pause/resume
/start-feature убрать зависимость UI от Google Fonts для offline exe
/start-feature onboarding: wizard первого запуска (vault + сообщения + группа)
/start-feature обновить AUDIT.md по результатам PROJECT-REVIEW
```

---

## 11. Итоговый вердикт

| Критерий | Оценка |
|----------|--------|
| Готовность для локальной работы (5–50 акк.) | **8/10** |
| Готовность к росту (100+ акк.) | **4/10** |
| Готовность к переносу на сервер | **5/10** (server hooks — stubs) |
| Качество кода / поддерживаемость | **5/10** |
| UX admin panel | **7/10** |

**MAX Sender v1.13 — зрелый локальный инструмент** с продуманным antiban и богатым UI. Основной технический долг: **монолит без тестов**. Для вашего сценария (локальная разработка → потом сервер) логичный порядок: **smoke-тесты → offline UI → onboarding → server hooks**.

---

*Review performed: static code analysis, 2026-07-28. No runtime execution on this machine.*
