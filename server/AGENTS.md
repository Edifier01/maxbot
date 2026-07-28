# MAX Sender — Server Agent Guide

Контекст для AI-агента при работе с **серверной** частью проекта.

## Стек

| Слой | Технология |
|------|------------|
| Backend | Python 3.12, FastAPI, uvicorn, PyMax |
| UI | `static/index.html` — один файл, vanilla CSS |
| Данные | SQLite (`data/`), volume в Docker |
| Очереди | Redis (+ опционально Celery) |
| Proxy | Caddy (HTTPS, Let's Encrypt) |
| Метрики | `GET /metrics` (Prometheus) |

## Структура

```
server/
  app/              — серверная логика (hooks.py, main.py)
  caddy/            — reverse proxy
  docker-compose.yml
  Dockerfile
  skills-curated/   — ⭐ используй только этот набор скиллов
  skills/           — полная библиотека (~1900), не сканировать целиком
```

## Skills — обязательно

1. Прочитай `server/skills-curated/SKILL.md`
2. Выбери скиллы из `server/skills-curated/manifest.json`
3. Открой полный файл скилла (`server/skills/<name>/SKILL.md`) перед работой

### По типу задачи

- **Deploy / Docker / domain** → `docker-expert`, `devops-deploy`, `vps-server-management`
- **Security / PIN / secrets** → `security-and-hardening`, `secrets-management`, `container-security-hardening`
- **API / server logic** → `python-fastapi-development`, `fastapi-pro`, `async-python-patterns`
- **UI / dashboard** → `ui-ux-pro-max`, `web-design-guidelines`, `ui-a11y`
- **Monitoring** → `prometheus-configuration`
- **Tests** → `webapp-testing`

## Правила изменений

1. Серверные отличия от локальной версии — в `server/app/`, не ломая `run.bat` / exe.
2. Инфраструктура — `server/docker-compose.yml`, `.env`, `caddy/Caddyfile`.
3. UI общий с локальной версией: `static/index.html` (при необходимости — отдельные server-стили позже).
4. Не публиковать порт 8765 без Caddy/PIN.
5. Не коммитить `server/.env`, `data/.app_key`.

## Деплой (кратко)

```bash
cd server
cp .env.example .env   # DOMAIN, LETSENCRYPT_EMAIL
docker compose up --build -d
```

Проверка: `curl -fsS https://$DOMAIN/api/health`

## Что ещё не реализовано

- Отдельная серверная бизнес-логика (заглушки в `server/app/hooks.py`)
- CI/CD pipeline (скилл `deployment-pipeline-design` — когда понадобится)
