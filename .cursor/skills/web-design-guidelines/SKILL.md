---
name: web-design-guidelines
description: Review UI code for Web Interface Guidelines compliance. Use when asked to "review my UI", "check accessibility", "audit design", "review UX", or "check my site against best practices".
metadata:
  author: vercel
  version: "1.0.0"
  argument-hint: <file-or-pattern>
source: vercel-labs/agent-skills (https://www.skills.sh/vercel-labs/agent-skills/web-design-guidelines)
---

# Web Interface Guidelines

Review files for compliance with Web Interface Guidelines.

Official install (project): `npx skills add https://github.com/vercel-labs/agent-skills --skill web-design-guidelines -a cursor --copy -y`

Canonical copy from the installer: `.agents/skills/web-design-guidelines/`. This file is the Cursor harness copy plus MAX Sender defaults.

## How It Works

1. Fetch the latest guidelines from the source URL below
2. Read the specified files (or prompt user for files/pattern)
3. Check against all rules in the fetched guidelines
4. Output findings in the terse `file:line` format

## Guidelines Source

Fetch fresh guidelines before each review:

```
https://raw.githubusercontent.com/vercel-labs/web-interface-guidelines/main/command.md
```

Use WebFetch to retrieve the latest rules. The fetched content contains all the rules and output format instructions.

## Usage

When a user provides a file or pattern argument:
1. Fetch guidelines from the source URL above
2. Read the specified files
3. Apply all rules from the fetched guidelines
4. Output findings using the format specified in the guidelines

If no files specified, ask the user which files to review.

## MAX Sender defaults

If no files/pattern given in this repo, audit:

- `static/index.html` (+ `static/js/index.js` if handlers/copy live there)
- `static/admin.html` (+ `static/js/admin.js`)
- `static/auth.html` (+ `static/js/auth.js`)

Context:

- Dark theme by default (`:root` vars). Keep `color-scheme: dark`.
- Russian UI copy — do not flag non-English labels. Title Case / Chicago-style English copy rules do not apply to Russian strings.
- Vanilla HTML/CSS/JS — no React/Vue-specific rules unless the DOM pattern still applies.
- Campaign/admin tables are data-dense; prioritize a11y (contrast, focus, labels) over decorative spacing.
- No frontend build step / Tailwind. Map guideline utilities (`focus-visible:ring-*`, `truncate`) to existing CSS.

## When to use

- Phase 1 of `maxserver-ui-workflow`
- Before/after `frontend-engineer` UI diffs
- Verifier re-check
