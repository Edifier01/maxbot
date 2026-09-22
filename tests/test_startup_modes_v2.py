"""T28 startup and documentation must describe the actual repository."""

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_startup_does_not_hide_required_router_import_failures() -> None:
    source = (ROOT / "main.py").read_text(encoding="utf-8-sig")
    assert "from app.register import register_server" in source
    registration = source[source.index("from app.register import register_server") :]
    assert "except ImportError" not in registration[:400]


def test_readme_describes_root_entrypoints_and_declares_unsupported_exe() -> None:
    source = (ROOT / "README.md").read_text(encoding="utf-8")
    assert "desktop/` - local Windows desktop build" not in source
    assert "server/` - VPS/Docker build" not in source
    assert "python -m app.main" in source
    assert "Docker Compose" in source
    assert "EXE" in source and "не поддерж" in source


def test_deploy_verification_has_explicit_health_failure_state() -> None:
    source = (ROOT / "scripts/verify_deploy.sh").read_text(encoding="utf-8")
    assert "health_ok=0" in source
    assert "health_ok=1" in source
    assert "db_ok" in source
    assert "readiness check did not succeed" in source


def test_required_routes_are_present_in_openapi_without_starting_services() -> None:
    import main

    paths = main.app.openapi()["paths"]
    for path in (
        "/api/health",
        "/api/status",
        "/api/diagnostics/auth-attempts/{attempt_id}",
        "/api/message-sets/preview",
    ):
        assert path in paths


def test_migration_runbook_is_additive_and_repeatable() -> None:
    source = (ROOT / "docs/audit/migrations.md").read_text(encoding="utf-8")
    assert "idempot" in source.lower()
    assert "backup" in source.lower()
    assert "no production schema migration" in source.lower()
