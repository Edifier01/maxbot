"""_setting_float / _setting_int must exist on main (used by circuit + dashboard)."""

from __future__ import annotations


def test_setting_float_int_helpers(tmp_path, monkeypatch):
    monkeypatch.setenv("MAX_TEST", "1")
    monkeypatch.setenv("MAX_SERVER_MODE", "0")

    import importlib

    import app.config as cfg

    importlib.reload(cfg)
    import main as m

    monkeypatch.setattr(m, "ROOT", tmp_path)
    m._refresh_data_paths()
    m.init_db()

    assert m._setting_float("missing_key_xyz", 1.5) == 1.5
    assert m._setting_int("missing_key_xyz", 7) == 7
    assert isinstance(m._setting_float("delay_min_sec", 60.0), float)
    assert isinstance(m._setting_int("delay_min_sec", 60), int)


def test_is_circuit_open_uses_setting_float(tmp_path, monkeypatch):
    monkeypatch.setenv("MAX_TEST", "1")
    monkeypatch.setenv("MAX_SERVER_MODE", "0")

    import importlib

    import app.config as cfg

    importlib.reload(cfg)
    import main as m

    monkeypatch.setattr(m, "ROOT", tmp_path)
    m._refresh_data_paths()
    m.init_db()
    m.RUNTIME.consecutive_errors.clear()
    m.RUNTIME.circuit_opened_at.clear()
    assert m._is_circuit_open(1) is False
