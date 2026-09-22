"""T27 records local rendered-browser evidence and hosted-CI limits."""

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_ui_review_records_local_browser_evidence_without_release_claim() -> None:
    source = (ROOT / "docs/audit/ui-review.md").read_text(encoding="utf-8")
    assert "Status: `LOCAL PASS / HOSTED CI PENDING`" in source
    assert "390" in source and "768" in source and "1440" in source
    assert "6 passed" in source
    assert "HOSTED CI" in source
    assert "Browser plugin was unavailable" in source
    assert "do not prove" in source
