# MAX Sender — серверное развёртывание

Отдельный стек для VPS с доменом и HTTPS. Папка самодостаточна: исходники, зависимости, UI и Docker-конфигурация лежат внутри `server/`.

Серверные расширения — в `server/app/`, общее ядро запуска — `main.py` в этой же папке.

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
  Dockerfile           — образ из текущей папки server/
  .env.example         — переменные окружения
  main.py              — FastAPI app и core-логика
  static/              — веб-панель
  caddy/Caddyfile      — reverse proxy + Let's Encrypt
  app/                 — серверная логика (TODO)
    main.py            — точка входа
    hooks.py           — расширения перед/после старта
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

## Разработка отдельно от desktop

Вносите серверные изменения внутри `server/`. Desktop-версия находится в соседней папке `desktop/` и не нужна для сборки Docker-образа.

## Автодеплой с GitHub

При push в `main` сначала проходит CI (`.github/workflows/ci.yml`), затем workflow **Deploy** по SSH обновляет код на VPS и пересобирает контейнеры.

### 1. Подготовка VPS (один раз)

```bash
# На сервере (Ubuntu 22.04+)
sudo bash scripts/bootstrap-vps.sh /opt/maxsender git@github.com:Edifier01/maxbot.git
```

Скрипт установит Docker, клонирует репо, создаст deploy key для `git pull` и черновик `.env`.

1. Добавьте **Deploy key** (публичный ключ из вывода) в GitHub:  
   `https://github.com/Edifier01/maxbot/settings/keys` → Add deploy key (read-only).
2. Заполните `server/.env` и выполните первый деплой:

```bash
cd /opt/maxsender/server
nano .env
bash scripts/deploy.sh
```

### 2. SSH-ключ для GitHub Actions → сервер

На **локальной машине** (не на сервере):

```bash
ssh-keygen -t ed25519 -f maxsender-gha -N "" -C "github-actions-deploy"
```

- Публичный ключ `maxsender-gha.pub` → на сервер в `~/.ssh/authorized_keys` пользователя деплоя.
- Приватный ключ `maxsender-gha` → в GitHub Secrets (см. ниже). **Не коммитить.**

### 3. Secrets в GitHub

Репозиторий → **Settings → Secrets and variables → Actions → New repository secret**:

| Secret | Пример | Описание |
|--------|--------|----------|
| `DEPLOY_HOST` | `203.0.113.10` | IP или домен VPS |
| `DEPLOY_USER` | `ubuntu` | SSH-пользователь |
| `DEPLOY_PATH` | `/opt/maxsender` | Корень git-клона (где лежит `server/`) |
| `DEPLOY_SSH_KEY` | содержимое `maxsender-gha` | Приватный ключ для SSH на сервер |
| `DEPLOY_PORT` | `22` | *(опционально)* нестандартный SSH-порт |

### 4. Проверка

```bash
# Ручной запуск деплоя без push
# GitHub → Actions → Deploy → Run workflow

# После успеха
curl -s https://ваш-домен.ru/api/health
```

Workflow: `.github/workflows/deploy.yml` — `git reset --hard origin/main`, `docker compose up --build -d`, health check с `db_ok`.
