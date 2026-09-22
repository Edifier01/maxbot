"""T24 scoped admin actions and institution-list contracts."""

from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_bulk_helpers_require_explicit_scope_and_report_partial_results() -> None:
    source = (ROOT / "static/js/features/admin.js").read_text(encoding="utf-8")
    for name in (
        "selection_mode",
        "explicit_all",
        "buildBulkPreview",
        "idempotency_key",
        "audit",
        "partial",
        "per_item",
        "emergency_stop",
    ):
        assert name in source
    assert "selectAll" not in source


def test_admin_ui_keeps_subscription_filters_and_safe_action_labels() -> None:
    source = (ROOT / "static/js/admin.js").read_text(encoding="utf-8")
    assert "loadExpiring" in source
    assert "expiring" in source
    assert "Подпис" in source
    assert "confirm" in source.lower()
