"""The lazy main proxy must not retain patched state between tests."""

from __future__ import annotations


def test_main_proxy_forwards_patch_and_restoration(monkeypatch) -> None:
    import main as runtime_module
    from app.runtime import main as runtime_proxy

    original = runtime_module._is_server_mode
    monkeypatch.setattr(runtime_proxy, "_is_server_mode", lambda: False)
    assert runtime_module._is_server_mode() is False
    assert "_is_server_mode" not in vars(runtime_proxy)

    monkeypatch.undo()
    assert runtime_module._is_server_mode is original
    assert "_is_server_mode" not in vars(runtime_proxy)


def test_main_proxy_deletes_forwarded_new_attribute(monkeypatch) -> None:
    import main as runtime_module
    from app.runtime import main as runtime_proxy

    name = "_runtime_proxy_test_only"
    assert not hasattr(runtime_module, name)

    monkeypatch.setattr(runtime_proxy, name, object(), raising=False)
    assert hasattr(runtime_module, name)
    assert name not in vars(runtime_proxy)

    monkeypatch.undo()
    assert not hasattr(runtime_module, name)
