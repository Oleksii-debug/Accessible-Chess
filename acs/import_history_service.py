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
        if int(attempt_id) < 1:
            raise ValueError("attempt_id must be positive")
        row = self._db.get_import_attempt(int(attempt_id))
        return self._item(row) if row else None

    def search(self, query: ImportHistoryQuery | None = None) -> ImportHistoryPage:
        query = query or ImportHistoryQuery()
        if query.status is not None and query.status not in IMPORT_ATTEMPT_STATUSES:
            raise ValueError(f"Unsupported import attempt status: {query.status}")
        if query.after_attempt_id is not None and int(query.after_attempt_id) < 1:
            raise ValueError("after_attempt_id must be positive")
        if not 1 <= int(query.limit) <= 200:
            raise ValueError("limit must be between 1 and 200")

        clauses: list[str] = []
        params: list[object] = []
        if query.status is not None:
            clauses.append("a.status=?")
            params.append(query.status)
        if query.sha256:
            clauses.append("a.sha256=?")
            params.append(query.sha256)
        if query.source_format:
            clauses.append("a.source_format=?")
            params.append(query.source_format.lower())
        if query.after_attempt_id is not None:
            clauses.append("a.id < ?")
            params.append(int(query.after_attempt_id))

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
        params.append(int(query.limit) + 1)

        rows = [dict(row) for row in self._db.conn.execute(sql, params).fetchall()]
        has_more = len(rows) > int(query.limit)
        rows = rows[: int(query.limit)]
        items = tuple(self._item(row) for row in rows)
        cursor = items[-1].attempt_id if has_more and items else None
        return ImportHistoryPage(items=items, next_after_attempt_id=cursor)

    @staticmethod
    def _item(row: dict) -> ImportAttemptItem:
        source: ImportSourceRef | None = None
        source_id = row.get("source_id")
        if source_id is not None:
            if "linked_source_name" in row:
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
