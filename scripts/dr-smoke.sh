#!/usr/bin/env bash
# CI-only: prove the existing backup/restore scripts recover both stores.
set -euo pipefail

cd "$(dirname "$0")/.."

trap 'docker compose down -v --remove-orphans || true' EXIT
docker compose up -d postgres redis app
for _ in {1..30}; do
  if docker compose exec -T postgres pg_isready -U maxsender -d maxsender >/dev/null; then
    break
  fi
  sleep 2
done
docker compose exec -T postgres psql -U maxsender -d maxsender -c \
  "CREATE TABLE dr_smoke (value text); INSERT INTO dr_smoke VALUES ('before');"
docker compose exec -T app sh -c "mkdir -p /app/data/dr-smoke && printf before > /app/data/dr-smoke/value"

backup_dir="${RUNNER_TEMP:-/tmp}/maxsender-dr-backup"
bash scripts/backup-volumes.sh "$backup_dir"

docker compose exec -T postgres psql -U maxsender -d maxsender -c "UPDATE dr_smoke SET value='after';"
docker compose run --rm -T --no-deps --entrypoint sh app -c "printf after > /app/data/dr-smoke/value"
bash scripts/restore-volumes.sh --yes "$backup_dir"

test "$(docker compose exec -T postgres psql -U maxsender -d maxsender -At -c 'SELECT value FROM dr_smoke')" = before
test "$(docker compose exec -T app cat /app/data/dr-smoke/value)" = before
