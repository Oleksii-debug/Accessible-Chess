from __future__ import annotations

"""Crash-safe persistence for current child-coaching lesson templates."""

from contextlib import contextmanager
from dataclasses import dataclass
import hashlib
import json
import os
from pathlib import Path
import tempfile

from .child_coaching import ChildCoachingError, LessonTemplate

CHILD_COACHING_STORE_SCHEMA_VERSION = 1
MAX_CHILD_COACHING_STORE_BYTES = 2_000_000
MAX_STORED_TEMPLATES = 512
MAX_WIRE_INTEGER = (1 << 53) - 1


class ChildCoachingStoreError(ValueError):
    """Malformed, unsupported or non-canonical durable template data."""


class ChildCoachingStoreConflictError(RuntimeError):
    """Durable template data changed since the caller observed it."""


class ChildCoachingStoreBusyError(RuntimeError):
    """Another process currently owns the template publication lock."""


class _StoreLockBusy(RuntimeError):
    """The OS-backed publication lock is currently owned elsewhere."""


@contextmanager
def _exclusive_store_lock(path: Path):
    """Crash-releasing cross-process advisory lock.

    The lock file may persist, but the kernel lock is released when the process
    or file descriptor exits. This avoids the permanent stale-directory lock
    failure mode of mkdir-based locking.
    """

    try:
        handle = path.open("a+b")
    except (IsADirectoryError, PermissionError, OSError) as exc:
        raise _StoreLockBusy("store publication lock is unavailable") from exc

    locked = False
    windows_lock = os.name == "nt"
    try:
        if windows_lock:
            import msvcrt

            handle.seek(0, os.SEEK_END)
            if handle.tell() == 0:
                handle.write(b"\0")
                handle.flush()
                os.fsync(handle.fileno())
            handle.seek(0)
            try:
                msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
            except OSError as exc:
                raise _StoreLockBusy("store publication lock is busy") from exc
        else:
            import fcntl

            try:
                fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            except OSError as exc:
                raise _StoreLockBusy("store publication lock is busy") from exc
        locked = True
        yield
    finally:
        if locked:
            if windows_lock:
                import msvcrt

                handle.seek(0)
                try:
                    msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
                except OSError:
                    pass
            else:
                import fcntl

                try:
                    fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
                except OSError:
                    pass
        handle.close()


def _sync_directory(path: Path) -> None:
    """Persist rename metadata on POSIX; Windows has no portable directory fsync."""

    if os.name == "nt":
        return
    flags = os.O_RDONLY | getattr(os, "O_DIRECTORY", 0)
    descriptor = os.open(path, flags)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


@dataclass(frozen=True, slots=True)
class LoadedChildCoachingTemplates:
    templates: tuple[LessonTemplate, ...]
    revision: str
    migrated_from_schema: int | None = None
    recovered_from_backup: bool = False


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
        raise ChildCoachingStoreError(
            "expected revision must be a lowercase SHA-256 digest or null"
        )
    return value


def _canonical_templates(
    templates: tuple[LessonTemplate, ...],
) -> tuple[LessonTemplate, ...]:
    if type(templates) is not tuple:
        raise TypeError("templates must be a tuple of LessonTemplate")
    if len(templates) > MAX_STORED_TEMPLATES:
        raise ChildCoachingStoreError("too many lesson templates")
    if any(type(item) is not LessonTemplate for item in templates):
        raise TypeError("templates must contain only LessonTemplate records")
    ids = [item.template_id for item in templates]
    if len(set(ids)) != len(ids):
        raise ChildCoachingStoreError("lesson template ids must be unique")
    return tuple(sorted(templates, key=lambda item: item.template_id))


def _envelope_bytes(templates: tuple[LessonTemplate, ...]) -> bytes:
    ordered = _canonical_templates(templates)
    payload = {
        "schema_version": CHILD_COACHING_STORE_SCHEMA_VERSION,
        "templates": [item.to_record() for item in ordered],
    }
    try:
        data = json.dumps(
            payload,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    except (TypeError, ValueError, UnicodeEncodeError, RecursionError) as exc:
        raise ChildCoachingStoreError(
            "lesson templates cannot be serialized for durable storage"
        ) from exc
    if len(data) > MAX_CHILD_COACHING_STORE_BYTES:
        raise ChildCoachingStoreError("lesson template store exceeds size limit")
    return data


def _reject_duplicate_pairs(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ChildCoachingStoreError(f"duplicate durable JSON key: {key}")
        result[key] = value
    return result


def _reject_constant(value):
    raise ChildCoachingStoreError(
        f"non-finite durable JSON constant is not allowed: {value}"
    )


def _parse_wire_integer(value: str) -> int:
    digits = value[1:] if value.startswith("-") else value
    if not digits or len(digits) > 16:
        raise ChildCoachingStoreError("durable JSON integer exceeds exact wire bounds")
    parsed = int(value, 10)
    if not -MAX_WIRE_INTEGER <= parsed <= MAX_WIRE_INTEGER:
        raise ChildCoachingStoreError("durable JSON integer exceeds exact wire bounds")
    return parsed


def _decode(data: bytes) -> tuple[tuple[LessonTemplate, ...], int | None]:
    if len(data) > MAX_CHILD_COACHING_STORE_BYTES:
        raise ChildCoachingStoreError("lesson template store exceeds size limit")
    try:
        payload = json.loads(
            data.decode("utf-8"),
            object_pairs_hook=_reject_duplicate_pairs,
            parse_constant=_reject_constant,
            parse_int=_parse_wire_integer,
        )
    except ChildCoachingStoreError:
        raise
    except (UnicodeDecodeError, json.JSONDecodeError, RecursionError) as exc:
        raise ChildCoachingStoreError("invalid lesson template store") from exc
    if type(payload) is not dict:
        raise ChildCoachingStoreError("invalid lesson template store envelope")

    migrated_from: int | None = None
    if "schema_version" not in payload:
        if set(payload) != {"templates"}:
            raise ChildCoachingStoreError("invalid legacy lesson template store envelope")
        schema_version = 0
        migrated_from = 0
        raw_templates = payload["templates"]
    else:
        if set(payload) != {"schema_version", "templates"}:
            raise ChildCoachingStoreError("invalid lesson template store envelope fields")
        schema_version = payload["schema_version"]
        if type(schema_version) is not int:
            raise ChildCoachingStoreError("lesson template store schema must be an integer")
        if schema_version != CHILD_COACHING_STORE_SCHEMA_VERSION:
            raise ChildCoachingStoreError(
                f"unsupported lesson template store schema version: {schema_version!r}"
            )
        raw_templates = payload["templates"]

    if type(raw_templates) is not list or len(raw_templates) > MAX_STORED_TEMPLATES:
        raise ChildCoachingStoreError("lesson template store templates must be a bounded array")
    try:
        templates = tuple(LessonTemplate.from_record(item) for item in raw_templates)
    except ChildCoachingError as exc:
        raise ChildCoachingStoreError("invalid lesson template payload") from exc
    return _canonical_templates(templates), migrated_from


class ChildCoachingTemplateStore:
    """Atomic CAS store with one known-valid previous snapshot for recovery.

    expected_revision=None is create-only. Updates require the exact revision
    returned by load/save. Before replacing a valid primary snapshot the prior
    bytes are atomically copied to a .bak file. A corrupt primary can therefore
    be recovered explicitly without allowing a stale writer to overwrite newer
    bytes.
    """

    def __init__(self, path: str | Path) -> None:
        if not isinstance(path, (str, Path)):
            raise TypeError("path must be a filesystem path")
        self.path = Path(path).expanduser()
        if str(self.path) in {"", "."}:
            raise ValueError("path must identify a child-coaching template file")
        self._lock_path = self.path.with_name(f".{self.path.name}.lock")
        self._backup_path = self.path.with_name(f"{self.path.name}.bak")

    def _read_bounded(self, path: Path) -> bytes | None:
        try:
            with path.open("rb") as handle:
                data = handle.read(MAX_CHILD_COACHING_STORE_BYTES + 1)
        except FileNotFoundError:
            return None
        if len(data) > MAX_CHILD_COACHING_STORE_BYTES:
            raise ChildCoachingStoreError("lesson template store exceeds size limit")
        return data

    def load(self) -> LoadedChildCoachingTemplates | None:
        primary = self._read_bounded(self.path)
        if primary is None:
            return None
        primary_revision = _revision(primary)
        try:
            templates, migrated_from = _decode(primary)
            return LoadedChildCoachingTemplates(
                templates=templates,
                revision=primary_revision,
                migrated_from_schema=migrated_from,
                recovered_from_backup=False,
            )
        except ChildCoachingStoreError as primary_error:
            backup = self._read_bounded(self._backup_path)
            if backup is None:
                raise primary_error
            try:
                templates, migrated_from = _decode(backup)
            except ChildCoachingStoreError:
                raise primary_error
            # Preserve the actual corrupt-primary revision so repair remains an
            # exact CAS operation rather than a blind overwrite.
            return LoadedChildCoachingTemplates(
                templates=templates,
                revision=primary_revision,
                migrated_from_schema=migrated_from,
                recovered_from_backup=True,
            )

    def save(
        self,
        templates: tuple[LessonTemplate, ...],
        *,
        expected_revision: str | None,
    ) -> str:
        expected = _validate_revision(expected_revision)
        data = _envelope_bytes(templates)
        new_revision = _revision(data)
        self.path.parent.mkdir(parents=True, exist_ok=True)

        try:
            with _exclusive_store_lock(self._lock_path):
                temporary: Path | None = None
                backup_temporary: Path | None = None
                try:
                    current = self._read_bounded(self.path)
                    current_revision = None if current is None else _revision(current)
                    if current_revision != expected:
                        raise ChildCoachingStoreConflictError(
                            "lesson templates changed since the caller last observed them"
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

                    # Never replace a good backup with corrupt primary bytes.
                    if current is not None:
                        try:
                            _decode(current)
                        except ChildCoachingStoreError:
                            pass
                        else:
                            bfd, braw = tempfile.mkstemp(
                                prefix=f".{self._backup_path.name}.",
                                suffix=".tmp",
                                dir=str(self.path.parent),
                            )
                            backup_temporary = Path(braw)
                            try:
                                with os.fdopen(bfd, "wb") as handle:
                                    handle.write(current)
                                    handle.flush()
                                    os.fsync(handle.fileno())
                            except Exception:
                                if backup_temporary.exists():
                                    backup_temporary.unlink()
                                backup_temporary = None
                                raise
                            os.replace(backup_temporary, self._backup_path)
                            backup_temporary = None
                            _sync_directory(self.path.parent)

                    os.replace(temporary, self.path)
                    temporary = None
                    _sync_directory(self.path.parent)
                    return new_revision
                finally:
                    if temporary is not None and temporary.exists():
                        temporary.unlink()
                    if backup_temporary is not None and backup_temporary.exists():
                        backup_temporary.unlink()
        except _StoreLockBusy as exc:
            raise ChildCoachingStoreBusyError(
                "lesson template store is busy"
            ) from exc

