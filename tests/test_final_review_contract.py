"""T32/S05 release wording stays conservative and evidence-bound."""

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_final_review_is_fix_not_commit_bound_go() -> None:
    source = (ROOT / "docs/audit/final-review.md").read_text(encoding="utf-8")
    assert "Verdict: `FIX`" in source
    assert "dirty working tree" in source
    assert "ENV_DOCKER_READY=PASS" in source
    assert "NOT RUN" in source
    assert "production readiness" in source
