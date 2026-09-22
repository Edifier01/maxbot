"""Pinned, quiet PyMax 2.4.1 runtime and session-identity boundary."""

from __future__ import annotations

from dataclasses import dataclass
from importlib.metadata import version as package_version
from pathlib import Path
from secrets import token_hex
import sqlite3

from pymax import Client, ExtraConfig
from pymax.api.session.payloads import MobileUserAgentPayload
from pymax.auth import AuthFlow
from pymax.session.models import SessionInfo
from pymax.types.domain.sync import SyncState
from pymax.versions.catalog import VersionCatalog


PYMAX_REQUIRED_VERSION = "2.4.1"
PYMAX_TCP_HOST = "api2.oneme.ru"
PYMAX_TCP_PORT = 443


class PyMaxContractError(RuntimeError):
    """Raised when the installed PyMax package is outside the pinned contract."""


class PyMaxSessionMigrationError(RuntimeError):
    """Raised when a saved session cannot be made identity-stable offline."""


@dataclass(frozen=True, slots=True)
class PyMaxRuntimeInfo:
    package_version: str
    app_version: str
    tcp_host: str
    tcp_port: int
    remote_catalog: bool


@dataclass(frozen=True, slots=True)
class PyMaxSessionIdentity:
    device_id: str
    mt_instance_id: str
    user_agent: MobileUserAgentPayload
    migrated: bool


def assert_pymax_contract() -> None:
    installed = package_version("maxapi-python")
    if installed != PYMAX_REQUIRED_VERSION:
        raise PyMaxContractError(
            f"maxapi-python {installed} installed; required {PYMAX_REQUIRED_VERSION}"
        )


def build_extra_config(
    *,
    proxy: str | None,
    identity: PyMaxSessionIdentity | None,
) -> ExtraConfig:
    """Build the only ExtraConfig shape used by the application."""
    assert_pymax_contract()
    kwargs: dict[str, object] = {
        "host": PYMAX_TCP_HOST,
        "port": PYMAX_TCP_PORT,
        "use_ssl": True,
        "proxy": proxy,
        "reconnect": False,
        "relogin": False,
        "telemetry": False,
        "persist_session": True,
        "log_level": "WARNING",
    }
    if identity is not None:
        kwargs.update(
            {
                "device_id": identity.device_id,
                "mt_instance_id": identity.mt_instance_id,
                "user_agent": identity.user_agent,
            }
        )
    return ExtraConfig(**kwargs)


def inspect_pymax_runtime() -> PyMaxRuntimeInfo:
    assert_pymax_contract()
    catalog = VersionCatalog(remote=False)
    extra = build_extra_config(proxy=None, identity=None)
    return PyMaxRuntimeInfo(
        package_version=package_version("maxapi-python"),
        app_version=VersionCatalog.RECOMMENDED_APP_VERSION,
        tcp_host=extra.host,
        tcp_port=extra.port,
        remote_catalog=catalog.remote,
    )


def build_pymax_client(
    *,
    phone: str,
    work_dir: str,
    session_name: str,
    auth_flow: AuthFlow,
    proxy: str | None,
    identity: PyMaxSessionIdentity | None,
) -> Client:
    """Create one PyMax client with the bundled catalog and quiet lifecycle."""
    assert_pymax_contract()
    catalog = VersionCatalog(remote=False)
    return Client(
        phone=phone,
        work_dir=work_dir,
        session_name=session_name,
        auth_flow=auth_flow,
        extra_config=build_extra_config(proxy=proxy, identity=identity),
        app_version=VersionCatalog.RECOMMENDED_APP_VERSION,
        catalog=catalog,
    )


def _validated_identity(
    session: SessionInfo,
    *,
    migrated: bool,
) -> PyMaxSessionIdentity:
    if not session.token.strip():
        raise PyMaxSessionMigrationError("session_token_missing")
    if not session.device_id.strip():
        raise PyMaxSessionMigrationError("session_device_id_missing")
    if not session.mt_instance_id.strip():
        raise PyMaxSessionMigrationError("session_instance_id_missing")
    if session.user_agent is None:
        raise PyMaxSessionMigrationError("session_user_agent_missing")

    catalog = VersionCatalog(remote=False)
    app_version = VersionCatalog.RECOMMENDED_APP_VERSION
    fingerprint = catalog.resolve(app_version)
    if (
        session.user_agent.app_version != app_version
        or session.user_agent.build_number != fingerprint.build_number
    ):
        raise PyMaxSessionMigrationError("session_user_agent_version_mismatch")
    return PyMaxSessionIdentity(
        device_id=session.device_id,
        mt_instance_id=session.mt_instance_id,
        user_agent=session.user_agent,
        migrated=migrated,
    )


def _sync_snapshot(session: SessionInfo) -> dict[str, object]:
    return session.sync.model_dump()


class _LocalSessionStore:
    """Small synchronous adapter for the offline migration only.

    The migration runs under the profile client lock before any socket is
    opened. Keeping this bounded operation on sqlite3 avoids introducing an
    asynchronous database worker into the encrypted-session hot path while
    retaining PyMax's public SessionInfo and MobileUserAgentPayload models.
    """

    _BASE_SCHEMA = """
        CREATE TABLE IF NOT EXISTS sessions (
            token TEXT NOT NULL PRIMARY KEY,
            device_id TEXT NOT NULL,
            phone TEXT NOT NULL,
            mt_instance_id TEXT NOT NULL DEFAULT '',
            chats_sync INTEGER NOT NULL DEFAULT -1,
            contacts_sync INTEGER NOT NULL DEFAULT -1,
            drafts_sync INTEGER NOT NULL DEFAULT -1,
            presence_sync INTEGER NOT NULL DEFAULT -1,
            config_hash TEXT NOT NULL DEFAULT '',
            user_agent TEXT
        )
    """
    _COLUMNS = {
        "mt_instance_id": "TEXT NOT NULL DEFAULT ''",
        "chats_sync": "INTEGER NOT NULL DEFAULT -1",
        "contacts_sync": "INTEGER NOT NULL DEFAULT -1",
        "drafts_sync": "INTEGER NOT NULL DEFAULT -1",
        "presence_sync": "INTEGER NOT NULL DEFAULT -1",
        "config_hash": "TEXT NOT NULL DEFAULT ''",
        "user_agent": "TEXT",
    }

    def __init__(self, work_dir: Path, session_name: str) -> None:
        self.path = work_dir / session_name
        work_dir.mkdir(parents=True, exist_ok=True)

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.path)
        conn.row_factory = sqlite3.Row
        conn.execute(self._BASE_SCHEMA)
        columns = {
            row["name"]
            for row in conn.execute("PRAGMA table_info(sessions)").fetchall()
        }
        for name, definition in self._COLUMNS.items():
            if name not in columns:
                conn.execute(f"ALTER TABLE sessions ADD COLUMN {name} {definition}")
        conn.commit()
        return conn

    @staticmethod
    def _row_to_session(row: sqlite3.Row) -> SessionInfo:
        return SessionInfo(
            token=row["token"],
            device_id=row["device_id"],
            phone=row["phone"],
            mt_instance_id=row["mt_instance_id"] or "",
            user_agent=(
                MobileUserAgentPayload.model_validate_json(row["user_agent"])
                if row["user_agent"] is not None
                else None
            ),
            sync=SyncState(
                chats_sync=row["chats_sync"],
                contacts_sync=row["contacts_sync"],
                drafts_sync=row["drafts_sync"],
                presence_sync=row["presence_sync"],
                config_hash=row["config_hash"] or "",
            ),
        )

    async def load_session(self) -> SessionInfo | None:
        conn = self._connect()
        try:
            row = conn.execute(
                "SELECT token, device_id, phone, mt_instance_id, chats_sync, "
                "contacts_sync, drafts_sync, presence_sync, config_hash, user_agent "
                "FROM sessions LIMIT 1"
            ).fetchone()
            return self._row_to_session(row) if row is not None else None
        finally:
            conn.close()

    async def save_session(self, session: SessionInfo) -> None:
        conn = self._connect()
        try:
            conn.execute(
                "INSERT OR REPLACE INTO sessions ("
                "token, device_id, phone, mt_instance_id, chats_sync, contacts_sync, "
                "drafts_sync, presence_sync, config_hash, user_agent"
                ") VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    session.token,
                    session.device_id,
                    session.phone,
                    session.mt_instance_id,
                    session.sync.chats_sync,
                    session.sync.contacts_sync,
                    session.sync.drafts_sync,
                    session.sync.presence_sync,
                    session.sync.config_hash,
                    (
                        session.user_agent.model_dump_json(
                            by_alias=True,
                            exclude_none=True,
                        )
                        if session.user_agent is not None
                        else None
                    ),
                ),
            )
            conn.commit()
        finally:
            conn.close()

    async def close(self) -> None:
        return None


async def load_session_identity(
    work_dir: Path,
    session_name: str,
) -> PyMaxSessionIdentity:
    """Load an already complete identity without changing the session file."""
    store = _LocalSessionStore(work_dir, session_name)
    try:
        session = await store.load_session()
        if session is None:
            raise PyMaxSessionMigrationError("session_missing")
        return _validated_identity(session, migrated=False)
    finally:
        await store.close()


async def ensure_session_identity(
    work_dir: Path,
    session_name: str,
) -> PyMaxSessionIdentity:
    """Perform one offline identity migration before the first network call."""
    store = _LocalSessionStore(work_dir, session_name)
    try:
        session = await store.load_session()
        if session is None:
            raise PyMaxSessionMigrationError("session_missing")
        if not session.token.strip():
            raise PyMaxSessionMigrationError("session_token_missing")
        if not session.device_id.strip():
            raise PyMaxSessionMigrationError("session_device_id_missing")

        catalog = VersionCatalog(remote=False)
        app_version = VersionCatalog.RECOMMENDED_APP_VERSION
        fingerprint = catalog.resolve(app_version)
        mt_instance_id = session.mt_instance_id or token_hex(8)
        if not mt_instance_id.strip():
            raise PyMaxSessionMigrationError("session_instance_id_missing")
        if session.user_agent is None:
            generator = build_extra_config(proxy=None, identity=None)
            user_agent = generator.generate_user_agent(
                app_version,
                fingerprint.build_number,
            )
        else:
            user_agent = session.user_agent.model_copy(
                update={
                    "app_version": app_version,
                    "build_number": fingerprint.build_number,
                }
            )

        migrated = (
            session.mt_instance_id != mt_instance_id
            or session.user_agent != user_agent
        )
        if migrated:
            await store.save_session(
                session.model_copy(
                    update={
                        "mt_instance_id": mt_instance_id,
                        "user_agent": user_agent,
                    }
                )
            )

        check = await store.load_session()
        if check is None:
            raise PyMaxSessionMigrationError("session_identity_not_persisted")
        if (
            check.mt_instance_id != mt_instance_id
            or check.user_agent != user_agent
        ):
            raise PyMaxSessionMigrationError("session_identity_not_persisted")
        if (
            check.token != session.token
            or check.device_id != session.device_id
            or check.phone != session.phone
            or _sync_snapshot(check) != _sync_snapshot(session)
        ):
            raise PyMaxSessionMigrationError("session_fields_changed")
        return _validated_identity(check, migrated=migrated)
    finally:
        await store.close()
