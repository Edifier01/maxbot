"""Optional Celery worker for MAX Sender (Sprint 6).

Enable:
  pip install -r requirements-scale.txt
  set REDIS_URL=redis://127.0.0.1:6379/0
  set USE_CELERY=1
  celery -A celery_worker.app worker --loglevel=info

Tasks are thin wrappers: the main campaign loop still lives in asyncio
inside main.py (worker pool). Use Celery when you need multi-process
horizontal scale across machines sharing the same data volume / Redis.
"""

from __future__ import annotations

import os

REDIS_URL = os.environ.get("REDIS_URL", "redis://127.0.0.1:6379/0")

try:
    from celery import Celery
except ImportError as e:  # pragma: no cover
    raise SystemExit(
        "Celery not installed. pip install -r requirements-scale.txt"
    ) from e

app = Celery("max_sender", broker=REDIS_URL, backend=REDIS_URL)
app.conf.update(
    task_serializer="json",
    accept_content=["json"],
    result_serializer="json",
    timezone="UTC",
    enable_utc=True,
    task_track_started=True,
)


@app.task(name="max_sender.ping")
def ping() -> dict:
    return {"ok": True, "service": "max_sender"}


@app.task(name="max_sender.enqueue_campaign_start")
def enqueue_campaign_start() -> dict:
    """Trigger campaign start via local HTTP API (same host)."""
    import json
    from urllib.request import Request, urlopen

    host = os.environ.get("MAX_HOST", "127.0.0.1")
    port = os.environ.get("MAX_PORT", "8765")
    url = f"http://{host}:{port}/api/campaign/start"
    req = Request(url, data=b"{}", method="POST")
    req.add_header("Content-Type", "application/json")
    pin = os.environ.get("MAX_API_PIN", "")
    if pin:
        req.add_header("Authorization", f"Bearer {pin}")
    with urlopen(req, timeout=30) as resp:
        body = resp.read().decode()
    return json.loads(body) if body else {"ok": True}


if __name__ == "__main__":
    print("Use: celery -A celery_worker.app worker --loglevel=info")
    print(f"broker={REDIS_URL}")
