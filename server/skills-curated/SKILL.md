---
name: max-sender-server
description: >-
  Curated skills for MAX Sender server deployment (Docker, Caddy, domain, HTTPS),
  FastAPI backend, security, monitoring, and admin UI. Read manifest.json and
  open the matching skill from server/skills/ before working in server/.
---

# MAX Sender — Server Skills Router

Перед задачами в `server/` **не перебирайте** всю папку `server/skills/` (~1900 скиллов).
Используйте только curated-набор из `server/skills-curated/manifest.json`.

## Быстрый выбор

| Задача | Скилл |
|--------|-------|
| Docker / compose / Dockerfile | `docker-expert` |
| VPS, SSH, деплой на сервер | `vps-server-management` + `devops-deploy` |
| Домен, HTTPS, Caddy | `docker-expert` (reverse proxy в compose) |
| API PIN, секреты, .env | `secrets-management` + `security-and-hardening` |
| Hardening контейнера | `container-security-hardening` |
| Новая серверная логика FastAPI | `python-fastapi-development` + `fastapi-pro` |
| Воркеры / asyncio | `async-python-patterns` |
| Redis / Celery | `redis-cli` |
| Prometheus `/metrics` | `prometheus-configuration` |
| UI панели `static/index.html` | `ui-ux-pro-max` + `web-design-guidelines` |
| E2E тесты панели | `webapp-testing` |

## Workflow

1. Прочитай `server/AGENTS.md` — контекст проекта.
2. Открой `server/skills-curated/manifest.json` — найди категорию.
3. Прочитай полный `SKILL.md` по полю `path` **до** изменений кода.
4. Серверная логика — только в `server/app/`; инфра — `server/docker-compose.yml`, `server/caddy/`.

## Ограничения проекта

- Публичный деплой **обязан** иметь API PIN.
- `data/` — зашифрованные сессии; не коммитить `.app_key`.
- Локальная версия (`main.py`, `run.bat`) и серверная (`server/app/`) разведены намеренно.
