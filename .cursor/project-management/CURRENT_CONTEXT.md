# Current Context — MAX Sender

> Обновляется parent-агентом в конце каждой сессии. Специалисты не редактируют этот файл.

## Product

**MAX Sender** — локальное и серверное приложение для текстовой рассылки через мессенджер MAX (неофициальный API PyMax / maxapi-python).

## Active Focus

**Фаза:** Серверная SaaS-версия (v1.14) — мультитенантность, auth, admin panel, CI/CD scaffold.

**Приоритеты:**
1. Деплой на VPS + проверка auth/register/admin flow
2. WebSocket auth в server mode (verifier note)
3. Integration tests для server auth
4. Локальная версия — без регрессий (run.bat)

## Architecture Snapshot

| Слой | Технология | Путь |
|------|------------|------|
| Backend (монолит) | Python 3.12, FastAPI | `main.py` |
| Server extensions | JWT auth, tenant scope | `server/app/` |
| Frontend | Vanilla HTML | `static/index.html`, `auth.html`, `admin.html` |
| DB (local) | SQLite | `data/app.db` |
| DB (server identity) | PostgreSQL | `schema_pg.sql` tenants/users/subscriptions |
| DB (server tenant data) | SQLite per tenant | `data/tenants/{id}/app.db` |
| DB (server global) | SQLite | `data/global/app.db` (settings, message pool) |
| Infra | Docker Compose + Caddy + Postgres | `server/docker-compose.yml` |
| CI/CD | GitHub Actions | `.github/workflows/` |

## Dual Deployment Model

| Режим | Запуск | Auth |
|-------|--------|------|
| **Local** | `run.bat` / exe | API PIN (optional) |
| **Server** | `server/docker compose up` | Email/password JWT, admin bootstrap |

## Security Notes

- Server: bcrypt passwords, JWT (JWT_SECRET required in .env)
- Per-tenant session encryption (.app_key per tenant dir)
- Impersonation audit log in PostgreSQL
- WS auth in server mode — TODO (verifier)
