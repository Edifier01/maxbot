"""MAX handshake must advertise a current client version."""

from __future__ import annotations

from types import SimpleNamespace


class _UA:
    def __init__(self, app_version: str, build_number: int) -> None:
        self.app_version = app_version
        self.build_number = build_number

    def model_copy(self, update=None):
        data = {"app_version": self.app_version, "build_number": self.build_number}
        data.update(update or {})
        return _UA(data["app_version"], data["build_number"])


def test_prefer_current_max_user_agent_pins_preferred_build(monkeypatch):
    import main as m

    monkeypatch.setattr(
        m, "_preferred_max_app_versions", lambda: (("26.25.0", 6790), ("26.17.1", 6712))
    )
    extra = SimpleNamespace(
        user_agent=None,
        generate_user_agent=lambda: _UA("26.9.1", 6643),
    )
    m._prefer_current_max_user_agent(extra)
    assert extra.user_agent.app_version == "26.25.0"
    assert extra.user_agent.build_number == 6790


def test_prefer_current_max_user_agent_keeps_explicit_ua():
    import main as m

    existing = _UA("26.1.0", 1)
    extra = SimpleNamespace(user_agent=existing, generate_user_agent=lambda: _UA("26.9.1", 6643))
    m._prefer_current_max_user_agent(extra)
    assert extra.user_agent is existing
