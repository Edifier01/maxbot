"""Connection catalog summaries and bounded, non-MAX proxy probes."""

from __future__ import annotations

import json
import sqlite3
import threading
from collections.abc import Callable, Mapping
from datetime import datetime, timezone
from dataclasses import dataclass

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from app.repositories.connections import ConnectionRepository


router = APIRouter(tags=["connections"])


class ConnectionConflict(RuntimeError):
    pass


class ProbeAlreadyRunning(RuntimeError):
    pass


@dataclass(frozen=True)
class ConnectionProbeInput:
    connection_id: int
    route_version: int
    result: dict[str, object]


class ConnectionCatalog:
    def __init__(self, repository: ConnectionRepository) -> None:
        self.repository = repository
        self.repository.ensure_schema()
        self._probe_locks: dict[int, threading.Lock] = {}
        self._probe_locks_guard = threading.Lock()
        self._ensure_probe_schema()

    def _ensure_probe_schema(self) -> None:
        self.repository.conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS connection_probe_history (
                id INTEGER PRIMARY KEY,
                connection_id INTEGER NOT NULL,
                route_version INTEGER NOT NULL,
                checked_at TEXT NOT NULL,
                ok INTEGER NOT NULL,
                error_code TEXT,
                stages_json TEXT NOT NULL,
                otp_calls INTEGER NOT NULL DEFAULT 0
            );
            CREATE INDEX IF NOT EXISTS idx_connection_probe_history
                ON connection_probe_history(connection_id, checked_at DESC);
            """
        )
        self.repository.conn.commit()

    def list_summaries(self, *, role: str) -> list[dict[str, object]]:
        del role  # summaries never expose credential references to any role
        rows = self.repository.conn.execute(
            """
            SELECT c.id, c.version, c.scheme, c.host, c.port, c.enabled,
                   c.use_count, c.sort_order,
                   COUNT(DISTINCT a.profile_id) AS assigned_profile_count,
                   MAX(h.checked_at) AS last_probe_at
            FROM connections c
            LEFT JOIN profile_route_assignments a ON a.connection_id=c.id
            LEFT JOIN connection_probe_history h ON h.connection_id=c.id
            GROUP BY c.id, c.version, c.scheme, c.host, c.port,
                     c.enabled, c.use_count, c.sort_order
            ORDER BY c.sort_order, c.id
            """
        ).fetchall()
        return [
            {
                "connection_id": int(row["id"]),
                "version": int(row["version"]),
                "scheme": str(row["scheme"]),
                "host": str(row["host"]),
                "port": int(row["port"]),
                "enabled": bool(row["enabled"]),
                "use_count": int(row["use_count"]),
                "sort_order": int(row["sort_order"]),
                "assigned_profile_count": int(row["assigned_profile_count"]),
                "last_probe_at": row["last_probe_at"],
                "credential_state": "configured",
            }
            for row in rows
        ]

    def update_connection(
        self,
        connection_id: int,
        *,
        expected_version: int,
        scheme: str | None = None,
        host: str | None = None,
        port: int | None = None,
        enabled: bool | None = None,
    ) -> dict[str, object]:
        current = self.repository.conn.execute(
            "SELECT * FROM connections WHERE id=?", (int(connection_id),)
        ).fetchone()
        if current is None:
            raise ConnectionConflict("connection_missing")
        if int(current["version"]) != int(expected_version):
            raise ConnectionConflict("route_version_conflict")
        values = {
            "scheme": scheme if scheme is not None else current["scheme"],
            "host": host if host is not None else current["host"],
            "port": int(port) if port is not None else int(current["port"]),
            "enabled": int(enabled) if enabled is not None else int(current["enabled"]),
        }
        cursor = self.repository.conn.execute(
            "UPDATE connections SET scheme=?, host=?, port=?, enabled=?, version=version+1 "
            "WHERE id=? AND version=?",
            (
                values["scheme"], values["host"], values["port"], values["enabled"],
                int(connection_id), int(expected_version),
            ),
        )
        if cursor.rowcount != 1:
            raise ConnectionConflict("route_version_conflict")
        self.repository.conn.commit()
        return next(
            item for item in self.list_summaries(role="admin")
            if item["connection_id"] == int(connection_id)
        )

    def record_probe(
        self,
        connection_id: int,
        *,
        route_version: int,
        result: Mapping[str, object],
    ) -> dict[str, object]:
        row = self.repository.conn.execute(
            "SELECT version FROM connections WHERE id=?", (int(connection_id),)
        ).fetchone()
        if row is None:
            raise ConnectionConflict("connection_missing")
        stages = result.get("stages")
        safe_stages = dict(stages) if isinstance(stages, Mapping) else {}
        checked_at = datetime.now(timezone.utc).isoformat(timespec="seconds")
        otp_calls = int(result.get("otp_calls", 0) or 0)
        self.repository.conn.execute(
            "INSERT INTO connection_probe_history "
            "(connection_id, route_version, checked_at, ok, error_code, stages_json, otp_calls) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            (
                int(connection_id),
                int(route_version),
                checked_at,
                int(bool(result.get("ok"))),
                str(result["error_code"]) if result.get("error_code") else None,
                json.dumps(safe_stages, sort_keys=True),
                max(0, otp_calls),
            ),
        )
        self.repository.conn.commit()
        return {
            "connection_id": int(connection_id),
            "route_version": int(route_version),
            "valid_for_route_version": int(route_version) == int(row["version"]),
            "checked_at": checked_at,
            "ok": bool(result.get("ok")),
            "error_code": result.get("error_code"),
            "stages": safe_stages,
            "otp_calls": max(0, otp_calls),
        }

    def probe_history(self, connection_id: int, *, limit: int = 20) -> list[dict[str, object]]:
        bounded = min(max(int(limit), 1), 100)
        rows = self.repository.conn.execute(
            "SELECT * FROM connection_probe_history WHERE connection_id=? "
            "ORDER BY checked_at DESC, id DESC LIMIT ?",
            (int(connection_id), bounded),
        ).fetchall()
        out: list[dict[str, object]] = []
        for row in rows:
            try:
                stages = json.loads(row["stages_json"])
            except (TypeError, ValueError, json.JSONDecodeError):
                stages = {}
            out.append(
                {
                    "id": int(row["id"]),
                    "connection_id": int(row["connection_id"]),
                    "route_version": int(row["route_version"]),
                    "checked_at": str(row["checked_at"]),
                    "ok": bool(row["ok"]),
                    "error_code": row["error_code"],
                    "stages": stages if isinstance(stages, dict) else {},
                    "otp_calls": int(row["otp_calls"]),
                }
            )
        return out

    def run_probe_once(
        self,
        connection_id: int,
        *,
        route_version: int,
        probe: Callable[[], Mapping[str, object]],
    ) -> dict[str, object]:
        with self._probe_locks_guard:
            lock = self._probe_locks.setdefault(int(connection_id), threading.Lock())
        if not lock.acquire(blocking=False):
            raise ProbeAlreadyRunning("probe_already_running")
        try:
            raw = dict(probe())
            return self.record_probe(
                connection_id, route_version=route_version, result=raw
            )
        except Exception:
            return self.record_probe(
                connection_id,
                route_version=route_version,
                result={
                    "ok": False,
                    "error_code": "PROBE_FAILED",
                    "stages": {"probe": "FAIL"},
                    "otp_calls": 0,
                },
            )
        finally:
            lock.release()


@router.get("/api/connections")
async def get_connections():
    from app.runtime import main as m

    with m._conn() as connection:
        catalog = ConnectionCatalog(ConnectionRepository(connection))
        return {"items": catalog.list_summaries(role="user")}


class ConnectionUpdateIn(BaseModel):
    expected_version: int
    scheme: str | None = None
    host: str | None = None
    port: int | None = None
    enabled: bool | None = None


@router.patch("/api/connections/{connection_id}")
async def update_connection(connection_id: int, body: ConnectionUpdateIn):
    from app.runtime import main as m

    with m._conn() as connection:
        catalog = ConnectionCatalog(ConnectionRepository(connection))
        try:
            return catalog.update_connection(
                connection_id,
                expected_version=body.expected_version,
                scheme=body.scheme,
                host=body.host,
                port=body.port,
                enabled=body.enabled,
            )
        except ConnectionConflict as exc:
            raise HTTPException(409, str(exc)) from exc
