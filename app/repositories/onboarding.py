"""Persistence helpers for self-service group onboarding."""

from __future__ import annotations

from datetime import datetime, timezone
import sqlite3
import unicodedata


MAX_FULL_NAME_LENGTH = 180


def normalize_full_name(value: str) -> str:
    raw = str(value or "")
    if any(unicodedata.category(char) in {"Cc", "Cf"} for char in raw):
        raise ValueError("FULL_NAME_INVALID")
    name = " ".join(raw.split())
    if not name:
        raise ValueError("FULL_NAME_REQUIRED")
    if len(name) > MAX_FULL_NAME_LENGTH:
        raise ValueError("FULL_NAME_TOO_LONG")
    return name


def token_hash(token: str) -> str:
    import hashlib

    return hashlib.sha256(token.encode("ascii")).hexdigest()


class OnboardingRepository:
    def __init__(self, conn: sqlite3.Connection) -> None:
        self.conn = conn

    def ensure_schema(self) -> None:
        profile_columns = {
            row[1] for row in self.conn.execute("PRAGMA table_info(profiles)")
        }
        if "full_name" not in profile_columns:
            self.conn.execute(
                "ALTER TABLE profiles ADD COLUMN full_name TEXT NOT NULL DEFAULT ''"
            )
        for statement in (
            """
            CREATE TABLE IF NOT EXISTS group_onboarding_invites (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                group_id INTEGER NOT NULL REFERENCES groups(id) ON DELETE CASCADE,
                token_hash TEXT NOT NULL UNIQUE,
                token_ciphertext TEXT NOT NULL,
                is_active INTEGER NOT NULL DEFAULT 1,
                created_by INTEGER,
                created_at TEXT NOT NULL,
                expires_at TEXT NOT NULL,
                max_uses INTEGER,
                uses_count INTEGER NOT NULL DEFAULT 0,
                revoked_at TEXT
            )
            """,
            "CREATE UNIQUE INDEX IF NOT EXISTS uq_group_onboarding_active ON group_onboarding_invites(group_id) WHERE is_active=1",
            "CREATE INDEX IF NOT EXISTS idx_group_onboarding_expiry ON group_onboarding_invites(is_active, expires_at)",
            """
            CREATE TABLE IF NOT EXISTS onboarding_sessions (
                id TEXT PRIMARY KEY,
                session_token_hash TEXT NOT NULL UNIQUE,
                invite_id INTEGER NOT NULL REFERENCES group_onboarding_invites(id),
                phone TEXT,
                full_name TEXT,
                consent_at TEXT,
                state TEXT NOT NULL,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                expires_at TEXT NOT NULL,
                last_error_code TEXT,
                auth_attempt_id TEXT,
                auth_revision INTEGER NOT NULL DEFAULT 0,
                max_user_id TEXT,
                profile_id INTEGER,
                created_profile INTEGER NOT NULL DEFAULT 0,
                promotion_state TEXT NOT NULL DEFAULT 'none',
                name_confirmation_required INTEGER NOT NULL DEFAULT 0
            )
            """,
            "CREATE INDEX IF NOT EXISTS idx_onboarding_sessions_expiry ON onboarding_sessions(state, expires_at)",
            """
            CREATE TABLE IF NOT EXISTS onboarding_consents (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                session_id TEXT NOT NULL UNIQUE REFERENCES onboarding_sessions(id),
                profile_id INTEGER NOT NULL REFERENCES profiles(id),
                group_id INTEGER NOT NULL REFERENCES groups(id),
                invite_id INTEGER NOT NULL REFERENCES group_onboarding_invites(id),
                source TEXT NOT NULL DEFAULT 'self_service_invite',
                accepted_at TEXT NOT NULL
            )
            """,
        ):
            self.conn.execute(statement)

    def create_invite(
        self,
        group_id: int,
        token_hash_value: str,
        token_ciphertext: str,
        created_at: str,
        expires_at: str,
        max_uses: int | None,
        created_by: int | None = None,
    ) -> int:
        self.ensure_schema()
        owns_transaction = not self.conn.in_transaction
        savepoint = "onboarding_create_invite"
        self.conn.execute("BEGIN IMMEDIATE" if owns_transaction else f"SAVEPOINT {savepoint}")
        try:
            group = self.conn.execute(
                "SELECT is_active, max_chat_id, destination_verified, invite_link "
                "FROM groups WHERE id=?",
                (int(group_id),),
            ).fetchone()
            if (
                group is None
                or not int(group["is_active"] or 0)
                or not str(group["max_chat_id"] or "").strip()
                or not int(group["destination_verified"] or 0)
                or not str(group["invite_link"] or "").strip()
            ):
                raise ValueError("DESTINATION_REVIEW_REQUIRED")
            self.conn.execute(
                "UPDATE group_onboarding_invites SET is_active=0, revoked_at=? "
                "WHERE group_id=? AND is_active=1",
                (created_at, int(group_id)),
            )
            cursor = self.conn.execute(
                "INSERT INTO group_onboarding_invites "
                "(group_id, token_hash, token_ciphertext, created_by, created_at, expires_at, max_uses) "
                "VALUES (?, ?, ?, ?, ?, ?, ?)",
                (
                    int(group_id), token_hash_value, token_ciphertext, created_by,
                    created_at, expires_at, max_uses,
                ),
            )
            invite_id = int(cursor.lastrowid)
            if owns_transaction:
                self.conn.commit()
            else:
                self.conn.execute(f"RELEASE SAVEPOINT {savepoint}")
            return invite_id
        except BaseException:
            if owns_transaction:
                self.conn.rollback()
            else:
                self.conn.execute(f"ROLLBACK TO SAVEPOINT {savepoint}")
                self.conn.execute(f"RELEASE SAVEPOINT {savepoint}")
            raise

    def get_active_invite(self, group_id: int) -> sqlite3.Row | None:
        return self.conn.execute(
            "SELECT * FROM group_onboarding_invites WHERE group_id=? AND is_active=1",
            (int(group_id),),
        ).fetchone()

    def get_invite_by_hash(self, digest: str) -> sqlite3.Row | None:
        return self.conn.execute(
            "SELECT i.*, g.name AS group_name, g.invite_link, g.max_chat_id, "
            "g.destination_verified, g.is_active AS group_is_active "
            "FROM group_onboarding_invites i JOIN groups g ON g.id=i.group_id "
            "WHERE i.token_hash=?",
            (str(digest),),
        ).fetchone()

    def revoke_invite(self, group_id: int, now: str) -> bool:
        cursor = self.conn.execute(
            "UPDATE group_onboarding_invites SET is_active=0, revoked_at=? "
            "WHERE group_id=? AND is_active=1",
            (now, int(group_id)),
        )
        self.conn.commit()
        return cursor.rowcount > 0

    def create_session(
        self,
        session_id: str,
        session_token_hash: str,
        invite_id: int,
        now: str,
        expires_at: str,
    ) -> None:
        self.conn.execute(
            "INSERT INTO onboarding_sessions "
            "(id, session_token_hash, invite_id, state, created_at, updated_at, expires_at) "
            "VALUES (?, ?, ?, 'created', ?, ?, ?)",
            (session_id, session_token_hash, int(invite_id), now, now, expires_at),
        )
        self.conn.commit()

    def get_session(self, session_id: str) -> sqlite3.Row | None:
        return self.conn.execute(
            "SELECT s.*, i.group_id, i.is_active AS invite_active, i.expires_at AS invite_expires_at, "
            "i.max_uses, i.uses_count, g.name AS group_name, g.invite_link, g.max_chat_id, "
            "g.destination_verified, g.is_active AS group_is_active "
            "FROM onboarding_sessions s "
            "JOIN group_onboarding_invites i ON i.id=s.invite_id "
            "JOIN groups g ON g.id=i.group_id WHERE s.id=?",
            (str(session_id),),
        ).fetchone()

    def get_session_by_token_hash(self, digest: str) -> sqlite3.Row | None:
        row = self.conn.execute(
            "SELECT id FROM onboarding_sessions WHERE session_token_hash=?",
            (str(digest),),
        ).fetchone()
        return self.get_session(str(row["id"])) if row else None

    def update_session(self, session_id: str, **fields: object) -> None:
        allowed = {
            "phone", "full_name", "consent_at", "state", "updated_at",
            "last_error_code", "auth_attempt_id", "auth_revision", "max_user_id",
            "profile_id", "created_profile", "promotion_state",
            "name_confirmation_required",
        }
        if not fields or not set(fields).issubset(allowed):
            raise ValueError("ONBOARDING_FIELDS_INVALID")
        assignments = ", ".join(f"{key}=?" for key in fields)
        self.conn.execute(
            f"UPDATE onboarding_sessions SET {assignments} WHERE id=?",
            (*fields.values(), str(session_id)),
        )
        self.conn.commit()

    def record_successful_use(
        self, session_id: str, group_id: int, profile_id: int, *, now: str | None = None
    ) -> bool:
        """Atomically link a profile and consume the invite once for this session."""
        timestamp = now or datetime.now(timezone.utc).isoformat(timespec="seconds")
        owns_transaction = not self.conn.in_transaction
        savepoint = "onboarding_finalize"
        self.conn.execute("BEGIN IMMEDIATE" if owns_transaction else f"SAVEPOINT {savepoint}")
        try:
            session = self.conn.execute(
                "SELECT s.state, s.invite_id, s.consent_at, i.is_active, i.expires_at, i.max_uses, i.uses_count "
                "FROM onboarding_sessions s JOIN group_onboarding_invites i ON i.id=s.invite_id "
                "WHERE s.id=?",
                (str(session_id),),
            ).fetchone()
            if session is None:
                raise ValueError("ONBOARDING_SESSION_NOT_FOUND")
            if session["state"] == "completed":
                if owns_transaction:
                    self.conn.commit()
                else:
                    self.conn.execute(f"RELEASE SAVEPOINT {savepoint}")
                return False
            if (
                not int(session["is_active"])
                or str(session["expires_at"]) <= timestamp
                or (session["max_uses"] is not None and int(session["uses_count"]) >= int(session["max_uses"]))
            ):
                raise ValueError("INVITE_UNAVAILABLE")
            already_linked = self.conn.execute(
                "SELECT 1 FROM group_profiles WHERE group_id=? AND profile_id=?",
                (int(group_id), int(profile_id)),
            ).fetchone() is not None
            if not already_linked:
                self.conn.execute(
                    "INSERT INTO group_profiles (group_id, profile_id, order_index) "
                    "SELECT ?, ?, COALESCE(MAX(order_index), -1)+1 FROM group_profiles WHERE group_id=?",
                    (int(group_id), int(profile_id), int(group_id)),
                )
            self.conn.execute(
                "INSERT OR IGNORE INTO onboarding_consents "
                "(session_id, profile_id, group_id, invite_id, accepted_at) "
                "VALUES (?, ?, ?, ?, ?)",
                (str(session_id), int(profile_id), int(group_id), int(session["invite_id"]), str(session["consent_at"] or timestamp)),
            )
            self.conn.execute(
                "UPDATE group_onboarding_invites SET uses_count=uses_count+1 "
                "WHERE id=? AND is_active=1 AND (max_uses IS NULL OR uses_count<max_uses)",
                (int(session["invite_id"]),),
            )
            if self.conn.execute("SELECT changes()").fetchone()[0] != 1:
                raise ValueError("INVITE_UNAVAILABLE")
            self.conn.execute(
                "UPDATE onboarding_sessions SET state='completed', updated_at=?, profile_id=?, promotion_state='complete' WHERE id=?",
                (timestamp, int(profile_id), str(session_id)),
            )
            if owns_transaction:
                self.conn.commit()
            else:
                self.conn.execute(f"RELEASE SAVEPOINT {savepoint}")
            return True
        except BaseException:
            if owns_transaction:
                self.conn.rollback()
            else:
                self.conn.execute(f"ROLLBACK TO SAVEPOINT {savepoint}")
                self.conn.execute(f"RELEASE SAVEPOINT {savepoint}")
            raise
