---
name: start-feature
description: Feature Plan для MAX Sender перед нетривиальной работой — orchestrator, зона desktop/server/both, agents и skills.
---

# Start Feature

Пользователь вызвал `/start-feature` с описанием задачи (текст после команды).

## Шаги

1. Прочитай `.cursor/skills/context-loading/SKILL.md` и выполни context loading.
2. Прочитай `.cursor/skills/start-feature/SKILL.md` — формат Feature Plan.
3. Прочитай `.cursor/rules/ai-skills-system.mdc` — маршрутизация skills.
4. Действуй как `.cursor/agents/project-orchestrator.md`.
5. Классифицируй задачу: `desktop` | `server` | `both`.
6. Верни **только Feature Plan** (с **Skills Assignment** и **Agent Assignment**).
7. Для MEDIUM/HIGH risk — **не начинай реализацию** до явного OK пользователя.

## Вывод

Feature Plan + критичные вопросы, блокирующие планирование. Без кода.
