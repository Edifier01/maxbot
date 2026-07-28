# MAX Sender — Полный технический аудит

> Документ предназначен для AI-агентов и разработчиков.  
> Используй его как техническое задание на исправление и улучшение проекта.  
> Каждая секция содержит конкретные проблемы и конкретные решения.

---

## Карта проекта

```
max-app/
  main.py           — ВСЯ backend логика (~1 359 строк)
  static/index.html — ВСЬ frontend (~637 строк)
  requirements.txt  — maxapi-python, fastapi, uvicorn, cryptography
  run.bat           — запуск из исходников
  build.bat         — PyInstaller сборка
  max-sender.spec   — конфигурация PyInstaller
  data/
    app.db          — SQLite база данных
    .app_key        — Fernet ключ шифрования (plaintext!)
    sessions/{id}/  — зашифрованные PyMax сессии
    messages/       — active.txt (пул сообщений)
```

### Технический стек
- **Backend:** Python 3.12, FastAPI, Uvicorn, SQLite (stdlib sqlite3)
- **Шифрование:** cryptography.Fernet (AES-128-CBC)
- **API мессенджера:** maxapi-python 2.3.1 (неофициальный PyMax)
- **Frontend:** Vanilla HTML + CSS + JS (без фреймворков)
- **Деплой:** PyInstaller EXE или run.bat + venv

### Схема БД (`data/app.db`)

```sql
profiles       (id, phone UNIQUE, label, status, messages_sent_today, sent_day, last_error, created_at)
groups         (id, name, max_chat_id, invite_link, is_active, created_at)
group_profiles (group_id, profile_id, order_index, is_enabled)  -- M2M
message_pool   (id, text, order_index, loaded_at)
settings       (key TEXT PK, value TEXT)  -- key-value хранилище
queue_state    (id=1, running, profile_idx, message_idx, group_idx)  -- singleton
send_log       (id, profile_id, group_id, message_idx, status, error, sent_at)
```

### API endpoints

| Метод | Путь | Описание |
|-------|------|----------|
| GET | `/api/status` | Статус воркера, прогресс, последние 80 строк лога |
| GET | `/api/profiles` | Список профилей (offset, limit, q) |
| GET | `/api/profiles/{id}` | Профиль + auth_step |
| POST | `/api/profiles/{id}/login` | Запустить вход (?fresh=true) |
| POST | `/api/profiles/{id}/login/reset` | Сброс зависшего входа |
| POST | `/api/profiles/{id}/sms` | Отправить SMS код |
| POST | `/api/profiles/{id}/password` | Отправить облачный пароль |
| PATCH | `/api/profiles/{id}/disable` | Отключить профиль |
| GET | `/api/groups` | Список групп |
| POST | `/api/groups` | Создать группу |
| DELETE | `/api/groups/{id}` | Удалить группу |
| GET | `/api/groups/{id}/profiles` | Профили группы (paginated) |
| POST | `/api/groups/{id}/profiles` | Добавить профиль в группу |
| DELETE | `/api/groups/{id}/profiles/{pid}` | Удалить профиль из группы |
| GET | `/api/messages` | Пул сообщений |
| POST | `/api/messages/upload` | Загрузить .txt файл |
| GET | `/api/settings` | Настройки |
| PUT | `/api/settings` | Обновить настройки |
| POST | `/api/campaign/start` | Запустить кампанию |
| POST | `/api/campaign/stop` | Остановить кампанию |
| GET | `/api/log` | Последние 200 строк лога |
| GET | `/api/send_log` | История отправок (paginated) |

---

## Оценки проекта

| Категория | Оценка | Причина |
|-----------|--------|---------|
| Архитектура | 4/10 | Монолит, нет слоёв, нет DI, нет репозиториев |
| Код | 5/10 | Чистый MVP, но 1 359 строк в одном файле |
| UI | 5/10 | Минимальный тёмный UI, нет иконок, нет loading states |
| UX | 4/10 | alert() для ошибок, 2с polling, нет паузы кампании |
| Производительность | 5/10 | Новое SQLite-соединение на каждый вызов |
| Масштабируемость | 3/10 | SQLite + in-process asyncio = потолок ~100 аккаунтов |
| Безопасность | 6/10 | Fernet хорошо, PIN и ключ без защиты |
| Поддерживаемость | 3/10 | 0 тестов, нет миграций, нет типизации |
| Автоматизация | 3/10 | Всё ручное, нет retry, нет мониторинга |
| **Продукт в целом** | **4/10** | Рабочий MVP при 5-20 акк., не готов к росту |

---

## КРИТИЧЕСКИЕ ПРОБЛЕМЫ (исправить в первую очередь)

### P0-1 — Прогресс кампании сбрасывается при Стоп/Старт
**Файл:** `main.py`, функция `_start_worker()`, строка ~796  
**Проблема:** `UPDATE queue_state SET running=1, profile_idx=0, message_idx=0, group_idx=0` — все индексы обнуляются. При повторном Старте кампания начинается заново, все сообщения отправляются повторно.  
**Решение:**
```python
# Не сбрасывать message_idx если он был > 0 (кампания была на паузе)
async def _start_worker() -> None:
    global _worker_task
    async with _worker_lock:
        if _worker_task and not _worker_task.done():
            return
        with _conn() as c:
            # Только сбрасываем running, не трогаем индексы прогресса
            c.execute("UPDATE queue_state SET running=1 WHERE id=1")
        _worker_task = asyncio.create_task(_worker_loop())
```
Добавить кнопку "Начать заново" в UI, которая отдельно сбрасывает индексы.

---

### P0-2 — Нет retry при ошибке отправки
**Файл:** `main.py`, `_worker_loop()`, строка ~758  
**Проблема:** Один сетевой сбой → профиль помечается `needs_reauth` и выбывает до ручного вмешательства.  
**Решение:**
```python
MAX_RETRY = 3
RETRY_DELAYS = [5, 15, 60]  # секунды

async def _send_with_retry(profile, group, text, messages, mi, gi, pi):
    for attempt in range(MAX_RETRY):
        try:
            # ... текущий код отправки ...
            return True  # успех
        except Exception as e:
            err = str(e)
            is_auth_err = "auth" in err.lower() or "session" in err.lower()
            if is_auth_err or attempt == MAX_RETRY - 1:
                _mark_profile_failed(profile["id"], err, is_auth_err)
                return False
            append_log(f"Попытка {attempt+1}/{MAX_RETRY} для #{profile['id']}, retry через {RETRY_DELAYS[attempt]}с")
            await asyncio.sleep(RETRY_DELAYS[attempt])
    return False
```

---

### P0-3 — Ключ Fernet в plaintext файле `.app_key`
**Файл:** `main.py`, функция `_get_fernet()`, строка ~254  
**Проблема:** Ключ хранится в открытом виде. Любой с доступом к `data/` может расшифровать все сессии.  
**Решение:** Защитить ключ паролем через PBKDF2:
```python
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC
from cryptography.hazmat.primitives import hashes
import base64, os

def _get_fernet(password: str) -> Fernet:
    salt_path = DATA / ".app_salt"
    if not salt_path.exists():
        salt_path.write_bytes(os.urandom(16))
    salt = salt_path.read_bytes()
    kdf = PBKDF2HMAC(algorithm=hashes.SHA256(), length=32, salt=salt, iterations=480000)
    key = base64.urlsafe_b64encode(kdf.derive(password.encode()))
    return Fernet(key)
```
UI: при первом запуске запрашивать пароль, при последующих — вводить для расшифровки.

---

### P0-4 — Сессия расшифровывается на диск во время работы
**Файл:** `main.py`, `_decrypt_session()` + `_with_client()`  
**Проблема:** `session.db` пишется на диск в открытом виде. При краше процесса остаётся незашифрованной.  
**Решение:** Обернуть весь блок в try/finally чтобы гарантировать шифрование:
```python
async def _with_client(profile_id, phone, fn, ...):
    _decrypt_session(profile_id)
    try:
        # ... вся текущая логика ...
    finally:
        _encrypt_session(profile_id)  # всегда, даже при исключении
```
В текущем коде `_encrypt_session` уже вызывается в `finally`, но только после `_safe_stop`. Убедиться что это происходит даже при `KeyboardInterrupt`.

---

### P0-5 — Graceful shutdown при Ctrl+C/SIGTERM
**Файл:** `main.py`, `if __name__ == "__main__":`  
**Проблема:** При Ctrl+C процесс убивается, `session.db` может остаться на диске.  
**Решение:**
```python
import signal

def _handle_signal(signum, frame):
    # Зашифровать все открытые сессии
    for profile_id in list(_auth_sessions.keys()):
        _encrypt_session(profile_id)
    sys.exit(0)

signal.signal(signal.SIGTERM, _handle_signal)
signal.signal(signal.SIGINT, _handle_signal)
```

---

### P0-6 — Новое SQLite-соединение на каждый вызов `_conn()`
**Файл:** `main.py`, функция `_conn()`, строка ~80  
**Проблема:** Каждый вызов открывает новое соединение. ~5-10 открытий на итерацию воркера = тысячи в час.  
**Решение:** Singleton соединение с WAL режимом:
```python
_db_conn: sqlite3.Connection | None = None
_db_lock = threading.Lock()

def _conn() -> sqlite3.Connection:
    global _db_conn
    with _db_lock:
        if _db_conn is None:
            _db_conn = sqlite3.connect(DB_PATH, check_same_thread=False)
            _db_conn.row_factory = sqlite3.Row
            _db_conn.execute("PRAGMA foreign_keys=ON")
            _db_conn.execute("PRAGMA journal_mode=WAL")
            _db_conn.execute("PRAGMA synchronous=NORMAL")
        return _db_conn
```
Или использовать `sqlite3.connect(..., check_same_thread=False)` с пулом через `threading.local()`.

---

### P0-7 — `get_setting()` читает БД без кеша
**Файл:** `main.py`, `get_setting()` и `_worker_loop()`  
**Проблема:** В `_worker_loop` `get_setting()` вызывается 3+ раз на каждую итерацию (delay_min, delay_max, jitter).  
**Решение:**
```python
_settings_cache: dict[str, str] = {}
_settings_cache_lock = threading.Lock()

def get_setting(key: str) -> str:
    with _settings_cache_lock:
        if key in _settings_cache:
            return _settings_cache[key]
    with _conn() as c:
        row = c.execute("SELECT value FROM settings WHERE key=?", (key,)).fetchone()
        val = row["value"] if row else DEFAULTS.get(key, "")
    with _settings_cache_lock:
        _settings_cache[key] = val
    return val

def set_setting(key: str, value: str) -> None:
    with _conn() as c:
        c.execute("INSERT INTO settings (key,value) VALUES(?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value", (key, value))
    with _settings_cache_lock:
        _settings_cache[key] = value  # инвалидация
```

---

### P0-8 — Persistent log теряется при перезапуске
**Файл:** `main.py`, `_log: list[str]` + `append_log()`  
**Проблема:** `_log` только в RAM, теряется при выходе из программы.  
**Решение:** Добавить таблицу `app_log` в SQLite:
```sql
CREATE TABLE IF NOT EXISTS app_log (
    id INTEGER PRIMARY KEY,
    ts TEXT DEFAULT (datetime('now')),
    msg TEXT NOT NULL
);
```
```python
def append_log(msg: str) -> None:
    line = f"[{date.today()}] {msg}"
    with _log_lock:
        _log.append(line)
        if len(_log) > 500:
            del _log[:len(_log) - 500]
    # Дополнительно писать в БД
    try:
        with _conn() as c:
            c.execute("INSERT INTO app_log (msg) VALUES (?)", (msg,))
            c.execute("DELETE FROM app_log WHERE id NOT IN (SELECT id FROM app_log ORDER BY id DESC LIMIT 5000)")
    except Exception:
        pass  # не ломаем основной поток
```

---

### P1-1 — PIN API хранится в SQLite без хеширования
**Файл:** `main.py`, `ApiPinMiddleware`, `get_settings()`, `update_settings()`  
**Проблема:** `settings.key='api_pin', value='plaintext'`  
**Решение:**
```python
from cryptography.hazmat.primitives.kdf.scrypt import Scrypt
import os, base64

def _hash_pin(pin: str) -> str:
    salt = os.urandom(16)
    kdf = Scrypt(salt=salt, length=32, n=2**14, r=8, p=1)
    key = kdf.derive(pin.encode())
    return base64.b64encode(salt + key).decode()

def _verify_pin(pin: str, stored: str) -> bool:
    try:
        raw = base64.b64decode(stored)
        salt, key = raw[:16], raw[16:]
        kdf = Scrypt(salt=salt, length=32, n=2**14, r=8, p=1)
        kdf.verify(pin.encode(), key)
        return True
    except Exception:
        return False
```
В `ApiPinMiddleware` использовать `_verify_pin(token, stored_hash)` вместо сравнения строк.

---

### P1-2 — Нет лимита размера загружаемого файла
**Файл:** `main.py`, `upload_messages()`  
**Решение:**
```python
MAX_UPLOAD_BYTES = 5 * 1024 * 1024  # 5 MB

@app.post("/api/messages/upload")
async def upload_messages(file: UploadFile = File(...)):
    content = await file.read(MAX_UPLOAD_BYTES + 1)
    if len(content) > MAX_UPLOAD_BYTES:
        raise HTTPException(413, "Файл слишком большой (максимум 5 МБ)")
    # ... остальной код ...
```

---

### P1-3 — Rate limiting на API endpoints
**Файл:** `main.py`, после `ApiPinMiddleware`  
**Решение:** Добавить простой rate limiter:
```python
from collections import defaultdict
import time

_rate_counters: dict[str, list[float]] = defaultdict(list)
RATE_LIMIT = 60  # запросов
RATE_WINDOW = 60  # секунд

class RateLimitMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        if not request.url.path.startswith("/api"):
            return await call_next(request)
        ip = request.client.host if request.client else "127.0.0.1"
        now = time.monotonic()
        window = _rate_counters[ip]
        _rate_counters[ip] = [t for t in window if now - t < RATE_WINDOW]
        if len(_rate_counters[ip]) >= RATE_LIMIT:
            return JSONResponse(status_code=429, content={"detail": "Слишком много запросов"})
        _rate_counters[ip].append(now)
        return await call_next(request)
```

---

### P1-4 — Magic strings для статуса профиля
**Файл:** `main.py`, везде  
**Решение:**
```python
from enum import StrEnum

class ProfileStatus(StrEnum):
    PENDING = "pending"
    ACTIVE = "active"
    NEEDS_REAUTH = "needs_reauth"
    DISABLED = "disabled"
```
Заменить все строки `'active'`, `'pending'`, `'needs_reauth'`, `'disabled'` на `ProfileStatus.*`.

---

### P1-5 — Валидация настроек в Pydantic
**Файл:** `main.py`, класс `SettingsIn`  
**Проблема:** `delay_min > delay_max` не проверяется.  
**Решение:**
```python
from pydantic import model_validator

class SettingsIn(BaseModel):
    delay_min_sec: int | None = None
    delay_max_sec: int | None = None
    max_msgs_per_profile_day: int | None = None
    jitter_percent: int | None = None
    password_max_attempts: int | None = None
    api_pin: str | None = None

    @model_validator(mode="after")
    def check_delays(self) -> "SettingsIn":
        lo = self.delay_min_sec
        hi = self.delay_max_sec
        if lo is not None and hi is not None and lo > hi:
            raise ValueError("delay_min_sec не может быть больше delay_max_sec")
        if self.jitter_percent is not None and not (0 <= self.jitter_percent <= 100):
            raise ValueError("jitter_percent должен быть от 0 до 100")
        return self
```

---

### P1-6 — Health check endpoint
**Файл:** `main.py`  
**Решение:**
```python
@app.get("/api/health")
async def health():
    try:
        with _conn() as c:
            c.execute("SELECT 1").fetchone()
        db_ok = True
    except Exception:
        db_ok = False
    return {
        "ok": db_ok,
        "worker_running": bool(_worker_task and not _worker_task.done()),
        "version": "1.0.0",
    }
```

---

## АРХИТЕКТУРНЫЕ УЛУЧШЕНИЯ (P1-P2)

### Рекомендуемая структура (после рефакторинга)
```
max_sender/
  api/
    __init__.py
    profiles.py      — /api/profiles/*
    groups.py        — /api/groups/*
    messages.py      — /api/messages/*
    campaign.py      — /api/campaign/*
    settings.py      — /api/settings
    logs.py          — /api/log, /api/send_log
  services/
    profile_service.py
    campaign_service.py
    auth_service.py
  repositories/
    profile_repo.py
    group_repo.py
    log_repo.py
  domain/
    enums.py         — ProfileStatus, AuthStep
    exceptions.py    — ProfileNotFound, AuthFailed, etc.
    models.py        — dataclasses Profile, Group, Campaign
  workers/
    campaign_worker.py
    retry_worker.py
  crypto/
    session_crypto.py
  config.py          — pydantic-settings, .env support
  database.py        — connection pool, init_db, migrations
  main.py            — FastAPI app factory только
tests/
  test_round_robin.py
  test_settings.py
  test_campaign.py
  test_api.py
```

### Alembic миграции
```bash
pip install alembic
alembic init alembic
```
Перенести `CREATE TABLE IF NOT EXISTS` из `init_db()` в миграции Alembic.  
Первая миграция: `001_initial_schema.py`.

---

## UX ИСПРАВЛЕНИЯ (P1-P2)

### 1. Toast-уведомления вместо alert()
**Файл:** `static/index.html`  
Добавить в CSS:
```css
#toast-container {
  position: fixed; bottom: 1.5rem; right: 1.5rem;
  display: flex; flex-direction: column; gap: .5rem; z-index: 200;
}
.toast {
  background: #27272a; border: 1px solid #3f3f46; color: #e4e4e7;
  padding: .6rem 1rem; border-radius: 8px; font-size: .85rem;
  animation: slideIn .2s ease; max-width: 320px;
}
.toast.success { border-color: #166534; }
.toast.error   { border-color: #991b1b; }
@keyframes slideIn { from { transform: translateX(100%); opacity: 0; } to { transform: translateX(0); opacity: 1; } }
```
Добавить в JS:
```javascript
function toast(msg, type = 'info', duration = 4000) {
  const c = document.getElementById('toast-container') || (() => {
    const el = document.createElement('div');
    el.id = 'toast-container';
    document.body.appendChild(el);
    return el;
  })();
  const t = document.createElement('div');
  t.className = `toast ${type}`;
  t.textContent = msg;
  c.appendChild(t);
  setTimeout(() => t.remove(), duration);
}
// Заменить все alert(e.message) на toast(e.message, 'error')
// Заменить все alert('Сохранено') на toast('Сохранено', 'success')
```

### 2. Loading state для кнопок
```javascript
async function withLoading(btn, asyncFn) {
  const orig = btn.textContent;
  btn.disabled = true;
  btn.textContent = '...';
  try {
    await asyncFn();
  } finally {
    btn.disabled = false;
    btn.textContent = orig;
  }
}
// Использование:
// onclick="withLoading(this, () => startCampaign())"
```

### 3. Progress bar кампании
В HTML заменить `<span id="campaignProgress" class="hint"></span>` на:
```html
<div id="progressWrap" style="display:none; flex:1; align-items:center; gap:.5rem">
  <div style="flex:1; height:6px; background:#27272a; border-radius:3px; overflow:hidden">
    <div id="progressBar" style="height:100%; background:#2563eb; border-radius:3px; transition:width .5s"></div>
  </div>
  <span id="campaignProgress" class="hint" style="white-space:nowrap"></span>
</div>
```
В `refreshStatus()`:
```javascript
const prog = s.campaign_progress || {};
if (prog.total > 0) {
  const pct = (prog.sent / prog.total * 100).toFixed(1);
  document.getElementById('progressWrap').style.display = 'flex';
  document.getElementById('progressBar').style.width = pct + '%';
  const eta = s.running ? _calcEta(prog.sent, prog.total) : '';
  document.getElementById('campaignProgress').textContent = `${prog.sent}/${prog.total}  ${eta}`;
} else {
  document.getElementById('progressWrap').style.display = 'none';
}
```

### 4. ETA вычисление (в JS)
```javascript
let _etaStartTime = null;
let _etaStartSent = 0;

function _calcEta(sent, total) {
  if (!_etaStartTime || sent <= _etaStartSent) {
    _etaStartTime = Date.now();
    _etaStartSent = sent;
    return '';
  }
  const elapsed = (Date.now() - _etaStartTime) / 1000;
  const rate = (sent - _etaStartSent) / elapsed;  // сообщений/сек
  if (rate <= 0) return '';
  const remaining = (total - sent) / rate;
  const m = Math.floor(remaining / 60);
  const s = Math.floor(remaining % 60);
  return `~${m}м ${s}с`;
}
```

### 5. Bulk CSV import профилей
В HTML (в секции groups):
```html
<input type="file" id="csvFile" accept=".csv,.txt" style="display:none">
<button class="small" onclick="document.getElementById('csvFile').click()">Импорт CSV</button>
```
В JS:
```javascript
document.getElementById('csvFile').addEventListener('change', async (e) => {
  const f = e.target.files[0];
  if (!f) return;
  const text = await f.text();
  const lines = text.split('\n').map(l => l.trim()).filter(Boolean);
  for (const line of lines) {
    const [phone, label = ''] = line.split(',');
    if (!phone) continue;
    try {
      await api(`/groups/${openGroupId}/profiles`, {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({ phone: phone.trim(), label: label.trim() }),
      });
    } catch (e) {
      toast(`${phone}: ${e.message}`, 'error');
    }
  }
  loadGroups(true);
  toast(`Импорт завершён`, 'success');
});
```

### 6. Подтверждение перед стартом
Заменить `startCampaign()`:
```javascript
async function startCampaign() {
  const s = await api('/status');
  const prog = s.campaign_progress || {};
  const profiles = Object.entries(s.profiles || {});
  const activeCount = s.profiles?.active || 0;
  const msg = [
    `Сообщений: ${prog.total || s.messages_count}`,
    `Активных профилей: ${activeCount}`,
    prog.sent > 0 ? `Продолжить с позиции ${prog.sent}` : 'Старт с начала',
  ].join('\n');
  if (!confirm(`Запустить рассылку?\n\n${msg}`)) return;
  try {
    await api('/campaign/start', { method: 'POST' });
    refreshStatus();
    toast('Рассылка запущена', 'success');
  } catch (e) {
    toast(e.message, 'error');
  }
}
```

### 7. Пауза / возобновление
Добавить endpoint в `main.py`:
```python
@app.post("/api/campaign/pause")
async def campaign_pause():
    """Остановить без сброса индексов."""
    global _worker_task
    with _conn() as c:
        c.execute("UPDATE queue_state SET running=0 WHERE id=1")
    if _worker_task:
        _worker_task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await _worker_task
        _worker_task = None
    return {"ok": True}
```
В HTML добавить кнопку "Пауза" рядом со "Стоп".

---

## ПРОИЗВОДИТЕЛЬНОСТЬ (P1-P2)

### Устранение N+1 в list_groups()
**Файл:** `main.py`, `list_groups()`, строка ~1119  
```python
@app.get("/api/groups")
async def list_groups():
    with _conn() as c:
        rows = c.execute("""
            SELECT g.*,
                   COUNT(CASE WHEN gp.is_enabled=1 AND p.status='active' THEN 1 END) AS active_count,
                   COUNT(CASE WHEN gp.is_enabled=1 THEN 1 END) AS profiles_count
            FROM groups g
            LEFT JOIN group_profiles gp ON gp.group_id = g.id
            LEFT JOIN profiles p ON p.id = gp.profile_id
            GROUP BY g.id
            ORDER BY g.id
        """).fetchall()
    return [dict(r) for r in rows]
```

### WebSocket вместо polling
**Файл:** `main.py` + `static/index.html`  
```python
from fastapi import WebSocket

@app.websocket("/ws/status")
async def ws_status(ws: WebSocket):
    await ws.accept()
    try:
        while True:
            status = await _build_status()
            await ws.send_json(status)
            await asyncio.sleep(1)
    except Exception:
        pass
```
В JS заменить `setInterval` на:
```javascript
const ws = new WebSocket('ws://127.0.0.1:8765/ws/status');
ws.onmessage = (e) => applyStatus(JSON.parse(e.data));
```

---

## БЕЗОПАСНОСТЬ (P0-P1)

### Checklist исправлений

- [ ] **Хеширование PIN** — использовать `scrypt` или `bcrypt` вместо plaintext в SQLite
- [ ] **Защита ключа Fernet** — PBKDF2 с паролем пользователя вместо plaintext `.app_key`
- [ ] **Rate limiting** — добавить `RateLimitMiddleware` (см. выше)
- [ ] **Лимит upload** — 5 MB максимум для `messages.txt`
- [ ] **Graceful shutdown** — шифровать сессии при SIGTERM/SIGINT
- [ ] **Аудит-лог** — логировать изменения настроек с временной меткой
- [ ] **PIN из localStorage** — рассмотреть sessionStorage или HTTP-only cookie

---

## НАДЁЖНОСТЬ (P1)

### Circuit breaker
```python
_consecutive_errors: dict[int, int] = {}  # profile_id -> count
MAX_CONSECUTIVE_ERRORS = 5
CIRCUIT_BREAK_MINUTES = 30

def _is_circuit_open(profile_id: int) -> bool:
    return _consecutive_errors.get(profile_id, 0) >= MAX_CONSECUTIVE_ERRORS

def _on_success(profile_id: int) -> None:
    _consecutive_errors.pop(profile_id, None)

def _on_error(profile_id: int) -> None:
    _consecutive_errors[profile_id] = _consecutive_errors.get(profile_id, 0) + 1
```

### Watchdog для воркера
```python
_worker_last_activity: float = 0.0
WORKER_TIMEOUT = 300  # 5 минут без активности = зависание

async def _watchdog_loop() -> None:
    while True:
        await asyncio.sleep(60)
        if _worker_task and not _worker_task.done():
            idle = time.monotonic() - _worker_last_activity
            if idle > WORKER_TIMEOUT:
                append_log(f"Watchdog: воркер завис ({idle:.0f}с без активности) — перезапуск")
                await _stop_worker()
                await _start_worker()
```

---

## НОВЫЕ ФУНКЦИИ (идеи для реализации)

### Высокий приоритет (P1-P2)

1. **Bulk CSV import** — `POST /api/groups/{id}/profiles/bulk`, принимает CSV с колонками `phone,label`
2. **Персонализация** — переменные `{{phone}}`, `{{label}}`, `{{date}}` в тексте сообщений
3. **История кампаний** — таблица `campaigns` с сохранением конфигурации каждого запуска
4. **Dashboard** — новая вкладка со статусом всех аккаунтов в виде карточек
5. **Расписание** — `POST /api/campaign/schedule` с параметром `start_at: datetime`
6. **Webhook** — `POST /api/settings` добавить поле `webhook_url`, вызывать при завершении
7. **Retry failed** — `POST /api/campaign/retry_failed` — повторить только строки из `send_log` со статусом `failed`
8. **Test send** — `POST /api/campaign/test` — отправить первое сообщение первым активным профилем

### Средний приоритет (P2-P3)

9. **Spintax** — парсер `{вариант1|вариант2|вариант3}` в тексте сообщений
10. **Черный список** — таблица `blocklist(phone)`, проверка перед отправкой
11. **Метки групп и профилей** — поле `tags TEXT` в таблицах, фильтрация по тегам
12. **Экспорт CSV** — `GET /api/send_log/export` с фильтрами
13. **Уведомление браузера** — Web Notification API при завершении кампании
14. **Имя аккаунта** — сохранять `me.first_name`, `me.last_name` после login в `profiles.display_name`
15. **Telegram webhook** — настройка bot_token + chat_id для уведомлений в Telegram

---

## ROADMAP

### Sprint 1 — Стабилизация (1-2 недели, сложность: Medium)
**Приоритет: Critical**

| Задача | Файл | Строки |
|--------|------|--------|
| WAL mode + singleton соединение | `main.py` `_conn()` | ~80 |
| Кеш настроек с invalidation | `main.py` `get_setting()` | ~154 |
| Сохранение message_idx при Stop | `main.py` `_start_worker()` | ~790 |
| Retry с backoff (3 попытки) | `main.py` `_worker_loop()` | ~715 |
| Persistent log в SQLite | `main.py` `append_log()` | ~169 |
| Graceful shutdown | `main.py` `__main__` | ~1339 |
| Enum ProfileStatus | `main.py` | везде |
| Pydantic validators в SettingsIn | `main.py` `SettingsIn` | ~834 |
| Лимит upload 5 MB | `main.py` `upload_messages()` | ~1261 |
| Rate limiting middleware | `main.py` | новый класс |

**Ожидаемый результат:** Стабильная работа при 10-50 аккаунтах, нет потери прогресса.

---

### Sprint 2 — UX (1-2 недели, сложность: Medium)
**Приоритет: High**

| Задача | Файл |
|--------|------|
| Toast вместо alert() | `index.html` |
| Loading states для кнопок | `index.html` |
| Progress bar + ETA | `index.html` |
| Подтверждение перед стартом | `index.html` |
| Пауза / возобновление | `main.py` + `index.html` |
| Bulk CSV import | `main.py` + `index.html` |
| Поиск/фильтр в истории | `main.py` + `index.html` |
| Dashboard вкладка | `index.html` |

**Ожидаемый результат:** Оператор работает в 2x быстрее, нет раздражающих alert().

---

### Sprint 3 — Безопасность (1 неделя, сложность: Medium-High)
**Приоритет: High**

| Задача | Файл |
|--------|------|
| Хеширование PIN (scrypt) | `main.py` |
| Защита ключа Fernet (PBKDF2) | `main.py` |
| Аудит-лог изменений настроек | `main.py` |
| Health check endpoint | `main.py` |
| Circuit breaker | `main.py` |
| Watchdog для воркера | `main.py` |

**Ожидаемый результат:** Безопасность ≥8/10, автовосстановление при зависании.

---

### Sprint 4 — UI (1 неделя, сложность: Medium)
**Приоритет: Medium**

| Задача | Файл |
|--------|------|
| SVG иконки для кнопок | `index.html` |
| Цветная подсветка FAIL/OK в логе | `index.html` |
| История как таблица | `index.html` |
| Empty states с подсказками | `index.html` |
| Tooltips для параметров | `index.html` |
| Responsive layout | `index.html` |
| Уведомление браузера при завершении | `index.html` |

**Ожидаемый результат:** Профессиональный внешний вид, быстрая ориентация.

---

### Sprint 5 — Автоматизация (2 недели, сложность: High)
**Приоритет: Medium**

| Задача | Файл |
|--------|------|
| Расписание кампаний | `main.py` |
| Webhook при завершении | `main.py` |
| Авто-реавторизация при InvalidToken | `main.py` |
| Telegram уведомления | `main.py` |
| История кампаний | `main.py` + `index.html` |
| Retry failed | `main.py` + `index.html` |
| Авто-backup БД | `main.py` |

**Ожидаемый результат:** Система работает без постоянного надзора.

---

### Sprint 6 — Масштабирование ✅ (v1.5.0)
**Приоритет: Low (когда нужно >100 аккаунтов)**

| Задача | Статус |
|--------|--------|
| PostgreSQL schema (`schema_pg.sql`) + DATABASE_URL guard | ✅ staged (runtime = SQLite) |
| Celery + Redis skeleton | ✅ optional |
| Worker pool (N параллельных) | ✅ |
| Prometheus `/metrics` | ✅ |
| Docker Compose | ✅ |

---

## TOP-100 УЛУЧШЕНИЙ

| # | Улучшение | Почему важно | Сложность | Приоритет |
|---|-----------|-------------|-----------|-----------|
| 1 | WAL mode SQLite | Блокировки при конкурентных операциях | Low | P0 |
| 2 | Кеш настроек в памяти | 3+ DB hit на каждое сообщение | Low | P0 |
| 3 | Сохранение message_idx при Stop | Дублирующие отправки при рестарте | Low | P0 |
| 4 | Retry с exponential backoff | Один сбой = профиль выбывает | Low | P0 |
| 5 | Graceful shutdown | session.db на диске при краше | Low | P0 |
| 6 | Persistent log в SQLite | Все события теряются при выходе | Low | P0 |
| 7 | Toast вместо alert() | alert() блокирует интерфейс | Low | P0 |
| 8 | Loading state кнопок | Двойное нажатие = дубли | Low | P0 |
| 9 | Хеширование PIN | PIN в SQLite plaintext | Low | P0 |
| 10 | Rate limiting | Brute-force PIN возможен | Low | P0 |
| 11 | Singleton SQLite conn | _conn() открывает соединение каждый раз | Low | P1 |
| 12 | Пауза / возобновление | Нельзя приостановить без потери места | Medium | P1 |
| 13 | Bulk CSV import | Только по одному номеру | Medium | P1 |
| 14 | Dashboard аккаунтов | Нет обзора без открытия каждой группы | Medium | P1 |
| 15 | Progress bar | Только текст X/Y | Low | P1 |
| 16 | Подтверждение перед стартом | Случайный старт с неверными данными | Low | P1 |
| 17 | ETA до конца | Нет возможности планировать | Low | P1 |
| 18 | Подсветка FAIL/OK в логе | Нет визуального различия | Low | P1 |
| 19 | История как таблица | Monospace строки нечитаемы | Low | P1 |
| 20 | Поиск/фильтр в истории | Нет способа найти запись | Medium | P1 |
| 21 | Alembic миграции | Нельзя изменить схему безопасно | Medium | P1 |
| 22 | Enum ProfileStatus | Magic strings везде | Low | P1 |
| 23 | Pydantic validators | delay_min > delay_max не проверяется | Low | P1 |
| 24 | Service / Repository layer | Endpoints напрямую с SQLite | High | P1 |
| 25 | Unit тесты (pytest) | 0 тестов | Medium | P1 |
| 26 | Webhook при завершении | Нет уведомлений вовне | Low | P2 |
| 27 | Расписание кампаний | Только ручной запуск | Medium | P2 |
| 28 | Персонализация {{переменные}} | Одинаковый текст для всех | Medium | P2 |
| 29 | SVG иконки | Только текстовые кнопки | Low | P2 |
| 30 | Empty states с подсказками | Пустые разделы без объяснений | Low | P2 |
| 31 | Tooltips для параметров | Jitter, round-robin непонятны | Low | P2 |
| 32 | Шаблоны сообщений в БД | Загружать файл каждый раз | Medium | P2 |
| 33 | История кампаний | Нет записи что запускалось | Medium | P2 |
| 34 | Авто-реавторизация | Ручной login при истечении сессии | High | P2 |
| 35 | Мониторинг аккаунтов по расписанию | Статус unknown до следующей отправки | Medium | P2 |
| 36 | Responsive UI | Неудобно на узких экранах | Medium | P2 |
| 37 | Экспорт CSV | Нет выгрузки данных | Low | P2 |
| 38 | Сортировка таблиц | Нет сортировки по колонкам | Low | P2 |
| 39 | Метки/теги | Нет категоризации | Medium | P2 |
| 40 | Приоритеты профилей | Все аккаунты одинаковые | Medium | P2 |
| 41 | Черный список номеров | Нельзя исключить номера | Low | P2 |
| 42 | Spintax {вариант1\|вариант2} | Одинаковые тексты = спам-паттерн | Medium | P2 |
| 43 | Защита ключа Fernet PBKDF2 | Ключ в plaintext файле | Medium | P1 |
| 44 | Бэкап/восстановление из UI | Нет защиты от потери данных | Medium | P2 |
| 45 | Health check /api/health | Нет мониторинга извне | Low | P1 |
| 46 | Уведомление браузера при завершении | Нужно держать вкладку | Low | P2 |
| 47 | Имя аккаунта после login | Только номер телефона | Low | P2 |
| 48 | Circuit breaker | Воркер долбит недоступный API | Medium | P1 |
| 49 | Watchdog воркера | Hung connection — молчание | Medium | P1 |
| 50 | WebSocket вместо polling 2с | 6+ API calls/сек | Medium | P2 |
| 51 | Swagger UI в настройках | API не задокументирован | Low | P3 |
| 52 | Favicon | Нет favicon | Low | P3 |
| 53 | Горячие клавиши | Только мышь | Low | P3 |
| 54 | Test-send (тест без кампании) | Нельзя проверить без запуска | Medium | P2 |
| 55 | Retry failed из истории | Запускать всю кампанию заново | Medium | P2 |
| 56 | Env переменные PORT/HOST | Захардкожены в main.py | Low | P2 |
| 57 | .env поддержка | Настройки только через UI | Low | P2 |
| 58 | Structured JSON logging | Plaintext лог без полей | Low | P3 |
| 59 | A/B тестирование сообщений | Нет проверки эффективности | Medium | P3 |
| 60 | AI-генерация вариантов | Ручное написание | High | P3 |
| 61 | Ротация прокси | Все запросы с одного IP | High | P3 |
| 62 | Прогрев аккаунта (warmup) | Новые акк. сразу на полной нагрузке | High | P2 |
| 63 | Квота на группу | Только лимит профиль/день | Medium | P3 |
| 64 | Аудит-лог настроек | Нет истории изменений | Low | P2 |
| 65 | Статус-строка 'N из M активных' | Нет быстрой сводки | Low | P1 |
| 66 | Inline редактирование метки | Нет редактирования после добавления | Low | P2 |
| 67 | Копирование группы | Нельзя дублировать | Medium | P3 |
| 68 | Импорт из Google Sheets | Нет внешних интеграций | High | P3 |
| 69 | Дедупликация пула сообщений | Дубликаты в txt не видны | Low | P2 |
| 70 | Preview персон. сообщения | Нельзя увидеть финальный текст | Low | P2 |
| 71 | Статистика по времени суток | Нет аналитики | Medium | P3 |
| 72 | Docker Compose | Только .bat файлы | Medium | P3 |
| 73 | Интеграционные тесты API | 0 тестов | High | P2 |
| 74 | Лимит upload 5 MB | Нет ограничения размера | Low | P1 |
| 75 | API версионирование /v1/ | Нет версий — сложно развивать | Low | P3 |
| 76 | Cooldown после бана | Продолжает пробовать | Medium | P2 |
| 77 | Авто-shuffle очерёдности | Строгий round-robin = паттерн | Low | P2 |
| 78 | Поддержка медиа в сообщениях | Только текст | High | P3 |
| 79 | Статистика по группе | Только количество профилей | Low | P2 |
| 80 | Задержка отдельно для группы | Глобальная задержка | Medium | P3 |
| 81 | Fernet key rotation | Нет смены ключа | Medium | P2 |
| 82 | Копирование лога в clipboard | Нельзя скопировать быстро | Low | P2 |
| 83 | Ограничение одновременных login | Можно запустить для всех | Low | P2 |
| 84 | last_login для профилей | Нет информации о свежести | Low | P2 |
| 85 | Мультипользовательский режим | Один пользователь без ролей | High | P3 |
| 86 | Промежуточный статус кампании | Нет понимания что происходит | Low | P1 |
| 87 | Группировка по статусу | Профили вперемешку | Low | P2 |
| 88 | Перемещение профиля | Только удалить + добавить заново | Medium | P3 |
| 89 | Sandbox режим | Нельзя тестировать без отправок | Medium | P2 |
| 90 | Отчёт действий оператора | Нет трейла | Low | P2 |
| 91 | Self-test по расписанию | Нет проверки работоспособности | Medium | P2 |
| 92 | Авто-обновление | Нет механизма обновления | High | P3 |
| 93 | Graceful 404 страница | Нет custom error pages | Low | P3 |
| 94 | Prometheus метрики | Нет внешнего мониторинга | Medium | P3 |
| 95 | Тёмная/светлая тема | Только тёмная | Low | P2 |
| 96 | Детализация ошибок | Только строка текста | Medium | P2 |
| 97 | Конфигурируемость EXE | Параметры только через UI | Low | P3 |
| 98 | Несколько кампаний одновременно | Одна кампания в момент | High | P3 |
| 99 | Статус в title вкладки | Нужно смотреть на вкладку | Low | P3 |
| 100 | Квоты на группу | Только лимит на профиль/день | Medium | P3 |

---

## ИНСТРУКЦИИ ДЛЯ АГЕНТОВ

### Как использовать этот документ

1. **Начни с Sprint 1** — все задачи там имеют приоритет P0/P1 и низкую-среднюю сложность
2. **Каждое исправление из секции "КРИТИЧЕСКИЕ ПРОБЛЕМЫ"** содержит конкретный код — используй его как основу
3. **Не трогай структуру файлов** — работай с `main.py` и `static/index.html` если не задана полная реструктуризация
4. **После каждого изменения** запускай `run.bat` и проверяй что сервер стартует без ошибок
5. **Тесты:** добавляй рядом с `_self_check_round_robin()` другие assertion-функции, вызывай их в `__main__`

### Порядок работы для агента

```
1. Прочитай AUDIT.md (этот файл)
2. Прочитай main.py полностью
3. Прочитай static/index.html полностью
4. Выбери задачу из Sprint 1
5. Применяй изменения минимальными патчами
6. Не удаляй существующую логику без явного указания
7. Сохраняй обратную совместимость API
```

### Правила изменения кода

- **main.py:** Python 3.12, использовать `asyncio`, `sqlite3`, `pathlib`. Не добавлять новые зависимости без необходимости.
- **index.html:** Vanilla JS, никаких фреймворков. Использовать существующий стиль `api()` хелпера.
- **requirements.txt:** Добавлять пакеты только если они критически необходимы.
- **Обратная совместимость:** Все существующие API endpoints должны продолжать работать.
- **БД:** Если добавляешь новую колонку — используй `ALTER TABLE ... ADD COLUMN ... DEFAULT ...` чтобы не сломать существующие данные.

---

*Документ создан автоматически. Версия: 2026-07-27.*
