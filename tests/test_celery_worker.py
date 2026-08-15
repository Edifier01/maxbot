"""D-2: Celery worker module smoke (no live Redis required for ping task)."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock

import pytest


@pytest.fixture(autouse=True)
def _redis_url(monkeypatch):
    monkeypatch.setenv("REDIS_URL", "redis://127.0.0.1:6379/0")


def test_celery_ping_task():
    from celery_worker import ping

    assert ping() == {"ok": True, "service": "max_sender"}


def test_celery_app_registered_tasks():
    from celery_worker import app

    names = set(app.tasks.keys())
    assert "max_sender.ping" in names
    assert "max_sender.enqueue_campaign_start" in names


def test_service_auth_header_prefers_internal_token(monkeypatch):
    monkeypatch.setenv("INTERNAL_SERVICE_TOKEN", "svc-tok")
    monkeypatch.delenv("MAX_API_PIN", raising=False)

    from celery_worker import _service_auth_header

    assert _service_auth_header() == {"Authorization": "Bearer svc-tok"}


def test_service_auth_header_empty_without_token(monkeypatch):
    monkeypatch.delenv("INTERNAL_SERVICE_TOKEN", raising=False)
    monkeypatch.delenv("MAX_API_PIN", raising=False)

    from celery_worker import _service_auth_header

    with pytest.raises(RuntimeError, match="INTERNAL_SERVICE_TOKEN"):
        _service_auth_header()


def test_enqueue_campaign_start_fails_closed_without_token(monkeypatch):
    monkeypatch.delenv("INTERNAL_SERVICE_TOKEN", raising=False)
    import urllib.request

    mock_urlopen = MagicMock()
    monkeypatch.setattr(urllib.request, "urlopen", mock_urlopen)

    from celery_worker import enqueue_campaign_start

    with pytest.raises(RuntimeError, match="INTERNAL_SERVICE_TOKEN"):
        enqueue_campaign_start(1)

    mock_urlopen.assert_not_called()


def test_compose_celery_profile_env():
    """Document expected Celery env in compose (static check)."""
    text = (Path(__file__).resolve().parents[1] / "docker-compose.yml").read_text(encoding="utf-8")
    assert 'profiles: ["celery"]' in text
    assert "celery-worker" in text
    assert 'USE_CELERY: "1"' in text
