"""P3-2: JWT jti + revoke helpers."""

from __future__ import annotations

from datetime import datetime, timezone

from app import auth


def test_create_token_has_jti():
    token = auth.create_token(1, tenant_id=2, role="user")
    payload = auth.decode_token(token)
    assert payload.get("jti")
    assert payload["sub"] == "1"


def test_token_expires_at_from_payload():
    token = auth.create_token(5, tenant_id=None, role="admin")
    payload = auth.decode_token(token)
    exp = auth.token_expires_at(payload)
    assert exp > datetime.now(timezone.utc)
