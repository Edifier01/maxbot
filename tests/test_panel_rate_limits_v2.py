"""T19: typed API errors and one bounded status fallback transport."""

from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_core_transport_modules_exist_with_retry_after_and_visibility_contract() -> None:
    api = (ROOT / "static/js/core/api.js").read_text(encoding="utf-8")
    events = (ROOT / "static/js/core/events.js").read_text(encoding="utf-8")
    store = (ROOT / "static/js/core/store.js").read_text(encoding="utf-8")
    errors = (ROOT / "static/js/core/errors.js").read_text(encoding="utf-8")
    assert "retry-after" in api.lower()
    assert "ApiError" in errors
    assert "visibilitychange" in events
    assert "WebSocket" in events
    assert "setInterval" not in events
    assert "revision" in store


def test_index_has_no_fast_two_second_fallback_or_false_profile_404() -> None:
    source = (ROOT / "static/js/index.js").read_text(encoding="utf-8")
    assert "}, 2000);" not in source
    assert "catch {\n        return null;\n      }" not in source
    assert "document.visibilityState" in source
