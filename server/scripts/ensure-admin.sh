#!/usr/bin/env bash
# Проверка / восстановление admin-аккаунта из .env на VDS.
set -euo pipefail
cd "$(dirname "$0")/.."
# shellcheck disable=SC1091
source .env

if [[ -z "${ADMIN_EMAIL:-}" ]]; then
  echo "ADMIN_EMAIL не задан в .env"
  exit 1
fi

email_sql="${ADMIN_EMAIL//\'/\'\'}"
echo "=== users ==="
docker compose exec -T postgres psql -U maxsender -d maxsender -c \
  "SELECT id, email, role, tenant_id FROM users ORDER BY id;"

echo
echo "=== ensure admin role for ${ADMIN_EMAIL} ==="
docker compose exec -T postgres psql -U maxsender -d maxsender -c \
  "UPDATE users SET role = 'admin', tenant_id = NULL WHERE lower(email) = lower('${email_sql}');"
docker compose exec -T postgres psql -U maxsender -d maxsender -c \
  "SELECT id, email, role, tenant_id FROM users WHERE lower(email) = lower('${email_sql}');"

echo
echo "Если строки нет — перезапустите app (hooks создаст admin из ADMIN_EMAIL/ADMIN_PASSWORD)."
