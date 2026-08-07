---
name: improve-ui
description: UI improvement workflow for MAX Sender static panels — audit, design brief, implement, verify.
---

# Improve UI

Пользователь вызвал `/improve-ui` с описанием (текст после команды) или без — полный audit панели.

## Шаги

1. Прочитай `.cursor/skills/maxserver-ui-workflow/SKILL.md`.
2. Действуй как orchestrator: **не** правь `static/*.html` сам на больших задачах.
3. **Round 1:** Task `ui-designer` — audit + design brief (scope из запроса или `index.html` + `admin.html`).
4. Покажи brief пользователю; жди OK на реализацию (если MEDIUM/HIGH visual change).
5. **Round 2:** Task `frontend-engineer` — implement brief.
6. **Round 3:** Task `qa-engineer` → `verifier`.

## Scope по умолчанию

- `static/index.html` — tenant panel
- `static/admin.html` — admin
- `static/auth.html` — если запрос про login/register

## Skills

`maxserver-ui-workflow`, `web-design-guidelines`, `ui-ux-pro-max`, `frontend-design-max`, `maxserver-static-ui`

## Вывод

Краткий audit summary + design brief; без кода до approve (если нет явного «делай сразу»).
