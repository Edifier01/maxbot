"""T21 shared visual tokens and accessible foundation."""

from __future__ import annotations

import re
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def _relative_luminance(color: str) -> float:
    channels = [int(color[index : index + 2], 16) / 255 for index in (1, 3, 5)]
    linear = [
        channel / 12.92 if channel <= 0.03928 else ((channel + 0.055) / 1.055) ** 2.4
        for channel in channels
    ]
    return 0.2126 * linear[0] + 0.7152 * linear[1] + 0.0722 * linear[2]


def _contrast_ratio(foreground: str, background: str) -> float:
    foreground_luminance = _relative_luminance(foreground)
    background_luminance = _relative_luminance(background)
    lighter = max(foreground_luminance, background_luminance)
    darker = min(foreground_luminance, background_luminance)
    return (lighter + 0.05) / (darker + 0.05)


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


def test_semantic_foreground_tokens_meet_wcag_aa_on_panel_backgrounds() -> None:
    tokens = (ROOT / "static/css/tokens.css").read_text(encoding="utf-8")

    def token(name: str) -> str:
        match = re.search(rf"--{name}:\s*(#[0-9a-fA-F]{{6}})\b", tokens)
        assert match, f"missing hex token --{name}"
        return match.group(1)

    backgrounds = {name: token(name) for name in ("bg", "bg-soft")}
    foreground_names = ("text", "muted", "faint", "accent", "ok", "warn", "danger")
    for foreground_name in foreground_names:
        foreground = token(foreground_name)
        for background_name, background in backgrounds.items():
            ratio = _contrast_ratio(foreground, background)
            assert ratio >= 4.5, (
                f"--{foreground_name} on --{background_name} has contrast {ratio:.2f}"
            )
