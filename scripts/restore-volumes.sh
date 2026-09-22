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
RESTORE_REVISION="${MAX_RESTORE_REVISION:-restore-$(basename "$SRC")-$(date -u +%Y%m%dT%H%M%SZ)}"

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
  -e "MAX_RESTORE_REVISION=$RESTORE_REVISION" \
  -v "$(cd "$SRC" && pwd):/backup:ro" \
  --user root \
  --entrypoint python \
  app -c 'import os, pathlib, shutil, tarfile
from datetime import datetime, timezone
import json, uuid
control = pathlib.Path("/app/control")
control.mkdir(parents=True, exist_ok=True)
hold = control / "recovery-hold.json"
if hold.exists():
    raise SystemExit("recovery hold already exists; release it before another restore")
revision = os.environ.get("MAX_RESTORE_REVISION", "").strip()
if not revision or len(revision) > 200 or not revision.isprintable():
    raise SystemExit("invalid restore revision")
payload = {
    "schema_version": 1,
    "revision": revision,
    "reason": "restore",
    "created_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
}
tmp = control / (".recovery-hold." + uuid.uuid4().hex + ".tmp")
try:
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o640)
    with os.fdopen(fd, "w", encoding="utf-8") as stream:
        json.dump(payload, stream, ensure_ascii=True, separators=(",", ":"))
        stream.write("\\n")
        stream.flush()
        os.fsync(stream.fileno())
    os.chown(tmp, 10001, 10001)
    os.link(tmp, hold)
finally:
    tmp.unlink(missing_ok=True)
root = pathlib.Path("/app/data")
incoming = root / ".incoming-restore"
outgoing = root / ".outgoing-restore"
if outgoing.exists():
    raise SystemExit("leftover .outgoing-restore; inspect before retry")
if incoming.exists():
    shutil.rmtree(incoming)
incoming.mkdir()
os.chown(incoming, 10001, 10001)
with tarfile.open("/backup/data.tar.gz") as archive:
    os.setegid(10001)
    os.seteuid(10001)
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
