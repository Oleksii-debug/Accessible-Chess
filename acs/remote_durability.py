"""Canonical D10 durability adapter for live remote-session networking.

This module is intentionally thin.  It does not define a second persistence
format: it loads the existing :class:`EducationWorkspaceStore`, delegates remote
checkpoint validation/publication to ``education_workspace.checkpoint_remote_session``,
and publishes the resulting workspace with the store's file-level CAS.
"""
from __future__ import annotations

from dataclasses import dataclass
import re

from . import education_workspace as ew
from . import education_workspace_store as ews
from .remote_session import RemoteSessionLog
from .teaching_session import LessonSession


_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$")


class RemoteDurabilityError(RuntimeError):
    """Sanitized remote durability failure."""


@dataclass(frozen=True, slots=True)
class RemoteDurablePoint:
    session_id: str
    last_sequence: int
    snapshot_digest: str
    session_revision: int
    ledger_revision: int
    store_revision: str
    closed_at: str | None

    @property
    def closed(self) -> bool:
        return self.closed_at is not None


class D10RemoteDurability:
    """Publish one remote session through the canonical D10 workspace authority."""

    def __init__(
        self,
        store: ews.EducationWorkspaceStore,
        lesson_session: LessonSession,
        *,
        record_id: str,
        started_at: str,
    ) -> None:
        if type(store) is not ews.EducationWorkspaceStore:
            raise RemoteDurabilityError("remote durable store is unavailable")
        if type(lesson_session) is not LessonSession:
            raise RemoteDurabilityError("remote lesson session is unavailable")
        self._store = store
        self._lesson_session = lesson_session
        self._record_id = _id(record_id, "remote checkpoint record id")
        self._started_at = _text(started_at, "remote session started_at")

    @property
    def session_id(self) -> str:
        return self._lesson_session.session_id

    def current(self) -> RemoteDurablePoint | None:
        loaded = self._load()
        record = self._find_record(loaded.workspace)
        if record is None:
            return None
        return self._point(loaded, record)

    def checkpoint(
        self,
        log: RemoteSessionLog,
        *,
        operation_id: str,
        closed_at: str | None = None,
    ) -> RemoteDurablePoint:
        if not isinstance(log, RemoteSessionLog) or log.state.session_id != self.session_id:
            raise RemoteDurabilityError("remote checkpoint session is invalid")
        operation_id = _id(operation_id, "remote checkpoint operation id")
        if closed_at is not None:
            closed_at = _text(closed_at, "remote session closed_at")

        loaded = self._load()
        existing = self._find_record(loaded.workspace)
        snapshot = log.to_snapshot()
        expected_digest = snapshot["digest"]
        expected_sequence = log.state.last_sequence

        if existing is not None and existing.closed_at is not None:
            if (
                closed_at == existing.closed_at
                and existing.last_remote_sequence == expected_sequence
                and existing.snapshot_digest == expected_digest
            ):
                return self._point(loaded, existing)
            raise RemoteDurabilityError("closed remote session cannot be changed")

        expected_session_revision = 0 if existing is None else existing.revision
        try:
            updated = ew.checkpoint_remote_session(
                loaded.workspace,
                record_id=self._record_id,
                operation_id=operation_id,
                lesson_session=self._lesson_session,
                remote_session_log=log,
                started_at=self._started_at,
                closed_at=closed_at,
                expected_session_revision=expected_session_revision,
                expected_revision=loaded.workspace.ledger.revision,
            )
            store_revision = self._store.save(
                updated,
                expected_revision=loaded.revision,
            )
        except (
            ew.EducationWorkspaceError,
            ews.EducationWorkspaceConflictError,
            ews.EducationWorkspaceBusyError,
            ews.EducationWorkspaceStoreError,
            TypeError,
            ValueError,
        ) as exc:
            raise RemoteDurabilityError("remote checkpoint could not be published") from exc

        record = self._find_record(updated)
        if record is None:
            raise RemoteDurabilityError("remote checkpoint publication is incomplete")
        if (
            record.last_remote_sequence != expected_sequence
            or record.snapshot_digest != expected_digest
            or record.closed_at != closed_at
        ):
            raise RemoteDurabilityError("remote checkpoint publication is inconsistent")
        return RemoteDurablePoint(
            session_id=record.session_id,
            last_sequence=record.last_remote_sequence,
            snapshot_digest=record.snapshot_digest,
            session_revision=record.revision,
            ledger_revision=updated.ledger.revision,
            store_revision=store_revision,
            closed_at=record.closed_at,
        )

    def _load(self) -> ews.LoadedEducationWorkspace:
        try:
            loaded = self._store.load()
        except (
            ews.EducationWorkspaceStoreError,
            ews.EducationWorkspaceBusyError,
            ValueError,
        ) as exc:
            raise RemoteDurabilityError("remote durable workspace is unavailable") from exc
        if loaded is None:
            raise RemoteDurabilityError("remote durable workspace is unavailable")
        return loaded

    def _find_record(self, workspace: ew.EducationWorkspace):
        matches = tuple(
            item
            for item in workspace.ledger.remote_sessions
            if item.session_id == self.session_id
        )
        if not matches:
            return None
        if len(matches) != 1:
            raise RemoteDurabilityError("remote checkpoint identity is ambiguous")
        record = matches[0]
        if (
            record.record_id != self._record_id
            or record.student_ids != self._lesson_session.student_ids
            or record.started_at != self._started_at
        ):
            raise RemoteDurabilityError("remote checkpoint identity does not match lesson session")
        return record

    @staticmethod
    def _point(
        loaded: ews.LoadedEducationWorkspace,
        record,
    ) -> RemoteDurablePoint:
        return RemoteDurablePoint(
            session_id=record.session_id,
            last_sequence=record.last_remote_sequence,
            snapshot_digest=record.snapshot_digest,
            session_revision=record.revision,
            ledger_revision=loaded.workspace.ledger.revision,
            store_revision=loaded.revision,
            closed_at=record.closed_at,
        )


def _id(value: object, label: str) -> str:
    if type(value) is not str or not _ID_RE.fullmatch(value):
        raise RemoteDurabilityError(f"{label} is invalid")
    return value


def _text(value: object, label: str) -> str:
    if type(value) is not str or not value or value != value.strip() or len(value) > 512:
        raise RemoteDurabilityError(f"{label} is invalid")
    try:
        value.encode("utf-8", errors="strict")
    except UnicodeEncodeError as exc:
        raise RemoteDurabilityError(f"{label} is invalid") from exc
    return value
