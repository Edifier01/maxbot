"""Smoke: onboarding wizard removed; vault init remains."""

from __future__ import annotations

from pathlib import Path

INDEX = Path(__file__).resolve().parents[1] / "static" / "index.html"


def test_onboarding_wizard_removed():
    html = INDEX.read_text(encoding="utf-8")
    assert 'id="onboardingOverlay"' not in html
    assert "max_sender_onboarding_v1" not in html
    assert "initVaultUI" in html


def test_groups_invite_link_only():
    html = INDEX.read_text(encoding="utf-8")
    assert 'id="groupLink"' in html
    assert 'placeholder="Пригласительная ссылка группы"' in html
    assert 'id="groupChatId"' not in html
    assert 'id="groupProxy"' not in html
