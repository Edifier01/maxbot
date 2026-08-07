# Current Context

## Product
MAX Sender is a Python/FastAPI app for controlled MAX messenger text sending with pacing, vault-protected sessions, a static UI panel, and an API.

## Repository Shape
- `desktop/`: local Windows/PyInstaller version.
- `server/`: VPS/Docker version with server-mode extensions.
- `.cursor/`: shared AI system for both versions.

## Current State
The project was split into two independent folders. Future agents must preserve that split and avoid rebuilding the old monolith.

## AI System
Skills and agent routing integrated — see `AGENTS.md` and `.cursor/rules/ai-skills-system.mdc`.

Active project skills:
- orchestration: `context-loading`, `start-feature`, `subagent-orchestrator`
- server: `maxserver-server-deploy`, `maxserver-fastapi-backend`, `maxserver-postgresql`, `maxserver-auth-security`
- app/domain: `maxserver-static-ui`, `maxserver-campaign`, `maxserver-testing`

`skills/` is a large vendored source library; do not load it wholesale.
