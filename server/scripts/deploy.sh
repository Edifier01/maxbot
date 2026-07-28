#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "$0")/.."

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

if ((${#missing[@]})); then
  echo "Заполните в .env (не оставляйте значения-заглушки): ${missing[*]}"
  exit 1
fi

echo "Deploy MAX Sender → https://${DOMAIN}"
docker compose pull redis caddy postgres 2>/dev/null || true
docker compose up --build -d

echo "Ожидание старта контейнеров…"
sleep 8

echo "Health (внутри контейнера app):"
if docker compose exec -T app python -c "
import urllib.request, json, sys
try:
    r = urllib.request.urlopen('http://127.0.0.1:8765/api/health', timeout=5)
    d = json.loads(r.read())
    print(json.dumps(d, ensure_ascii=False, indent=2))
    sys.exit(0 if d.get('db_ok') else 1)
except Exception as e:
    print('FAIL:', e)
    sys.exit(1)
"; then
  echo "OK"
else
  echo "Health check failed. Логи: docker compose logs --tail=80 app"
  exit 1
fi

echo
echo "Панель:  https://${DOMAIN}/auth.html"
echo "Админ:   https://${DOMAIN}/admin.html  (логин: ${ADMIN_EMAIL})"
echo "Логи:    docker compose logs -f app"
