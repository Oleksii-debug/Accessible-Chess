from __future__ import annotations

"""Fail-closed Version 2 package tree and ZIP readback validation.

This module validates an already assembled package. It deliberately does not
build, publish, sign, or promote a Windows candidate; D05 retains that authority.
"""

from dataclasses import dataclass, replace
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
import stat
import tempfile
import wave
import zipfile

from .acsdb import ACSDB_SCHEMA_VERSION
from .settings import SCHEMA_VERSION as SETTINGS_SCHEMA_VERSION
from .sound_events import SoundEvent
from .sound_windows import (
    DEFAULT_SOUND_MANIFEST,
    DEFAULT_SOUND_RELATIVE_DIR,
    SOUND_MANIFEST_SCHEMA_VERSION,
)
from .stockfish_runtime import PACKAGED_STOCKFISH_RELATIVE_PATH
from .version2_upgrade import UPGRADE_JOURNAL_SCHEMA_VERSION


MANIFEST_NAME = "RELEASE_MANIFEST.json"
CHECKSUMS_NAME = "SHA256SUMS.txt"
V2_PACKAGE_MANIFEST_SCHEMA_VERSION = 1
V2_PACKAGE_PROFILE = "version2-default"

_SHA40_RE = re.compile(r"^[0-9a-f]{40}$")
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
_WIN_BAD = set('<>:"/\\|?*')
_WIN_RESERVED = {
    "CON", "PRN", "AUX", "NUL",
    *(f"COM{i}" for i in range(1, 10)),
    *(f"LPT{i}" for i in range(1, 10)),
    "COM¹", "COM²", "COM³",
    "LPT¹", "LPT²", "LPT³",
}
_FORBIDDEN_COMPONENTS = {
    ".git", ".pytest_cache", "__pycache__", "build", "build_parts10k",
    "build_snapshot_exact", "build_snapshot_parts", "dist", "package",
    "source", "tests",
}
_RAW_SOURCE_SUFFIXES = {
    ".py", ".pyc", ".pyo", ".ipynb", ".c", ".cc", ".cpp", ".cxx",
    ".h", ".hpp", ".hh", ".rs",
}
_USER_STATE_NAMES = {
    "settings.json",
    "library.acsdb",
    "library.acsdb-wal",
    "library.acsdb-shm",
    "library.acsdb-journal",
    ".v2-upgrade-state.json",
    ".v2-upgrade.lock",
}
_SECRET_FILE_NAMES = {
    ".env", "credentials.json", "token.json", "secrets.json",
    "id_rsa", "id_ed25519",
}
_SECRET_SUFFIXES = {".pem", ".key", ".pfx", ".p12"}
_BACKEND_BINARY_SUFFIXES = {
    "", ".exe", ".dll", ".so", ".dylib", ".a", ".lib",
    ".zip", ".7z", ".tar", ".gz",
}
_WINDOWS_PE_BINARY_SUFFIXES = frozenset({".exe", ".dll", ".pyd"})
_ALLOWED_TOP_LEVEL_FILES = {
    MANIFEST_NAME,
    CHECKSUMS_NAME,
    "native-menu-self-diagnostic.json",
    "packaged-uia-strict-summary.json",
}
_ALLOWED_TOP_LEVEL_DIRS = {"AccessibleChess", "THIRD_PARTY_NOTICES"}
_PRIVATE_PATH_PATTERNS = (
    re.compile(r"(?i)[a-z]:[\\/]+users[\\/]+[^\\/\s]+[\\/]"),
    re.compile(r"/home/[^/\s]+/"),
    re.compile(r"/Users/[^/\s]+/"),
)
_SECRET_PATTERNS = (
    re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----"),
    re.compile(r"\bgithub_pat_[A-Za-z0-9_]{20,}\b"),
    re.compile(r"\bghp_[A-Za-z0-9]{20,}\b"),
    re.compile(r"\bAKIA[0-9A-Z]{16}\b"),
    re.compile(r"\bsk-[A-Za-z0-9_-]{20,}\b"),
)
_PRODUCT_ROOT = PurePosixPath("AccessibleChess")
_REQUIRED_STOCKFISH = (
    _PRODUCT_ROOT / PurePosixPath(PACKAGED_STOCKFISH_RELATIVE_PATH.as_posix())
).as_posix()
_REQUIRED_SOUND_ROOT = (
    _PRODUCT_ROOT / PurePosixPath(DEFAULT_SOUND_RELATIVE_DIR.as_posix())
)
_REQUIRED_SOUND_MANIFEST = (
    _REQUIRED_SOUND_ROOT / DEFAULT_SOUND_MANIFEST
).as_posix()
_REQUIRED_SOUND_PROVENANCE = "THIRD_PARTY_NOTICES/SOUND_PROVENANCE.json"
_SOUND_PROVENANCE_SCHEMA_VERSION = 1
_PROVENANCE_PLACEHOLDERS = frozenset({"unknown", "unlicensed", "tbd", "todo", "none", "n/a"})
_REQUIRED_STOCKFISH_SOURCE = "THIRD_PARTY_NOTICES/Stockfish-18-source.zip"
_REQUIRED_STOCKFISH_NOTICE = "THIRD_PARTY_NOTICES/Stockfish-NOTICE.txt"
_REQUIRED_WEB_FILES = (
    "AccessibleChess/web/index.html",
    "AccessibleChess/web/stage1_release_bootstrap.js",
    "AccessibleChess/web/stage1_board_actions.js",
    "AccessibleChess/web/full_product_pgn.js",
    "AccessibleChess/web/full_product_library.js",
    "AccessibleChess/web/full_product_books_training.js",
    "AccessibleChess/web/full_product_teacher.js",
    "AccessibleChess/web/full_product_education.js",
    "AccessibleChess/web/version2_final_product_bootstrap.js",
    "AccessibleChess/web/version2_release_bootstrap.js",
)


class Version2PackagePreflightError(RuntimeError):
    """Raised when a Version 2 package violates a release-data invariant."""


@dataclass(frozen=True, slots=True)
class PackageLimits:
    max_files: int = 50_000
    max_bytes: int = 8 * 1024 * 1024 * 1024
    max_archive_bytes: int = 4 * 1024 * 1024 * 1024
    max_member_bytes: int = 2 * 1024 * 1024 * 1024
    max_compression_ratio: int = 200
    max_text_scan_bytes: int = 2 * 1024 * 1024

    def __post_init__(self) -> None:
        for name in (
            "max_files", "max_bytes", "max_archive_bytes", "max_member_bytes",
            "max_compression_ratio", "max_text_scan_bytes",
        ):
            value = getattr(self, name)
            if type(value) is not int or value < 1:
                raise ValueError(f"{name} must be a positive integer")


@dataclass(frozen=True, slots=True)
class Version2PackagePreflightReport:
    integration_sha: str
    inventory: tuple[str, ...]
    total_bytes: int
    checksums_verified: int
    archive_sha256: str | None = None

    def as_dict(self) -> dict[str, object]:
        return {
            "integration_sha": self.integration_sha,
            "inventory": list(self.inventory),
            "inventory_count": len(self.inventory),
            "total_bytes": self.total_bytes,
            "checksums_verified": self.checksums_verified,
            "archive_sha256": self.archive_sha256,
            "nvda_verified": False,
            "result": "PASS",
        }


def _fail(message: str) -> None:
    raise Version2PackagePreflightError(message)


def _portable_component(value: str, *, label: str) -> None:
    if not value or value in {".", ".."}:
        _fail(f"{label} contains an empty or reserved component")
    if value[-1] in {" ", "."}:
        _fail(f"{label} is not Windows-portable")
    if any(ord(char) < 32 or char in _WIN_BAD for char in value):
        _fail(f"{label} is not Windows-portable")
    if value.split(".", 1)[0].upper() in _WIN_RESERVED:
        _fail(f"{label} uses a reserved Windows name")


def _relative_token(value: str, *, label: str) -> str:
    if not isinstance(value, str) or not value or "\x00" in value:
        _fail(f"{label} must be non-empty text")
    normalized = value.replace("\\", "/")
    token = PurePosixPath(normalized)
    if (
        token.is_absolute()
        or normalized.startswith("/")
        or re.match(r"^[A-Za-z]:", normalized)
        or any(part in {"", ".", ".."} for part in token.parts)
    ):
        _fail(f"{label} is unsafe")
    for part in token.parts:
        _portable_component(part, label=label)
    canonical = token.as_posix()
    if canonical != normalized:
        _fail(f"{label} is not canonical")
    return canonical


def _reparse(info: os.stat_result) -> bool:
    flag = getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400)
    return bool(getattr(info, "st_file_attributes", 0) & flag)


def _safe_lstat(path: Path, *, label: str) -> os.stat_result:
    try:
        info = path.lstat()
    except OSError as exc:
        _fail(f"{label} cannot be inspected: {type(exc).__name__}")
    if stat.S_ISLNK(info.st_mode) or _reparse(info):
        _fail(f"{label} must not be a symlink or reparse point")
    return info


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    try:
        with path.open("rb") as handle:
            for block in iter(lambda: handle.read(1024 * 1024), b""):
                digest.update(block)
    except OSError as exc:
        _fail(f"package file cannot be read: {type(exc).__name__}")
    return digest.hexdigest()


def _same_file_snapshot(left: os.stat_result, right: os.stat_result) -> bool:
    """Compare pathname/open-handle identity plus content-relevant metadata."""
    try:
        same_identity = os.path.samestat(left, right)
    except (AttributeError, OSError):
        same_identity = (
            getattr(left, "st_dev", None),
            getattr(left, "st_ino", None),
        ) == (
            getattr(right, "st_dev", None),
            getattr(right, "st_ino", None),
        )
    return bool(
        same_identity
        and int(left.st_size) == int(right.st_size)
        and getattr(left, "st_mtime_ns", None) == getattr(right, "st_mtime_ns", None)
    )


def _snapshot_regular_file(
    path: Path,
    *,
    label: str,
    max_bytes: int,
):
    """Copy one verified pathname identity once, then validate immutable snapshot bytes."""
    before = _safe_lstat(path, label=label)
    if not stat.S_ISREG(before.st_mode):
        _fail(f"{label} must be a regular file")
    if before.st_size > max_bytes:
        _fail(f"{label} exceeds archive byte limit")

    snapshot = tempfile.SpooledTemporaryFile(
        max_size=min(max_bytes, 64 * 1024 * 1024),
        mode="w+b",
    )
    source = None
    digest = hashlib.sha256()
    try:
        source = path.open("rb")
        opened = os.fstat(source.fileno())
        if not stat.S_ISREG(opened.st_mode) or _reparse(opened):
            _fail(f"{label} must remain a regular non-reparse file")
        if not _same_file_snapshot(before, opened):
            _fail(f"{label} changed while being opened")

        copied = 0
        while True:
            block = source.read(1024 * 1024)
            if not block:
                break
            copied += len(block)
            if copied > max_bytes:
                _fail(f"{label} exceeds archive byte limit")
            digest.update(block)
            snapshot.write(block)

        after_read = os.fstat(source.fileno())
        after_path = _safe_lstat(path, label=label)
        if (
            not _same_file_snapshot(opened, after_read)
            or not _same_file_snapshot(after_read, after_path)
            or copied != int(after_read.st_size)
        ):
            _fail(f"{label} changed while being read")
        snapshot.seek(0)
        return snapshot, digest.hexdigest()
    except Version2PackagePreflightError:
        snapshot.close()
        raise
    except OSError as exc:
        snapshot.close()
        _fail(f"{label} cannot be read safely: {type(exc).__name__}")
    finally:
        if source is not None:
            source.close()


def _register_zip_topology(
    token: str,
    *,
    is_dir: bool,
    files: set[str],
    directories: set[str],
    label: str,
) -> None:
    parts = token.casefold().split("/")
    folded = "/".join(parts)
    ancestors = {"/".join(parts[:index]) for index in range(1, len(parts))}
    if any(parent in files for parent in ancestors):
        _fail(f"{label} path topology collision")
    if is_dir:
        if folded in files:
            _fail(f"{label} path topology collision")
        directories.add(folded)
    else:
        if folded in directories:
            _fail(f"{label} path topology collision")
        files.add(folded)
    directories.update(ancestors)


def _backend_payload(relative: str) -> bool:
    name = PurePosixPath(relative).name.casefold()
    suffix = PurePosixPath(name).suffix
    if name in {"uncbv", "uncbv.exe", "libcbh-json-bridge", "libcbh-json-bridge.exe"}:
        return True
    if "libcbh" in name or name.startswith("uncbv") or name.startswith("scidb"):
        return suffix in _BACKEND_BINARY_SUFFIXES
    return False


def _validate_file_policy(relative: str) -> None:
    token = PurePosixPath(relative)
    folded_parts = tuple(part.casefold() for part in token.parts)
    if any(part in _FORBIDDEN_COMPONENTS for part in folded_parts):
        _fail(f"build/source component is forbidden: {relative}")
    if token.suffix.casefold() in _RAW_SOURCE_SUFFIXES:
        _fail(f"raw source is forbidden in the default package: {relative}")
    name = token.name.casefold()
    if name in _USER_STATE_NAMES or any(
        part.endswith(".upgrade-backups") for part in folded_parts
    ):
        _fail(f"user state is forbidden in the default package: {relative}")
    if name in _SECRET_FILE_NAMES or token.suffix.casefold() in _SECRET_SUFFIXES:
        _fail(f"secret-bearing file type is forbidden: {relative}")
    if _backend_payload(relative):
        _fail(f"optional external backend payload is forbidden: {relative}")


def _inventory(root: Path, limits: PackageLimits) -> tuple[tuple[str, ...], int]:
    root_info = _safe_lstat(root, label="package root")
    if not stat.S_ISDIR(root_info.st_mode):
        _fail("package root must be a directory")

    seen: set[str] = set()
    files: list[str] = []
    total = 0
    try:
        walker = os.walk(root, topdown=True, followlinks=False)
        for dirpath, dirnames, filenames in walker:
            parent = Path(dirpath)
            for name in list(dirnames):
                path = parent / name
                relative = _relative_token(
                    PurePosixPath(*path.relative_to(root).parts).as_posix(),
                    label="package directory",
                )
                info = _safe_lstat(path, label="package directory")
                if not stat.S_ISDIR(info.st_mode):
                    _fail(f"package directory entry is not a directory: {relative}")
                folded = relative.casefold()
                if folded in seen:
                    _fail("package paths collide under Windows case-folding")
                seen.add(folded)
                if PurePosixPath(relative).name.casefold() in _FORBIDDEN_COMPONENTS:
                    _fail(f"build/source component is forbidden: {relative}")

            for name in filenames:
                path = parent / name
                relative = _relative_token(
                    PurePosixPath(*path.relative_to(root).parts).as_posix(),
                    label="package file",
                )
                folded = relative.casefold()
                if folded in seen:
                    _fail("package paths collide under Windows case-folding")
                seen.add(folded)
                info = _safe_lstat(path, label="package file")
                if not stat.S_ISREG(info.st_mode):
                    _fail(f"package entry must be a regular file: {relative}")
                _validate_file_policy(relative)
                files.append(relative)
                total += int(info.st_size)
                if len(files) > limits.max_files:
                    _fail("package exceeds file-count limit")
                if total > limits.max_bytes:
                    _fail("package exceeds byte limit")
    except Version2PackagePreflightError:
        raise
    except (OSError, ValueError) as exc:
        _fail(f"package inventory failed: {type(exc).__name__}")
    return tuple(sorted(files, key=str.casefold)), total


def _validate_topology(root: Path, inventory: tuple[str, ...]) -> None:
    top_dirs = set()
    top_files = set()
    for path in root.iterdir():
        info = _safe_lstat(path, label="top-level package entry")
        if stat.S_ISDIR(info.st_mode):
            top_dirs.add(path.name)
        elif stat.S_ISREG(info.st_mode):
            top_files.add(path.name)
        else:
            _fail("top-level package entry must be a regular file or directory")
    unexpected_dirs = sorted(top_dirs - _ALLOWED_TOP_LEVEL_DIRS)
    unexpected_files = sorted(top_files - _ALLOWED_TOP_LEVEL_FILES)
    if unexpected_dirs:
        _fail("unexpected top-level directory in Version 2 package")
    if unexpected_files:
        _fail("unexpected top-level file in Version 2 package")
    if "AccessibleChess" not in top_dirs:
        _fail("AccessibleChess product directory is missing")
    if "THIRD_PARTY_NOTICES" not in top_dirs:
        _fail("THIRD_PARTY_NOTICES directory is missing")
    exe_hits = [
        item
        for item in inventory
        if PurePosixPath(item).name.casefold() == "accessiblechess.exe"
    ]
    if exe_hits != ["AccessibleChess/AccessibleChess.exe"]:
        _fail("package must contain exactly one canonical AccessibleChess.exe")
    if (root / "AccessibleChess" / "AccessibleChess").exists():
        _fail("double AccessibleChess directory nesting is forbidden")


def _json_no_duplicates(text: str, *, label: str) -> dict[str, object]:
    def hook(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                _fail(f"{label} contains duplicate JSON keys")
            result[key] = value
        return result

    try:
        value = json.loads(text, object_pairs_hook=hook)
    except Version2PackagePreflightError:
        raise
    except (json.JSONDecodeError, TypeError, ValueError) as exc:
        _fail(f"{label} is invalid JSON: {type(exc).__name__}")
    if not isinstance(value, dict):
        _fail(f"{label} must be a JSON object")
    return value


def _require_package_file(
    root: Path,
    inventory: tuple[str, ...],
    relative: str,
    *,
    label: str,
    min_bytes: int = 1,
) -> Path:
    if relative not in inventory:
        _fail(f"{label} is missing")
    path = root.joinpath(*PurePosixPath(relative).parts)
    info = _safe_lstat(path, label=label)
    if not stat.S_ISREG(info.st_mode) or info.st_size < min_bytes:
        _fail(f"{label} is empty or invalid")
    return path


def _has_windows_pe_structure(path: Path) -> bool:
    """Recognize the bounded PE structure used by package validation and hygiene."""
    with path.open("rb") as handle:
        dos_header = handle.read(64)
        if len(dos_header) < 64 or dos_header[:2] != b"MZ":
            return False
        pe_offset = int.from_bytes(dos_header[0x3C:0x40], "little")
        handle.seek(0, os.SEEK_END)
        file_size = handle.tell()
        if pe_offset < 0x40 or pe_offset > file_size - 24:
            return False
        handle.seek(pe_offset)
        pe_header = handle.read(24)
        if len(pe_header) != 24 or pe_header[:4] != b"PE\x00\x00":
            return False

        machine = int.from_bytes(pe_header[4:6], "little")
        section_count = int.from_bytes(pe_header[6:8], "little")
        optional_header_size = int.from_bytes(pe_header[20:22], "little")
        characteristics = int.from_bytes(pe_header[22:24], "little")
        if (
            machine == 0
            or section_count == 0
            or optional_header_size < 2
            or not characteristics & 0x0002
            or pe_offset + 24 + optional_header_size > file_size
        ):
            return False

        optional_magic = handle.read(2)
        return optional_magic in {b"\x0b\x01", b"\x0b\x02"}


def _validate_windows_pe_executable(path: Path, *, label: str) -> None:
    """Require enough PE structure to reject DOS stubs and MZ-only impostors."""
    try:
        if not _has_windows_pe_structure(path):
            _fail(f"{label} is not a valid Windows PE executable")
    except Version2PackagePreflightError:
        raise
    except OSError as exc:
        _fail(f"{label} cannot be read: {type(exc).__name__}")


def _provenance_text(value: object, *, label: str, max_length: int) -> str:
    if not isinstance(value, str):
        _fail(f"sound provenance {label} must be text")
    normalized = value.strip()
    if (
        not normalized
        or len(normalized) > max_length
        or any(ord(character) < 32 or ord(character) == 127 for character in normalized)
    ):
        _fail(f"sound provenance {label} is invalid")
    return normalized


def _validate_sound_provenance(
    root: Path,
    inventory: tuple[str, ...],
    mapping: dict[object, object],
) -> None:
    provenance_path = _require_package_file(
        root,
        inventory,
        _REQUIRED_SOUND_PROVENANCE,
        label="sound provenance notice",
    )
    try:
        text = provenance_path.read_text(encoding="utf-8-sig")
    except (OSError, UnicodeError) as exc:
        _fail(f"sound provenance notice is unreadable: {type(exc).__name__}")
    provenance = _json_no_duplicates(text, label="sound provenance notice")
    if set(provenance) != {"schema_version", "events"}:
        _fail("sound provenance root contract is invalid")
    if type(provenance.get("schema_version")) is not int or provenance.get(
        "schema_version"
    ) != _SOUND_PROVENANCE_SCHEMA_VERSION:
        _fail("sound provenance schema is invalid")
    events = provenance.get("events")
    if not isinstance(events, dict):
        _fail("sound provenance events must be an object")
    expected_events = {event.value for event in SoundEvent}
    if set(events) != expected_events:
        _fail("sound provenance must declare every semantic sound event exactly once")

    for event in SoundEvent:
        entry = events.get(event.value)
        if not isinstance(entry, dict) or set(entry) != {
            "file",
            "sha256",
            "license_id",
            "source",
            "creator",
        }:
            _fail(f"sound provenance entry contract is invalid: {event.value}")
        file_name = _provenance_text(entry.get("file"), label="file", max_length=255)
        if file_name != mapping.get(event.value):
            _fail(f"sound provenance file does not match manifest: {event.value}")
        token = _relative_token(file_name, label="sound provenance asset path")
        if PurePosixPath(token).suffix.casefold() != ".wav":
            _fail(f"sound provenance asset is not WAV: {event.value}")
        sound_relative = (_REQUIRED_SOUND_ROOT / PurePosixPath(token)).as_posix()
        sound_path = _require_package_file(
            root,
            inventory,
            sound_relative,
            label=f"packaged sound asset {event.value}",
            min_bytes=45,
        )
        digest = _provenance_text(entry.get("sha256"), label="sha256", max_length=64)
        if not _SHA256_RE.fullmatch(digest):
            _fail(f"sound provenance SHA-256 is invalid: {event.value}")
        if _sha256(sound_path) != digest:
            _fail(f"sound provenance SHA-256 mismatch: {event.value}")
        license_id = _provenance_text(
            entry.get("license_id"), label="license_id", max_length=128
        )
        if license_id.casefold() in _PROVENANCE_PLACEHOLDERS:
            _fail(f"sound provenance license identity is unresolved: {event.value}")
        source = _provenance_text(entry.get("source"), label="source", max_length=1024)
        if not (source.startswith("https://") or source.startswith("urn:")):
            _fail(f"sound provenance source must be an HTTPS URL or URN: {event.value}")
        creator = _provenance_text(entry.get("creator"), label="creator", max_length=512)
        if creator.casefold() in _PROVENANCE_PLACEHOLDERS:
            _fail(f"sound provenance creator identity is unresolved: {event.value}")


def _validate_stockfish_source_archive(
    source_archive: Path,
    limits: PackageLimits,
) -> None:
    """Validate one immutable snapshot of the nested corresponding-source ZIP."""
    snapshot, _ = _snapshot_regular_file(
        source_archive,
        label="Stockfish source ZIP",
        max_bytes=limits.max_archive_bytes,
    )
    try:
        with snapshot:
            with zipfile.ZipFile(snapshot) as archive:
                infos = archive.infolist()
                if not infos:
                    _fail("Stockfish corresponding source archive is empty")
                if len(infos) > limits.max_files * 2:
                    _fail("Stockfish source ZIP exceeds member-count limit")

                seen: set[str] = set()
                topology_files: set[str] = set()
                topology_directories: set[str] = set()
                file_count = 0
                total = 0
                has_source_file = False
                for info in infos:
                    raw = (
                        info.filename[:-1]
                        if info.is_dir() and info.filename.endswith("/")
                        else info.filename
                    )
                    token = _relative_token(raw, label="Stockfish source ZIP member path")
                    folded = token.casefold()
                    if folded in seen:
                        _fail("Stockfish source ZIP members collide under Windows case-folding")
                    seen.add(folded)

                    unix_mode = (info.external_attr >> 16) & 0xFFFF
                    file_type = stat.S_IFMT(unix_mode)
                    if file_type == stat.S_IFLNK:
                        _fail("Stockfish source ZIP symbolic links are forbidden")
                    if file_type not in {0, stat.S_IFREG, stat.S_IFDIR}:
                        _fail("Stockfish source ZIP special files are forbidden")
                    if info.flag_bits & 0x1:
                        _fail("encrypted Stockfish source ZIP members are forbidden")
                    _register_zip_topology(
                        token,
                        is_dir=info.is_dir(),
                        files=topology_files,
                        directories=topology_directories,
                        label="Stockfish source ZIP",
                    )
                    if info.is_dir():
                        continue

                    file_count += 1
                    if file_count > limits.max_files:
                        _fail("Stockfish source ZIP exceeds file-count limit")
                    if info.file_size > limits.max_member_bytes:
                        _fail("Stockfish source ZIP member exceeds uncompressed size limit")
                    total += int(info.file_size)
                    if total > limits.max_bytes:
                        _fail("Stockfish source ZIP exceeds total uncompressed byte limit")
                    if info.file_size:
                        if info.compress_size <= 0:
                            _fail("Stockfish source ZIP member has invalid compressed size")
                        if info.file_size > info.compress_size * limits.max_compression_ratio:
                            _fail("Stockfish source ZIP member exceeds compression-ratio limit")

                    written = 0
                    try:
                        with archive.open(info, "r") as source:
                            while True:
                                block = source.read(1024 * 1024)
                                if not block:
                                    break
                                written += len(block)
                                if written > info.file_size or written > limits.max_member_bytes:
                                    _fail("Stockfish source ZIP member expanded beyond declared bounds")
                    except Version2PackagePreflightError:
                        raise
                    except (OSError, RuntimeError, zipfile.BadZipFile) as exc:
                        _fail(
                            "Stockfish source ZIP member readback failed: "
                            f"{type(exc).__name__}"
                        )
                    if written != info.file_size:
                        _fail("Stockfish source ZIP member readback size mismatch")
                    if written and "/src/" in f"/{token}":
                        has_source_file = True

                if not has_source_file:
                    _fail("Stockfish corresponding source archive does not contain source files")
    except Version2PackagePreflightError:
        raise
    except (OSError, zipfile.BadZipFile, zipfile.LargeZipFile) as exc:
        _fail(f"Stockfish corresponding source archive is invalid: {type(exc).__name__}")

def _validate_required_runtime_resources(
    root: Path,
    inventory: tuple[str, ...],
    limits: PackageLimits,
) -> None:
    for relative in _REQUIRED_WEB_FILES:
        _require_package_file(
            root,
            inventory,
            relative,
            label="packaged Version 2 web resource",
        )

    stockfish = _require_package_file(
        root,
        inventory,
        _REQUIRED_STOCKFISH,
        label="packaged Stockfish 18 executable",
        min_bytes=64,
    )
    _validate_windows_pe_executable(
        stockfish,
        label="packaged Stockfish 18 executable",
    )

    manifest_path = _require_package_file(
        root,
        inventory,
        _REQUIRED_SOUND_MANIFEST,
        label="packaged sound manifest",
    )
    try:
        manifest_text = manifest_path.read_text(encoding="utf-8-sig")
    except (OSError, UnicodeError) as exc:
        _fail(f"packaged sound manifest is unreadable: {type(exc).__name__}")
    manifest = _json_no_duplicates(manifest_text, label="packaged sound manifest")
    schema = manifest.get("schema_version")
    if type(schema) is not int or schema != SOUND_MANIFEST_SCHEMA_VERSION:
        _fail("packaged sound manifest schema is invalid")
    mapping = manifest.get("files")
    if not isinstance(mapping, dict):
        _fail("packaged sound manifest files must be an object")
    expected_events = {event.value for event in SoundEvent}
    if set(mapping) != expected_events:
        _fail("packaged sound manifest must declare every semantic sound event exactly once")

    seen_sound_paths: set[str] = set()
    for event in SoundEvent:
        value = mapping.get(event.value)
        if not isinstance(value, str) or not value:
            _fail(f"packaged sound manifest entry is invalid: {event.value}")
        token = _relative_token(value, label="sound asset path")
        folded_token = token.casefold()
        if folded_token in seen_sound_paths:
            _fail("packaged sound events must use distinct WAV assets")
        seen_sound_paths.add(folded_token)
        if PurePosixPath(token).suffix.casefold() != ".wav":
            _fail(f"packaged sound asset is not WAV: {event.value}")
        relative = (_REQUIRED_SOUND_ROOT / PurePosixPath(token)).as_posix()
        sound_path = _require_package_file(
            root,
            inventory,
            relative,
            label=f"packaged sound asset {event.value}",
            min_bytes=45,
        )
        try:
            with wave.open(str(sound_path), "rb") as reader:
                if (
                    reader.getsampwidth() != 2
                    or reader.getframerate() <= 0
                    or reader.getnframes() <= 0
                ):
                    _fail(f"packaged sound asset is not usable 16-bit PCM: {event.value}")
        except Version2PackagePreflightError:
            raise
        except (OSError, EOFError, wave.Error) as exc:
            _fail(f"packaged sound asset is invalid: {event.value} ({type(exc).__name__})")

    _validate_sound_provenance(root, inventory, mapping)

    source_archive = _require_package_file(
        root,
        inventory,
        _REQUIRED_STOCKFISH_SOURCE,
        label="Stockfish 18 corresponding source archive",
    )
    _validate_stockfish_source_archive(source_archive, limits)

    notice_path = _require_package_file(
        root,
        inventory,
        _REQUIRED_STOCKFISH_NOTICE,
        label="Stockfish GPL notice",
    )
    try:
        notice = notice_path.read_text(encoding="utf-8-sig").casefold()
    except (OSError, UnicodeError) as exc:
        _fail(f"Stockfish GPL notice is unreadable: {type(exc).__name__}")
    if (
        "stockfish 18" not in notice
        or "gpl" not in notice
        or "source" not in notice
    ):
        _fail("Stockfish GPL notice is incomplete")


def _manifest(root: Path) -> tuple[str, dict[str, object]]:
    path = root / MANIFEST_NAME
    info = _safe_lstat(path, label="release manifest")
    if not stat.S_ISREG(info.st_mode):
        _fail("release manifest must be a file")
    try:
        text = path.read_text(encoding="utf-8-sig")
    except (OSError, UnicodeError) as exc:
        _fail(f"release manifest is unreadable: {type(exc).__name__}")
    data = _json_no_duplicates(text, label="release manifest")

    required = {
        "manifest_schema": V2_PACKAGE_MANIFEST_SCHEMA_VERSION,
        "product": "Accessible Chess",
        "package_profile": V2_PACKAGE_PROFILE,
        "nvda_verified": False,
        "upgrade_from_version1": True,
        "upgrade_journal_schema": UPGRADE_JOURNAL_SCHEMA_VERSION,
        "settings_schema": SETTINGS_SCHEMA_VERSION,
        "acsdb_schema": ACSDB_SCHEMA_VERSION,
        "user_data_bundled": False,
        "raw_source_bundled": False,
        "optional_external_backends_bundled": False,
    }
    for field, expected in required.items():
        actual = data.get(field)
        if type(actual) is not type(expected) or actual != expected:
            _fail(f"release manifest contract mismatch: {field}")
    integration_sha = data.get("integration_sha")
    if (
        not isinstance(integration_sha, str)
        or not _SHA40_RE.fullmatch(integration_sha.casefold())
    ):
        _fail("release manifest integration_sha must be a 40-hex commit")
    return integration_sha.casefold(), data


def _checksums(root: Path, inventory: tuple[str, ...]) -> dict[str, str]:
    path = root / CHECKSUMS_NAME
    info = _safe_lstat(path, label="checksum inventory")
    if not stat.S_ISREG(info.st_mode):
        _fail("checksum inventory must be a file")
    try:
        lines = path.read_text(encoding="utf-8-sig").splitlines()
    except (OSError, UnicodeError) as exc:
        _fail(f"checksum inventory is unreadable: {type(exc).__name__}")

    result: dict[str, str] = {}
    folded: set[str] = set()
    for line in lines:
        if len(line) < 67 or line[64:66] != "  ":
            _fail("checksum inventory line is malformed")
        digest = line[:64].casefold()
        if not _SHA256_RE.fullmatch(digest):
            _fail("checksum inventory digest is invalid")
        relative = _relative_token(line[66:], label="checksum path")
        key = relative.casefold()
        if key in folded:
            _fail("checksum inventory contains duplicate paths")
        folded.add(key)
        result[relative] = digest

    expected = set(inventory) - {CHECKSUMS_NAME}
    if set(result) != expected:
        _fail("checksum inventory must cover every package file exactly once")
    for relative, expected_digest in result.items():
        actual = _sha256(root.joinpath(*PurePosixPath(relative).parts))
        if actual != expected_digest:
            _fail(f"package checksum mismatch: {relative}")
    return result


def _scan_text_hygiene(root: Path, inventory: tuple[str, ...], limits: PackageLimits) -> None:
    # max_text_scan_bytes is the streaming read bound, never an exemption.
    chunk_size = min(limits.max_text_scan_bytes, 1024 * 1024)
    overlap_bytes = 512
    for relative in inventory:
        path = root.joinpath(*PurePosixPath(relative).parts)
        tail = b""
        try:
            # A PE image can legitimately contain compiler/debug build paths.  Do
            # not classify those embedded binary strings as package text merely
            # because UTF-8 error-ignoring happens to expose them.  This is
            # structure-based, not suffix-only: text renamed to .dll/.exe still
            # follows the normal path-leak gate.  Credential signatures remain
            # scanned even inside recognized PE images.
            is_pe_binary = (
                PurePosixPath(relative).suffix.casefold() in _WINDOWS_PE_BINARY_SUFFIXES
                and _has_windows_pe_structure(path)
            )
            with path.open("rb") as handle:
                while True:
                    block = handle.read(chunk_size)
                    if not block:
                        break
                    window = tail + block
                    # Signatures are ASCII; ignore unrelated invalid UTF-8 bytes
                    # without treating a large file as a scan exemption.
                    text = window.decode("utf-8", errors="ignore")
                    if (
                        not is_pe_binary
                        and any(pattern.search(text) for pattern in _PRIVATE_PATH_PATTERNS)
                    ):
                        _fail(f"private local path leaked into package text: {relative}")
                    if any(pattern.search(text) for pattern in _SECRET_PATTERNS):
                        _fail(f"secret-like credential leaked into package text: {relative}")
                    tail = window[-overlap_bytes:]
        except Version2PackagePreflightError:
            raise
        except OSError as exc:
            _fail(f"package hygiene scan failed: {type(exc).__name__}")


def _normalize_expected_integration_sha(value: str) -> str:
    if not isinstance(value, str) or not _SHA40_RE.fullmatch(value.casefold()):
        _fail("expected integration authority must be a 40-hex commit")
    return value.casefold()


def validate_version2_package_tree(
    root: str | Path,
    *,
    expected_integration_sha: str,
    limits: PackageLimits = PackageLimits(),
) -> Version2PackagePreflightReport:
    if not isinstance(limits, PackageLimits):
        raise TypeError("limits must be PackageLimits")
    expected_sha = _normalize_expected_integration_sha(expected_integration_sha)
    root = Path(root)
    inventory, total = _inventory(root, limits)
    _validate_topology(root, inventory)
    _validate_required_runtime_resources(root, inventory, limits)
    integration_sha, _ = _manifest(root)
    if integration_sha != expected_sha:
        _fail("release manifest integration_sha does not match expected integration authority")
    checksums = _checksums(root, inventory)
    _scan_text_hygiene(root, inventory, limits)
    return Version2PackagePreflightReport(
        integration_sha=integration_sha,
        inventory=inventory,
        total_bytes=total,
        checksums_verified=len(checksums),
    )


def _zip_member_token(info: zipfile.ZipInfo) -> str:
    raw = info.filename[:-1] if info.is_dir() and info.filename.endswith("/") else info.filename
    return _relative_token(raw, label="ZIP member path")


def _validate_zip_entries(
    archive: zipfile.ZipFile,
    limits: PackageLimits,
) -> tuple[tuple[zipfile.ZipInfo, str], ...]:
    infos = archive.infolist()
    if not infos:
        _fail("Version 2 ZIP is empty")
    if len(infos) > limits.max_files * 2:
        _fail("Version 2 ZIP exceeds member-count limit")
    seen: set[str] = set()
    topology_files: set[str] = set()
    topology_directories: set[str] = set()
    total = 0
    validated: list[tuple[zipfile.ZipInfo, str]] = []
    for info in infos:
        token = _zip_member_token(info)
        folded = token.casefold()
        if folded in seen:
            _fail("ZIP members collide under Windows case-folding")
        seen.add(folded)
        unix_mode = (info.external_attr >> 16) & 0xFFFF
        file_type = stat.S_IFMT(unix_mode)
        if file_type == stat.S_IFLNK:
            _fail("ZIP symbolic links are forbidden")
        if file_type not in {0, stat.S_IFREG, stat.S_IFDIR}:
            _fail("ZIP special files are forbidden")
        if info.flag_bits & 0x1:
            _fail("encrypted ZIP members are forbidden")
        _register_zip_topology(
            token,
            is_dir=info.is_dir(),
            files=topology_files,
            directories=topology_directories,
            label="Version 2 ZIP",
        )
        if not info.is_dir():
            _validate_file_policy(token)
            if info.file_size > limits.max_member_bytes:
                _fail("ZIP member exceeds uncompressed size limit")
            total += int(info.file_size)
            if total > limits.max_bytes:
                _fail("ZIP exceeds total uncompressed byte limit")
            if info.file_size:
                if info.compress_size <= 0:
                    _fail("ZIP member has invalid compressed size")
                if info.file_size > info.compress_size * limits.max_compression_ratio:
                    _fail("ZIP member exceeds compression-ratio limit")
        validated.append((info, token))
    return tuple(validated)

def validate_version2_package_zip(
    zip_path: str | Path,
    *,
    expected_integration_sha: str,
    limits: PackageLimits = PackageLimits(),
) -> Version2PackagePreflightReport:
    if not isinstance(limits, PackageLimits):
        raise TypeError("limits must be PackageLimits")
    expected_sha = _normalize_expected_integration_sha(expected_integration_sha)
    path = Path(zip_path)
    snapshot, archive_sha = _snapshot_regular_file(
        path,
        label="Version 2 ZIP",
        max_bytes=limits.max_archive_bytes,
    )

    try:
        with snapshot:
            with zipfile.ZipFile(snapshot) as archive:
                entries = _validate_zip_entries(archive, limits)
                with tempfile.TemporaryDirectory(prefix="accessible-chess-v2-readback-") as td:
                    root = Path(td)
                    extracted_files: set[str] = set()
                    for member, token in entries:
                        target = root.joinpath(*PurePosixPath(token).parts)
                        if member.is_dir():
                            target.mkdir(parents=True, exist_ok=True)
                            continue
                        target.parent.mkdir(parents=True, exist_ok=True)
                        written = 0
                        try:
                            with archive.open(member, "r") as source, target.open("xb") as destination:
                                while True:
                                    block = source.read(1024 * 1024)
                                    if not block:
                                        break
                                    written += len(block)
                                    if written > member.file_size or written > limits.max_member_bytes:
                                        _fail("ZIP member expanded beyond declared bounds")
                                    destination.write(block)
                        except Version2PackagePreflightError:
                            raise
                        except (OSError, RuntimeError, zipfile.BadZipFile) as exc:
                            _fail(f"ZIP member readback failed: {type(exc).__name__}")
                        if written != member.file_size:
                            _fail("ZIP member readback size mismatch")
                        extracted_files.add(token)
                    report = validate_version2_package_tree(
                        root,
                        expected_integration_sha=expected_sha,
                        limits=limits,
                    )
                    if set(report.inventory) != extracted_files:
                        _fail("ZIP readback inventory differs from archive file inventory")
                    return replace(report, archive_sha256=archive_sha)
    except Version2PackagePreflightError:
        raise
    except (OSError, zipfile.BadZipFile, zipfile.LargeZipFile) as exc:
        _fail(f"Version 2 ZIP is unreadable or corrupt: {type(exc).__name__}")
