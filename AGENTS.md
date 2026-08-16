# MAX Sender — AI System

Единая AI-система для `desktop/` и `server/`. Конфигурация в `.cursor/`.

**Серверная версия — самодостаточный проект** в `server/`: собственные `AGENTS.md`, `.cursor/`, `.github/`. Откройте `server/` как корень workspace или скопируйте папку отдельно — desktop не нужен.

## Быстрый старт

1. `/start-feature [задача]` — Feature Plan перед нетривиальной работой.
2. `/improve-ui [scope]` — audit и улучшение static UI (см. `maxserver-ui-workflow`).
3. `/deploy-server [изменение]` — Docker/VPS/deploy по checklist.
4. `/ponytail-review` — оверинжиниринг текущего diff.
5. `/audit-harness` — проверка путей agents/skills.
6. Классифицировать: `desktop` | `server` | `both`.
7. Загрузить skills по зоне (см. таблицу ниже).
8. Назначить agents → реализация через Task (см. `.cursor/rules/specialist-delegation.mdc`) → verifier.

## Skills

| Skill | Когда |
|-------|-------|
| `context-loading` | Старт, resume, выбор зоны |
| `start-feature` | Feature Plan |
| `subagent-orchestrator` | Multi-domain, routing |
| `maxserver-harness` | `/audit-harness`, новые agents/skills |
| `maxserver-server-deploy` | Docker, VPS, Caddy, deploy, CI/CD |
| `maxserver-fastapi-backend` | API, hooks, `app/` |
| `maxserver-postgresql` | Schema, `db_pg.py`, migrations |
| `maxserver-auth-security` | JWT, tenant, secrets |
| `maxserver-static-ui` | Vanilla HTML/CSS/JS UI, auth/admin panel |
| `maxserver-ui-workflow` | UI audit → design brief → implement → verify |
| `web-design-guidelines` | Vercel Web Interface Guidelines audit |
| `ui-ux-pro-max` | Design system CLI + UX rules (from Knowlange) |
| `frontend-design-max` | Visual direction brief for static UI |
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
| UI Designer | `.cursor/agents/ui-designer.md` |
| Database | `.cursor/agents/database-engineer.md` |
| DevOps | `.cursor/agents/devops-engineer.md` |
| Security | `.cursor/agents/security-engineer.md` |
| QA | `.cursor/agents/qa-engineer.md` |
| Campaign | `.cursor/agents/campaign-specialist.md` |

Не расширяйте roster без `/audit-harness` и строки в `ai-skills-system.mdc`. Extra persona files without routing are unused.

## External Skills Library

Не грузите `skills/` или `Knowlange/` целиком. Активный слой — `.cursor/skills/`. Generics (`fastapi-patterns`, …) читаются из facade `maxserver-*`, не вместо него.

## Rules

- `max-sender-workspace.mdc` — общие правила (always)
- `ai-skills-system.mdc` — маршрутизация skills/agents (always)
- `server-workspace.mdc` — `server/**`
- `desktop-workspace.mdc` — `desktop/**` (N/A если workspace = этот server tree)

## Документация

- `docs/MASTER-AI-WORKFLOW.md` — архитектура и model routing
- `.cursor/workflows/feature-lifecycle.md` — жизненный цикл задачи
- `.cursor/skills/README.md` — индекс + маппинг на внешнюю библиотеку skills
