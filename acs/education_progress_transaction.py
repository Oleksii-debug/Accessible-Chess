from __future__ import annotations

"""Recoverable D10 publication for explicit student deletion across two stores.

The EducationWorkspace and StudentProgress stores are intentionally separate
authorities. A privacy deletion that changes both therefore needs a durable
intent record so a crash cannot leave the Classroom tombstone and review
progress permanently split.

The journal is privacy-monotonic: it stores identifiers, CAS revisions and
digests only. It never stores the pre-delete review records that the operation
is trying to purge. Recovery always rolls the explicit deletion forward.
"""

from dataclasses import dataclass
import hashlib
import json
import os
from pathlib import Path
import tempfile
from typing import Mapping

from . import education_workspace as ew
from .education_progress_lifecycle import (
    _purge_student_reviews,
    delete_student_and_purge_reviews,
)
from .education_workspace_store import EducationWorkspaceStore
from .student_progress import StudentProgressLedger
from .student_progress_store import StudentProgressStore


TRANSACTION_JOURNAL_SCHEMA_VERSION = 1
MAX_TRANSACTION_JOURNAL_BYTES = 16_384
_MAX_IDENTIFIER_LENGTH = 256
_MAX_WIRE_INTEGER = (1 << 53) - 1
_JOURNAL_FIELDS = frozenset(
    {
        "schema_version",
        "student_id",
        "operation_id",
        "expected_student_revision",
        "expected_ledger_revision",
        "old_workspace_revision",
        "old_progress_revision",
        "new_workspace_digest",
        "new_progress_digest",
        "purged_record_count",
    }
)


class EducationProgressTransactionError(RuntimeError):
    """Base error for the cross-store student-deletion publication protocol."""


class EducationProgressRecoveryRequired(EducationProgressTransactionError):
    """Raised when a durable intent exists and must be recovered first."""


class EducationProgressTransactionConflict(EducationProgressTransactionError):
    """Raised when durable state no longer matches either transaction state."""


class EducationProgressJournalError(ValueError):
    """Raised for a malformed, oversized, or non-canonical transaction journal."""


@dataclass(frozen=True, slots=True)
class DurableStudentDeletionResult:
    workspace_revision: str
    progress_revision: str | None
    purged_record_count: int
    recovered: bool


@dataclass(frozen=True, slots=True)
class _DeletionJournal:
    student_id: str
    operation_id: str
    expected_student_revision: int
    expected_ledger_revision: int
    old_workspace_revision: str
    old_progress_revision: str
    new_workspace_digest: str
    new_progress_digest: str
    purged_record_count: int

    def as_payload(self) -> dict[str, object]:
        return {
            "schema_version": TRANSACTION_JOURNAL_SCHEMA_VERSION,
            "student_id": self.student_id,
            "operation_id": self.operation_id,
            "expected_student_revision": self.expected_student_revision,
            "expected_ledger_revision": self.expected_ledger_revision,
            "old_workspace_revision": self.old_workspace_revision,
            "old_progress_revision": self.old_progress_revision,
            "new_workspace_digest": self.new_workspace_digest,
            "new_progress_digest": self.new_progress_digest,
            "purged_record_count": self.purged_record_count,
        }

    @classmethod
    def from_payload(cls, payload: Mapping[str, object]) -> "_DeletionJournal":
        if set(payload) != _JOURNAL_FIELDS:
            raise EducationProgressJournalError(
                "student deletion journal fields are invalid"
            )
        schema = payload["schema_version"]
        if type(schema) is not int or schema != TRANSACTION_JOURNAL_SCHEMA_VERSION:
            raise EducationProgressJournalError(
                f"unsupported student deletion journal schema version: {schema!r}"
            )
        return cls(
            student_id=_identifier(payload["student_id"], name="student_id"),
            operation_id=_identifier(payload["operation_id"], name="operation_id"),
            expected_student_revision=_wire_counter(
                payload["expected_student_revision"],
                name="expected_student_revision",
            ),
            expected_ledger_revision=_wire_counter(
                payload["expected_ledger_revision"],
                name="expected_ledger_revision",
            ),
            old_workspace_revision=_sha256(
                payload["old_workspace_revision"],
                name="old_workspace_revision",
            ),
            old_progress_revision=_sha256(
                payload["old_progress_revision"],
                name="old_progress_revision",
            ),
            new_workspace_digest=_sha256(
                payload["new_workspace_digest"],
                name="new_workspace_digest",
            ),
            new_progress_digest=_sha256(
                payload["new_progress_digest"],
                name="new_progress_digest",
            ),
            purged_record_count=_wire_counter(
                payload["purged_record_count"],
                name="purged_record_count",
            ),
        )


def _identifier(value: object, *, name: str) -> str:
    if type(value) is not str:
        raise EducationProgressJournalError(f"{name} must be text")
    token = value.strip()
    if not token or len(token) > _MAX_IDENTIFIER_LENGTH:
        raise EducationProgressJournalError(f"{name} must be bounded non-empty text")
    if any(ord(character) < 32 or ord(character) == 127 for character in token):
        raise EducationProgressJournalError(f"{name} contains a control character")
    return token


def _wire_counter(value: object, *, name: str) -> int:
    if type(value) is not int or not 0 <= value <= _MAX_WIRE_INTEGER:
        raise EducationProgressJournalError(
            f"{name} must be a non-negative exact wire integer"
        )
    return value


def _sha256(value: object, *, name: str) -> str:
    if (
        type(value) is not str
        or len(value) != 64
        or value != value.lower()
        or any(character not in "0123456789abcdef" for character in value)
    ):
        raise EducationProgressJournalError(
            f"{name} must be a lowercase SHA-256 digest"
        )
    return value


def _canonical_bytes(payload: Mapping[str, object]) -> bytes:
    try:
        data = json.dumps(
            payload,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        ).encode("utf-8")
    except (TypeError, ValueError, UnicodeEncodeError, RecursionError) as exc:
        raise EducationProgressJournalError(
            "student deletion journal cannot be serialized"
        ) from exc
    if len(data) > MAX_TRANSACTION_JOURNAL_BYTES:
        raise EducationProgressJournalError("student deletion journal exceeds size limit")
    return data


def _payload_digest(payload: Mapping[str, object]) -> str:
    try:
        data = json.dumps(
            payload,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        ).encode("utf-8")
    except (TypeError, ValueError, UnicodeEncodeError, RecursionError) as exc:
        raise EducationProgressTransactionError(
            "transaction state cannot be serialized canonically"
        ) from exc
    return hashlib.sha256(data).hexdigest()


def _workspace_digest(workspace: ew.EducationWorkspace) -> str:
    if type(workspace) is not ew.EducationWorkspace:
        raise TypeError("workspace must be EducationWorkspace")
    return _payload_digest(workspace.to_record())


def _progress_digest(progress: StudentProgressLedger) -> str:
    if type(progress) is not StudentProgressLedger:
        raise TypeError("progress must be StudentProgressLedger")
    return _payload_digest(progress.snapshot())


def _journal_path(workspace_store: EducationWorkspaceStore) -> Path:
    return workspace_store.path.with_name(
        f".{workspace_store.path.name}.student-delete.journal"
    )


def _read_journal(path: Path) -> _DeletionJournal:
    try:
        with path.open("rb") as handle:
            data = handle.read(MAX_TRANSACTION_JOURNAL_BYTES + 1)
    except FileNotFoundError:
        raise
    if len(data) > MAX_TRANSACTION_JOURNAL_BYTES:
        raise EducationProgressJournalError("student deletion journal exceeds size limit")
    try:
        payload = json.loads(data.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError, RecursionError) as exc:
        raise EducationProgressJournalError("invalid student deletion journal") from exc
    if type(payload) is not dict:
        raise EducationProgressJournalError(
            "student deletion journal must be an object"
        )
    canonical = _canonical_bytes(payload)
    if canonical != data:
        raise EducationProgressJournalError(
            "student deletion journal is not canonical JSON"
        )
    return _DeletionJournal.from_payload(payload)


def _publish_journal(path: Path, journal: _DeletionJournal) -> None:
    data = _canonical_bytes(journal.as_payload())
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, raw_path = tempfile.mkstemp(
        prefix=f".{path.name}.",
        suffix=".tmp",
        dir=str(path.parent),
    )
    temporary = Path(raw_path)
    try:
        with os.fdopen(fd, "wb") as handle:
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
        try:
            # A hard-link publication is create-only on both NTFS and POSIX
            # filesystems: a second coordinator cannot replace an active intent.
            os.link(temporary, path)
        except FileExistsError as exc:
            raise EducationProgressRecoveryRequired(
                "a student deletion transaction is already pending recovery"
            ) from exc
        except OSError as exc:
            raise EducationProgressJournalError(
                "student deletion journal could not be published atomically"
            ) from exc
    finally:
        try:
            temporary.unlink()
        except FileNotFoundError:
            pass


def _remove_journal(path: Path) -> None:
    try:
        path.unlink()
    except FileNotFoundError:
        pass


def _require_stores(
    workspace_store: EducationWorkspaceStore,
    progress_store: StudentProgressStore,
) -> None:
    if not isinstance(workspace_store, EducationWorkspaceStore):
        raise TypeError("workspace_store must be EducationWorkspaceStore")
    if not isinstance(progress_store, StudentProgressStore):
        raise TypeError("progress_store must be StudentProgressStore")


def _derive_workspace(
    workspace: ew.EducationWorkspace,
    journal: _DeletionJournal,
) -> ew.EducationWorkspace:
    candidate = ew.delete_student(
        workspace,
        student_id=journal.student_id,
        operation_id=journal.operation_id,
        expected_student_revision=journal.expected_student_revision,
        expected_ledger_revision=journal.expected_ledger_revision,
    )
    if _workspace_digest(candidate) != journal.new_workspace_digest:
        raise EducationProgressTransactionConflict(
            "recovered workspace does not match the durable deletion intent"
        )
    return candidate


def _derive_progress(
    progress: StudentProgressLedger,
    journal: _DeletionJournal,
) -> StudentProgressLedger:
    candidate, purged = _purge_student_reviews(
        progress,
        student_id=journal.student_id,
    )
    if (
        purged != journal.purged_record_count
        or _progress_digest(candidate) != journal.new_progress_digest
    ):
        raise EducationProgressTransactionConflict(
            "recovered progress does not match the durable deletion intent"
        )
    return candidate


def _state(
    *,
    revision: str,
    old_revision: str,
    semantic_digest: str,
    new_digest: str,
) -> str:
    if semantic_digest == new_digest:
        return "new"
    if revision == old_revision:
        return "old"
    return "other"


def _complete_pending(
    workspace_store: EducationWorkspaceStore,
    progress_store: StudentProgressStore,
    *,
    recovered: bool,
) -> DurableStudentDeletionResult:
    journal_path = _journal_path(workspace_store)
    journal = _read_journal(journal_path)

    loaded_workspace = workspace_store.load()
    loaded_progress = progress_store.load()
    if loaded_workspace is None or loaded_progress is None:
        raise EducationProgressTransactionConflict(
            "a durable store disappeared while student deletion was pending"
        )

    workspace_state = _state(
        revision=loaded_workspace.revision,
        old_revision=journal.old_workspace_revision,
        semantic_digest=_workspace_digest(loaded_workspace.workspace),
        new_digest=journal.new_workspace_digest,
    )
    progress_state = _state(
        revision=loaded_progress.revision,
        old_revision=journal.old_progress_revision,
        semantic_digest=_progress_digest(loaded_progress.ledger),
        new_digest=journal.new_progress_digest,
    )
    if "other" in {workspace_state, progress_state}:
        raise EducationProgressTransactionConflict(
            "durable state changed outside the pending student deletion transaction"
        )

    if progress_state == "old":
        new_progress = _derive_progress(loaded_progress.ledger, journal)
        progress_store.save(
            new_progress,
            expected_revision=loaded_progress.revision,
        )

    if workspace_state == "old":
        new_workspace = _derive_workspace(loaded_workspace.workspace, journal)
        workspace_store.save(
            new_workspace,
            expected_revision=loaded_workspace.revision,
        )

    verified_workspace = workspace_store.load()
    verified_progress = progress_store.load()
    if (
        verified_workspace is None
        or verified_progress is None
        or _workspace_digest(verified_workspace.workspace)
        != journal.new_workspace_digest
        or _progress_digest(verified_progress.ledger) != journal.new_progress_digest
    ):
        raise EducationProgressTransactionConflict(
            "student deletion could not be verified after publication"
        )

    _remove_journal(journal_path)
    return DurableStudentDeletionResult(
        workspace_revision=verified_workspace.revision,
        progress_revision=verified_progress.revision,
        purged_record_count=journal.purged_record_count,
        recovered=recovered,
    )


def recover_pending_student_deletion(
    workspace_store: EducationWorkspaceStore,
    progress_store: StudentProgressStore,
) -> DurableStudentDeletionResult | None:
    """Roll a pending explicit deletion forward, or fail closed on divergence."""

    _require_stores(workspace_store, progress_store)
    journal_path = _journal_path(workspace_store)
    if not journal_path.exists():
        return None
    return _complete_pending(
        workspace_store,
        progress_store,
        recovered=True,
    )


def delete_student_and_purge_reviews_durable(
    workspace_store: EducationWorkspaceStore,
    progress_store: StudentProgressStore,
    *,
    student_id: str,
    operation_id: str,
    expected_student_revision: int,
    expected_ledger_revision: int,
) -> DurableStudentDeletionResult:
    """Durably publish one explicit student deletion across both local stores.

    If a crash occurs after the journal is published, callers must invoke
    :func:`recover_pending_student_deletion` before accepting new education
    mutations. Recovery never restores deleted review records; it completes
    the explicit privacy deletion from the exact CAS revisions recorded in the
    journal.
    """

    _require_stores(workspace_store, progress_store)
    journal_path = _journal_path(workspace_store)
    if journal_path.exists():
        raise EducationProgressRecoveryRequired(
            "recover the pending student deletion before starting another"
        )

    loaded_workspace = workspace_store.load()
    if loaded_workspace is None:
        raise EducationProgressTransactionError(
            "education workspace must exist before durable student deletion"
        )
    loaded_progress = progress_store.load()

    progress = (
        StudentProgressLedger()
        if loaded_progress is None
        else loaded_progress.ledger
    )
    transition = delete_student_and_purge_reviews(
        loaded_workspace.workspace,
        progress,
        student_id=student_id,
        operation_id=operation_id,
        expected_student_revision=expected_student_revision,
        expected_ledger_revision=expected_ledger_revision,
    )

    # With no durable review-progress authority there is no second publication
    # to coordinate. The canonical workspace store remains a single atomic CAS.
    if loaded_progress is None:
        workspace_revision = workspace_store.save(
            transition.workspace,
            expected_revision=loaded_workspace.revision,
        )
        return DurableStudentDeletionResult(
            workspace_revision=workspace_revision,
            progress_revision=None,
            purged_record_count=transition.purged_record_count,
            recovered=False,
        )

    journal = _DeletionJournal(
        student_id=_identifier(student_id, name="student_id"),
        operation_id=_identifier(operation_id, name="operation_id"),
        expected_student_revision=_wire_counter(
            expected_student_revision,
            name="expected_student_revision",
        ),
        expected_ledger_revision=_wire_counter(
            expected_ledger_revision,
            name="expected_ledger_revision",
        ),
        old_workspace_revision=_sha256(
            loaded_workspace.revision,
            name="old_workspace_revision",
        ),
        old_progress_revision=_sha256(
            loaded_progress.revision,
            name="old_progress_revision",
        ),
        new_workspace_digest=_workspace_digest(transition.workspace),
        new_progress_digest=_progress_digest(transition.progress),
        purged_record_count=_wire_counter(
            transition.purged_record_count,
            name="purged_record_count",
        ),
    )
    _publish_journal(journal_path, journal)

    try:
        # Privacy-monotonic ordering: purge separate review records before
        # publishing the Classroom tombstone. The journal then rolls forward.
        progress_store.save(
            transition.progress,
            expected_revision=loaded_progress.revision,
        )
        workspace_store.save(
            transition.workspace,
            expected_revision=loaded_workspace.revision,
        )
    except Exception as exc:
        raise EducationProgressRecoveryRequired(
            "student deletion publication was interrupted; recovery is required"
        ) from exc

    return _complete_pending(
        workspace_store,
        progress_store,
        recovered=False,
    )
