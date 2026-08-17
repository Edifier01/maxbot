#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "$0")/.."

if [[ ! -f .env && -f server/.env ]]; then
  cp server/.env .env
  echo "Перенесён .env из server/.env (старый layout)"
fi

if [[ ! -f .env ]]; then
  echo "Создайте .env из .env.example:"
  echo "  cp .env.example .env && nano .env"
  cp -n .env.example .env 2>/dev/null || true
  exit 1
fi

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
  for _ in 1 2 3 4 5 6 7 8 9 10; do
    if docker compose exec -T postgres pg_isready -U maxsender -d maxsender >/dev/null 2>&1; then
      break
    fi
    sleep 2
  done
  bash scripts/backup-volumes.sh
else
  echo "No postgres volume/data — skipping volume backup (first deploy)"
fi
if [[ "${USE_CELERY:-0}" == "1" || "${USE_CELERY:-0}" == "true" ]]; then
  docker compose --profile celery pull redis caddy postgres 2>/dev/null || true
  docker compose --profile celery up --build -d
else
  docker compose pull redis caddy postgres 2>/dev/null || true
  docker compose up --build -d
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
