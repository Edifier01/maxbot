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
# App image has tar; compose has no alpine service. -T keeps the archive binary-clean.
docker compose run --rm -T --no-deps --entrypoint tar \
  app czf - -C /app/data . > "$DEST/data.tar.gz"

cat > "$DEST/README.txt" <<EOF
MAX Sender backup $STAMP
Restore: bash scripts/restore-volumes.sh $DEST
EOF

echo "  Verifying archives…"
if [[ ! -s "$DEST/pg.dump" ]]; then
  echo "ERROR: pg.dump is empty or missing" >&2
  exit 1
fi
# Cheap format check: pg_dump -Fc magic is PGDMP (avoids docker pg_restore -l).
if [[ "$(head -c 5 "$DEST/pg.dump")" != "PGDMP" ]]; then
  echo "ERROR: pg.dump is not a PostgreSQL custom-format dump" >&2
  exit 1
fi
if ! gzip -t "$DEST/data.tar.gz"; then
  echo "ERROR: data.tar.gz failed gzip integrity check" >&2
  exit 1
fi
listing=$(tar -tzf "$DEST/data.tar.gz") || {
  echo "ERROR: data.tar.gz is not a readable tar" >&2
  exit 1
}
if [[ -z "$listing" ]]; then
  echo "ERROR: data.tar.gz has no tar members (empty archive)" >&2
  exit 1
fi

echo "Done: $DEST (pg.dump + data.tar.gz)"
