from __future__ import annotations

"""Durable, presentation-neutral persistence for local training progress.

The training domain owns snapshot semantics in :mod:`acs.training`.  This module
only owns filesystem publication and optimistic concurrency.  It does not parse
moves, validate positions, or introduce another chess/application authority.

Writes are serialized with an atomic peer lock directory, validated against the
caller's exact previously observed revision, written to a peer temporary file,
fsynced, and atomically published.  A missing expected revision is create-only;
updates therefore cannot silently overwrite progress that the caller never
observed.
"""

from dataclasses import dataclass
import hashlib
import json
import os
from pathlib import Path
import tempfile
from typing import Mapping

from .training import ExerciseDefinition, ExerciseSession

TRAINING_PROGRESS_STORE_SCHEMA_VERSION = 1
_ENVELOPE_FIELDS = frozenset({"schema_version", "snapshot"})


class TrainingProgressConflictError(RuntimeError):
    """Raised when durable progress changed since the caller last observed it."""


class TrainingProgressBusyError(RuntimeError):
    """Raised when another writer currently owns the peer publication lock."""


@dataclass(frozen=True, slots=True)
class LoadedTrainingProgress:
    session: ExerciseSession
    revision: str


def _canonical_bytes(payload: Mapping[str, object]) -> bytes:
    return json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")


def _revision(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _validate_revision(value: str | None) -> str | None:
    if value is None:
        return None
    if type(value) is not str:
        raise TypeError("expected_revision must be a string or None")
    if (
        len(value) != 64
        or value != value.lower()
        or any(character not in "0123456789abcdef" for character in value)
    ):
        raise ValueError("expected_revision must be a lowercase SHA-256 digest")
    return value


class TrainingProgressStore:
    """Atomic single-exercise progress file with compare-and-swap updates.

    ``expected_revision=None`` means create-only.  To update an existing file,
    callers must first :meth:`load` it and pass the returned exact revision.
    This makes stale progress writes fail closed instead of last-writer-wins.
    """

    def __init__(self, path: str | Path) -> None:
        if not isinstance(path, (str, Path)):
            raise TypeError("path must be a filesystem path")
        self.path = Path(path).expanduser()
        if str(self.path) in {"", "."}:
            raise ValueError("path must identify a progress file")
        self._lock_path = self.path.with_name(f".{self.path.name}.lock")

    def load(self, definition: ExerciseDefinition) -> LoadedTrainingProgress | None:
        try:
            data = self.path.read_bytes()
        except FileNotFoundError:
            return None
        try:
            payload = json.loads(data.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise ValueError("invalid training progress file") from exc
        if type(payload) is not dict:
            raise ValueError("invalid training progress envelope")
        if set(payload) != _ENVELOPE_FIELDS:
            raise ValueError("invalid training progress envelope fields")
        schema_version = payload["schema_version"]
        if type(schema_version) is not int:
            raise TypeError("training progress schema_version must be an integer")
        if schema_version != TRAINING_PROGRESS_STORE_SCHEMA_VERSION:
            raise ValueError(
                f"unsupported training progress schema_version: {schema_version}"
            )
        snapshot = payload["snapshot"]
        if not isinstance(snapshot, Mapping):
            raise TypeError("training progress snapshot must be a mapping")
        session = ExerciseSession.restore(definition, snapshot)
        return LoadedTrainingProgress(session=session, revision=_revision(data))

    def save(
        self,
        session: ExerciseSession,
        *,
        expected_revision: str | None,
    ) -> str:
        if not isinstance(session, ExerciseSession):
            raise TypeError("session must be an ExerciseSession")
        expected = _validate_revision(expected_revision)
        self.path.parent.mkdir(parents=True, exist_ok=True)

        try:
            self._lock_path.mkdir()
        except FileExistsError as exc:
            raise TrainingProgressBusyError("training progress store is busy") from exc

        temporary: Path | None = None
        try:
            current_revision: str | None
            try:
                current_data = self.path.read_bytes()
            except FileNotFoundError:
                current_revision = None
            else:
                current_revision = _revision(current_data)

            if current_revision != expected:
                raise TrainingProgressConflictError(
                    "training progress changed since the caller last observed it"
                )

            envelope: dict[str, object] = {
                "schema_version": TRAINING_PROGRESS_STORE_SCHEMA_VERSION,
                "snapshot": session.snapshot(),
            }
            data = _canonical_bytes(envelope)
            new_revision = _revision(data)

            fd, raw_path = tempfile.mkstemp(
                prefix=f".{self.path.name}.",
                suffix=".tmp",
                dir=str(self.path.parent),
            )
            temporary = Path(raw_path)
            try:
                with os.fdopen(fd, "wb") as handle:
                    handle.write(data)
                    handle.flush()
                    os.fsync(handle.fileno())
            except Exception:
                if temporary.exists():
                    temporary.unlink()
                temporary = None
                raise

            os.replace(temporary, self.path)
            temporary = None
            return new_revision
        finally:
            if temporary is not None and temporary.exists():
                temporary.unlink()
            try:
                self._lock_path.rmdir()
            except FileNotFoundError:
                pass
