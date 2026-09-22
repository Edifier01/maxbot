"""T21 shared visual tokens and accessible foundation."""

from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_shared_css_assets_are_loaded_by_all_panel_pages() -> None:
    expected = ["tokens.css", "components.css", "layout.css"]
    for page in ("static/index.html", "static/admin.html", "static/auth.html"):
        source = (ROOT / page).read_text(encoding="utf-8")
        for asset in expected:
            assert f'/static/css/{asset}' in source


def test_shared_css_has_focus_reduced_motion_and_semantic_tokens() -> None:
    tokens = (ROOT / "static/css/tokens.css").read_text(encoding="utf-8")
    components = (ROOT / "static/css/components.css").read_text(encoding="utf-8")
    layout = (ROOT / "static/css/layout.css").read_text(encoding="utf-8")
    assert "--accent" in tokens and "--danger" in tokens
    assert "focus-visible" in components
    assert "prefers-reduced-motion" in components
    assert "min-height: 44px" in components
    assert "grid" in layout or "flex" in layout
