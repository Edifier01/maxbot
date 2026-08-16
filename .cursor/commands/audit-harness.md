---
name: audit-harness
description: Audit MAX Sender Cursor agents/skills/approvals without adding a new runtime.
---

# Audit Harness

Пользователь вызвал `/audit-harness`.

## Шаги

1. Прочитай `.cursor/skills/maxserver-harness/SKILL.md`.
2. Сверь routing в `.cursor/rules/ai-skills-system.mdc` и `AGENTS.md` с файлами в `.cursor/skills/*/SKILL.md` и `.cursor/agents/*.md`.
3. Отметь broken paths, дубли персон, always-on раздутие контекста.
4. Предложи **минимальный** фикс (удалить/сцепить/добавить одну строку routing). Не ставь ECC/DeerFlow/2000 skills.

## Вывод

Чеклист из skill + GO/NO-GO. Без кода, пока пользователь не сказал «правь».
