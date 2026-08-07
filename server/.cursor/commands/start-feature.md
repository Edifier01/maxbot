---
name: start-feature
description: Feature Plan для MAX Sender Server — context loading, orchestrator, agents, models, proceed gate.
---

# Start Feature

Пользователь вызвал `/start-feature` с описанием задачи.

## Шаги

1. `.cursor/skills/context-loading/SKILL.md` — загрузить контекст.
2. `.cursor/skills/start-feature/SKILL.md` — формат Feature Plan.
3. `.cursor/agents/project-orchestrator.md` — действовать как orchestrator.
4. Вернуть **только Feature Plan** (с Model Strategy, File Ownership, Agent/Skills Assignment).
5. **Ждать `proceed`** — не писать код для STANDARD/COMPLEX.

## Подтверждение

`proceed`, `ok`, `yes`, `да`, `go ahead`, `начинай`

## После proceed

1. Mission Brief (`.cursor/skills/subagent-orchestrator/SKILL.md`)
2. Scoped implementation
3. Verifier → PASSED / FAILED
4. Обновить PM state

## Вывод

Feature Plan + до 2 блокирующих вопросов. Без кода до подтверждения.
