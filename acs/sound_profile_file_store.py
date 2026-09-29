from __future__ import annotations

"""Atomic bounded JSON persistence for SoundProfileManager."""

from collections.abc import Mapping
from contextlib import contextmanager
import json
import os
from pathlib import Path
import stat
import tempfile
import threading
from typing import Iterator

from .sound_profiles import SoundProfile


MAX_SOUND_PROFILE_BYTES = 256 * 1024
_MALFORMED_SCHEMA_MARKER = "__malformed_sound_profile_storage__"

_PROCESS_LOCKS_GUARD = threading.Lock()
_PROCESS_LOCKS: dict[str, threading.RLock] = {}


class SoundProfileFileError(ValueError):
    """Stable local profile persistence failure without path disclosure."""


def _is_reparse_point(metadata: os.stat_result) -> bool:
    flag = getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0)
    attributes = getattr(metadata, "st_file_attributes", 0)
    return bool(flag and attributes & flag)


def _require_regular_metadata(
    metadata: os.stat_result,
    *,
    message: str,
) -> None:
    if (
        stat.S_ISLNK(metadata.st_mode)
        or _is_reparse_point(metadata)
        or not stat.S_ISREG(metadata.st_mode)
    ):
        raise SoundProfileFileError(message)


def _process_lock_for(path: Path) -> threading.RLock:
    key = os.path.normcase(os.path.abspath(os.fspath(path)))
    with _PROCESS_LOCKS_GUARD:
        lock = _PROCESS_LOCKS.get(key)
        if lock is None:
            lock = threading.RLock()
            _PROCESS_LOCKS[key] = lock
        return lock


def _reject_duplicate_pairs(
    pairs: list[tuple[str, object]],
) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise SoundProfileFileError(
                "sound profile contains duplicate JSON object keys"
            )
        result[key] = value
    return result


def _malformed_payload() -> dict[str, object]:
    return {"schema_version": _MALFORMED_SCHEMA_MARKER}


class JsonSoundProfileStorage:
    """Concrete SoundProfileStoragePort backed by one atomic JSON file.

    Malformed or resource-invalid JSON is projected as a deliberately invalid
    current-process payload. SoundProfileManager then applies its normal
    MALFORMED recovery path and atomically replaces it with a canonical profile.
    A syntactically valid future-schema object is returned unchanged so the
    manager can block ordinary writes and preserve forward compatibility.
    """

    def __init__(
        self,
        path: str | os.PathLike[str],
        *,
        max_bytes: int = MAX_SOUND_PROFILE_BYTES,
    ) -> None:
        if not isinstance(path, (str, os.PathLike)):
            raise TypeError("sound profile path must be path-like")
        if isinstance(max_bytes, bool) or not isinstance(max_bytes, int):
            raise TypeError("max_bytes must be an integer")
        if max_bytes <= 0:
            raise ValueError("max_bytes must be positive")
        self.path = Path(path)
        self.max_bytes = max_bytes
        self._process_lock = _process_lock_for(self.path)

    @property
    def _lock_path(self) -> Path:
        return self.path.with_name(self.path.name + ".lock")

    @staticmethod
    def _lock_descriptor(descriptor: int) -> None:
        try:
            if os.name == "nt":
                import msvcrt

                os.lseek(descriptor, 0, os.SEEK_SET)
                msvcrt.locking(descriptor, msvcrt.LK_LOCK, 1)
            else:
                import fcntl

                fcntl.flock(descriptor, fcntl.LOCK_EX)
        except OSError as exc:
            raise SoundProfileFileError(
                "sound profile storage is busy"
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

    def _open_lock_descriptor(self) -> int:
        try:
            existing = os.lstat(self._lock_path)
        except FileNotFoundError:
            existing = None
        except OSError as exc:
            raise SoundProfileFileError(
                "sound profile storage lock is unavailable"
            ) from exc
        if existing is not None:
            _require_regular_metadata(
                existing,
                message="sound profile storage lock is not a regular file",
            )

        flags = os.O_RDWR | os.O_CREAT
        flags |= getattr(os, "O_BINARY", 0)
        flags |= getattr(os, "O_NOINHERIT", 0)
        flags |= getattr(os, "O_CLOEXEC", 0)
        flags |= getattr(os, "O_NOFOLLOW", 0)
        try:
            descriptor = os.open(self._lock_path, flags, 0o600)
        except OSError as exc:
            raise SoundProfileFileError(
                "sound profile storage lock is unavailable"
            ) from exc
        try:
            metadata = os.fstat(descriptor)
            _require_regular_metadata(
                metadata,
                message="sound profile storage lock is not a regular file",
            )
            if metadata.st_size == 0:
                os.write(descriptor, b"\0")
                os.fsync(descriptor)
            return descriptor
        except BaseException:
            os.close(descriptor)
            raise

    @contextmanager
    def _exclusive_access(self) -> Iterator[None]:
        with self._process_lock:
            try:
                self.path.parent.mkdir(parents=True, exist_ok=True)
            except OSError as exc:
                raise SoundProfileFileError(
                    "sound profile storage is unavailable"
                ) from exc
            descriptor = self._open_lock_descriptor()
            acquired = False
            try:
                self._lock_descriptor(descriptor)
                acquired = True
                yield
            finally:
                if acquired:
                    self._unlock_descriptor(descriptor)
                os.close(descriptor)

    def _read_raw(self) -> bytes | None:
        try:
            metadata = os.lstat(self.path)
        except FileNotFoundError:
            return None
        except OSError as exc:
            raise SoundProfileFileError(
                "sound profile storage is unavailable"
            ) from exc
        _require_regular_metadata(
            metadata,
            message="sound profile storage is not a regular file",
        )
        if metadata.st_size > self.max_bytes:
            return b""

        flags = os.O_RDONLY
        flags |= getattr(os, "O_BINARY", 0)
        flags |= getattr(os, "O_NOINHERIT", 0)
        flags |= getattr(os, "O_CLOEXEC", 0)
        flags |= getattr(os, "O_NOFOLLOW", 0)
        try:
            descriptor = os.open(self.path, flags)
        except OSError as exc:
            raise SoundProfileFileError(
                "sound profile storage could not be read"
            ) from exc
        try:
            opened = os.fstat(descriptor)
            _require_regular_metadata(
                opened,
                message="sound profile storage is not a regular file",
            )
            if opened.st_size > self.max_bytes:
                return b""
            with os.fdopen(descriptor, "rb", closefd=False) as stream:
                raw = stream.read(self.max_bytes + 1)
            if len(raw) > self.max_bytes:
                return b""
            return raw
        except SoundProfileFileError:
            raise
        except OSError as exc:
            raise SoundProfileFileError(
                "sound profile storage could not be read"
            ) from exc
        finally:
            os.close(descriptor)

    def read_profile(self) -> Mapping[str, object] | None:
        raw = self._read_raw()
        if raw is None:
            return None
        if not raw:
            return _malformed_payload()
        try:
            parsed = json.loads(
                raw.decode("utf-8"),
                object_pairs_hook=_reject_duplicate_pairs,
                parse_constant=lambda value: (_ for _ in ()).throw(
                    SoundProfileFileError(
                        f"sound profile contains non-finite JSON: {value}"
                    )
                ),
            )
        except (
            SoundProfileFileError,
            UnicodeDecodeError,
            json.JSONDecodeError,
            RecursionError,
        ):
            return _malformed_payload()
        if not isinstance(parsed, Mapping) or any(
            type(key) is not str for key in parsed
        ):
            return _malformed_payload()
        return dict(parsed)

    def _canonical_bytes(
        self,
        payload: Mapping[str, object],
    ) -> bytes:
        if not isinstance(payload, Mapping):
            raise TypeError("sound profile payload must be a mapping")
        try:
            profile = SoundProfile.from_mapping(payload)
        except (TypeError, ValueError, OverflowError) as exc:
            raise SoundProfileFileError(
                "only a valid current sound profile may be persisted"
            ) from exc
        canonical = profile.to_mapping()
        if dict(payload) != canonical:
            raise SoundProfileFileError(
                "sound profile payload must already be canonical"
            )
        try:
            encoded = (
                json.dumps(
                    canonical,
                    ensure_ascii=False,
                    sort_keys=True,
                    separators=(",", ":"),
                    allow_nan=False,
                )
                + "\n"
            ).encode("utf-8")
        except (TypeError, ValueError, UnicodeEncodeError) as exc:
            raise SoundProfileFileError(
                "sound profile payload cannot be serialized"
            ) from exc
        if len(encoded) > self.max_bytes:
            raise SoundProfileFileError(
                "sound profile payload exceeds the resource limit"
            )
        return encoded

    def write_profile_atomically(
        self,
        payload: Mapping[str, object],
    ) -> None:
        encoded = self._canonical_bytes(payload)
        with self._exclusive_access():
            try:
                existing = os.lstat(self.path)
            except FileNotFoundError:
                existing = None
            except OSError as exc:
                raise SoundProfileFileError(
                    "sound profile storage is unavailable"
                ) from exc
            if existing is not None:
                _require_regular_metadata(
                    existing,
                    message="sound profile storage is not a regular file",
                )

            temp_path: Path | None = None
            try:
                descriptor, temp_name = tempfile.mkstemp(
                    prefix=f".{self.path.name}.",
                    suffix=".tmp",
                    dir=self.path.parent,
                )
                temp_path = Path(temp_name)
                with os.fdopen(descriptor, "wb") as stream:
                    stream.write(encoded)
                    stream.flush()
                    os.fsync(stream.fileno())
                os.replace(temp_path, self.path)
                temp_path = None
            except OSError as exc:
                raise SoundProfileFileError(
                    "sound profile storage could not be updated"
                ) from exc
            finally:
                if temp_path is not None:
                    try:
                        temp_path.unlink(missing_ok=True)
                    except OSError:
                        pass
