"""Smoke: onboarding wizard первого запуска."""

from __future__ import annotations

from pathlib import Path

INDEX = Path(__file__).resolve().parents[1] / "static" / "index.html"


def test_onboarding_wizard_markup():
    html = INDEX.read_text(encoding="utf-8")
    assert 'id="onboardingOverlay"' in html
    assert 'id="obSkip"' in html
    assert 'id="obNext"' in html
    assert 'id="obBack"' in html
    assert "max_sender_onboarding_v1" in html
    assert "Шаг 4 из 4" in html
    assert "Пропустить" in html
    assert "Перейти к группам" in html


def test_onboarding_uses_existing_apis():
    html = INDEX.read_text(encoding="utf-8")
    assert "/vault/setup" in html
    assert "/vault/unlock" in html
    assert "/messages/upload" in html
    assert "/groups" in html
    assert "maybeStartOnboarding" in html
