"""ADR 002: runtime delay floor 5s (lognormal + SQLite bypass)."""

from __future__ import annotations

import antiban_core


def test_lognormal_delay_sec_never_below_five():
    for _ in range(50):
        assert antiban_core.lognormal_delay_sec(5, 15) >= 5.0


def test_compute_send_delay_sec_floors_sqlite_one(monkeypatch):
    from app.campaign_send import compute_send_delay_sec

    def fake_int(key: str, default: int) -> int:
        if key == "delay_min_sec":
            return 1
        if key == "delay_max_sec":
            return 15
        return default

    monkeypatch.setattr("app.campaign_send._setting_int", fake_int)
    monkeypatch.setattr("app.campaign_send._human_pauses_enabled", lambda: False)
    delay, _kind = compute_send_delay_sec()
    assert delay >= 5.0
