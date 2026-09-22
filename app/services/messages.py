"""Draft validation and immutable reusable message-library service."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from typing import Union

from app.repositories.message_sets import MessageSetRepository


class MessageValidationError(ValueError):
    """A draft/version reference is invalid or unavailable."""


@dataclass(frozen=True)
class DraftValidationResult:
    items: tuple[str, ...]
    errors: tuple[str, ...] = ()
    warnings: tuple[str, ...] = ()

    @property
    def valid(self) -> bool:
        return not self.errors and bool(self.items)


@dataclass(frozen=True)
class MessageVersion:
    scope: str
    version_id: str
    checksum: str
    items: tuple[str, ...]


class MessageLibrary:
    MAX_BYTES = 5 * 1024 * 1024
    MAX_ITEMS = 10_000

    def __init__(self, repository: MessageSetRepository | None = None) -> None:
        self.repository = repository

    def preview_draft(self, raw: Union[str, bytes]) -> DraftValidationResult:
        if isinstance(raw, bytes):
            if len(raw) > self.MAX_BYTES:
                raise MessageValidationError("draft is too large")
            try:
                text = raw.decode("utf-8-sig")
            except UnicodeDecodeError as exc:
                raise MessageValidationError("draft must be UTF-8") from exc
        else:
            text = str(raw)
            if len(text.encode("utf-8")) > self.MAX_BYTES:
                raise MessageValidationError("draft is too large")
            if text.startswith("\ufeff"):
                text = text[1:]
        items = tuple(
            line.strip()
            for line in text.splitlines()
            if line.strip() and not line.strip().startswith("#")
        )
        if not items:
            raise MessageValidationError("draft is empty")
        if len(items) > self.MAX_ITEMS:
            raise MessageValidationError("draft has too many items")
        warnings: list[str] = []
        if len(set(items)) != len(items):
            warnings.append("duplicate_texts_are_allowed")
        return DraftValidationResult(items=items, warnings=tuple(warnings))

    def publish_draft(
        self, scope: str, draft: DraftValidationResult | str | bytes
    ) -> MessageVersion:
        repository = self._repository()
        if isinstance(draft, DraftValidationResult):
            validation = draft
        else:
            validation = self.preview_draft(draft)
        if not validation.valid:
            raise MessageValidationError("draft validation failed")
        version_id, checksum = repository.publish(scope, validation.items)
        return MessageVersion(scope, version_id, checksum, validation.items)

    def current(self, scope: str) -> MessageVersion:
        repository = self._repository()
        row = repository.current(scope)
        if row is None:
            raise MessageValidationError("no current message version")
        return self._version(scope, str(row["version_id"]))

    def get_version(self, scope: str, version_id: str) -> MessageVersion:
        repository = self._repository()
        if repository.version(scope, version_id) is None:
            raise MessageValidationError("message version is unavailable")
        return self._version(scope, version_id)

    def immutable_items(self, scope: str, version_id: str) -> tuple[str, ...]:
        version = self.get_version(scope, version_id)
        return version.items

    def summary(self, scope: str, *, day_selection_count: int = 0) -> dict[str, object]:
        version = self.current(scope)
        return {
            "library_count": len(version.items),
            "day_selection_count": max(0, int(day_selection_count)),
            "version_id": version.version_id,
            "checksum": version.checksum,
        }

    def _version(self, scope: str, version_id: str) -> MessageVersion:
        repository = self._repository()
        row = repository.version(scope, version_id)
        if row is None:
            raise MessageValidationError("message version is unavailable")
        rows = repository.items(scope, version_id)
        items = tuple(str(item["text"]) for item in rows)
        checksum = hashlib.sha256("\n".join(items).encode("utf-8")).hexdigest()
        if checksum != str(row["checksum"]):
            raise MessageValidationError("message version checksum mismatch")
        return MessageVersion(scope, version_id, checksum, items)

    def _repository(self) -> MessageSetRepository:
        if self.repository is None:
            raise MessageValidationError("message repository is unavailable")
        return self.repository
