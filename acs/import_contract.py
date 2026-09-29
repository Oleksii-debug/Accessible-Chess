from __future__ import annotations

"""Read-only import contract for external chess database families.

This module establishes the safety and reporting boundary every format adapter
must obey: never mutate the source, preserve provenance, and report full/
partial/damaged outcomes explicitly instead of silently dropping records.
Semantic CBH and CBV import lives behind separately configured external
backends; the placeholder below remains the fail-closed registry adapter used
when those optional backends are not configured.
"""

from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Iterable, Protocol
import hashlib
import os
import stat


class ImportQuality(str, Enum):
    FULL = "full"
    PARTIAL = "partial"
    DAMAGED = "damaged"
    WARNING = "warning"


@dataclass(frozen=True)
class SourceFingerprint:
    path: str
    size: int
    sha256: str
    suffix: str


@dataclass(frozen=True)
class ImportedRecord:
    source_record_id: str
    quality: ImportQuality
    game_id: int | None = None
    message: str = ""
    warnings: tuple[str, ...] = ()


@dataclass
class ImportReport:
    source: SourceFingerprint
    format_name: str
    records: list[ImportedRecord] = field(default_factory=list)
    global_warnings: list[str] = field(default_factory=list)

    def add(self, record: ImportedRecord) -> None:
        self.records.append(record)

    @property
    def counts(self) -> dict[str, int]:
        result = {quality.value: 0 for quality in ImportQuality}
        for record in self.records:
            result[record.quality.value] += 1
        return result

    @property
    def total(self) -> int:
        return len(self.records)

    @property
    def has_damage(self) -> bool:
        return any(record.quality is ImportQuality.DAMAGED for record in self.records)


class ReadOnlyImporter(Protocol):
    format_name: str
    suffixes: tuple[str, ...]

    def inspect(self, path: Path) -> ImportReport:
        ...


def _is_reparse_point(st: os.stat_result) -> bool:
    attrs = getattr(st, "st_file_attributes", 0)
    marker = getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400)
    return bool(attrs & marker)


def _lexical_absolute(path: Path) -> Path:
    return Path(os.path.abspath(os.fspath(path.expanduser())))


def _validate_source_path(path: Path) -> tuple[Path, os.stat_result]:
    """Reject filesystem indirection and non-regular external sources.

    Validation is intentionally lexical: it must not call ``resolve()`` before
    deciding whether any path component is a symlink/reparse point.
    """

    absolute = _lexical_absolute(path)
    parts = absolute.parts
    if not parts:
        raise ValueError("Import source path is empty")

    current = Path(parts[0])
    for part in parts[1:]:
        current = current / part
        try:
            st = current.lstat()
        except FileNotFoundError:
            if current == absolute:
                raise
            continue
        if stat.S_ISLNK(st.st_mode) or _is_reparse_point(st):
            raise ValueError("Import source must not traverse filesystem indirection")

    leaf = absolute.lstat()
    if stat.S_ISLNK(leaf.st_mode) or _is_reparse_point(leaf):
        raise ValueError("Import source must not be a symlink or reparse point")
    if not stat.S_ISREG(leaf.st_mode):
        raise ValueError("Import source must be a regular file")
    return absolute, leaf



def _windows_open_readonly_no_reparse(path: Path) -> int:
    """Open one Windows disk file without following the final reparse point.

    Validation is performed on the opened Windows handle before conversion to a
    CRT descriptor.  A path that becomes a reparse object after lexical checks
    therefore cannot redirect source-byte reads through its target.
    """

    import ctypes
    from ctypes import wintypes
    import msvcrt

    GENERIC_READ = 0x80000000
    FILE_SHARE_READ = 0x00000001
    FILE_SHARE_WRITE = 0x00000002
    FILE_SHARE_DELETE = 0x00000004
    OPEN_EXISTING = 3
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
        GENERIC_READ,
        FILE_SHARE_READ | FILE_SHARE_WRITE | FILE_SHARE_DELETE,
        None,
        OPEN_EXISTING,
        FILE_ATTRIBUTE_NORMAL | FILE_FLAG_OPEN_REPARSE_POINT,
        None,
    )
    invalid = ctypes.c_void_p(-1).value
    if handle == invalid:
        error = ctypes.get_last_error()
        if error in {ERROR_FILE_NOT_FOUND, ERROR_PATH_NOT_FOUND}:
            raise FileNotFoundError(error, "could not open import source", str(path))
        raise OSError(error, "could not open import source")

    transferred = False
    try:
        if get_file_type(handle) != FILE_TYPE_DISK:
            raise ValueError("Import source must be a regular disk file")
        info = FILE_ATTRIBUTE_TAG_INFO()
        if not get_info(
            handle,
            FILE_ATTRIBUTE_TAG_INFO_CLASS,
            ctypes.byref(info),
            ctypes.sizeof(info),
        ):
            error = ctypes.get_last_error()
            raise OSError(error, "could not inspect opened import source")
        if info.FileAttributes & FILE_ATTRIBUTE_REPARSE_POINT:
            raise ValueError("Import source must not be a symlink or reparse point")

        flags = os.O_RDONLY
        flags |= getattr(os, "O_BINARY", 0)
        flags |= getattr(os, "O_NOINHERIT", 0)
        descriptor = msvcrt.open_osfhandle(int(handle), flags)
        transferred = True
        return descriptor
    finally:
        if not transferred:
            close_handle(handle)


def _open_readonly_no_reparse(path: Path) -> int:
    """Open an existing source so the opened object is the authority."""

    if os.name == "nt":
        return _windows_open_readonly_no_reparse(path)

    nofollow = getattr(os, "O_NOFOLLOW", None)
    if nofollow is None:
        raise OSError("no-follow source open is unavailable")
    flags = os.O_RDONLY | nofollow
    flags |= getattr(os, "O_BINARY", 0)
    flags |= getattr(os, "O_CLOEXEC", 0)
    return os.open(os.fspath(path), flags)


def _publish_opened_fingerprint(
    submitted: Path,
    absolute: Path,
    path_before: os.stat_result,
    fd_before: os.stat_result,
    fd_after: os.stat_result,
    verified_sha256: str,
) -> SourceFingerprint:
    """Publish provenance only when one opened object and its public path stay stable."""

    path_after = absolute.lstat()
    stable_fd = (
        fd_before.st_dev == fd_after.st_dev
        and fd_before.st_ino == fd_after.st_ino
        and fd_before.st_size == fd_after.st_size
        and fd_before.st_mtime_ns == fd_after.st_mtime_ns
    )
    stable_path = (
        path_before.st_dev == path_after.st_dev
        and path_before.st_ino == path_after.st_ino
        and path_before.st_size == path_after.st_size
        and path_before.st_mtime_ns == path_after.st_mtime_ns
        and not stat.S_ISLNK(path_after.st_mode)
        and not _is_reparse_point(path_after)
    )
    if not stable_fd or not stable_path:
        raise ValueError("Import source changed while fingerprinting")

    public_path = absolute.resolve(strict=True)
    _, absolute_publication_stat = _validate_source_path(absolute)
    public_absolute, public_stat = _validate_source_path(public_path)
    expected_identity = (fd_after.st_dev, fd_after.st_ino)
    if (
        (absolute_publication_stat.st_dev, absolute_publication_stat.st_ino)
        != expected_identity
        or (public_stat.st_dev, public_stat.st_ino) != expected_identity
    ):
        raise ValueError("Import source changed before provenance publication")

    return SourceFingerprint(
        path=str(public_absolute),
        size=fd_after.st_size,
        sha256=verified_sha256,
        suffix=submitted.suffix.lower(),
    )


def fingerprint(path: str | Path, chunk_size: int = 1024 * 1024) -> SourceFingerprint:
    if chunk_size <= 0:
        raise ValueError("chunk_size must be positive")

    submitted = Path(path)
    absolute, path_before = _validate_source_path(submitted)
    fd = _open_readonly_no_reparse(absolute)
    try:
        fd_before = os.fstat(fd)
        if not stat.S_ISREG(fd_before.st_mode):
            raise ValueError("Import source must be a regular file")
        if (fd_before.st_dev, fd_before.st_ino) != (path_before.st_dev, path_before.st_ino):
            raise ValueError("Import source changed before it could be opened safely")

        def digest_open_inode() -> str:
            digest = hashlib.sha256()
            while True:
                chunk = os.read(fd, chunk_size)
                if not chunk:
                    return digest.hexdigest()
                digest.update(chunk)

        first_sha256 = digest_open_inode()

        # A same-size in-place writer can race inside the first hash pass and,
        # on filesystems with coarse timestamp updates, leave mtime_ns looking
        # unchanged. Re-hash the exact already-open inode so provenance is
        # published only when two complete byte snapshots agree.
        os.lseek(fd, 0, os.SEEK_SET)
        verified_sha256 = digest_open_inode()
        if first_sha256 != verified_sha256:
            raise ValueError("Import source changed while fingerprinting")
        fd_after = os.fstat(fd)
    finally:
        os.close(fd)

    return _publish_opened_fingerprint(
        submitted,
        absolute,
        path_before,
        fd_before,
        fd_after,
        verified_sha256,
    )


def verify_source_unchanged(before: SourceFingerprint, path: str | Path) -> bool:
    after = fingerprint(path)
    return before.size == after.size and before.sha256 == after.sha256


class UnsupportedChessBaseImporter:
    """Safety placeholder used when no verified external decoder is configured.

    It recognizes ChessBase-family suffixes but intentionally refuses to claim
    successful decoding. This prevents future UI code from treating an
    unimplemented or heuristic parser as full compatibility.
    """

    format_name = "ChessBase family (optional decoder not configured)"
    suffixes = (".cbh", ".cbv", ".cbf", ".2cbh", ".cbone")

    def inspect(self, path: Path) -> ImportReport:
        source = fingerprint(path)
        report = ImportReport(source=source, format_name=self.format_name)
        if source.suffix not in self.suffixes:
            report.global_warnings.append(f"Unsupported suffix: {source.suffix or '<none>'}")
            return report
        report.add(
            ImportedRecord(
                source_record_id="container",
                quality=ImportQuality.WARNING,
                message="Recognized ChessBase-family source; optional verified decoder is not configured.",
                warnings=("No source bytes were modified.",),
            )
        )
        return report


def summarize_reports(reports: Iterable[ImportReport]) -> dict[str, int]:
    total = {quality.value: 0 for quality in ImportQuality}
    for report in reports:
        for key, value in report.counts.items():
            total[key] += value
    return total
