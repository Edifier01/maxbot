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

echo "Восстановление data volume…"
# python:3.12-slim has tar/python, not findutils. Extract to .incoming-restore,
# verify, then swap live children into .outgoing-restore (same volume, rename).
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
incoming.rmdir()
shutil.rmtree(outgoing)'

echo "Восстановление PostgreSQL…"
# Data volume is already swapped. If pg_restore fails, data is new and PG may be old.
docker compose exec -T postgres pg_restore -U maxsender -d maxsender --clean --if-exists --no-owner \
  < "$SRC/pg.dump"

echo "Запуск стека…"
docker compose up -d
bash scripts/verify_deploy.sh

echo "Restore complete."
