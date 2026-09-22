"""Lazy proxy to root main.py — single import point for app/ modules."""

from __future__ import annotations


class _MainProxy:
    """Lazy proxy — main is fully loaded before first attribute access."""

    def __getattr__(self, name: str):
        import main as m

        return getattr(m, name)

    def __setattr__(self, name: str, value: object) -> None:
        """Keep assignments on the real module, not on the proxy object.

        Application modules keep this proxy to avoid an eager circular import.
        Test patching and runtime configuration must nevertheless affect the
        same namespace that ``__getattr__`` reads from.
        """
        import main as m

        setattr(m, name, value)

    def __delattr__(self, name: str) -> None:
        """Delete attributes from the real module when the proxy is patched."""
        import main as m

        delattr(m, name)


main = _MainProxy()
