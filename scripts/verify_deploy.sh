#!/usr/bin/env bash
# Post-deploy verification — run on VPS after deploy.sh or from CI smoke on staging.
set -euo pipefail

cd "$(dirname "$0")/.."

if [[ -f .env ]]; then
  # shellcheck disable=SC1091
  source .env
fi

DOMAIN="${DOMAIN:-}"
USE_CELERY="${USE_CELERY:-0}"
CHECK_HTTPS="${CHECK_HTTPS:-1}"
REQUIRE_MAX_ACTIONS="${REQUIRE_MAX_ACTIONS:-0}"

echo "=== docker compose config ==="
docker compose config -q

echo "=== services ==="
docker compose ps

echo "=== health (app container) ==="
health_json=""
health_ok=0
for i in $(seq 1 30); do
  if health_json=$(docker compose exec -T app python -c "
import json, sys, urllib.request
r = urllib.request.urlopen('http://127.0.0.1:8765/api/health', timeout=10)
d = json.loads(r.read())
print(json.dumps(d, ensure_ascii=False))
sys.exit(0 if d.get('db_ok') is True else 1)
" 2>/dev/null); then
    health_ok=1
    break
  fi
  sleep 3
done
if [[ "$health_ok" != "1" ]]; then
  echo "FAIL: readiness check did not succeed"
  docker compose logs --tail=80 app
  exit 1
fi
echo "$health_json"

if [[ "$REQUIRE_MAX_ACTIONS" == "1" || "$REQUIRE_MAX_ACTIONS" == "true" ]]; then
  if ! python3 -c '
import json, sys
data = json.load(sys.stdin)
ok = data.get("max_external_actions") == "authorized" and data.get("recovery_hold") is False
sys.exit(0 if ok else 1)
' <<<"$health_json"; then
    echo "FAIL: MAX external actions remain held" >&2
    exit 1
  fi
fi

if [[ "$CHECK_HTTPS" == "1" && -n "$DOMAIN" && "$DOMAIN" != *example.com* ]]; then
  echo "=== health (HTTPS via Caddy) ==="
  curl -sf "https://${DOMAIN}/api/health" | python3 -m json.tool
fi

if [[ "$USE_CELERY" == "1" || "$USE_CELERY" == "true" ]]; then
  echo "=== celery worker ==="
  if ! docker compose ps celery-worker --status running -q | grep -q .; then
    echo "FAIL: celery-worker not running (USE_CELERY=1)"
    exit 1
  fi
  docker compose exec -T celery-worker celery -A celery_worker.app inspect ping -d celery@$(hostname) 2>/dev/null \
    || docker compose exec -T celery-worker celery -A celery_worker.app inspect ping
fi

echo "=== verify OK ==="
