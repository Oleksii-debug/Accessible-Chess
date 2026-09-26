from __future__ import annotations

"""Crash-safe local persistence for :mod:`acs.learning_mastery`.

The mastery domain owns schema/digest validation. This module owns filesystem
publication and optimistic concurrency only. Writes use a persistent advisory
lock, exact observed-revision compare-and-swap, fsync, and atomic replace.
Symlink/reparse targets fail closed rather than redirecting mastery data.
"""

from contextlib import contextmanager
from dataclasses import dataclass
import hashlib
import os
from pathlib import Path
import stat
import tempfile
from typing import Iterator

from .learning_mastery import MasteryState


MAX_MASTERY_STORE_BYTES = 2 * 1024 * 1024


class MasteryStoreConflictError(RuntimeError):
    pass


class MasteryStoreBusyError(RuntimeError):
    pass


class MasteryStoreResourceError(ValueError):
    pass


@dataclass(frozen=True, slots=True)
class LoadedMastery:
    state: MasteryState
    revision: str


def _revision(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _validate_revision(value: str | None) -> str | None:
    if value is None:
        return None
    if (
        type(value) is not str
        or len(value) != 64
        or value != value.lower()
        or any(ch not in "0123456789abcdef" for ch in value)
    ):
        raise ValueError("expected_revision must be a lowercase SHA-256 digest or None")
    return value


def _is_reparse(metadata: os.stat_result) -> bool:
    flag = getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400)
    return bool(getattr(metadata, "st_file_attributes", 0) & flag)


def _windows_open_no_reparse(path: Path, *, create: bool) -> int:
    import ctypes
    from ctypes import wintypes
    import msvcrt

    GENERIC_READ = 0x80000000
    GENERIC_WRITE = 0x40000000
    FILE_SHARE_READ = 0x00000001
    FILE_SHARE_WRITE = 0x00000002
    FILE_SHARE_DELETE = 0x00000004
    OPEN_EXISTING = 3
    OPEN_ALWAYS = 4
    FILE_ATTRIBUTE_NORMAL = 0x00000080
    FILE_ATTRIBUTE_REPARSE_POINT = 0x00000400
    FILE_FLAG_OPEN_REPARSE_POINT = 0x00200000
    FILE_TYPE_DISK = 0x0001
    FILE_ATTRIBUTE_TAG_INFO_CLASS = 9
    ERROR_FILE_NOT_FOUND = 2
    ERROR_PATH_NOT_FOUND = 3

    class FILE_ATTRIBUTE_TAG_INFO(ctypes.Structure):
        _fields_ = [
            ("FileAttributes", wintypes.DWORD),
            ("ReparseTag", wintypes.DWORD),
        ]

    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    create_file = kernel32.CreateFileW
    create_file.argtypes = [
        wintypes.LPCWSTR,
        wintypes.DWORD,
        wintypes.DWORD,
        ctypes.c_void_p,
        wintypes.DWORD,
        wintypes.DWORD,
        wintypes.HANDLE,
    ]
    create_file.restype = wintypes.HANDLE

    get_file_type = kernel32.GetFileType
    get_file_type.argtypes = [wintypes.HANDLE]
    get_file_type.restype = wintypes.DWORD

    get_info = kernel32.GetFileInformationByHandleEx
    get_info.argtypes = [
        wintypes.HANDLE,
        ctypes.c_int,
        ctypes.c_void_p,
        wintypes.DWORD,
    ]
    get_info.restype = wintypes.BOOL

    close_handle = kernel32.CloseHandle
    close_handle.argtypes = [wintypes.HANDLE]
    close_handle.restype = wintypes.BOOL

    handle = create_file(
        str(path),
        GENERIC_READ | (GENERIC_WRITE if create else 0),
        FILE_SHARE_READ | FILE_SHARE_WRITE | FILE_SHARE_DELETE,
        None,
        OPEN_ALWAYS if create else OPEN_EXISTING,
        FILE_ATTRIBUTE_NORMAL | FILE_FLAG_OPEN_REPARSE_POINT,
        None,
    )
    invalid = ctypes.c_void_p(-1).value
    if handle == invalid:
        error = ctypes.get_last_error()
        if error in {ERROR_FILE_NOT_FOUND, ERROR_PATH_NOT_FOUND}:
            raise FileNotFoundError(error, "mastery storage is unavailable", str(path))
        raise OSError(error, "mastery storage could not be opened")

    transferred = False
    try:
        if get_file_type(handle) != FILE_TYPE_DISK:
            raise OSError("mastery storage is not a disk file")
        info = FILE_ATTRIBUTE_TAG_INFO()
        if not get_info(
            handle,
            FILE_ATTRIBUTE_TAG_INFO_CLASS,
            ctypes.byref(info),
            ctypes.sizeof(info),
        ):
            error = ctypes.get_last_error()
            raise OSError(error, "mastery storage could not be inspected")
        if info.FileAttributes & FILE_ATTRIBUTE_REPARSE_POINT:
            raise OSError("mastery storage is a reparse point")
        flags = (os.O_RDWR if create else os.O_RDONLY)
        flags |= getattr(os, "O_BINARY", 0)
        flags |= getattr(os, "O_NOINHERIT", 0)
        descriptor = msvcrt.open_osfhandle(int(handle), flags)
        transferred = True
        return descriptor
    finally:
        if not transferred:
            close_handle(handle)


def _open_no_reparse(path: Path, *, create: bool) -> int:
    if os.name == "nt":
        return _windows_open_no_reparse(path, create=create)
    flags = (os.O_RDWR | os.O_CREAT) if create else os.O_RDONLY
    flags |= getattr(os, "O_CLOEXEC", 0)
    flags |= getattr(os, "O_NOFOLLOW", 0)
    return os.open(path, flags, 0o600) if create else os.open(path, flags)


def _require_regular(metadata: os.stat_result, *, label: str) -> None:
    if (
        stat.S_ISLNK(metadata.st_mode)
        or _is_reparse(metadata)
        or not stat.S_ISREG(metadata.st_mode)
    ):
        raise ValueError(f"{label} is not a direct regular file")


class MasteryStore:
    def __init__(self, path: str | Path) -> None:
        if not isinstance(path, (str, Path)):
            raise TypeError("path must be a filesystem path")
        self.path = Path(path).expanduser()
        if str(self.path) in {"", "."}:
            raise ValueError("path must identify a mastery file")
        self._lock_path = self.path.with_name(f".{self.path.name}.lock")

    def _read_bytes(self, *, missing_ok: bool) -> bytes | None:
        try:
            descriptor = _open_no_reparse(self.path, create=False)
        except FileNotFoundError:
            if missing_ok:
                return None
            raise ValueError("mastery file is unavailable")
        except OSError as exc:
            raise ValueError("mastery file could not be inspected") from exc

        try:
            metadata = os.fstat(descriptor)
            _require_regular(metadata, label="mastery storage")
            if metadata.st_size > MAX_MASTERY_STORE_BYTES:
                raise MasteryStoreResourceError("mastery file exceeds the resource limit")
            chunks: list[bytes] = []
            remaining = MAX_MASTERY_STORE_BYTES + 1
            while remaining:
                chunk = os.read(descriptor, min(64 * 1024, remaining))
                if not chunk:
                    break
                chunks.append(chunk)
                remaining -= len(chunk)
            data = b"".join(chunks)
            if len(data) > MAX_MASTERY_STORE_BYTES:
                raise MasteryStoreResourceError("mastery file exceeds the resource limit")
            return data
        except OSError as exc:
            raise ValueError("mastery file could not be read") from exc
        finally:
            os.close(descriptor)

    def load(self) -> LoadedMastery | None:
        data = self._read_bytes(missing_ok=True)
        if data is None:
            return None
        try:
            text = data.decode("utf-8")
        except UnicodeDecodeError as exc:
            raise ValueError("mastery file is not valid UTF-8") from exc
        state = MasteryState.from_json(text)
        return LoadedMastery(state=state, revision=_revision(data))

    def _open_lock_descriptor(self) -> int:
        try:
            descriptor = _open_no_reparse(self._lock_path, create=True)
        except OSError as exc:
            raise MasteryStoreBusyError("mastery store is busy") from exc
        try:
            metadata = os.fstat(descriptor)
            _require_regular(metadata, label="mastery lock")
            if metadata.st_size == 0:
                os.write(descriptor, b"\0")
                os.fsync(descriptor)
            return descriptor
        except BaseException:
            os.close(descriptor)
            raise

    @staticmethod
    def _lock(descriptor: int) -> None:
        try:
            if os.name == "nt":
                import msvcrt

                os.lseek(descriptor, 0, os.SEEK_SET)
                msvcrt.locking(descriptor, msvcrt.LK_NBLCK, 1)
            else:
                import fcntl

                fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except (OSError, BlockingIOError) as exc:
            raise MasteryStoreBusyError("mastery store is busy") from exc

    @staticmethod
    def _unlock(descriptor: int) -> None:
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
    def _exclusive_access(self) -> Iterator[None]:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        descriptor = self._open_lock_descriptor()
        acquired = False
        try:
            self._lock(descriptor)
            acquired = True
            yield
        finally:
            if acquired:
                self._unlock(descriptor)
            os.close(descriptor)

    def save(self, state: MasteryState, *, expected_revision: str | None) -> str:
        if type(state) is not MasteryState:
            raise TypeError("state must be MasteryState")
        expected = _validate_revision(expected_revision)
        data = state.to_json().encode("utf-8")
        if len(data) > MAX_MASTERY_STORE_BYTES:
            raise MasteryStoreResourceError("mastery snapshot exceeds the resource limit")
        new_revision = _revision(data)

        temporary: Path | None = None
        with self._exclusive_access():
            try:
                current = self._read_bytes(missing_ok=True)
                current_revision = None if current is None else _revision(current)
                if current_revision != expected:
                    raise MasteryStoreConflictError(
                        "mastery changed since the caller last observed it"
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
                    try:
                        temporary.unlink()
                    except FileNotFoundError:
                        pass
                    temporary = None
                    raise

                publication_base = self._read_bytes(missing_ok=True)
                publication_revision = (
                    None if publication_base is None else _revision(publication_base)
                )
                if publication_revision != current_revision:
                    raise MasteryStoreConflictError(
                        "mastery changed during publication"
                    )

                os.replace(temporary, self.path)
                temporary = None
                self._fsync_parent_directory()
                return new_revision
            finally:
                if temporary is not None:
                    try:
                        temporary.unlink()
                    except FileNotFoundError:
                        pass

    def _fsync_parent_directory(self) -> None:
        if os.name == "nt":
            return
        flags = os.O_RDONLY | getattr(os, "O_DIRECTORY", 0)
        try:
            descriptor = os.open(self.path.parent, flags)
        except OSError:
            return
        try:
            os.fsync(descriptor)
        except OSError:
            pass
        finally:
            os.close(descriptor)


__all__ = [
    "LoadedMastery",
    "MasteryStore",
    "MasteryStoreBusyError",
    "MasteryStoreConflictError",
    "MasteryStoreResourceError",
]
