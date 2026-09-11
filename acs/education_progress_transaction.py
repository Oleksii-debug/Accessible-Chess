from __future__ import annotations

"""Crash/restart-safe composition for D10 student deletion privacy.

The canonical education workspace and review-progress ledger intentionally remain
separate domain authorities. This module coordinates their durable publication
without inventing a second Classroom or progress model.

The transaction has one durable commit point: the ``prepared`` journal. Before
that point neither canonical store is modified. After that point recovery is
roll-forward-only, so a committed student deletion can never be "recovered" by
resurrecting personally bound review records.
"""

from contextlib import contextmanager
from dataclasses import dataclass
import hashlib
import json
import os
from pathlib import Path
import stat
import tempfile
from typing import Callable, Iterator, Mapping
import uuid

from .education_progress_lifecycle import (
    StudentDeletionWithProgress,
    delete_student_and_purge_reviews,
)
from .education_workspace_store import EducationWorkspaceStore
from .student_progress import StudentProgressLedger
from .student_progress_store import StudentProgressStore


TRANSACTION_SCHEMA_VERSION = 1
JOURNAL_NAME = ".education-progress-transaction.json"
GLOBAL_LOCK_NAME = ".education-progress-transaction.lock"
STAGE_PREFIX = ".education-progress-transaction-"
PEER_LOCK_MARKER_KIND = "education-progress-transaction-peer-lock"
_MAX_JOURNAL_BYTES = 32 * 1024

_PRECOMMIT_PHASES = frozenset({"staging", "locking", "locked"})
_COMMITTED_PHASES = frozenset({"prepared", "workspace_published", "both_published"})
_ALL_PHASES = _PRECOMMIT_PHASES | _COMMITTED_PHASES
_JOURNAL_FIELDS = frozenset(
    {
        "schema_version",
        "transaction_id",
        "phase",
        "workspace_name",
        "progress_name",
        "workspace_old_revision",
        "progress_old_revision",
        "workspace_new_revision",
        "progress_new_revision",
        "stage_name",
    }
)
_LOCK_MARKER_FIELDS = frozenset({"schema_version", "kind", "transaction_id"})


class EducationProgressTransactionError(RuntimeError):
    """Base class for bounded durable-composition failures."""


class EducationProgressTransactionBusyError(EducationProgressTransactionError):
    """Another writer or transaction owns a required publication lock."""


class EducationProgressTransactionConflictError(EducationProgressTransactionError):
    """Durable state changed outside the exact transaction revision set."""


class EducationProgressTransactionRecoveryError(EducationProgressTransactionError):
    """A committed transaction cannot be safely recovered automatically."""


@dataclass(frozen=True, slots=True)
class PublishedStudentDeletion:
    """Exact durable revisions after a completed privacy transaction."""

    workspace_revision: str
    progress_revision: str
    purged_record_count: int


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _validate_revision(value: object, *, name: str) -> str | None:
    if value is None:
        return None
    if (
        type(value) is not str
        or len(value) != 64
        or value != value.lower()
        or any(character not in "0123456789abcdef" for character in value)
    ):
        raise ValueError(f"{name} must be a lowercase SHA-256 digest or null")
    return value


def _reject_duplicate_pairs(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise EducationProgressTransactionRecoveryError(
                "durable education transaction contains duplicate JSON keys"
            )
        result[key] = value
    return result


def _reject_constant(value: str) -> None:
    raise EducationProgressTransactionRecoveryError(
        "durable education transaction contains a non-finite JSON value"
    )


def _canonical_json(value: Mapping[str, object]) -> bytes:
    try:
        data = json.dumps(
            value,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        ).encode("utf-8")
    except (TypeError, ValueError, UnicodeEncodeError) as exc:
        raise EducationProgressTransactionRecoveryError(
            "durable education transaction cannot be serialized"
        ) from exc
    if len(data) > _MAX_JOURNAL_BYTES:
        raise EducationProgressTransactionRecoveryError(
            "durable education transaction journal exceeds its size limit"
        )
    return data


def _is_reparse_point(metadata: os.stat_result) -> bool:
    flag = getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0)
    attributes = getattr(metadata, "st_file_attributes", 0)
    return bool(flag and attributes & flag)


def _require_regular_file(path: Path, *, missing_ok: bool = False) -> bool:
    try:
        metadata = os.lstat(path)
    except FileNotFoundError:
        if missing_ok:
            return False
        raise EducationProgressTransactionRecoveryError(
            "durable education transaction file is unavailable"
        )
    except OSError as exc:
        raise EducationProgressTransactionRecoveryError(
            "durable education transaction storage is unavailable"
        ) from exc
    if (
        stat.S_ISLNK(metadata.st_mode)
        or _is_reparse_point(metadata)
        or not stat.S_ISREG(metadata.st_mode)
    ):
        raise EducationProgressTransactionRecoveryError(
            "durable education transaction path is not a regular file"
        )
    return True


def _read_raw(path: Path) -> bytes | None:
    if not _require_regular_file(path, missing_ok=True):
        return None
    try:
        return path.read_bytes()
    except OSError as exc:
        raise EducationProgressTransactionRecoveryError(
            "durable education transaction state could not be read"
        ) from exc


def _revision(path: Path) -> str | None:
    raw = _read_raw(path)
    return None if raw is None else _sha256(raw)


def _fsync_parent(parent: Path) -> None:
    """Best-effort directory durability; Windows file flushes remain authoritative."""

    if os.name == "nt":
        return
    flags = (
        os.O_RDONLY
        | getattr(os, "O_DIRECTORY", 0)
        | getattr(os, "O_CLOEXEC", 0)
    )
    try:
        descriptor = os.open(parent, flags)
    except OSError:
        return
    try:
        os.fsync(descriptor)
    except OSError:
        pass
    finally:
        os.close(descriptor)


def _atomic_publish_bytes(target: Path, data: bytes) -> None:
    target.parent.mkdir(parents=True, exist_ok=True)
    _require_regular_file(target, missing_ok=True)
    temporary: Path | None = None
    try:
        descriptor, raw_name = tempfile.mkstemp(
            prefix=f".{target.name}.",
            suffix=".txn.tmp",
            dir=target.parent,
        )
        temporary = Path(raw_name)
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, target)
        temporary = None
        _fsync_parent(target.parent)
    finally:
        if temporary is not None:
            try:
                temporary.unlink(missing_ok=True)
            except OSError:
                pass


class EducationProgressDeletionTransaction:
    """Coordinate privacy-safe publication across the two canonical D10 stores."""

    def __init__(
        self,
        workspace_store: EducationWorkspaceStore,
        progress_store: StudentProgressStore,
    ) -> None:
        if not isinstance(workspace_store, EducationWorkspaceStore):
            raise TypeError("workspace_store must be EducationWorkspaceStore")
        if not isinstance(progress_store, StudentProgressStore):
            raise TypeError("progress_store must be StudentProgressStore")

        workspace_path = Path(os.path.abspath(os.fspath(workspace_store.path)))
        progress_path = Path(os.path.abspath(os.fspath(progress_store.path)))
        if workspace_path.parent != progress_path.parent:
            raise ValueError(
                "education workspace and review progress must share one durable parent"
            )
        if workspace_path == progress_path:
            raise ValueError(
                "education workspace and review progress must use distinct files"
            )
        if workspace_path.name in {JOURNAL_NAME, GLOBAL_LOCK_NAME} or progress_path.name in {
            JOURNAL_NAME,
            GLOBAL_LOCK_NAME,
        }:
            raise ValueError("canonical store name collides with transaction metadata")

        self.workspace_store = workspace_store
        self.progress_store = progress_store
        self._workspace_path = workspace_path
        self._progress_path = progress_path
        self._parent = workspace_path.parent
        self._journal_path = self._parent / JOURNAL_NAME
        self._global_lock_path = self._parent / GLOBAL_LOCK_NAME
        # These exact sibling names are the current concurrency contract enforced
        # by both stores: their normal save() calls use mkdir() at this path.
        self._workspace_peer_lock = self._workspace_path.with_name(
            f".{self._workspace_path.name}.lock"
        )
        self._progress_peer_lock = self._progress_path.with_name(
            f".{self._progress_path.name}.lock"
        )

    @property
    def journal_path(self) -> Path:
        """Infrastructure-only transaction journal path for startup recovery."""

        return self._journal_path

    @staticmethod
    def _after_phase(phase: str) -> None:
        """Fault-injection checkpoint used by deterministic crash/restart tests."""

        del phase

    @staticmethod
    def _lock_descriptor(descriptor: int) -> None:
        try:
            if os.name == "nt":
                import msvcrt

                os.lseek(descriptor, 0, os.SEEK_SET)
                msvcrt.locking(descriptor, msvcrt.LK_NBLCK, 1)
            else:
                import fcntl

                fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError as exc:
            raise EducationProgressTransactionBusyError(
                "education progress transaction is busy"
            ) from exc

    @staticmethod
    def _unlock_descriptor(descriptor: int) -> None:
        try:
            if os.name == "nt":
                import msvcrt

                os.lseek(descriptor, 0, os.SEEK_SET)
                msvcrt.locking(descriptor, msvcrt.LK_UNLCK, 1)
            else:
                import fcntl

                fcntl.flock(descriptor, fcntl.LOCK_UN)
        except OSError:
            pass

    @contextmanager
    def _exclusive_transaction(self) -> Iterator[None]:
        self._parent.mkdir(parents=True, exist_ok=True)
        flags = os.O_RDWR | os.O_CREAT
        flags |= getattr(os, "O_BINARY", 0)
        flags |= getattr(os, "O_NOINHERIT", 0)
        flags |= getattr(os, "O_CLOEXEC", 0)
        flags |= getattr(os, "O_NOFOLLOW", 0)
        try:
            descriptor = os.open(self._global_lock_path, flags, 0o600)
        except OSError as exc:
            raise EducationProgressTransactionRecoveryError(
                "education progress transaction lock is unavailable"
            ) from exc
        acquired = False
        try:
            metadata = os.fstat(descriptor)
            if (
                stat.S_ISLNK(metadata.st_mode)
                or _is_reparse_point(metadata)
                or not stat.S_ISREG(metadata.st_mode)
            ):
                raise EducationProgressTransactionRecoveryError(
                    "education progress transaction lock is invalid"
                )
            if metadata.st_size == 0:
                os.write(descriptor, b"\0")
                os.fsync(descriptor)
            self._lock_descriptor(descriptor)
            acquired = True
            self._cleanup_orphaned_peer_locks_without_journal()
            yield
        finally:
            if acquired:
                self._unlock_descriptor(descriptor)
            os.close(descriptor)

    @staticmethod
    def _valid_transaction_id(value: object) -> bool:
        return (
            type(value) is str
            and len(value) == 32
            and value == value.lower()
            and all(character in "0123456789abcdef" for character in value)
        )

    @staticmethod
    def _peer_marker_bytes(transaction_id: str) -> bytes:
        return _canonical_json(
            {
                "schema_version": TRANSACTION_SCHEMA_VERSION,
                "kind": PEER_LOCK_MARKER_KIND,
                "transaction_id": transaction_id,
            }
        )

    @classmethod
    def _decode_peer_marker(cls, raw: bytes) -> str | None:
        try:
            value = json.loads(
                raw.decode("utf-8"),
                object_pairs_hook=_reject_duplicate_pairs,
                parse_constant=_reject_constant,
            )
        except (
            UnicodeDecodeError,
            json.JSONDecodeError,
            EducationProgressTransactionRecoveryError,
        ):
            return None
        if type(value) is not dict or set(value) != _LOCK_MARKER_FIELDS:
            return None
        if (
            type(value.get("schema_version")) is not int
            or value.get("schema_version") != TRANSACTION_SCHEMA_VERSION
        ):
            return None
        if value.get("kind") != PEER_LOCK_MARKER_KIND:
            return None
        transaction_id = value.get("transaction_id")
        if not cls._valid_transaction_id(transaction_id):
            return None
        return transaction_id

    def _peer_lock_owner(self, path: Path) -> str | None:
        try:
            metadata = os.lstat(path)
        except FileNotFoundError:
            return None
        except OSError as exc:
            raise EducationProgressTransactionBusyError(
                "education progress peer store is busy"
            ) from exc
        if stat.S_ISDIR(metadata.st_mode):
            # Normal canonical store writers own a directory at this path.
            return "foreign"
        if (
            stat.S_ISLNK(metadata.st_mode)
            or _is_reparse_point(metadata)
            or not stat.S_ISREG(metadata.st_mode)
        ):
            return "foreign"
        try:
            raw = path.read_bytes()
        except OSError:
            return "foreign"
        return self._decode_peer_marker(raw) or "foreign"

    def _acquire_peer_lock(
        self,
        path: Path,
        transaction_id: str,
        *,
        adopt: bool,
    ) -> None:
        owner = self._peer_lock_owner(path)
        if owner is not None:
            if adopt and owner == transaction_id:
                return
            raise EducationProgressTransactionBusyError(
                "education progress peer store is busy"
            )

        marker = self._peer_marker_bytes(transaction_id)
        descriptor, raw_name = tempfile.mkstemp(
            prefix=f".{path.name}.txn-",
            suffix=".lock",
            dir=path.parent,
        )
        temporary = Path(raw_name)
        try:
            with os.fdopen(descriptor, "wb") as stream:
                stream.write(marker)
                stream.flush()
                os.fsync(stream.fileno())
            try:
                # Hard-link publication is atomic and no-clobber, unlike replacing
                # a lock directory. Existing canonical store mkdir() writers are
                # blocked by either this regular file or their normal directory.
                os.link(temporary, path)
            except FileExistsError as exc:
                raise EducationProgressTransactionBusyError(
                    "education progress peer store is busy"
                ) from exc
            except OSError as exc:
                if path.exists():
                    raise EducationProgressTransactionBusyError(
                        "education progress peer store is busy"
                    ) from exc
                raise EducationProgressTransactionRecoveryError(
                    "education progress peer lock could not be acquired"
                ) from exc
            _fsync_parent(path.parent)
        finally:
            try:
                temporary.unlink(missing_ok=True)
            except OSError:
                pass

    def _acquire_peer_locks(self, transaction_id: str, *, adopt: bool) -> None:
        acquired: list[Path] = []
        for path in sorted(
            (self._workspace_peer_lock, self._progress_peer_lock),
            key=lambda item: os.path.normcase(os.fspath(item)),
        ):
            try:
                self._acquire_peer_lock(path, transaction_id, adopt=adopt)
                acquired.append(path)
            except Exception:
                # Fresh publication can release its markers before the commit
                # point. During committed recovery adopted crash-residue markers
                # must remain if another peer lock is foreign; releasing them
                # would let a normal writer race the unresolved transaction.
                if not adopt:
                    for owned in reversed(acquired):
                        self._release_peer_lock(owned, transaction_id)
                raise

    def _release_peer_lock(self, path: Path, transaction_id: str) -> None:
        if self._peer_lock_owner(path) != transaction_id:
            return
        try:
            path.unlink()
            _fsync_parent(path.parent)
        except OSError as exc:
            raise EducationProgressTransactionRecoveryError(
                "education progress peer lock could not be released"
            ) from exc

    def _release_peer_locks(self, transaction_id: str) -> None:
        for path in (self._workspace_peer_lock, self._progress_peer_lock):
            self._release_peer_lock(path, transaction_id)

    def _cleanup_orphaned_peer_locks_without_journal(self) -> None:
        if self._journal_path.exists():
            return
        for path in (self._workspace_peer_lock, self._progress_peer_lock):
            owner = self._peer_lock_owner(path)
            if owner not in {None, "foreign"}:
                try:
                    path.unlink()
                except OSError as exc:
                    raise EducationProgressTransactionRecoveryError(
                        "orphaned education progress peer lock could not be cleaned"
                    ) from exc
        _fsync_parent(self._parent)

    def _write_journal(self, journal: Mapping[str, object]) -> None:
        data = _canonical_json(journal)
        temporary: Path | None = None
        try:
            descriptor, raw_name = tempfile.mkstemp(
                prefix=f".{JOURNAL_NAME}.",
                suffix=".tmp",
                dir=self._parent,
            )
            temporary = Path(raw_name)
            with os.fdopen(descriptor, "wb") as stream:
                stream.write(data)
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temporary, self._journal_path)
            temporary = None
            _fsync_parent(self._parent)
        finally:
            if temporary is not None:
                try:
                    temporary.unlink(missing_ok=True)
                except OSError:
                    pass

    def _read_journal(self) -> dict[str, object] | None:
        raw = _read_raw(self._journal_path)
        if raw is None:
            return None
        if len(raw) > _MAX_JOURNAL_BYTES:
            raise EducationProgressTransactionRecoveryError(
                "durable education transaction journal exceeds its size limit"
            )
        try:
            value = json.loads(
                raw.decode("utf-8"),
                object_pairs_hook=_reject_duplicate_pairs,
                parse_constant=_reject_constant,
            )
        except EducationProgressTransactionRecoveryError:
            raise
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise EducationProgressTransactionRecoveryError(
                "durable education transaction journal is corrupt"
            ) from exc
        if type(value) is not dict or set(value) != _JOURNAL_FIELDS:
            raise EducationProgressTransactionRecoveryError(
                "durable education transaction journal fields are invalid"
            )
        if (
            type(value["schema_version"]) is not int
            or value["schema_version"] != TRANSACTION_SCHEMA_VERSION
        ):
            raise EducationProgressTransactionRecoveryError(
                "durable education transaction schema is unsupported"
            )
        transaction_id = value["transaction_id"]
        if not self._valid_transaction_id(transaction_id):
            raise EducationProgressTransactionRecoveryError(
                "durable education transaction identity is invalid"
            )
        if value["phase"] not in _ALL_PHASES:
            raise EducationProgressTransactionRecoveryError(
                "durable education transaction phase is invalid"
            )
        if (
            value["workspace_name"] != self._workspace_path.name
            or value["progress_name"] != self._progress_path.name
        ):
            raise EducationProgressTransactionRecoveryError(
                "durable education transaction targets do not match this coordinator"
            )
        if value["stage_name"] != f"{STAGE_PREFIX}{transaction_id}":
            raise EducationProgressTransactionRecoveryError(
                "durable education transaction staging identity is invalid"
            )
        for field in (
            "workspace_old_revision",
            "progress_old_revision",
            "workspace_new_revision",
            "progress_new_revision",
        ):
            try:
                _validate_revision(value[field], name=field)
            except ValueError as exc:
                raise EducationProgressTransactionRecoveryError(
                    "durable education transaction revision is invalid"
                ) from exc
        if value["phase"] in _COMMITTED_PHASES and (
            value["workspace_new_revision"] is None
            or value["progress_new_revision"] is None
        ):
            raise EducationProgressTransactionRecoveryError(
                "committed education transaction is missing new revisions"
            )
        return value

    def _stage_path(self, journal: Mapping[str, object]) -> Path:
        return self._parent / str(journal["stage_name"])

    def _cleanup_stage(self, journal: Mapping[str, object]) -> None:
        stage = self._stage_path(journal)
        try:
            metadata = os.lstat(stage)
        except FileNotFoundError:
            return
        except OSError as exc:
            raise EducationProgressTransactionRecoveryError(
                "education progress transaction staging is unavailable"
            ) from exc
        if (
            stat.S_ISLNK(metadata.st_mode)
            or _is_reparse_point(metadata)
            or not stat.S_ISDIR(metadata.st_mode)
        ):
            raise EducationProgressTransactionRecoveryError(
                "education progress transaction staging is invalid"
            )
        allowed = {"workspace.new", "progress.new"}
        try:
            entries = list(stage.iterdir())
        except OSError as exc:
            raise EducationProgressTransactionRecoveryError(
                "education progress transaction staging cannot be inspected"
            ) from exc
        if any(entry.name not in allowed for entry in entries):
            raise EducationProgressTransactionRecoveryError(
                "education progress transaction staging contains unexpected data"
            )
        for entry in entries:
            _require_regular_file(entry)
            try:
                entry.unlink()
            except OSError as exc:
                raise EducationProgressTransactionRecoveryError(
                    "education progress transaction staging cannot be cleaned"
                ) from exc
        try:
            stage.rmdir()
        except OSError as exc:
            raise EducationProgressTransactionRecoveryError(
                "education progress transaction staging cannot be cleaned"
            ) from exc
        _fsync_parent(self._parent)

    def _delete_journal(self) -> None:
        try:
            self._journal_path.unlink(missing_ok=True)
        except OSError as exc:
            raise EducationProgressTransactionRecoveryError(
                "education progress transaction journal cannot be cleaned"
            ) from exc
        _fsync_parent(self._parent)

    def _abort_precommit(self, journal: Mapping[str, object]) -> None:
        transaction_id = str(journal["transaction_id"])
        self._cleanup_stage(journal)
        self._delete_journal()
        self._release_peer_locks(transaction_id)

    def _stage_result(
        self,
        journal: dict[str, object],
        result: StudentDeletionWithProgress,
    ) -> dict[str, object]:
        stage = self._stage_path(journal)
        try:
            stage.mkdir(mode=0o700)
        except OSError as exc:
            raise EducationProgressTransactionRecoveryError(
                "education progress transaction staging cannot be created"
            ) from exc
        workspace_stage = EducationWorkspaceStore(stage / "workspace.new")
        progress_stage = StudentProgressStore(stage / "progress.new")
        workspace_revision = workspace_stage.save(
            result.workspace,
            expected_revision=None,
        )
        progress_revision = progress_stage.save(
            result.progress,
            expected_revision=None,
        )
        workspace_loaded = workspace_stage.load()
        progress_loaded = progress_stage.load()
        if (
            workspace_loaded is None
            or progress_loaded is None
            or workspace_loaded.revision != workspace_revision
            or progress_loaded.revision != progress_revision
            or workspace_loaded.workspace.to_record() != result.workspace.to_record()
            or progress_loaded.ledger.snapshot() != result.progress.snapshot()
        ):
            raise EducationProgressTransactionRecoveryError(
                "staged education progress transaction failed canonical readback"
            )
        updated = dict(journal)
        updated["workspace_new_revision"] = workspace_revision
        updated["progress_new_revision"] = progress_revision
        updated["phase"] = "locking"
        self._write_journal(updated)
        return updated

    def _stage_component(
        self,
        journal: Mapping[str, object],
        name: str,
        expected: str,
    ) -> bytes:
        path = self._stage_path(journal) / name
        raw = _read_raw(path)
        if raw is None or _sha256(raw) != expected:
            raise EducationProgressTransactionRecoveryError(
                "committed education progress transaction staging is unavailable"
            )
        return raw

    def _publish_component_from_stage(
        self,
        *,
        target: Path,
        old_revision: str | None,
        new_revision: str,
        stage_bytes: Callable[[], bytes],
    ) -> None:
        current = _revision(target)
        if current == new_revision:
            return
        if current != old_revision:
            raise EducationProgressTransactionConflictError(
                "education progress transaction found an unexpected durable revision"
            )
        raw = stage_bytes()
        if _sha256(raw) != new_revision:
            raise EducationProgressTransactionRecoveryError(
                "education progress transaction staged revision is invalid"
            )
        _atomic_publish_bytes(target, raw)
        if _revision(target) != new_revision:
            raise EducationProgressTransactionRecoveryError(
                "education progress transaction publication readback failed"
            )

    def _recover_locked(self) -> bool:
        journal = self._read_journal()
        if journal is None:
            self._cleanup_orphaned_peer_locks_without_journal()
            return False
        transaction_id = str(journal["transaction_id"])
        phase = str(journal["phase"])
        if phase in _PRECOMMIT_PHASES:
            self._abort_precommit(journal)
            return True

        self._acquire_peer_locks(transaction_id, adopt=True)
        workspace_old = _validate_revision(
            journal["workspace_old_revision"],
            name="workspace_old_revision",
        )
        progress_old = _validate_revision(
            journal["progress_old_revision"],
            name="progress_old_revision",
        )
        workspace_new = _validate_revision(
            journal["workspace_new_revision"],
            name="workspace_new_revision",
        )
        progress_new = _validate_revision(
            journal["progress_new_revision"],
            name="progress_new_revision",
        )
        assert workspace_new is not None and progress_new is not None

        self._publish_component_from_stage(
            target=self._workspace_path,
            old_revision=workspace_old,
            new_revision=workspace_new,
            stage_bytes=lambda: self._stage_component(
                journal,
                "workspace.new",
                workspace_new,
            ),
        )
        self._publish_component_from_stage(
            target=self._progress_path,
            old_revision=progress_old,
            new_revision=progress_new,
            stage_bytes=lambda: self._stage_component(
                journal,
                "progress.new",
                progress_new,
            ),
        )
        if (
            _revision(self._workspace_path) != workspace_new
            or _revision(self._progress_path) != progress_new
        ):
            raise EducationProgressTransactionRecoveryError(
                "recovered education progress transaction did not reach one exact state"
            )

        self._cleanup_stage(journal)
        self._delete_journal()
        self._release_peer_locks(transaction_id)
        return True

    def recover_pending(self) -> bool:
        """Recover or discard one interrupted transaction under the durable contract."""

        with self._exclusive_transaction():
            return self._recover_locked()

    def publish(
        self,
        result: StudentDeletionWithProgress,
        *,
        expected_workspace_revision: str | None,
        expected_progress_revision: str | None,
    ) -> PublishedStudentDeletion:
        """Publish one already-validated #644 deletion result transactionally."""

        if not isinstance(result, StudentDeletionWithProgress):
            raise TypeError("result must be StudentDeletionWithProgress")
        workspace_old = _validate_revision(
            expected_workspace_revision,
            name="expected_workspace_revision",
        )
        progress_old = _validate_revision(
            expected_progress_revision,
            name="expected_progress_revision",
        )

        with self._exclusive_transaction():
            self._recover_locked()
            transaction_id = uuid.uuid4().hex
            journal: dict[str, object] = {
                "schema_version": TRANSACTION_SCHEMA_VERSION,
                "transaction_id": transaction_id,
                "phase": "staging",
                "workspace_name": self._workspace_path.name,
                "progress_name": self._progress_path.name,
                "workspace_old_revision": workspace_old,
                "progress_old_revision": progress_old,
                "workspace_new_revision": None,
                "progress_new_revision": None,
                "stage_name": f"{STAGE_PREFIX}{transaction_id}",
            }
            self._write_journal(journal)
            self._after_phase("staging")
            phase = "staging"
            try:
                journal = self._stage_result(journal, result)
                phase = "locking"
                self._after_phase("locking")
                self._acquire_peer_locks(transaction_id, adopt=False)

                if (
                    _revision(self._workspace_path) != workspace_old
                    or _revision(self._progress_path) != progress_old
                ):
                    raise EducationProgressTransactionConflictError(
                        "education progress changed since the deletion transition was prepared"
                    )

                journal["phase"] = "locked"
                self._write_journal(journal)
                phase = "locked"
                self._after_phase("locked")

                journal["phase"] = "prepared"
                self._write_journal(journal)
                phase = "prepared"
                self._after_phase("prepared")

                workspace_new = str(journal["workspace_new_revision"])
                progress_new = str(journal["progress_new_revision"])
                workspace_raw = self._stage_component(
                    journal,
                    "workspace.new",
                    workspace_new,
                )
                _atomic_publish_bytes(self._workspace_path, workspace_raw)
                if _revision(self._workspace_path) != workspace_new:
                    raise EducationProgressTransactionRecoveryError(
                        "education workspace publication readback failed"
                    )
                journal["phase"] = "workspace_published"
                self._write_journal(journal)
                phase = "workspace_published"
                self._after_phase("workspace_published")

                progress_raw = self._stage_component(
                    journal,
                    "progress.new",
                    progress_new,
                )
                _atomic_publish_bytes(self._progress_path, progress_raw)
                if _revision(self._progress_path) != progress_new:
                    raise EducationProgressTransactionRecoveryError(
                        "review progress publication readback failed"
                    )
                journal["phase"] = "both_published"
                self._write_journal(journal)
                phase = "both_published"
                self._after_phase("both_published")

                workspace_loaded = self.workspace_store.load()
                progress_loaded = self.progress_store.load()
                if (
                    workspace_loaded is None
                    or progress_loaded is None
                    or workspace_loaded.revision != workspace_new
                    or progress_loaded.revision != progress_new
                    or workspace_loaded.workspace.to_record() != result.workspace.to_record()
                    or progress_loaded.ledger.snapshot() != result.progress.snapshot()
                ):
                    raise EducationProgressTransactionRecoveryError(
                        "durable education deletion failed canonical final readback"
                    )

                self._cleanup_stage(journal)
                self._delete_journal()
                self._release_peer_locks(transaction_id)
                return PublishedStudentDeletion(
                    workspace_revision=workspace_new,
                    progress_revision=progress_new,
                    purged_record_count=result.purged_record_count,
                )
            except Exception as exc:
                if phase in _PRECOMMIT_PHASES:
                    try:
                        current = self._read_journal() or journal
                        self._abort_precommit(current)
                    except Exception as cleanup_exc:
                        raise EducationProgressTransactionRecoveryError(
                            "pre-commit education deletion cleanup requires recovery"
                        ) from cleanup_exc
                    raise
                raise EducationProgressTransactionRecoveryError(
                    "committed education deletion requires roll-forward recovery"
                ) from exc

    def delete_student(
        self,
        *,
        student_id: str,
        operation_id: str,
        expected_student_revision: int,
        expected_ledger_revision: int,
    ) -> PublishedStudentDeletion:
        """Load, apply canonical D10 deletion, and durably publish both authorities."""

        self.recover_pending()
        loaded_workspace = self.workspace_store.load()
        if loaded_workspace is None:
            raise EducationProgressTransactionError(
                "education workspace is unavailable for student deletion"
            )
        loaded_progress = self.progress_store.load()
        if loaded_progress is None:
            progress = StudentProgressLedger()
            progress_revision = None
        else:
            progress = loaded_progress.ledger
            progress_revision = loaded_progress.revision

        result = delete_student_and_purge_reviews(
            loaded_workspace.workspace,
            progress,
            student_id=student_id,
            operation_id=operation_id,
            expected_student_revision=expected_student_revision,
            expected_ledger_revision=expected_ledger_revision,
        )
        return self.publish(
            result,
            expected_workspace_revision=loaded_workspace.revision,
            expected_progress_revision=progress_revision,
        )
