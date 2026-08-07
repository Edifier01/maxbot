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

if ((${#missing[@]})); then
  echo "Заполните в .env (не оставляйте значения-заглушки): ${missing[*]}"
  exit 1
fi

echo "Деплой MAX Sender → https://${DOMAIN}"
docker compose pull redis caddy postgres 2>/dev/null || true
docker compose up --build -d

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
