"""T23 account list, draft and safe drawer contracts."""

from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_account_filters_keep_server_pagination_and_safe_drawer() -> None:
    source = (ROOT / "static/js/features/groups.js").read_text(encoding="utf-8")
    for name in (
        "group_id",
        "role",
        "availability",
        "daily_plan",
        "connection_problem",
        "createAccountQuery",
        "page",
        "limit",
        "next_action",
        "association_count",
    ):
        assert name in source
    assert "password" not in source.lower()
    assert "credential_ref" not in source


def test_account_filters_preserve_drafts_and_normalize_phone() -> None:
    source = (ROOT / "static/js/features/groups.js").read_text(encoding="utf-8")
    assert "preserveDirtyDraft" in source
    assert "normalizePhone" in source
    assert "server_revision" in source
    assert "conflict" in source.lower()


def test_profile_api_remains_bounded_and_group_membership_is_scoped() -> None:
    profiles = (ROOT / "app/routes_profiles.py").read_text(encoding="utf-8")
    groups = (ROOT / "app/routes_groups.py").read_text(encoding="utf-8")
    assert "LIMIT ? OFFSET ?" in profiles
    assert "LIMIT ? OFFSET ?" in groups
    assert "group_id=? AND profile_id=?" in profiles
    assert "Группа не найдена" in groups
