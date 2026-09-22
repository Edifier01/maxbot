"""T30 evidence keeps timeout and workload limitations explicit."""

from pathlib import Path
import re


ROOT = Path(__file__).resolve().parents[1]


def test_performance_report_does_not_turn_timeout_into_pass() -> None:
    source = (ROOT / "docs/audit/performance.md").read_text(encoding="utf-8")
    assert "Status: `PASS`" in source
    assert "493 passed, 19 skipped" in source
    assert "exit 124" in source
    assert re.search(r"\d+ collected on \d{4}-\d{2}-\d{2}", source)
    assert "NOT RUN" in source
    assert "T31 is `OFF / NOT_ADOPTED`" in source
