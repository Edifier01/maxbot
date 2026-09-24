#!/usr/bin/env bash
# Explicit administrator password recovery; run on the configured VPS only.
set -euo pipefail
umask 077

cd "$(dirname "$0")/.."
if [[ ! -f .env ]]; then
  echo "Создайте .env в корне deployment checkout" >&2
  exit 1
fi
# shellcheck disable=SC1091
source .env

if [[ -z "${ADMIN_EMAIL:-}" ]]; then
  echo "ADMIN_EMAIL не задан в .env" >&2
  exit 1
fi

read -r -p "Authorization reference (non-secret): " authorization_reference
if [[ -z "$authorization_reference" ]]; then
  echo "Authorization reference обязателен" >&2
  exit 1
fi
read -r -s -p "New administrator password: " new_password
printf '\n'
read -r -s -p "Repeat administrator password: " repeated_password
printf '\n'
if [[ "$new_password" != "$repeated_password" ]]; then
  unset new_password repeated_password
  echo "Пароли не совпадают" >&2
  exit 1
fi

printf '%s\n' "$new_password" | docker compose run --rm -T --no-deps --user root \
  app python -m app.admin_recovery \
  --email "$ADMIN_EMAIL" \
  --authorization-reference "$authorization_reference" \
  --password-stdin
unset new_password repeated_password authorization_reference
