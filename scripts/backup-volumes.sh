#!/usr/bin/env bash
# Backup PostgreSQL + max_server_data volume before deploy or on schedule.
# Usage: bash scripts/backup-volumes.sh [output-dir]
set -euo pipefail

cd "$(dirname "$0")/.."

STAMP=$(date +%Y%m%d-%H%M%S)
DEST="${1:-./backups/$STAMP}"
mkdir -p "$DEST"

echo "Backup → $DEST"

echo "  PostgreSQL dump…"
docker compose exec -T postgres pg_dump -U maxsender -Fc maxsender > "$DEST/pg.dump"

echo "  max_server_data volume…"
docker compose run --rm --no-deps \
  -v max_server_data:/data:ro \
  -v "$DEST:/backup" \
  alpine sh -c 'tar czf /backup/data.tar.gz -C /data .'

cat > "$DEST/README.txt" <<EOF
MAX Sender backup $STAMP
Restore: bash scripts/restore-volumes.sh $DEST
EOF

echo "Done: $DEST (pg.dump + data.tar.gz)"
