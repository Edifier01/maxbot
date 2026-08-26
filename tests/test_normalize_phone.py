"""Phone normalization used by groups API."""

import pytest

from app.runtime import main as m


def test_normalize_phone_ru_8_prefix():
    assert m._normalize_phone("89380021575") == "+79380021575"


def test_normalize_phone_already_e164():
    assert m._normalize_phone("+79380021575") == "+79380021575"


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("8 (938) 002-15-75", "+79380021575"),
        ("+1 (415) 555-2671", "+14155552671"),
        ("44.20.7946.0958", "+442079460958"),
    ],
)
def test_normalize_phone_removes_formatting(raw, expected):
    assert m._normalize_phone(raw) == expected


@pytest.mark.parametrize(
    "raw",
    ["+7CALLME", "123456789", "1" * 16, "++--"],
)
def test_normalize_phone_rejects_invalid_input(raw):
    with pytest.raises(ValueError):
        m._normalize_phone(raw)
