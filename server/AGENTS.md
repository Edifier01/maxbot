# MAX Sender Server — AI System

Самодостаточный серверный проект: FastAPI, Docker, PostgreSQL, Caddy. Конфигурация AI — в `.cursor/` этой же папки.

Откройте **эту папку** как корень workspace в Cursor — desktop не нужен.

## Быстрый старт

1. `/start-feature [задача]` — Feature Plan → **ждать `proceed`** → реализация
2. `/deploy-server [изменение]` — deploy checklist
3. Загрузить skills по домену (см. таблицу ниже)
4. Назначить agents → реализация → verifier (PASSED/FAILED)

## Project Plan

Стратегический план: `docs/PROJECT_PLAN.md`  
Workflow + model routing: `docs/MASTER-AI-WORKFLOW.md`  
Bootstrap source: `ai-agent-system-bootstrap/`

## Skills

| Skill | Когда |
|-------|-------|
| `context-loading` | Старт, resume |
| `start-feature` | Feature Plan + proceed gate |
| `subagent-orchestrator` | Multi-domain после proceed |
| `maxserver-server-deploy` | Docker, VPS, Caddy, deploy, CI/CD |
| `maxserver-fastapi-backend` | API, hooks, `app/` |
| `maxserver-postgresql` | Schema, `db_pg.py`, migrations |
| `maxserver-auth-security` | JWT, tenant, secrets |
| `maxserver-static-ui` | Vanilla HTML/CSS/JS UI |
| `maxserver-campaign` | Anti-ban pacing, warmup, sending |
| `maxserver-testing` | pytest, smoke, deploy verify |

Инвентарь: `.cursor/skills/SKILLS-INVENTORY.md`

## Agents

| Agent | Model | Файл |
|-------|-------|------|
| Orchestrator | GPT-5.5 | `.cursor/agents/project-orchestrator.md` |
| Verifier | Composer 2.5 | `.cursor/agents/verifier.md` |
| Backend | Composer 2.5 | `.cursor/agents/backend-engineer.md` |
| Frontend | Composer 2.5 | `.cursor/agents/frontend-engineer.md` |
| Database | Composer 2.5 | `.cursor/agents/database-engineer.md` |
| DevOps | Composer 2.5 | `.cursor/agents/devops-engineer.md` |
| Security | Opus | `.cursor/agents/security-engineer.md` |
| Campaign | Composer 2.5 | `.cursor/agents/campaign-specialist.md` |
| QA | Composer 2.5 | `.cursor/agents/qa-engineer.md` |

## Rules

- `max-sender-workspace.mdc` — общие правила (always)
- `ai-skills-system.mdc` — маршрутизация skills/agents (always)
- `server-workspace.mdc` — globs для кода проекта

## Project Management

Перед работой читать:

- `.cursor/project-management/CURRENT_CONTEXT.md`
- `.cursor/project-management/PROJECT_STATUS.md`
- `.cursor/project-management/TASKS.md`
- `.cursor/project-management/DECISIONS.md`
- `.cursor/project-management/HANDOFF.md`

## Команды

- `/start-feature [описание]` → Feature Plan → `proceed` → реализация
- `/deploy-server [описание]` → devops-engineer + deploy checklist

## Документация

- `docs/PROJECT_PLAN.md` — vision, milestones, risks
- `docs/MASTER-AI-WORKFLOW.md` — model routing, coordination
- `docs/PRODUCTION-OPS.md` — production runbook
- `.cursor/workflows/feature-lifecycle.md` — жизненный цикл фичи
