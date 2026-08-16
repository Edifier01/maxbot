---
name: maxserver-testing
description: MAX Sender pytest, UI smoke, compose-config, and verifier evidence. Use before claiming a task done or when adding tests.
---

# MAX Sender Testing

Compose: `python-testing` for pytest style. **Ignore** its 80% coverage dogma — this repo uses targeted smoke + one test per non-trivial behavior (ponytail).

## Commands (workspace = this server tree)

```powershell
$env:MAX_TEST='1'; $env:MAX_SERVER_MODE='1'; python -m pytest tests/ -q
$env:MAX_TEST='1'; $env:MAX_SERVER_MODE='1'; python -m pytest tests/test_e2e_server.py -q
docker compose config -q
```

Deploy: `bash scripts/verify_deploy.sh`

UI string/DOM contracts: `tests/test_saas_ux_static.py` when `static/*.html` changes.

## Verifier evidence (required to say “done”)

- Command run + pass/fail counts (or why not run)
- Desktop/server independence if both exist
- Residual risks (skipped tests, untested UI, secrets, pacing)

## Do not

- Skip isolation/vault tests to go green
- Weaken `skipif` so CI hides Postgres-dependent modules
- Claim deploy-ready without compose-config / health when infra changed
