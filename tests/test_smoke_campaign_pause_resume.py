"""Smoke: campaign pause/resume сохраняет прогресс; reset обнуляет."""

from __future__ import annotations

from tests.conftest import queue_indices, seed_campaign_db, setup_vault

EXPECTED = (5, 7, 2)


def test_campaign_pause_resume_preserves_progress(client, main_module, idle_worker):
    setup_vault(client)
    seed_campaign_db(main_module, profile_idx=5, message_idx=7, group_idx=2)

    r = client.post("/api/campaign/start")
    assert r.status_code == 200, r.text
    assert client.get("/api/status").json()["running"] is True
    assert queue_indices(client) == EXPECTED

    r = client.post("/api/campaign/pause")
    assert r.status_code == 200
    assert client.get("/api/status").json()["running"] is False
    assert queue_indices(client) == EXPECTED

    r = client.post("/api/campaign/start")
    assert r.status_code == 200, r.text
    assert client.get("/api/status").json()["running"] is True
    assert queue_indices(client) == EXPECTED

    r = client.post("/api/campaign/stop")
    assert r.status_code == 200
    assert client.get("/api/status").json()["running"] is False
    assert queue_indices(client) == EXPECTED


def test_campaign_reset_clears_progress(client, main_module, idle_worker):
    setup_vault(client)
    seed_campaign_db(main_module, profile_idx=5, message_idx=7, group_idx=2)

    client.post("/api/campaign/start")
    client.post("/api/campaign/stop")
    assert queue_indices(client) == EXPECTED

    r = client.post("/api/campaign/reset")
    assert r.status_code == 200
    assert queue_indices(client) == (0, 0, 0)
