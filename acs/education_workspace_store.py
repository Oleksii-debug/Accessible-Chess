from __future__ import annotations

"""Crash-safe single-file persistence for :mod:`acs.education_workspace`.

The store publishes the canonical current ClassroomSnapshot and its anchored
EducationLedger in one filesystem replacement. It is intentionally separate
from D07 ACSDB storage and D09 live Classroom transport/session state.
"""

from dataclasses import dataclass
import hashlib
import json
import os
from pathlib import Path
import tempfile
from typing import Mapping

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
    try:
        text = json.dumps(
            payload,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )
        data = text.encode("utf-8")
    except (TypeError, ValueError, UnicodeEncodeError, RecursionError) as exc:
        raise EducationWorkspaceStoreError(
            "education workspace cannot be serialized for durable storage"
        ) from exc
    if len(data) > MAX_WORKSPACE_STORE_BYTES:
        raise EducationWorkspaceStoreError("education workspace store exceeds size limit")
    return data


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

        try:
            self._lock_path.mkdir()
        except FileExistsError as exc:
            raise EducationWorkspaceBusyError(
                "education workspace store is busy"
            ) from exc

        temporary: Path | None = None
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
            return new_revision
        finally:
            if temporary is not None and temporary.exists():
                temporary.unlink()
            try:
                self._lock_path.rmdir()
            except FileNotFoundError:
                pass
