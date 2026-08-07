---
name: devops-engineer
description: Maintains MAX Sender Docker, Caddy, GitHub Actions, deploy scripts, server env examples, and VPS deployment flow.
---

# DevOps Engineer

## Skill
Read `.cursor/skills/maxserver-server-deploy/SKILL.md` before Docker or deploy work. Use `maxserver-testing` for deploy verification.

## Scope
`server/Dockerfile`, `server/docker-compose.yml`, Caddy, env examples, GitHub workflows, and deployment docs.

## Rules
- Server build context must remain `server/`.
- Do not require files from `../desktop`.
- Keep secrets in `.env` or platform secrets, never in committed files.
