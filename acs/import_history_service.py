from __future__ import annotations

"""Presentation-neutral import audit/history API for ACSDB.

This module deliberately hides sqlite rows and SQL from UI/application callers.
It treats the persisted ``import_attempts`` table as the single audit source of
truth and only follows ``source_id`` to immutable source provenance metadata.
"""

from dataclasses import dataclass
from typing import Literal

from .acsdb import AcsDatabase, IMPORT_ATTEMPT_STATUSES

ImportAttemptStatus = Literal["pending", "full", "warning", "damaged", "failed"]
_SQLITE_INTEGER_MAX = (1 << 63) - 1


def _exact_int(value: object, *, name: str) -> int:
    if type(value) is not int:
        raise TypeError(f"{name} must be an integer")
    return value


def _sqlite_record_id(value: object, *, name: str) -> int:
    """Validate an application id before it reaches SQLite's integer binder."""
    normalized = _exact_int(value, name=name)
    if normalized < 1:
        raise ValueError(f"{name} must be positive")
    if normalized > _SQLITE_INTEGER_MAX:
        raise ValueError(f"{name} exceeds SQLite integer range")
    return normalized


@dataclass(frozen=True, slots=True)
class ImportSourceRef:
    source_id: int
    source_name: str
    source_format: str
    sha256: str | None
    imported_at: str


@dataclass(frozen=True, slots=True)
class ImportAttemptItem:
    attempt_id: int
    source_name: str
    source_format: str
    sha256: str
    started_at: str
    finished_at: str | None
    status: ImportAttemptStatus
    game_count: int
    warning_count: int
    error_message: str | None
    source: ImportSourceRef | None


@dataclass(frozen=True, slots=True)
class ImportHistoryQuery:
    status: ImportAttemptStatus | None = None
    sha256: str | None = None
    source_format: str | None = None
    after_attempt_id: int | None = None
    limit: int = 50


@dataclass(frozen=True, slots=True)
class ImportHistoryPage:
    items: tuple[ImportAttemptItem, ...]
    next_after_attempt_id: int | None


class ImportHistoryService:
    """Read-only application contract for import reports and provenance."""

    def __init__(self, database: AcsDatabase) -> None:
        self._db = database

    def get(self, attempt_id: int) -> ImportAttemptItem | None:
        normalized_id = _sqlite_record_id(attempt_id, name="attempt_id")
        row = self._db.get_import_attempt(normalized_id)
        if row is None:
            return None
        source_id = row.get("source_id")
        if source_id is not None:
            source = self._db.get_source(int(source_id))
            if source is not None:
                row = dict(row)
                row.update(
                    linked_source_name=source["source_name"],
                    linked_source_format=source["source_format"],
                    linked_source_sha256=source["sha256"],
                    linked_source_imported_at=source["imported_at"],
                )
        return self._item(row)

    def search(self, query: ImportHistoryQuery | None = None) -> ImportHistoryPage:
        query = query or ImportHistoryQuery()
        if query.status is not None:
            if type(query.status) is not str:
                raise TypeError("status must be text")
            if query.status not in IMPORT_ATTEMPT_STATUSES:
                raise ValueError(f"Unsupported import attempt status: {query.status}")

        after_attempt_id: int | None = None
        if query.after_attempt_id is not None:
            after_attempt_id = _sqlite_record_id(
                query.after_attempt_id,
                name="after_attempt_id",
            )

        limit = _exact_int(query.limit, name="limit")
        if not 1 <= limit <= 200:
            raise ValueError("limit must be between 1 and 200")

        sha256 = query.sha256
        if sha256 is not None and type(sha256) is not str:
            raise TypeError("sha256 must be text")

        source_format = query.source_format
        if source_format is not None:
            if type(source_format) is not str:
                raise TypeError("source_format must be text")
            source_format = source_format.strip().lower() or None

        clauses: list[str] = []
        params: list[object] = []
        if query.status is not None:
            clauses.append("a.status=?")
            params.append(query.status)
        if sha256:
            clauses.append("a.sha256=?")
            params.append(sha256)
        if source_format:
            clauses.append("a.source_format=?")
            params.append(source_format)
        if after_attempt_id is not None:
            clauses.append("a.id < ?")
            params.append(after_attempt_id)

        sql = """
            SELECT a.*, s.source_name AS linked_source_name,
                   s.source_format AS linked_source_format,
                   s.sha256 AS linked_source_sha256,
                   s.imported_at AS linked_source_imported_at
            FROM import_attempts a
            LEFT JOIN sources s ON s.id = a.source_id
        """
        if clauses:
            sql += " WHERE " + " AND ".join(clauses)
        sql += " ORDER BY a.id DESC LIMIT ?"
        params.append(limit + 1)

        rows = [dict(row) for row in self._db.conn.execute(sql, params).fetchall()]
        has_more = len(rows) > limit
        rows = rows[:limit]
        items = tuple(self._item(row) for row in rows)
        cursor = items[-1].attempt_id if has_more and items else None
        return ImportHistoryPage(items=items, next_after_attempt_id=cursor)

    @staticmethod
    def _item(row: dict) -> ImportAttemptItem:
        source: ImportSourceRef | None = None
        source_id = row.get("source_id")
        if source_id is not None and row.get("linked_source_name") is not None:
            source = ImportSourceRef(
                source_id=int(source_id),
                source_name=row["linked_source_name"],
                source_format=row["linked_source_format"],
                sha256=row["linked_source_sha256"],
                imported_at=row["linked_source_imported_at"],
            )
        return ImportAttemptItem(
            attempt_id=int(row["id"]),
            source_name=row["source_name"],
            source_format=row["source_format"],
            sha256=row["sha256"],
            started_at=row["started_at"],
            finished_at=row.get("finished_at"),
            status=row["status"],
            game_count=int(row["game_count"]),
            warning_count=int(row["warning_count"]),
            error_message=row.get("error_message"),
            source=source,
        )