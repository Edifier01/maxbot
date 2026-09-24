"""A43 rendering rules: literal content is not silently rewritten."""

from __future__ import annotations

import random


def test_literal_json_and_explicit_brace_escape_survive_rendering() -> None:
    import main as m

    profile = {"phone": "+79990000000", "label": "Тест"}
    group = {"name": "Группа"}

    assert m._render_message('{"value":"a|b"}', profile, group) == (
        '{"value":"a|b"}'
    )
    assert m._render_message(r"\{a|b\}", profile, group) == "{a|b}"

    random.seed(4)
    assert m._render_message("{a|b}", profile, group) in {"a", "b"}
