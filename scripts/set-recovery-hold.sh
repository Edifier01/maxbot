#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "$0")/.."
revision="${1:?usage: set-recovery-hold.sh REVISION [REASON]}"
reason="${2:-deploy}"
hold_script="$PWD/scripts/create-recovery-hold.py"

docker compose run --build --rm -T --no-deps --user root \
  -v "$hold_script:/tmp/create-recovery-hold.py:ro" \
  --entrypoint python \
  app /tmp/create-recovery-hold.py --revision "$revision" --reason "$reason"
