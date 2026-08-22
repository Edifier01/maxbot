#!/usr/bin/env bash
# Restore PostgreSQL + max_server_data from backup-volumes.sh output.
# Usage: bash scripts/restore-volumes.sh [--yes] ./backups/20260101-120000
set -euo pipefail

cd "$(dirname "$0")/.."

ASSUME_YES=0
if [[ "${1:-}" == "--yes" || "${1:-}" == "-y" ]]; then
  ASSUME_YES=1
  shift
fi
SRC="${1:?укажите каталог бэкапа (pg.dump + data.tar.gz)}"
[[ -f "$SRC/pg.dump" ]] || { echo "нет $SRC/pg.dump"; exit 1; }
[[ -f "$SRC/data.tar.gz" ]] || { echo "нет $SRC/data.tar.gz"; exit 1; }

echo "ВНИМАНИЕ: перезапишет PG и volume max_server_data."
if [[ "$ASSUME_YES" != "1" ]]; then
  read -r -p "Продолжить? [y/N] " ans
  [[ "$ans" == "y" || "$ans" == "Y" ]] || exit 0
fi

echo "Остановка app и celery…"
docker compose stop app celery-worker 2>/dev/null || docker compose stop app

echo "Восстановление data volume…"
# python:3.12-slim has tar/python, not findutils. Extract to .incoming-restore,
# verify, then swap live children into .outgoing-restore (same volume, rename).
# Do not rmtree .outgoing-restore until PostgreSQL restore succeeds (rollback on PG fail).
docker compose run --rm -T --no-deps \
  -v "$(cd "$SRC" && pwd):/backup:ro" \
  --entrypoint python \
  app -c 'import pathlib, shutil, tarfile
root = pathlib.Path("/app/data")
incoming = root / ".incoming-restore"
outgoing = root / ".outgoing-restore"
if outgoing.exists():
    raise SystemExit("leftover .outgoing-restore; inspect before retry")
if incoming.exists():
    shutil.rmtree(incoming)
incoming.mkdir()
with tarfile.open("/backup/data.tar.gz") as archive:
    archive.extractall(incoming, filter="data")
if not any(incoming.iterdir()):
    shutil.rmtree(incoming)
    raise SystemExit("empty extract")
outgoing.mkdir()
for child in list(root.iterdir()):
    if child.name in (".incoming-restore", ".outgoing-restore"):
        continue
    child.rename(outgoing / child.name)
for child in list(incoming.iterdir()):
    child.rename(root / child.name)
incoming.rmdir()'

echo "Восстановление PostgreSQL…"
if docker compose exec -T postgres pg_restore -U maxsender -d maxsender --clean --if-exists --no-owner \
  --exit-on-error --single-transaction \
  < "$SRC/pg.dump"; then
  echo "pg_restore OK — removing .outgoing-restore"
  docker compose run --rm -T --no-deps --entrypoint python app -c 'import pathlib, shutil
outgoing = pathlib.Path("/app/data/.outgoing-restore")
if outgoing.exists():
    shutil.rmtree(outgoing)'
else
  echo "pg_restore failed — rolling data volume back from .outgoing-restore" >&2
  docker compose run --rm -T --no-deps --entrypoint python app -c 'import pathlib, shutil
root = pathlib.Path("/app/data")
incoming = root / ".incoming-restore"
outgoing = root / ".outgoing-restore"
if not outgoing.exists():
    raise SystemExit("pg_restore failed and .outgoing-restore missing; cannot rollback data")
if incoming.exists():
    shutil.rmtree(incoming)
incoming.mkdir()
for child in list(root.iterdir()):
    if child.name in (".incoming-restore", ".outgoing-restore"):
        continue
    child.rename(incoming / child.name)
for child in list(outgoing.iterdir()):
    child.rename(root / child.name)
for child in list(incoming.iterdir()):
    child.rename(outgoing / child.name)
incoming.rmdir()'
  echo "Data volume rolled back. Inspect leftover .outgoing-restore before retry." >&2
  exit 1
fi

echo "Запуск стека…"
docker compose up -d
bash scripts/verify_deploy.sh

echo "Restore complete."
