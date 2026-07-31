# MAX Sender — серверное развёртывание

**Самодостаточный проект**: исходники, AI-система (`.cursor/`), CI/CD (`.github/`), Docker, UI и тесты — всё в этой папке.

Откройте **эту папку** как корень workspace в Cursor. Desktop не нужен — папку можно скопировать куда угодно и работать отдельно.

## Требования

- Linux VPS (Ubuntu 22.04+) для production
- Docker и Docker Compose
- Домен, A-запись → IP сервера

## Быстрый старт

```bash
cp .env.example .env
# Отредактируйте .env: DOMAIN, LETSENCRYPT_EMAIL, JWT_SECRET, ADMIN_*, POSTGRES_PASSWORD, INTERNAL_SERVICE_TOKEN

docker compose up --build -d
```

Панель: **https://ваш-домен.ru**

Проверка: `curl -s https://ваш-домен.ru/api/health`

## Структура

```
./
  AGENTS.md            — entry point AI-системы
  .cursor/             — skills, agents, rules, commands
  .github/workflows/   — CI и Deploy (standalone)
  docker-compose.yml   — app + Redis + Caddy + PostgreSQL
  Dockerfile           — образ из текущей папки (context .)
  main.py              — FastAPI app и core-логика
  app/                 — SaaS-слой (JWT, tenant, admin, PG)
  static/              — веб-панель
  tests/               — unit/smoke + e2e
  docs/                — runbook и AI workflow
  scripts/             — deploy, backup, bootstrap
```

## AI-система

- Entry: `AGENTS.md`
- `/start-feature [задача]` — Feature Plan
- `/deploy-server [изменение]` — deploy checklist

## Безопасность

1. **Обязательно** задайте секреты в `.env` (не оставляйте `change-me*`).
2. Приложение слушает только внутри Docker-сети; наружу — Caddy на 80/443.
3. Volume `max_server_data` — сессии и ключ шифрования. Делайте бэкапы.

## Переменные окружения

| Переменная | Описание |
|------------|----------|
| `DOMAIN` | Домен (например `sender.example.com`) |
| `LETSENCRYPT_EMAIL` | Email для Let's Encrypt |
| `JWT_SECRET` | Секрет JWT (≥32 символов) |
| `ADMIN_EMAIL` / `ADMIN_PASSWORD` | Первый админ |
| `POSTGRES_PASSWORD` | Пароль PostgreSQL |
| `INTERNAL_SERVICE_TOKEN` | Service-to-service auth |
| `WORKER_POOL_SIZE` | Число воркеров отправки (default 4) |
| `USE_CELERY` | `1` — Celery (`--profile celery`) |

## Опции

Runbook: [`docs/PRODUCTION-OPS.md`](docs/PRODUCTION-OPS.md)

```bash
bash scripts/deploy.sh
bash scripts/verify_deploy.sh
bash scripts/backup-volumes.sh
USE_CELERY=1 docker compose --profile celery up --build -d
docker compose logs -f app
```

## Локальная разработка

```bash
pip install -r requirements.txt -r requirements-server.txt
pip install pytest httpx
MAX_TEST=1 MAX_SERVER_MODE=1 python -m pytest tests/ -q
```

## Автодеплой с GitHub

Репозиторий = **корень этой папки** (не monorepo с desktop).

### 1. Подготовка VPS

```bash
sudo bash scripts/bootstrap-vps.sh /opt/maxsender git@github.com:YOU/maxsender-server.git
```

1. Deploy key → GitHub repo Settings → Deploy keys
2. Заполните `.env`, первый деплой:

```bash
cd /opt/maxsender
nano .env
bash scripts/deploy.sh
```

### 2. Secrets в GitHub

| Secret | Пример | Описание |
|--------|--------|----------|
| `DEPLOY_HOST` | `203.0.113.10` | IP или домен VPS |
| `DEPLOY_USER` | `ubuntu` | SSH-пользователь |
| `DEPLOY_PATH` | `/opt/maxsender` | Корень git-клона (**без** `/server`) |
| `DEPLOY_SSH_KEY` | приватный ключ | SSH для Actions → VPS |

Workflow: `.github/workflows/deploy.yml`

## Перенос в другое место

```bash
cp -a server/ /path/to/maxsender-server/
cd /path/to/maxsender-server
# Откройте эту папку в Cursor — AGENTS.md и .cursor/ уже внутри
```
