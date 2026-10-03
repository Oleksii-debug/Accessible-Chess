from __future__ import annotations

"""Crash-safe single-file persistence for :mod:`acs.education_workspace`.

The store publishes the canonical current ClassroomSnapshot and its anchored
EducationLedger in one filesystem replacement. It is intentionally separate
from D07 ACSDB storage and D09 live Classroom transport/session state.
"""

from contextlib import contextmanager
from dataclasses import dataclass
import hashlib
import json
import os
from pathlib import Path
import tempfile
from typing import Iterator, Mapping

if os.name == "nt":
    import msvcrt
else:
    import fcntl

from .education_workspace import (
    EducationWorkspace,
    EducationWorkspaceError,
    MAX_WORKSPACE_JSON_BYTES,
)


EDUCATION_WORKSPACE_STORE_VERSION = 1
MAX_WORKSPACE_STORE_BYTES = MAX_WORKSPACE_JSON_BYTES + 128_000
MAX_WIRE_INTEGER = (1 << 53) - 1
_ENVELOPE_FIELDS = frozenset({"schema_version", "workspace"})


class EducationWorkspaceConflictError(RuntimeError):
    """Raised when durable workspace state changed after the caller loaded it."""


class EducationWorkspaceBusyError(RuntimeError):
    """Raised while another writer owns the peer publication lock."""


class EducationWorkspaceStoreError(ValueError):
    """Raised for malformed, unsupported, oversized, or non-canonical storage."""


@dataclass(frozen=True)
class LoadedEducationWorkspace:
    workspace: EducationWorkspace
    revision: str


def _canonical_bytes(payload: Mapping[str, object]) -> bytes:
    encoder = json.JSONEncoder(
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    data = bytearray()
    try:
        for chunk in encoder.iterencode(payload):
            encoded = chunk.encode("utf-8")
            if len(data) + len(encoded) > MAX_WORKSPACE_STORE_BYTES:
                raise EducationWorkspaceStoreError(
                    "education workspace store exceeds size limit"
                )
            data.extend(encoded)
    except EducationWorkspaceStoreError:
        raise
    except (TypeError, ValueError, UnicodeEncodeError, RecursionError) as exc:
        raise EducationWorkspaceStoreError(
            "education workspace cannot be serialized for durable storage"
        ) from exc
    return bytes(data)


def _sync_published_path(path: Path) -> None:
    """Confirm the replaced namespace entry is on stable storage.

    The temporary file is fsynced before replacement.  Windows has no portable
    directory-fsync primitive, so FlushFileBuffers is requested through
    os.fsync() on the reopened destination.  POSIX additionally fsyncs the
    containing directory so the rename itself is durability-confirmed.
    """

    if os.name == "nt":
        with path.open("rb") as handle:
            os.fsync(handle.fileno())
        return

    flags = os.O_RDONLY
    if hasattr(os, "O_DIRECTORY"):
        flags |= os.O_DIRECTORY
    directory_fd = os.open(os.fspath(path.parent), flags)
    try:
        os.fsync(directory_fd)
    finally:
        os.close(directory_fd)


def _revision(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _validate_revision(value: object) -> str | None:
    if value is None:
        return None
    if (
        type(value) is not str
        or len(value) != 64
        or value != value.lower()
        or any(character not in "0123456789abcdef" for character in value)
    ):
        raise EducationWorkspaceStoreError(
            "expected revision must be a lowercase SHA-256 digest or null"
        )
    return value


def _reject_duplicate_pairs(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise EducationWorkspaceStoreError(f"duplicate durable JSON key: {key}")
        result[key] = value
    return result


def _reject_constant(value):
    raise EducationWorkspaceStoreError(
        f"non-finite durable JSON constant is not allowed: {value}"
    )


def _parse_wire_integer(value: str) -> int:
    digits = value[1:] if value.startswith("-") else value
    if not digits or len(digits) > 16:
        raise EducationWorkspaceStoreError(
            "durable JSON integer exceeds exact wire bounds"
        )
    try:
        parsed = int(value, 10)
    except ValueError as exc:
        raise EducationWorkspaceStoreError("invalid durable JSON integer") from exc
    if not -MAX_WIRE_INTEGER <= parsed <= MAX_WIRE_INTEGER:
        raise EducationWorkspaceStoreError(
            "durable JSON integer exceeds exact wire bounds"
        )
    return parsed


class EducationWorkspaceDurabilityError(RuntimeError):
    """Raised after replace when stable publication could not be confirmed.

    The new file may already be visible.  Callers must reload before deciding
    whether a retry is safe.
    """


class EducationWorkspaceStore:
    """Atomic file store with exact file-level CAS.

    ``expected_revision=None`` means create-only. Updates require the exact
    revision returned by :meth:`load` or :meth:`save`. The peer lock prevents
    simultaneous publishers from both passing CAS before replacement.
    """

    def __init__(self, path: str | Path) -> None:
        if not isinstance(path, (str, Path)):
            raise TypeError("path must be a filesystem path")
        self.path = Path(path).expanduser()
        if str(self.path) in {"", "."}:
            raise ValueError("path must identify an education workspace file")
        self._lock_path = self.path.with_name(f".{self.path.name}.lock")

    @contextmanager
    def _peer_lock(self) -> Iterator[None]:
        """Acquire a process-owned non-blocking publication lock.

        Kernel advisory locks are released automatically if the writer process
        crashes.  The tiny lock file intentionally remains in place; unlinking
        it after unlock would introduce an inode-replacement race that could let
        two writers hold locks on different files with the same path.
        """

        try:
            handle = self._lock_path.open("a+b")
        except OSError as exc:
            if self._lock_path.is_dir():
                raise EducationWorkspaceBusyError(
                    "education workspace store has a legacy peer lock directory"
                ) from exc
            raise

        acquired = False
        try:
            if os.name == "nt":
                handle.seek(0, os.SEEK_END)
                if handle.tell() == 0:
                    handle.write(b"\0")
                    handle.flush()
                handle.seek(0)
                try:
                    msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
                except OSError as exc:
                    raise EducationWorkspaceBusyError(
                        "education workspace store is busy"
                    ) from exc
            else:
                try:
                    fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
                except OSError as exc:
                    raise EducationWorkspaceBusyError(
                        "education workspace store is busy"
                    ) from exc
            acquired = True
            yield
        finally:
            if acquired:
                try:
                    if os.name == "nt":
                        handle.seek(0)
                        msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
                    else:
                        fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
                except OSError:
                    # Closing the descriptor releases process-owned locks even
                    # if an explicit unlock syscall reports a cleanup error.
                    pass
            handle.close()

    def _read_current_bytes(self) -> bytes | None:
        try:
            with self.path.open("rb") as handle:
                data = handle.read(MAX_WORKSPACE_STORE_BYTES + 1)
        except FileNotFoundError:
            return None
        if len(data) > MAX_WORKSPACE_STORE_BYTES:
            raise EducationWorkspaceStoreError(
                "education workspace store exceeds size limit"
            )
        return data

    def load(self) -> LoadedEducationWorkspace | None:
        data = self._read_current_bytes()
        if data is None:
            return None
        try:
            text = data.decode("utf-8")
            payload = json.loads(
                text,
                object_pairs_hook=_reject_duplicate_pairs,
                parse_constant=_reject_constant,
                parse_int=_parse_wire_integer,
            )
        except (UnicodeDecodeError, json.JSONDecodeError, RecursionError) as exc:
            raise EducationWorkspaceStoreError(
                "invalid education workspace store"
            ) from exc
        if type(payload) is not dict or set(payload) != _ENVELOPE_FIELDS:
            raise EducationWorkspaceStoreError(
                "invalid education workspace store envelope"
            )
        schema = payload["schema_version"]
        if type(schema) is not int or schema != EDUCATION_WORKSPACE_STORE_VERSION:
            raise EducationWorkspaceStoreError(
                f"unsupported education workspace store schema version: {schema!r}"
            )
        raw_workspace = payload["workspace"]
        if not isinstance(raw_workspace, Mapping):
            raise EducationWorkspaceStoreError(
                "education workspace payload must be an object"
            )
        try:
            workspace = EducationWorkspace.from_record(raw_workspace)
        except EducationWorkspaceError as exc:
            raise EducationWorkspaceStoreError(
                "invalid education workspace payload"
            ) from exc
        return LoadedEducationWorkspace(
            workspace=workspace,
            revision=_revision(data),
        )

    def save(
        self,
        workspace: EducationWorkspace,
        *,
        expected_revision: str | None,
    ) -> str:
        if type(workspace) is not EducationWorkspace:
            raise TypeError("workspace must be EducationWorkspace")
        try:
            canonical_workspace = EducationWorkspace.from_record(
                workspace.to_record()
            )
        except EducationWorkspaceError as exc:
            raise EducationWorkspaceStoreError(
                "workspace is not valid for durable publication"
            ) from exc

        expected = _validate_revision(expected_revision)
        envelope = {
            "schema_version": EDUCATION_WORKSPACE_STORE_VERSION,
            "workspace": canonical_workspace.to_record(),
        }
        data = _canonical_bytes(envelope)
        new_revision = _revision(data)
        self.path.parent.mkdir(parents=True, exist_ok=True)

        temporary: Path | None = None
        with self._peer_lock():
            try:
                current_data = self._read_current_bytes()
                current_revision = (
                    None if current_data is None else _revision(current_data)
                )
                if current_revision != expected:
                    raise EducationWorkspaceConflictError(
                        "education workspace changed since the caller last observed it"
                    )

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
                try:
                    _sync_published_path(self.path)
                except OSError as exc:
                    raise EducationWorkspaceDurabilityError(
                        "workspace was replaced but durable publication could not "
                        "be confirmed; reload before retrying"
                    ) from exc
                return new_revision
            finally:
                if temporary is not None and temporary.exists():
                    temporary.unlink()
