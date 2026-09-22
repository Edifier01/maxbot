"""T22 overview state projection stays truthful and scoped."""

from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_overview_module_distinguishes_waiting_stopped_and_connection_lost() -> None:
    source = (ROOT / "static/js/features/overview.js").read_text(encoding="utf-8")
    assert "waiting_window" in source
    assert "waiting_limit" in source
    assert "connection_lost" in source
    assert "unknown" in source
    assert "delivered" not in source.lower()


def test_overview_keeps_stop_accessible_and_separates_library_from_plan() -> None:
    source = (ROOT / "static/js/features/overview.js").read_text(encoding="utf-8")
    assert "library_count" in source
    assert "day_selection_count" in source
    assert "stop" in source.lower()
    assert "next_action" in source
