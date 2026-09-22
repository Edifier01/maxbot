"""T17: auth wizard must resume an attempt without secret persistence."""

from __future__ import annotations

from pathlib import Path

from app.routes_models import CodeIn


ROOT = Path(__file__).resolve().parents[1]


def test_password_model_preserves_leading_and_trailing_spaces() -> None:
    assert CodeIn(code="  literal password  ").code == "  literal password  "


def test_auth_wizard_module_has_attempt_identity_and_no_restore_reset() -> None:
    source = (ROOT / "static/js/features/auth.js").read_text(encoding="utf-8")
    assert "attempt_id" in source
    assert "revision" in source
    assert "one-time-code" in source
    assert "current-password" in source
    assert "login/reset" not in source
    assert "setInterval" not in source


def test_password_endpoint_does_not_trim_the_secret() -> None:
    source = (ROOT / "app/routes_profiles.py").read_text(encoding="utf-8")
    password_block = source.split('@router.post("/api/profiles/{profile_id}/password")', 1)[1]
    password_block = password_block.split('@router.patch("/api/profiles/{profile_id}/disable")', 1)[0]
    assert "body.code.strip()" not in password_block
