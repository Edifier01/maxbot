# MAX Sender — серверное развёртывание

Отдельный стек для VPS с доменом и HTTPS. Локальная версия (`run.bat`, `dist/MAX-Sender.exe`) не затрагивается.

Серверная бизнес-логика — в `server/app/` (пока заглушки, делегируют в корневой `main.py`).

## Требования

- Linux VPS (Ubuntu 22.04+)
- Docker и Docker Compose
- Домен, A-запись → IP сервера

## Быстрый старт

```bash
cd server
cp .env.example .env
# Отредактируйте .env: DOMAIN, LETSENCRYPT_EMAIL

docker compose up --build -d
```

Панель: **https://ваш-домен.ru**

Проверка: `curl -s https://ваш-домен.ru/api/health`

## Структура

```
server/
  docker-compose.yml   — app + Redis + Caddy (HTTPS)
  Dockerfile           — образ из корня проекта
  .env.example         — переменные окружения
  caddy/Caddyfile      — reverse proxy + Let's Encrypt
  app/                 — серверная логика (TODO)
    main.py            — точка входа
    hooks.py           — расширения перед/после старта
  scripts/deploy.sh    — деплой одной командой
  skills-curated/      — отобранные AI-скиллы (26 шт.)
  SKILLS.md            — каталог скиллов по категориям
  AGENTS.md            — инструкции для AI-агента
```

## Безопасность

1. **Обязательно** задайте API PIN в настройках панели (или через переменную при первом запуске).
2. Приложение слушает только внутри Docker-сети; наружу — только Caddy на 80/443.
3. Папка `data/` (volume `max_server_data`) — сессии и ключ шифрования. Делайте бэкапы.

## Переменные окружения

| Переменная | Описание |
|------------|----------|
| `DOMAIN` | Домен (например `sender.example.com`) |
| `LETSENCRYPT_EMAIL` | Email для сертификата Let's Encrypt |
| `WORKER_POOL_SIZE` | Число воркеров отправки (по умолчанию 4) |
| `USE_CELERY` | `1` — включить Celery (`--profile celery`) |

## Опции

```bash
# Celery-воркеры
USE_CELERY=1 docker compose --profile celery up --build -d

# Отладка без HTTPS (временно пробросить порт)
docker compose run --rm --service-ports app

# Логи
docker compose logs -f app
```

## Миграция данных с локального ПК

```bash
# На Windows: скопируйте папку data/ на сервер
scp -r data/ user@server:/opt/max-app/server/

# На сервере — в volume (если уже запускали compose):
docker compose run --rm app sh -c 'cp -a /backup/data/. /app/data/'
# или смонтируйте ./data в compose перед первым запуском
```

## Когда будет готова серверная логика

1. Реализуйте хуки в `server/app/hooks.py`
2. Перенесите отличия в `server/app/main.py`
3. В `Dockerfile` смените CMD на `python -m server.app.main`

## AI-скиллы

В `server/skills/` — ~1900 community-скиллов. Для работы используйте **только curated-набор**:

- `server/SKILLS.md` — таблица по категориям
- `server/skills-curated/manifest.json` — машиночитаемый список
- `server/AGENTS.md` — контекст для агента

Правило Cursor: `.cursor/rules/server-workspace.mdc` (автоматически при работе в `server/`).
