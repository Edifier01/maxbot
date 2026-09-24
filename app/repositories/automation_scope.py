"""Persistence for one approved automation group and destination revision."""

from __future__ import annotations

from dataclasses import dataclass
import sqlite3


class AutomationScopeError(RuntimeError):
    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


@dataclass(frozen=True, slots=True)
class ScopeMigrationManifest:
    status: str
    code: str | None
    group_id: int | None


class AutomationScopeRepository:
    def __init__(self, conn: sqlite3.Connection) -> None:
        self.conn = conn

    def ensure_schema(self) -> None:
        self.conn.execute(
            """
            CREATE TABLE IF NOT EXISTS profile_automation_scope (
                profile_id INTEGER PRIMARY KEY,
                automation_group_id INTEGER,
                consent_state TEXT NOT NULL DEFAULT 'active',
                revision INTEGER NOT NULL DEFAULT 1
            )
            """
        )
        columns = {
            row[1]
            for row in self.conn.execute("PRAGMA table_info(groups)").fetchall()
        }
        if "destination_revision" not in columns:
            self.conn.execute(
                "ALTER TABLE groups ADD COLUMN destination_revision INTEGER NOT NULL DEFAULT 0"
            )
        if "destination_verified" not in columns:
            self.conn.execute(
                "ALTER TABLE groups ADD COLUMN destination_verified INTEGER NOT NULL DEFAULT 0"
            )
        self.conn.commit()

    def legacy_group_ids(self, profile_id: int) -> list[int]:
        try:
            rows = self.conn.execute(
                "SELECT group_id FROM group_profiles WHERE profile_id=? AND is_enabled=1 ORDER BY group_id",
                (int(profile_id),),
            ).fetchall()
        except sqlite3.OperationalError:
            return []
        return [int(row[0]) for row in rows]

    def migration_manifest(self, profile_id: int) -> ScopeMigrationManifest:
        groups = self.legacy_group_ids(profile_id)
        if len(groups) == 1:
            return ScopeMigrationManifest("READY", None, groups[0])
        if len(groups) > 1:
            return ScopeMigrationManifest("BLOCKED", "WORK_GROUP_SELECTION_REQUIRED", None)
        return ScopeMigrationManifest("BLOCKED", "WORK_GROUP_SELECTION_REQUIRED", None)

    def migrate_unambiguous_legacy_scopes(self) -> int:
        """Upgrade only profiles with exactly one enabled legacy membership.

        Existing scope rows are never rewritten: an explicit unselected or
        revoked state is an operator decision and must survive restart or
        schema migration. Profiles with multiple memberships stay without a
        selected scope until an explicit choice is made.
        """
        self.ensure_schema()
        try:
            rows = self.conn.execute(
                """
                SELECT gp.profile_id, MIN(gp.group_id) AS group_id
                FROM group_profiles gp
                LEFT JOIN profile_automation_scope s
                  ON s.profile_id = gp.profile_id
                WHERE gp.is_enabled=1 AND s.profile_id IS NULL
                GROUP BY gp.profile_id
                HAVING COUNT(*)=1
                ORDER BY gp.profile_id
                """
            ).fetchall()
        except sqlite3.OperationalError:
            return 0
        migrated = 0
        for row in rows:
            cursor = self.conn.execute(
                """
                INSERT OR IGNORE INTO profile_automation_scope(
                    profile_id, automation_group_id, consent_state, revision
                ) VALUES (?, ?, 'active', 1)
                """,
                (int(row["profile_id"]), int(row["group_id"])),
            )
            migrated += int(cursor.rowcount or 0)
        self.conn.commit()
        return migrated

    def scope_for(self, profile_id: int) -> sqlite3.Row:
        self.ensure_schema()
        row = self.conn.execute(
            "SELECT * FROM profile_automation_scope WHERE profile_id=?",
            (int(profile_id),),
        ).fetchone()
        if row is None:
            self.conn.execute(
                "INSERT INTO profile_automation_scope(profile_id) VALUES (?)",
                (int(profile_id),),
            )
            self.conn.commit()
            row = self.conn.execute(
                "SELECT * FROM profile_automation_scope WHERE profile_id=?",
                (int(profile_id),),
            ).fetchone()
        return row

    def select_work_group(self, profile_id: int, group_id: int) -> None:
        self.ensure_schema()
        if int(group_id) not in self.legacy_group_ids(profile_id):
            raise AutomationScopeError("WORK_GROUP_SELECTION_REQUIRED")
        self.conn.execute(
            "INSERT INTO profile_automation_scope(profile_id, automation_group_id, consent_state, revision) "
            "VALUES (?, ?, 'active', 1) "
            "ON CONFLICT(profile_id) DO UPDATE SET automation_group_id=excluded.automation_group_id, "
            "consent_state='active', revision=profile_automation_scope.revision+1",
            (int(profile_id), int(group_id)),
        )
        self.conn.commit()

    def migrate_legacy_scope(self, profile_id: int) -> int:
        manifest = self.migration_manifest(profile_id)
        if manifest.status != "READY" or manifest.group_id is None:
            raise AutomationScopeError(manifest.code or "WORK_GROUP_SELECTION_REQUIRED")
        self.select_work_group(profile_id, manifest.group_id)
        return manifest.group_id

    def destination_snapshot(self, group_id: int) -> dict[str, object]:
        self.ensure_schema()
        row = self.conn.execute(
            "SELECT id, invite_link, max_chat_id, destination_revision, destination_verified "
            "FROM groups WHERE id=?",
            (int(group_id),),
        ).fetchone()
        if row is None:
            raise AutomationScopeError("OBJECT_NOT_FOUND")
        return {
            "group_id": int(row["id"]),
            "invite_link": str(row["invite_link"] or ""),
            "max_chat_id": str(row["max_chat_id"] or ""),
            "destination_revision": int(row["destination_revision"]),
            "destination_verified": bool(row["destination_verified"]),
        }

    def update_destination(self, group_id: int, invite_link: str) -> None:
        self.ensure_schema()
        if not invite_link.strip():
            raise AutomationScopeError("DESTINATION_REVIEW_REQUIRED")
        cur = self.conn.execute(
            "UPDATE groups SET invite_link=?, max_chat_id='', destination_verified=0, "
            "destination_revision=destination_revision+1 WHERE id=?",
            (invite_link.strip(), int(group_id)),
        )
        if cur.rowcount != 1:
            raise AutomationScopeError("OBJECT_NOT_FOUND")
        self.conn.commit()

    def verify_destination(
        self,
        group_id: int,
        chat_id: str,
        *,
        expected_revision: int | None = None,
    ) -> None:
        if not str(chat_id).strip():
            raise AutomationScopeError("DESTINATION_REVIEW_REQUIRED")
        if expected_revision is None:
            cur = self.conn.execute(
                "UPDATE groups SET max_chat_id=?, destination_verified=1 WHERE id=?",
                (str(chat_id).strip(), int(group_id)),
            )
        else:
            cur = self.conn.execute(
                "UPDATE groups SET max_chat_id=?, destination_verified=1 "
                "WHERE id=? AND destination_revision=?",
                (str(chat_id).strip(), int(group_id), int(expected_revision)),
            )
        if cur.rowcount != 1:
            raise AutomationScopeError(
                "DESTINATION_REVIEW_REQUIRED"
                if expected_revision is not None
                else "OBJECT_NOT_FOUND"
            )
        self.conn.commit()

    def revoke_consent(self, profile_id: int) -> None:
        self.ensure_schema()
        self.conn.execute(
            "INSERT INTO profile_automation_scope(profile_id, consent_state, revision) VALUES (?, 'revoked', 1) "
            "ON CONFLICT(profile_id) DO UPDATE SET consent_state='revoked', "
            "revision=profile_automation_scope.revision+1",
            (int(profile_id),),
        )
        self.conn.commit()

    def unlink_work_group(self, profile_id: int) -> None:
        self.ensure_schema()
        self.conn.execute(
            "INSERT INTO profile_automation_scope(profile_id, automation_group_id, consent_state, revision) "
            "VALUES (?, NULL, 'unselected', 1) ON CONFLICT(profile_id) DO UPDATE SET "
            "automation_group_id=NULL, consent_state='unselected', "
            "revision=profile_automation_scope.revision+1",
            (int(profile_id),),
        )
        self.conn.commit()

    def require_external_action(
        self,
        profile_id: int,
        group_id: int,
        destination_revision: int,
    ) -> dict[str, object]:
        scope = self.scope_for(profile_id)
        if scope["consent_state"] != "active":
            raise AutomationScopeError("CONSENT_REVOKED")
        if scope["automation_group_id"] != int(group_id):
            raise AutomationScopeError("WORK_GROUP_SELECTION_REQUIRED")
        destination = self.destination_snapshot(group_id)
        if (
            int(destination["destination_revision"]) != int(destination_revision)
            or not destination["destination_verified"]
            or not destination["max_chat_id"]
        ):
            raise AutomationScopeError("DESTINATION_REVIEW_REQUIRED")
        return {
            "profile_id": int(profile_id),
            "group_id": int(group_id),
            "chat_id": destination["max_chat_id"],
            "destination_revision": destination["destination_revision"],
            "scope_revision": int(scope["revision"]),
        }
