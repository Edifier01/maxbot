"""Lazy proxy to root main.py — single import point for app/ modules."""

from __future__ import annotations


class _MainProxy:
    """Lazy proxy — main is fully loaded before first attribute access."""

    def __getattr__(self, name: str):
        import main as m

        return getattr(m, name)


main = _MainProxy()
