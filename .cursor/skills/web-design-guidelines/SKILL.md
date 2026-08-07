---
name: web-design-guidelines
description: Audit MAX Sender static HTML for Vercel Web Interface Guidelines compliance. Use in UI audit phase before implementing fixes.
source: Knowlange/agentic-awesome-skills (community)
---

# Web Interface Guidelines Audit

## Default targets (MAX Sender server)

- `static/index.html`
- `static/admin.html`
- `static/auth.html`

## Process

1. **Fetch** fresh rules (WebFetch):

```
https://raw.githubusercontent.com/vercel-labs/web-interface-guidelines/main/command.md
```

2. **Read** specified files (or all three defaults).
3. **Apply** every rule from fetched guidelines.
4. **Output** findings in the terse format required by the guidelines (typically `file:line`).

## MAX Sender context

- Dark theme by default (`:root` vars in `index.html`).
- Russian UI copy — do not flag non-English labels.
- Vanilla JS — no React/Vue-specific rules unless applicable to DOM patterns.
- Campaign/admin tables are data-dense; prioritize a11y (contrast, focus, labels) over decorative spacing.

## When to use

- Phase 1 of `maxserver-ui-workflow`
- Before/after `frontend-engineer` UI diffs
- Verifier re-check

## Limitations

- Guidelines fetch requires network.
- Does not replace manual browser testing or `ui-ux-pro-max` design-system recommendations.
