"""A43 profile import contract is bounded and quote-aware in the browser."""

from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_profile_import_uses_quote_aware_bounded_parser() -> None:
    source = (ROOT / "static/js/index.js").read_text(encoding="utf-8-sig")
    assert "parseDelimitedRecords" in source
    assert "MAX_PROFILE_IMPORT_BYTES" in source
    assert "MAX_PROFILE_IMPORT_ROWS" in source
    assert "Незакрытая кавычка в CSV" in source
    assert "line.split(/[,;\\t]/)" not in source
