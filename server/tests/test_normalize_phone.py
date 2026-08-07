"""Phone normalization used by groups API."""

from app.runtime import main as m


def test_normalize_phone_ru_8_prefix():
    assert m._normalize_phone("89380021575") == "+79380021575"


def test_normalize_phone_already_e164():
    assert m._normalize_phone("+79380021575") == "+79380021575"
