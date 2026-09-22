"""T29 security review contract and fail-closed boundary checks."""

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_security_review_records_scope_and_does_not_claim_unrun_gates() -> None:
    source = (ROOT / "docs/audit/security-review.md").read_text(encoding="utf-8")
    for marker in ("Severity", "Evidence", "pip-audit", "BLOCKED", "NOT RUN", "SHA"):
        assert marker in source
    assert "PASS: no vulnerabilities" not in source


def test_webhook_and_ws_boundaries_are_fail_closed() -> None:
    config = (ROOT / "app/config.py").read_text(encoding="utf-8")
    monitor = (ROOT / "app/routes_monitor.py").read_text(encoding="utf-8")
    assert "url.scheme == \"https\"" in config
    assert "not url.username" in config and "not url.password" in config
    assert "_ws_origin_allowed" in monitor
    assert "parsed.netloc.lower() == host.lower()" in monitor


def test_diagnostics_source_has_no_secret_bearing_fields() -> None:
    source = (ROOT / "app/routes_diagnostics.py").read_text(encoding="utf-8")
    assert "sms_q" not in source
    assert "pwd_q" not in source
    assert "token" not in source.lower()
