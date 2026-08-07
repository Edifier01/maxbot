"""Тесты check_proxy / parse_proxy_list."""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import antiban_core


def test_parse_proxy_list_multiline():
    raw = "socks5://a:b@1.1.1.1:1080\n# comment\nsocks5://c:d@2.2.2.2:1080"
    assert antiban_core.parse_proxy_list(raw) == [
        "socks5://a:b@1.1.1.1:1080",
        "socks5://c:d@2.2.2.2:1080",
    ]


def test_check_proxy_empty_ok():
    ok, err = antiban_core.check_proxy("")
    assert ok is True
    assert err == ""


def test_check_proxy_bad_url():
    ok, err = antiban_core.check_proxy("not-a-url")
    assert ok is False
    assert "некорректный" in err


def test_check_proxy_unreachable():
    ok, err = antiban_core.check_proxy(
        "socks5://u:p@127.0.0.1:1", timeout=0.5
    )
    assert ok is False
    assert err
