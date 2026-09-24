from __future__ import annotations

import sqlite3

from app.repositories.onboarding import OnboardingRepository, normalize_full_name


def _db() -> sqlite3.Connection:
    c = sqlite3.connect(":memory:")
    c.row_factory = sqlite3.Row
    c.executescript(
        "CREATE TABLE profiles (id INTEGER PRIMARY KEY, phone TEXT UNIQUE, label TEXT DEFAULT '', status TEXT DEFAULT 'pending');"
        "CREATE TABLE groups (id INTEGER PRIMARY KEY, name TEXT, invite_link TEXT, max_chat_id TEXT, destination_verified INTEGER DEFAULT 0, is_active INTEGER DEFAULT 1);"
        "CREATE TABLE group_profiles (group_id INTEGER, profile_id INTEGER, order_index INTEGER, is_enabled INTEGER DEFAULT 1, PRIMARY KEY(group_id, profile_id));"
    )
    c.execute("INSERT INTO groups (id, name, invite_link, max_chat_id, destination_verified) VALUES (1, 'G', 'https://max.ru/join/a', '55', 1)")
    return c


def test_onboarding_schema_adds_full_name_and_unique_active_invite():
    c = _db()
    repo = OnboardingRepository(c)
    repo.ensure_schema()
    columns = {row[1] for row in c.execute("PRAGMA table_info(profiles)")}
    assert "full_name" in columns
    c.execute("INSERT INTO group_onboarding_invites (group_id, token_hash, token_ciphertext, created_at, expires_at) VALUES (1, 'hash1', 'cipher', 'now', 'later')")
    try:
        c.execute("INSERT INTO group_onboarding_invites (group_id, token_hash, token_ciphertext, created_at, expires_at) VALUES (1, 'hash2', 'cipher', 'now', 'later')")
    except sqlite3.IntegrityError:
        pass
    else:
        raise AssertionError("a group must have at most one active invite")


def test_invite_use_count_is_atomic_and_once_per_session():
    c = _db()
    repo = OnboardingRepository(c)
    repo.ensure_schema()
    invite_id = repo.create_invite(1, "hash", "cipher", "2026-09-24T00:00:00+00:00", "2026-10-01T00:00:00+00:00", None)
    c.execute("INSERT INTO profiles (id, phone, status) VALUES (1, '+79991234567', 'active')")
    c.execute("INSERT INTO onboarding_sessions (id, session_token_hash, invite_id, state, created_at, updated_at, expires_at) VALUES ('s1', 'session-hash', ?, 'finalizing', 'now', 'now', 'later')", (invite_id,))
    assert repo.record_successful_use("s1", 1, 1) is True
    assert repo.record_successful_use("s1", 1, 1) is False
    assert c.execute("SELECT uses_count FROM group_onboarding_invites WHERE id=?", (invite_id,)).fetchone()[0] == 1
    assert c.execute("SELECT COUNT(*) FROM group_profiles WHERE group_id=1 AND profile_id=1").fetchone()[0] == 1


def test_invite_limit_counts_a_separate_session_for_existing_group_profile():
    c = _db()
    repo = OnboardingRepository(c)
    repo.ensure_schema()
    invite_id = repo.create_invite(1, "hash", "cipher", "2026-09-24T00:00:00+00:00", "2026-10-01T00:00:00+00:00", 1)
    c.execute("INSERT INTO profiles (id, phone, status) VALUES (1, '+79991234567', 'active')")
    c.execute("INSERT INTO group_profiles (group_id, profile_id, order_index) VALUES (1, 1, 0)")
    for session_id in ("first", "second"):
        c.execute(
            "INSERT INTO onboarding_sessions (id, session_token_hash, invite_id, state, created_at, updated_at, expires_at) "
            "VALUES (?, ?, ?, 'finalizing', 'now', 'now', 'later')",
            (session_id, f"{session_id}-hash", invite_id),
        )
    assert repo.record_successful_use("first", 1, 1) is True
    assert repo.record_successful_use("first", 1, 1) is False
    try:
        repo.record_successful_use("second", 1, 1)
    except ValueError as exc:
        assert str(exc) == "INVITE_UNAVAILABLE"
    else:
        raise AssertionError("each distinct successful session must consume one use")
    assert c.execute("SELECT uses_count FROM group_onboarding_invites WHERE id=?", (invite_id,)).fetchone()[0] == 1


def test_full_name_normalization_rejects_control_characters():
    assert normalize_full_name("  Иванов   Иван  ") == "Иванов Иван"
    try:
        normalize_full_name("Иванов\nИван")
    except ValueError:
        pass
    else:
        raise AssertionError("control characters must be rejected")
