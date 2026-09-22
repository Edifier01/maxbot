"""T07: ordinary login failures do not destructively retry with a fresh session."""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock


def test_saved_session_failure_does_not_trigger_fresh_retry(monkeypatch) -> None:
    from app import routes_profiles

    login = AsyncMock(side_effect=RuntimeError("network connection failed"))
    monkeypatch.setattr(routes_profiles.m, "_login_max", login)

    async def run() -> None:
        try:
            await routes_profiles._run_login_attempt(
                7,
                "+79990014402",
                fresh=False,
                group_id=None,
            )
        except RuntimeError as exc:
            assert str(exc) == "network connection failed"
        else:
            raise AssertionError("ordinary saved-session failure must be returned")

    asyncio.run(run())
    login.assert_awaited_once_with(7, "+79990014402", fresh=False, group_id=None)
