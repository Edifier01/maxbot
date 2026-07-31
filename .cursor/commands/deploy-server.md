---
name: deploy-server
description: Deploy MAX Sender на VPS — Docker Compose, Caddy, .env, health check, pre-deploy checklist.
---

# Deploy Server

Пользователь вызвал `/deploy-server` (опционально с описанием изменения).

## Шаги

1. Context loading: `.cursor/skills/context-loading/SKILL.md`, зона `server`.
2. Skill: `.cursor/skills/maxserver-server-deploy/SKILL.md`.
3. Agent: `.cursor/agents/devops-engineer.md`.
4. Если затронуты auth/secrets → `maxserver-auth-security` + security-engineer.
5. Если затронута schema → `maxserver-postgresql` + database-engineer.
6. Pre-deploy checklist **до** production-действий.
7. Рабочая директория Docker: `server/`.
8. После изменений: `docker compose config`.
9. Health check; qa-engineer + verifier перед «готово».

## Вывод

- Что изменено
- Команды и результаты
- Статус checklist
- Непроверенные риски
