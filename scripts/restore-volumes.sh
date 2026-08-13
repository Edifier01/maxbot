#!/usr/bin/env bash
# Restore PostgreSQL + max_server_data from backup-volumes.sh output.
# Usage: bash scripts/restore-volumes.sh ./backups/20260101-120000
set -euo pipefail

cd "$(dirname "$0")/.."

SRC="${1:?укажите каталог бэкапа (pg.dump + data.tar.gz)}"
[[ -f "$SRC/pg.dump" ]] || { echo "нет $SRC/pg.dump"; exit 1; }
[[ -f "$SRC/data.tar.gz" ]] || { echo "нет $SRC/data.tar.gz"; exit 1; }

echo "ВНИМАНИЕ: перезапишет PG и volume max_server_data."
read -r -p "Продолжить? [y/N] " ans
[[ "$ans" == "y" || "$ans" == "Y" ]] || exit 0

echo "Остановка app и celery…"
docker compose stop app celery-worker 2>/dev/null || docker compose stop app

echo "Восстановление PostgreSQL…"
docker compose exec -T postgres pg_restore -U maxsender -d maxsender --clean --if-exists --no-owner \
  < "$SRC/pg.dump"

echo "Восстановление data volume…"
docker compose run --rm --no-deps \
  -v max_server_data:/data \
  -v "$(cd "$SRC" && pwd):/backup:ro" \
  alpine sh -c 'find /data -mindepth 1 -delete && tar xzf /backup/data.tar.gz -C /data'

echo "Запуск стека…"
docker compose up -d
bash scripts/verify_deploy.sh

echo "Restore complete."
