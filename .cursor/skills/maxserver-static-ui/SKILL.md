---
name: maxserver-static-ui
description: Vanilla HTML/CSS/JS panels for MAX Sender server and desktop. Use when editing static UI, auth/admin panels, or campaign UX without a build step.
---

# MAX Sender Static UI

## Scope

| File | Purpose |
|------|---------|
| `static/index.html` | Tenant: groups + start/stop + stats; admin/impersonation sees full ops |
| `static/admin.html` | Admin SaaS (users, subscriptions, global settings/messages) |
| `static/auth.html` | Login / register |

Desktop mirror: `desktop/static/` when workspace includes desktop — keep server independent.

## Constraints (non-negotiable)

- **No frontend build step** (no Vite/Webpack/Tailwind pipeline) without explicit approval.
- **Offline-friendly** for desktop builds.
- Self-hosted fonts under `static/fonts/` (Manrope, JetBrains Mono).
- API via `fetch` + Bearer cookie `max_token`; respect role (`user` vs `admin`).

## Design tokens (server `index.html`)

Existing `:root` CSS variables — extend, do not replace wholesale:

- Surfaces: `--bg`, `--bg-elev`, `--bg-soft`
- Lines: `--line`, `--line-soft`
- Text: `--text`, `--muted`, `--faint`
- Semantic: `--accent`, `--ok`, `--warn`, `--danger`
- Layout: `--radius`, `--radius-sm`, `--shadow`
- Fonts: `--font`, `--mono`

Admin panel should stay visually consistent with tenant panel (same token names where possible).

## Patterns

- Nav tabs: `nav button[data-tab="…"]` + sections `#campaign`, `#groups`, etc.
- Badges: `.badge` variants (`ok`, `warn`, `danger`, `stop`, …)
- Settings rows: `.settings-row`, `.controls`
- Toasts/alerts: prefer non-blocking toasts in admin and tenant panel; subscription start gate uses `toast(..., 'error')`, not `alert()`
- Role CSS: `.header-user-hide`, `.settings-admin-only`, `.campaign-admin-only`

## Server-mode UX rules

- Users without subscription: can manage groups/profiles; **cannot** start campaigns; message pool is admin-only.
- Show subscription state in header (`#subscriptionBadge`).
- `worker_pool_size` UI is **admin-only** (not tenant settings).

## Verification

- Grep for orphaned tab/section IDs after nav changes.
- Manual smoke: auth → campaign → groups → admin.
- Optional: `tests/test_saas_ux_static.py` for critical strings/DOM contracts.

## Related skills

UI improvement workflow: `maxserver-ui-workflow` → audit with `web-design-guidelines` / `ui-ux-pro-max`, implement here.
