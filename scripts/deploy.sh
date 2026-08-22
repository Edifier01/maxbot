#!/usr/bin/env bash
set -euo pipefail
umask 077

cd "$(dirname "$0")/.."

if [[ ! -f .env && -f server/.env ]]; then
  install -m 600 server/.env .env
  echo "Перенесён .env из server/.env (старый layout)"
fi

if [[ ! -f .env ]]; then
  echo "Создайте .env из .env.example:"
  echo "  cp .env.example .env && nano .env"
  install -m 600 .env.example .env 2>/dev/null || true
  exit 1
fi

chmod 600 .env

# shellcheck disable=SC1091
source .env

missing=()
[[ -z "${DOMAIN:-}" ]] && missing+=("DOMAIN")
[[ -z "${LETSENCRYPT_EMAIL:-}" ]] && missing+=("LETSENCRYPT_EMAIL")
[[ -z "${JWT_SECRET:-}" || "${JWT_SECRET}" == change-me* ]] && missing+=("JWT_SECRET")
[[ -z "${ADMIN_EMAIL:-}" ]] && missing+=("ADMIN_EMAIL")
[[ -z "${ADMIN_PASSWORD:-}" || "${ADMIN_PASSWORD}" == change-me* ]] && missing+=("ADMIN_PASSWORD")
[[ -z "${POSTGRES_PASSWORD:-}" || "${POSTGRES_PASSWORD}" == change-me* ]] && missing+=("POSTGRES_PASSWORD")
[[ -z "${INTERNAL_SERVICE_TOKEN:-}" || "${INTERNAL_SERVICE_TOKEN}" == change-me* ]] && missing+=("INTERNAL_SERVICE_TOKEN")
[[ -z "${REDIS_PASSWORD:-}" || "${REDIS_PASSWORD}" == change-me* ]] && missing+=("REDIS_PASSWORD")

if ((${#missing[@]})); then
  echo "Заполните в .env (не оставляйте значения-заглушки): ${missing[*]}"
  exit 1
fi

echo "Деплой MAX Sender → https://${DOMAIN}"
pg_vol=$(docker volume ls -q | grep -E '(^|_)max_server_pg$' || true)
pg_ctr=$(docker compose ps -a -q postgres 2>/dev/null || true)
if [[ -n "$pg_vol" || -n "$pg_ctr" ]]; then
  echo "PostgreSQL volume/data present — starting postgres, then backing up volumes…"
  docker compose up -d postgres
  postgres_ready=0
  for _ in 1 2 3 4 5 6 7 8 9 10; do
    if docker compose exec -T postgres pg_isready -U maxsender -d maxsender >/dev/null 2>&1; then
      postgres_ready=1
      break
    fi
    sleep 2
  done
  if [[ "$postgres_ready" != "1" ]]; then
    echo "PostgreSQL не готов после 20 секунд; backup и deploy остановлены." >&2
    docker compose logs --tail=80 postgres >&2 || true
    exit 1
  fi
  bash scripts/backup-volumes.sh
else
  echo "No postgres volume/data — skipping volume backup (first deploy)"
fi
if [[ "${USE_CELERY:-0}" == "1" || "${USE_CELERY:-0}" == "true" ]]; then
  docker compose --profile celery pull redis caddy postgres 2>/dev/null || true
  docker compose --profile celery build app celery-worker
  docker compose --profile celery run --rm -T --no-deps --user root \
    --entrypoint chown app -R 10001:10001 /app/data
  docker compose --profile celery up -d
else
  docker compose pull redis caddy postgres 2>/dev/null || true
  docker compose build app
  docker compose run --rm -T --no-deps --user root \
    --entrypoint chown app -R 10001:10001 /app/data
  docker compose up -d
fi

echo "Ожидание старта контейнеров…"
sleep 8

CHECK_HTTPS=0 bash scripts/verify_deploy.sh || {
  echo "Проверка не прошла. Логи: docker compose logs --tail=80 app"
  exit 1
}

echo
echo "Панель:  https://${DOMAIN}/auth.html"
echo "Админ:   https://${DOMAIN}/admin.html  (логин: ${ADMIN_EMAIL})"
echo "Полная проверка (HTTPS): bash scripts/verify_deploy.sh"
echo "Логи:    docker compose logs -f app"
