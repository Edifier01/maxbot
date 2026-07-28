# Curated Skills для серверной версии

В `server/skills/` лежит **~1900** community-скиллов (antigravity bundle). Для MAX Sender на сервере нужен только **curated-набор** — см. `skills-curated/manifest.json`.

## Зачем отбор

| Проблема | Решение |
|----------|---------|
| 1900 скиллов перегружают контекст | `skills-curated/` — 26 релевантных |
| Разные стеки (WordPress, K8s, Vercel…) | Исключены; стек: Docker + Caddy + FastAPI |
| UI не Tailwind/React | Vanilla CSS в `static/index.html` |

---

## Deploy и инфраструктура

| Скилл | Когда использовать |
|-------|-------------------|
| [vps-server-management](skills/vps-server-management/SKILL.md) | SSH, VPS, статус, логи |
| [docker-expert](skills/docker-expert/SKILL.md) | Dockerfile, compose, volumes, healthcheck |
| [devops-deploy](skills/devops-deploy/SKILL.md) | Production deploy, rollback |
| [deployment-pipeline-design](skills/deployment-pipeline-design/SKILL.md) | CI/CD pipeline (будущее) |
| [environment-setup-guide](skills/environment-setup-guide/SKILL.md) | Первичная настройка сервера |
| [ci-cd-and-automation](skills/ci-cd-and-automation/SKILL.md) | GitHub Actions |
| [bash-pro](skills/bash-pro/SKILL.md) | `scripts/deploy.sh` |

## Безопасность

| Скилл | Когда использовать |
|-------|-------------------|
| [container-security-hardening](skills/container-security-hardening/SKILL.md) | Hardening Docker |
| [security-and-hardening](skills/security-and-hardening/SKILL.md) | Auth, PIN, threat model |
| [secrets-management](skills/secrets-management/SKILL.md) | `.env`, API keys, rotation |
| [top-web-vulnerabilities](skills/top-web-vulnerabilities/SKILL.md) | Аудит публичного сайта |

## Backend

| Скилл | Когда использовать |
|-------|-------------------|
| [python-fastapi-development](skills/python-fastapi-development/SKILL.md) | Новые API, async |
| [fastapi-pro](skills/fastapi-pro/SKILL.md) | WebSocket, middleware |
| [fastapi-templates](skills/fastapi-templates/SKILL.md) | Scaffold модулей |
| [async-python-patterns](skills/async-python-patterns/SKILL.md) | Воркеры рассылки |
| [python-patterns](skills/python-patterns/SKILL.md) | `server/app/` |
| [openapi-spec-generator](skills/openapi-spec-generator/SKILL.md) | Документация API |
| [redis-cli](skills/redis-cli/SKILL.md) | Redis, Celery |

## Мониторинг

| Скилл | Когда использовать |
|-------|-------------------|
| [prometheus-configuration](skills/prometheus-configuration/SKILL.md) | `/metrics`, scrape |
| [observability-engineer](skills/observability-engineer/SKILL.md) | Logs, health, alerts |

## UI и сайт

| Скилл | Когда использовать |
|-------|-------------------|
| [ui-ux-pro-max](skills/ui-ux-pro-max/SKILL.md) | Dashboard, палитра, UX |
| [web-design-guidelines](skills/web-design-guidelines/SKILL.md) | Ревью UI по guidelines |
| [ui-a11y](skills/ui-a11y/SKILL.md) | Доступность |
| [wcag-audit-patterns](skills/wcag-audit-patterns/SKILL.md) | WCAG-аудит |
| [web-performance-optimization](skills/web-performance-optimization/SKILL.md) | Скорость панели |
| [site-architecture](skills/site-architecture/SKILL.md) | Landing + панель + разделы |

## Тестирование

| Скилл | Когда использовать |
|-------|-------------------|
| [webapp-testing](skills/webapp-testing/SKILL.md) | Playwright E2E |
| [web-security-testing](skills/web-security-testing/SKILL.md) | Security-тесты |

---

## Не включены (и почему)

- **Vercel / Netlify / Cloud Run** — свой VPS + Docker
- **Kubernetes** — избыточно для v1
- **Tailwind / React / shadcn** — UI на vanilla CSS
- **WordPress, Shopify, n8n…** — не относится к проекту
- **~1800 остальных** — automation, ML, marketing и т.д.

Полный список установленных скиллов: `skills/.antigravity-install-manifest.json`.
