"""Fail-closed route resolution for persisted account proxy assignments."""

from __future__ import annotations

from dataclasses import dataclass
import sqlite3
from urllib.parse import urlparse

from app.repositories.connections import ConnectionRepository


@dataclass(frozen=True, slots=True)
class RouteSnapshot:
    connection_id: int
    version: int
    scheme: str
    host: str
    port: int
    credential_ref: str
    source: str


class RouteResolutionError(RuntimeError):
    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


def legacy_route_migration_report(
    catalog: ConnectionRepository,
) -> list[dict[str, object]]:
    """Report legacy direct routes without migrating, probing, or logging them.

    Server mode must not silently discard ``profiles.proxy``.  The report is
    intentionally actionable but credential-free: an operator must resolve the
    legacy route explicitly before a catalog assignment can be created.
    """
    try:
        rows = catalog.conn.execute(
            "SELECT id, proxy FROM profiles WHERE proxy IS NOT NULL AND TRIM(proxy) <> ''"
        ).fetchall()
    except sqlite3.OperationalError:
        return []

    report: list[dict[str, object]] = []
    for row in rows:
        profile_id = int(row["id"])
        try:
            assignment = catalog.assignment_for(profile_id)
        except sqlite3.OperationalError:
            assignment = None
        report.append(
            {
                "profile_id": profile_id,
                "status": "REVIEW_REQUIRED",
                "reason": "LEGACY_DIRECT_ROUTE",
                "assignment_present": assignment is not None,
                "requires_explicit_resolution": True,
                "writes": 0,
                "probe_calls": 0,
                "login_calls": 0,
            }
        )
    return report


def _snapshot(row: sqlite3.Row, *, source: str) -> RouteSnapshot:
    return RouteSnapshot(
        connection_id=int(row["id"]),
        version=int(row["version"]),
        scheme=str(row["scheme"]),
        host=str(row["host"]),
        port=int(row["port"]),
        credential_ref=str(row["credential_ref"]),
        source=source,
    )


def _legacy_direct_route(catalog: ConnectionRepository, profile_id: int) -> RouteSnapshot | None:
    """Return a local-only legacy route without exposing its credentials."""
    try:
        row = catalog.conn.execute(
            "SELECT proxy FROM profiles WHERE id=?", (int(profile_id),)
        ).fetchone()
    except sqlite3.OperationalError:
        return None
    raw = str(row[0] or "").strip() if row else ""
    if not raw:
        return None
    parsed = urlparse(raw)
    scheme = (parsed.scheme or "").lower()
    if scheme not in {"socks5", "http", "https"} or not parsed.hostname:
        raise RouteResolutionError("ROUTE_CONFLICT")
    return RouteSnapshot(
        connection_id=0,
        version=0,
        scheme=scheme,
        host=parsed.hostname,
        port=int(parsed.port or (1080 if scheme == "socks5" else 8080)),
        credential_ref=f"legacy_profile:{int(profile_id)}",
        source="legacy_profile",
    )


def resolve_route(
    scope: object,
    profile_id: int,
    group_id: int | None,
    purpose: str,
    *,
    catalog: ConnectionRepository,
    server_mode: bool = True,
) -> RouteSnapshot:
    """Resolve one stable route; never silently fall back or reshuffle.

    ``scope`` and ``purpose`` are carried by the caller as part of the lease
    contract.  This repository is already scope-local, so the resolver does
    not open another database or reuse a process-global cache.
    """
    del scope
    if int(profile_id) < 1 or not purpose.strip():
        raise RouteResolutionError("ROUTE_MISSING")
    catalog.ensure_schema()

    profile_groups = catalog.profile_groups(profile_id)
    if group_id is None:
        if len(profile_groups) != 1:
            raise RouteResolutionError("WORK_GROUP_SELECTION_REQUIRED")
        group_id = profile_groups[0]
    elif profile_groups and int(group_id) not in profile_groups:
        raise RouteResolutionError("ROUTE_CONFLICT")
    group_id = int(group_id)

    assignment = catalog.assignment_for(profile_id)
    if assignment is not None:
        if int(assignment["automation_group_id"]) != group_id:
            raise RouteResolutionError("ROUTE_CONFLICT")
        row = catalog.conn.execute(
            "SELECT c.* FROM connections c "
            "JOIN connection_group_pool p ON p.connection_id=c.id "
            "WHERE p.group_id=? AND c.id=?",
            (group_id, int(assignment["connection_id"])),
        ).fetchone()
        if row is None:
            raise RouteResolutionError("ROUTE_CONFLICT")
        if not bool(row["enabled"]):
            raise RouteResolutionError("ROUTE_DISABLED")
        return _snapshot(row, source="persisted_assignment")

    if server_mode and _legacy_direct_route(catalog, profile_id) is not None:
        raise RouteResolutionError("ROUTE_CONFLICT")
    if not server_mode:
        legacy = _legacy_direct_route(catalog, profile_id)
        if legacy is not None:
            return legacy

    candidates = [row for row in catalog.group_connections(group_id) if bool(row["enabled"])]
    if not candidates:
        if catalog.group_connections(group_id):
            raise RouteResolutionError("ROUTE_DISABLED")
        raise RouteResolutionError("ROUTE_MISSING")
    selected = candidates[0]
    catalog.assign_route(
        profile_id,
        group_id,
        int(selected["id"]),
        source="initial_least_used",
    )
    catalog.bump_assignment_use_count(int(selected["id"]))
    return _snapshot(selected, source="initial_assignment")
