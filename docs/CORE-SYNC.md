# Core sync — desktop ↔ server

`desktop/main.py` и `server/main.py` — **независимые копии** общего ядра (worker, SQLite, anti-ban, MAX client). Сервер добавляет SaaS-слой в `server/app/` и выносит routes/vault/campaign-state в модули.

## Когда запускать

После любого изменения в:

- `desktop/main.py` или `server/main.py` (core-логика)
- `desktop/antiban_core.py` или `server/antiban_core.py`
- поведении campaign / pacing / vault / SQLite schema

## Checklist (mirror edit)

1. Определи зону: только desktop, только server, или **оба** (shared core).
2. Если shared — внеси **симметричное** изменение во вторую копию (с учётом server-only path helpers и `server.app.vault`).
3. Запусти sync-check:

   ```bash
   cd maxserverapp
   python scripts/check_core_sync.py
   python scripts/check_core_sync.py --strict   # CI / перед merge
   ```

4. Прогони оба smoke:

   ```bash
   cd desktop && pytest tests/ -q
   cd ../server && python -m pytest tests/ -q
   ```

5. Если менялся SaaS-only код (`server/app/*`) — достаточно server tests + `docker compose config`.

## Что считается intentional drift

| Область | desktop | server |
|---------|---------|--------|
| Vault crypto | inline в `main.py` | `server/app/vault.py` + thin wrappers |
| API routes | inline `@app.*` | `server/app/routes_*.py` |
| Campaign runtime globals | module-level vars | `campaign_runtime.RUNTIME` |
| Data paths | `_refresh_data_paths()` globals | `_data_dir()` helpers |

Скрипт `check_core_sync.py` игнорирует route handlers и server path helpers; сравнивает **тела** общих символов и **байт-в-байт** `antiban_core.py`.

## Не делать без Feature Plan + ADR

- Вынос shared code в отдельный pip-пакет
- Автоматический односторонний sync desktop → server
