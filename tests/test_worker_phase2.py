"""Worker monolith phase 2: explicit deps, send/pacing in campaign_send."""

from __future__ import annotations

from pathlib import Path


def test_campaign_worker_has_no_lazy_m_bridge():
    src = Path(__file__).resolve().parents[1] / "app" / "campaign_worker.py"
    text = src.read_text(encoding="utf-8")
    assert "def _m(" not in text
    assert "_m()" not in text


def test_campaign_send_importable():
    from app.campaign_send import compute_send_delay_sec, send_with_retry, sleep_send_delay

    delay, kind = compute_send_delay_sec()
    assert delay > 0
    assert kind in ("normal", "short", "long")
    assert callable(send_with_retry)
    assert callable(sleep_send_delay)


def test_campaign_facade_proxy():
    from app.campaign_facade import main

    assert main.APP_VERSION
