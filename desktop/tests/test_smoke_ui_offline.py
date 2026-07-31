"""Smoke: UI не зависит от Google Fonts CDN."""

from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
INDEX = ROOT / "static" / "index.html"
FONTS = ROOT / "static" / "fonts"

REQUIRED_FONTS = (
    "manrope-400.ttf",
    "manrope-500.ttf",
    "manrope-600.ttf",
    "manrope-700.ttf",
    "jetbrains-mono-400.ttf",
    "jetbrains-mono-500.ttf",
)


def test_index_has_no_google_fonts_cdn():
    html = INDEX.read_text(encoding="utf-8")
    assert "fonts.googleapis.com" not in html
    assert "fonts.gstatic.com" not in html


def test_index_uses_local_font_faces():
    html = INDEX.read_text(encoding="utf-8")
    assert '@font-face' in html
    assert "/static/fonts/manrope-400.ttf" in html
    assert "/static/fonts/jetbrains-mono-400.ttf" in html


def test_font_files_exist():
    for name in REQUIRED_FONTS:
        path = FONTS / name
        assert path.is_file(), f"missing {name}"
        assert path.stat().st_size > 10_000, f"font too small: {name}"


def test_fonts_served(client):
    for name in REQUIRED_FONTS:
        r = client.get(f"/static/fonts/{name}")
        assert r.status_code == 200, name
        assert r.headers.get("content-type", "").startswith("font/") or "octet-stream" in r.headers.get("content-type", "")
