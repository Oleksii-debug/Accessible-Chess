from __future__ import annotations

"""Filesystem primitives for release publication that must never replace output."""

import ctypes
import errno
import os
from pathlib import Path
import stat
import sys


_AT_FDCWD = -100
_RENAME_NOREPLACE = 1
_WINDOWS_ALREADY_EXISTS = frozenset({80, 145, 183})


class AtomicPublicationError(RuntimeError):
    """Raised when a validated directory cannot be published without replacement."""


def _fail(message: str) -> None:
    raise AtomicPublicationError(message)


def _reparse(info: os.stat_result) -> bool:
    flag = getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400)
    return bool(getattr(info, "st_file_attributes", 0) & flag)


def _entry_exists(path: Path) -> bool:
    try:
        path.lstat()
    except FileNotFoundError:
        return False
    except OSError as exc:
        _fail(f"publication destination cannot be inspected: {type(exc).__name__}")
    return True


def _require_directory(path: Path, *, label: str) -> None:
    try:
        info = path.lstat()
    except OSError as exc:
        _fail(f"{label} cannot be inspected: {type(exc).__name__}")
    if stat.S_ISLNK(info.st_mode) or _reparse(info) or not stat.S_ISDIR(info.st_mode):
        _fail(f"{label} must be a real directory")


def publish_directory_no_replace(staged: str | Path, output: str | Path) -> None:
    """Atomically publish a staged directory without replacing any output entry.

    Source and destination must be siblings on the same filesystem because an
    atomic rename is required. Existing files, directories, links, or reparse
    points at the destination are never replaced.
    """

    source = Path(staged)
    destination = Path(output)
    _require_directory(source, label="staged publication directory")

    try:
        source_parent = source.parent.resolve(strict=True)
        destination_parent = destination.parent.resolve(strict=True)
    except (OSError, RuntimeError) as exc:
        _fail(f"publication parent cannot be resolved: {type(exc).__name__}")
    if source_parent != destination_parent:
        _fail("staged publication directory and destination must share one parent")

    if os.name == "nt":
        from ctypes import wintypes

        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        move_file_ex = kernel32.MoveFileExW
        move_file_ex.argtypes = [wintypes.LPCWSTR, wintypes.LPCWSTR, wintypes.DWORD]
        move_file_ex.restype = wintypes.BOOL
        if move_file_ex(str(source), str(destination), 0):
            return
        error = ctypes.get_last_error()
        if error in _WINDOWS_ALREADY_EXISTS or _entry_exists(destination):
            _fail("publication destination appeared and will not be overwritten")
        _fail(f"validated directory could not be published atomically: WinError {error}")

    if sys.platform.startswith("linux"):
        libc = ctypes.CDLL(None, use_errno=True)
        renameat2 = getattr(libc, "renameat2", None)
        if renameat2 is None:
            _fail("atomic no-overwrite directory publication is unsupported")
        renameat2.argtypes = [
            ctypes.c_int,
            ctypes.c_char_p,
            ctypes.c_int,
            ctypes.c_char_p,
            ctypes.c_uint,
        ]
        renameat2.restype = ctypes.c_int
        result = renameat2(
            _AT_FDCWD,
            os.fsencode(source),
            _AT_FDCWD,
            os.fsencode(destination),
            _RENAME_NOREPLACE,
        )
        if result == 0:
            return
        error = ctypes.get_errno()
        if error in {errno.EEXIST, errno.ENOTEMPTY} or _entry_exists(destination):
            _fail("publication destination appeared and will not be overwritten")
        _fail(
            "validated directory could not be published atomically: "
            + errno.errorcode.get(error, "OSERROR")
        )

    _fail("atomic no-overwrite directory publication is unsupported on this platform")


__all__ = ["AtomicPublicationError", "publish_directory_no_replace"]
