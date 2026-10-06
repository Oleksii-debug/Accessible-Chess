from __future__ import annotations

"""Read-only application service for canonical ACSDB import-attempt reports.

This boundary deliberately exposes only already-persisted import audit state. It
never accepts a filesystem path, opens a source file, decodes a chess format, or
writes to ACSDB. Database ownership and import semantics remain in AcsDatabase
and the existing import services.
"""

from collections.abc import Mapping
from dataclasses import dataclass
import re

from .acsdb import AcsDatabase, IMPORT_ATTEMPT_STATUSES
from .report_paths import report_safe_name


_SQLITE_INTEGER_MAX = (1 << 63) - 1
_AGENT_PAGE_MAX = 100
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
_ROW_FIELDS = frozenset(
    {
        "id",
        "source_name",
        "source_format",
        "sha256",
        "started_at",
        "finished_at",
        "status",
        "source_id",
        "game_count",
        "warning_count",
        "error_message",
    }
)


class FormatImportReportError(ValueError):
    """Raised when persisted report state cannot be exposed safely."""


def _positive_id(value: object, *, name: str) -> int:
    if type(value) is not int:
        raise FormatImportReportError(f"{name} must be an integer")
    if value < 1 or value > _SQLITE_INTEGER_MAX:
        raise FormatImportReportError(f"{name} is outside the supported range")
    return value


def _bounded_count(value: object, *, name: str) -> int:
    if type(value) is not int:
        raise FormatImportReportError(f"{name} must be an integer")
    if value < 0 or value > _SQLITE_INTEGER_MAX:
        raise FormatImportReportError(f"{name} is outside the supported range")
    return value


def _text(
    value: object,
    *,
    name: str,
    maximum: int,
    allow_empty: bool = False,
) -> str:
    if type(value) is not str:
        raise FormatImportReportError(f"{name} must be text")
    if len(value) > maximum or (not allow_empty and not value):
        raise FormatImportReportError(f"{name} is outside the supported bound")
    if any(ord(char) < 0x20 and char not in "\t" for char in value):
        raise FormatImportReportError(f"{name} contains invalid control text")
    return value


def _optional_text(
    value: object,
    *,
    name: str,
    maximum: int,
) -> str | None:
    if value is None:
        return None
    return _text(value, name=name, maximum=maximum, allow_empty=True)


@dataclass(frozen=True, slots=True)
class ImportAttemptReportView:
    attempt_id: int
    source_name: str
    source_format: str
    source_sha256: str
    started_at: str
    finished_at: str | None
    status: str
    source_id: int | None
    game_count: int
    warning_count: int
    error_message: str | None

    def as_dict(self) -> dict[str, object]:
        return {
            "attemptId": self.attempt_id,
            "sourceName": self.source_name,
            "sourceFormat": self.source_format,
            "sourceSha256": self.source_sha256,
            "startedAt": self.started_at,
            "finishedAt": self.finished_at,
            "status": self.status,
            "sourceId": self.source_id,
            "gameCount": self.game_count,
            "warningCount": self.warning_count,
            "errorMessage": self.error_message,
        }


@dataclass(frozen=True, slots=True)
class ImportAttemptReportPage:
    items: tuple[ImportAttemptReportView, ...]
    has_more: bool
    next_before_id: int | None

    def as_dict(self) -> dict[str, object]:
        return {
            "items": [item.as_dict() for item in self.items],
            "hasMore": self.has_more,
            "nextBeforeId": self.next_before_id,
        }


def _view_from_row(row: Mapping[str, object]) -> ImportAttemptReportView:
    if frozenset(row) != _ROW_FIELDS:
        raise FormatImportReportError("import report row has unexpected schema")

    attempt_id = _positive_id(row["id"], name="attempt_id")
    source_name = report_safe_name(
        _text(row["source_name"], name="source_name", maximum=4096)
    )
    source_name = _text(
        source_name, name="safe source_name", maximum=1024
    )
    source_format = _text(
        row["source_format"], name="source_format", maximum=64
    )
    source_sha256 = _text(
        row["sha256"], name="source_sha256", maximum=64
    )
    if _SHA256_RE.fullmatch(source_sha256) is None:
        raise FormatImportReportError("source_sha256 is not canonical")

    started_at = _text(row["started_at"], name="started_at", maximum=96)
    finished_at = _optional_text(
        row["finished_at"], name="finished_at", maximum=96
    )
    status = _text(row["status"], name="status", maximum=16)
    if status not in IMPORT_ATTEMPT_STATUSES:
        raise FormatImportReportError("import report status is not canonical")

    source_id_value = row["source_id"]
    source_id = (
        None
        if source_id_value is None
        else _positive_id(source_id_value, name="source_id")
    )
    game_count = _bounded_count(row["game_count"], name="game_count")
    warning_count = _bounded_count(
        row["warning_count"], name="warning_count"
    )
    error_message = _optional_text(
        row["error_message"], name="error_message", maximum=4096
    )

    if status == "pending" and finished_at is not None:
        raise FormatImportReportError("pending import report is already finished")
    if status != "pending" and finished_at is None:
        raise FormatImportReportError("terminal import report has no finish time")

    return ImportAttemptReportView(
        attempt_id=attempt_id,
        source_name=source_name,
        source_format=source_format,
        source_sha256=source_sha256,
        started_at=started_at,
        finished_at=finished_at,
        status=status,
        source_id=source_id,
        game_count=game_count,
        warning_count=warning_count,
        error_message=error_message,
    )


class FormatImportReportService:
    """Expose bounded, path-safe ACSDB import audit state to application clients."""

    def __init__(self, database: AcsDatabase) -> None:
        if not isinstance(database, AcsDatabase):
            raise TypeError("database must be AcsDatabase")
        self._database = database

    def get(self, attempt_id: int) -> ImportAttemptReportView | None:
        canonical_id = _positive_id(attempt_id, name="attempt_id")
        row = self._database.get_import_attempt(canonical_id)
        if row is None:
            return None
        return _view_from_row(row)

    def list(
        self,
        *,
        status: str | None = None,
        before_id: int | None = None,
        limit: int = 20,
    ) -> ImportAttemptReportPage:
        if status is not None:
            if type(status) is not str or status not in IMPORT_ATTEMPT_STATUSES:
                raise FormatImportReportError("status is not canonical")
        cursor = (
            None
            if before_id is None
            else _positive_id(before_id, name="before_id")
        )
        if type(limit) is not int:
            raise FormatImportReportError("limit must be an integer")
        if limit < 1 or limit > _AGENT_PAGE_MAX:
            raise FormatImportReportError(
                f"limit must be between 1 and {_AGENT_PAGE_MAX}"
            )

        rows = self._database.list_import_attempts(
            status=status,
            before_id=cursor,
            limit=limit + 1,
        )
        has_more = len(rows) > limit
        visible = rows[:limit]
        items = tuple(_view_from_row(row) for row in visible)
        next_before_id = (
            items[-1].attempt_id if has_more and items else None
        )
        return ImportAttemptReportPage(
            items=items,
            has_more=has_more,
            next_before_id=next_before_id,
        )
