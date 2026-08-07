# MAX Sender

The project is split into two independent working folders:

- `desktop/` - local Windows desktop build: `run.bat`, `build.bat`, PyInstaller exe, SQLite runtime data next to the app.
- `server/` - VPS/Docker build: FastAPI core, `server/app/`, Caddy/HTTPS, Redis, PostgreSQL and server-mode extensions.

The shared AI development system lives in `.cursor/` and covers both versions. Entry point: **`AGENTS.md`**. Work inside the target folder, but keep architecture decisions and handoff in the shared project-management files.
