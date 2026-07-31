# MAX Sender — AI System

Единая AI-система для `desktop/` и `server/`. Конфигурация в `.cursor/`.

**Серверная версия — самодостаточный проект** в `server/`: собственные `AGENTS.md`, `.cursor/`, `.github/`. Откройте `server/` как корень workspace или скопируйте папку отдельно — desktop не нужен.
## Быстрый старт

1. `/start-feature [задача]` — Feature Plan перед нетривиальной работой.
2. `/deploy-server [изменение]` — Docker/VPS/deploy по checklist.
3. Классифицировать: `desktop` | `server` | `both`.
4. Загрузить skills по зоне (см. таблицу ниже).
5. Назначить agents → реализация → verifier.

## Skills

| Skill | Когда |
|-------|-------|
| `context-loading` | Старт, resume, выбор зоны |
| `start-feature` | Feature Plan |
| `subagent-orchestrator` | Multi-domain, routing |
| `maxserver-server-deploy` | Docker, VPS, Caddy, deploy, CI/CD |
| `maxserver-fastapi-backend` | API, hooks, `server/app/` |
| `maxserver-postgresql` | Schema, `db_pg.py`, migrations |
| `maxserver-auth-security` | JWT, tenant, secrets |
| `maxserver-static-ui` | Vanilla HTML/CSS/JS UI, auth/admin panel |
| `maxserver-campaign` | Anti-ban pacing, warmup, retry, pause/resume |
| `maxserver-testing` | pytest, UI smoke, deploy verification, verifier gate |

Путь: `.cursor/skills/<name>/SKILL.md`

## Agents

| Agent | Файл |
|-------|------|
| Orchestrator | `.cursor/agents/project-orchestrator.md` |
| Verifier | `.cursor/agents/verifier.md` |
| Backend | `.cursor/agents/backend-engineer.md` |
| Frontend | `.cursor/agents/frontend-engineer.md` |
| Database | `.cursor/agents/database-engineer.md` |
| DevOps | `.cursor/agents/devops-engineer.md` |
| Security | `.cursor/agents/security-engineer.md` |
| QA | `.cursor/agents/qa-engineer.md` |
| Campaign | `.cursor/agents/campaign-specialist.md` |

## External Skills Library

Большая библиотека находится в `skills/` и не должна загружаться целиком. Project skills выше уже вобрали нужное из релевантных source skills: `fastapi-pro`, `docker-expert`, `postgresql`, `auth-implementation-patterns`, `async-python-patterns`, `webapp-testing`, `frontend-api-integration-patterns`, `verification-before-completion` и др.

## Rules

- `max-sender-workspace.mdc` — общие правила (always)
- `ai-skills-system.mdc` — маршрутизация skills/agents (always)
- `server-workspace.mdc` — `server/**`
- `desktop-workspace.mdc` — `desktop/**`

## Документация

- `docs/MASTER-AI-WORKFLOW.md` — архитектура и model routing
- `.cursor/workflows/feature-lifecycle.md` — жизненный цикл задачи
- `.cursor/skills/README.md` — индекс + маппинг на внешнюю библиотеку skills
