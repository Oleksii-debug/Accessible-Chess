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
import xml.etree.ElementTree as ET

from .acsdb import ACSDB_SCHEMA_VERSION
from .settings import SCHEMA_VERSION as SETTINGS_SCHEMA_VERSION
from .sound_events import SoundEvent
from .sound_windows import (
    DEFAULT_SOUND_LAYERS_MANIFEST,
    DEFAULT_SOUND_MANIFEST,
    DEFAULT_SOUND_RELATIVE_DIR,
    DEFAULT_SOUND_VARIANTS_MANIFEST,
    PackagedSoundAssetResolver,
    SOUND_MANIFEST_SCHEMA_VERSION,
)
from .stockfish_runtime import PACKAGED_STOCKFISH_RELATIVE_PATH
from .version2_upgrade import UPGRADE_JOURNAL_SCHEMA_VERSION


MANIFEST_NAME = "RELEASE_MANIFEST.json"
CHECKSUMS_NAME = "SHA256SUMS.txt"
V2_PACKAGE_MANIFEST_SCHEMA_VERSION = 1
V2_PACKAGE_PROFILE = "version2-default"

_WINFORMS_ACCESSIBILITY_SWITCHES = (
    "Switch.UseLegacyAccessibilityFeatures",
    "Switch.UseLegacyAccessibilityFeatures.2",
    "Switch.UseLegacyAccessibilityFeatures.3",
    "Switch.UseLegacyAccessibilityFeatures.4",
    "Switch.UseLegacyAccessibilityFeatures.5",
)
_MAX_APPCONFIG_BYTES = 64 * 1024
_MAX_RELEASE_MANIFEST_BYTES = 64 * 1024
_RELEASE_MANIFEST_MAX_OBJECT_MEMBERS = 64
_RELEASE_MANIFEST_MAX_KEY_CHARS = 128

_SHA40_RE = re.compile(r"^[0-9a-f]{40}$")
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
_WIN_BAD = set('<>:"/\\|?*')
_WIN_RESERVED = {
    "CON", "PRN", "AUX", "NUL", "CONIN$", "CONOUT$",
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
_REQUIRED_SOUND_INVENTORY = (
    _REQUIRED_SOUND_ROOT / "inventory.json"
).as_posix()
_REQUIRED_SOUND_INVENTORY_NOTICE = "THIRD_PARTY_NOTICES/SOUND_INVENTORY.json"
_SOUND_PROVENANCE_SCHEMA_VERSION = 1
_SOUND_INVENTORY_SCHEMA_VERSION = 1
_USER_SOUND_EXPECTED_WAV_COUNT = 330
_USER_SOUND_EXPECTED_INVENTORY_SHA256 = (
    "41f3223040e0720b2268e5c28f3ccec140a4f9d3386c12ffa7a82fc283a1f920"
)
_USER_SOUND_SOURCE = "urn:accessible-chess:user-upload:sound-archive:2026-10-03"
_USER_SOUND_LICENSE_ID = "USER_PROVIDED"
_USER_SOUND_CREATOR = "User-provided legacy chess sound archive"
_MAX_SOUND_INVENTORY_BYTES = 4 * 1024 * 1024
_MAX_SOUND_FILE_BYTES = 64 * 1024 * 1024
_MAX_SOUND_LIBRARY_WAV_BYTES = 512 * 1024 * 1024
_PROVENANCE_PLACEHOLDERS = frozenset({"unknown", "unlicensed", "tbd", "todo", "none", "n/a"})
_REQUIRED_STOCKFISH_SOURCE = "THIRD_PARTY_NOTICES/Stockfish-18-source.zip"
_REQUIRED_STOCKFISH_NOTICE = "THIRD_PARTY_NOTICES/Stockfish-NOTICE.txt"
_REQUIRED_WINFORMS_APPCONFIG = "AccessibleChess/AccessibleChess.exe.config"
# Minimal desktop startup closure for the pinned Windows standalone stack.
# These files are all present in the successful W5 one-click artifact and are
# loaded before/while pythonnet + pywebview create the first accessible window.
_REQUIRED_DESKTOP_RUNTIME_FILES = (
    "AccessibleChess/python312.dll",
    "AccessibleChess/_cffi_backend.pyd",
    "AccessibleChess/libffi-8.dll",
    "AccessibleChess/vcruntime140.dll",
    "AccessibleChess/vcruntime140_1.dll",
    "AccessibleChess/_sqlite3.pyd",
    "AccessibleChess/sqlite3.dll",
    "AccessibleChess/pythonnet/runtime/Python.Runtime.dll",
    "AccessibleChess/clr_loader/ffi/dlls/amd64/ClrLoader.dll",
    "AccessibleChess/webview/lib/Microsoft.Web.WebView2.Core.dll",
    "AccessibleChess/webview/lib/Microsoft.Web.WebView2.WinForms.dll",
    "AccessibleChess/webview/lib/runtimes/win-x64/native/WebView2Loader.dll",
)
_REQUIRED_AMD64_DESKTOP_RUNTIME_FILES = frozenset(
    {
        "AccessibleChess/python312.dll",
        "AccessibleChess/_cffi_backend.pyd",
        "AccessibleChess/libffi-8.dll",
        "AccessibleChess/vcruntime140.dll",
        "AccessibleChess/vcruntime140_1.dll",
        "AccessibleChess/_sqlite3.pyd",
        "AccessibleChess/sqlite3.dll",
        "AccessibleChess/clr_loader/ffi/dlls/amd64/ClrLoader.dll",
        "AccessibleChess/webview/lib/runtimes/win-x64/native/WebView2Loader.dll",
    }
)
_REQUIRED_MANAGED_DESKTOP_RUNTIME_FILES = frozenset(
    {
        "AccessibleChess/pythonnet/runtime/Python.Runtime.dll",
        "AccessibleChess/clr_loader/ffi/dlls/amd64/ClrLoader.dll",
        "AccessibleChess/webview/lib/Microsoft.Web.WebView2.Core.dll",
        "AccessibleChess/webview/lib/Microsoft.Web.WebView2.WinForms.dll",
    }
)
_REQUIRED_I386_MANAGED_DESKTOP_RUNTIME_FILES = frozenset(
    {
        "AccessibleChess/pythonnet/runtime/Python.Runtime.dll",
        "AccessibleChess/webview/lib/Microsoft.Web.WebView2.Core.dll",
        "AccessibleChess/webview/lib/Microsoft.Web.WebView2.WinForms.dll",
    }
)
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
    "AccessibleChess/web/version2_local_profile.js",
    "AccessibleChess/web/p0_accessibility_runtime.js",
    "AccessibleChess/web/version2_release_bootstrap.js",
    "AccessibleChess/web/docs/ACCESSIBLE_CHESS_HOTKEYS_UK.txt",
    "AccessibleChess/web/docs/ACCESSIBLE_CHESS_CAPABILITIES_TESTING_UK.txt",
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
            "human_tested": False,
            "nvda_verified": False,
            "result": "PASS",
        }


def _fail(message: str) -> None:
    raise Version2PackagePreflightError(message)


def _portable_component(value: str, *, label: str) -> None:
    if not value or value in {".", ".."}:
        _fail(f"{label} contains an empty or reserved component")
    try:
        utf16_units = len(value.encode("utf-16-le", errors="strict")) // 2
    except UnicodeEncodeError:
        _fail(f"{label} is not valid Win32 Unicode")
    if utf16_units > 255:
        _fail(f"{label} exceeds Windows 255 UTF-16 code-unit component limit")
    if value[-1] in {" ", "."}:
        _fail(f"{label} is not Windows-portable")
    if any(ord(char) < 32 or ord(char) == 0x7F or char in _WIN_BAD for char in value):
        _fail(f"{label} is not Windows-portable")
    device_stem = value.split(".", 1)[0].rstrip(" .").upper()
    if device_stem in _WIN_RESERVED:
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


def _read_stable_bytes_file(path: Path, *, label: str, max_bytes: int) -> bytes:
    """Read one bounded metadata file from the exact stable snapshot."""
    if type(max_bytes) is not int or max_bytes < 1:
        raise ValueError("max_bytes must be a positive integer")
    snapshot, _ = _snapshot_regular_file(
        path,
        label=label,
        max_bytes=max_bytes,
    )
    try:
        with snapshot:
            return snapshot.read(max_bytes)
    except Version2PackagePreflightError:
        raise
    except OSError as exc:
        _fail(f"{label} cannot be read: {type(exc).__name__}")


def _sha256(path: Path) -> str:
    """Hash one exact regular-file snapshot, rejecting concurrent mutation."""
    before = _safe_lstat(path, label="package file")
    if not stat.S_ISREG(before.st_mode):
        _fail("package file must be a regular file")

    digest = hashlib.sha256()
    copied = 0
    try:
        with path.open("rb") as handle:
            opened = os.fstat(handle.fileno())
            if not stat.S_ISREG(opened.st_mode) or _reparse(opened):
                _fail("package file must remain a regular non-reparse file")
            if not _same_file_snapshot(before, opened):
                _fail("package file changed while being opened")

            while True:
                block = handle.read(1024 * 1024)
                if not block:
                    break
                copied += len(block)
                digest.update(block)

            after_read = os.fstat(handle.fileno())
    except Version2PackagePreflightError:
        raise
    except OSError as exc:
        _fail(f"package file cannot be read: {type(exc).__name__}")

    after_path = _safe_lstat(path, label="package file")
    if (
        copied != getattr(after_read, "st_size", None)
        or not _same_file_snapshot(opened, after_read)
        or not _same_file_snapshot(after_read, after_path)
    ):
        _fail("package file changed while being read")
    return digest.hexdigest()


def _stable_change_metadata(st: os.stat_result) -> tuple[int, ...] | None:
    """Return platform-reliable mutation metadata for snapshot comparison.

    Windows exposes st_ctime_ns as creation time, so only nanosecond mtime is a
    portable change signal there. POSIX ctime is mutation metadata and closes a
    same-size rewrite gap when mtime is restored. Missing, non-integer or
    negative required metadata is fail-closed rather than being treated as an
    equal change signal.
    """

    mtime_ns = getattr(st, "st_mtime_ns", None)
    if type(mtime_ns) is not int or mtime_ns < 0:
        return None
    if os.name == "nt":
        return (mtime_ns,)

    ctime_ns = getattr(st, "st_ctime_ns", None)
    if type(ctime_ns) is not int or ctime_ns < 0:
        return None
    return mtime_ns, ctime_ns


def _same_file_snapshot(left: os.stat_result, right: os.stat_result) -> bool:
    """Compare pathname/open-handle identity, size and safe change metadata."""
    try:
        same_identity = os.path.samestat(left, right)
    except (AttributeError, OSError):
        left_identity = (
            getattr(left, "st_dev", None),
            getattr(left, "st_ino", None),
        )
        right_identity = (
            getattr(right, "st_dev", None),
            getattr(right, "st_ino", None),
        )
        values = left_identity + right_identity
        same_identity = bool(
            all(type(value) is int and value > 0 for value in values)
            and left_identity == right_identity
        )

    left_size = getattr(left, "st_size", None)
    right_size = getattr(right, "st_size", None)
    left_change = _stable_change_metadata(left)
    right_change = _stable_change_metadata(right)
    return bool(
        same_identity
        and type(left_size) is int
        and type(right_size) is int
        and left_size >= 0
        and right_size >= 0
        and left_size == right_size
        and left_change is not None
        and left_change == right_change
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


def _json_no_duplicates(
    text: str,
    *,
    label: str,
    max_object_members: int | None = None,
    max_key_chars: int | None = None,
) -> dict[str, object]:
    def hook(pairs):
        result = {}
        member_count = 0
        for key, value in pairs:
            member_count += 1
            if max_object_members is not None and member_count > max_object_members:
                _fail(f"{label} contains too many JSON object members")
            if max_key_chars is not None and (
                not isinstance(key, str) or len(key) > max_key_chars
            ):
                _fail(f"{label} JSON key is too long")
            if key in result:
                _fail(f"{label} contains duplicate JSON keys")
            result[key] = value
        return result

    def reject_nonfinite(value: str) -> object:
        _fail(f"{label} contains non-finite JSON number: {value}")

    try:
        value = json.loads(
            text,
            object_pairs_hook=hook,
            parse_constant=reject_nonfinite,
        )
    except Version2PackagePreflightError:
        raise
    except (json.JSONDecodeError, TypeError, ValueError, RecursionError) as exc:
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


def _raw_offset_for_pe_section(
    section_table: bytes,
    *,
    section_count: int,
    file_size: int,
    rva: int,
    size: int,
) -> int | None:
    if rva <= 0 or size <= 0:
        return None
    for index in range(section_count):
        offset = index * 40
        virtual_address = int.from_bytes(
            section_table[offset + 12:offset + 16],
            "little",
        )
        raw_size = int.from_bytes(
            section_table[offset + 16:offset + 20],
            "little",
        )
        raw_pointer = int.from_bytes(
            section_table[offset + 20:offset + 24],
            "little",
        )
        if rva < virtual_address:
            continue
        delta = rva - virtual_address
        if delta > raw_size or size > raw_size - delta:
            continue
        file_offset = raw_pointer + delta
        if file_offset > file_size or size > file_size - file_offset:
            continue
        return file_offset
    return None


def _inspect_windows_pe_stream(
    source,
    *,
    inspect_clr: bool = False,
) -> tuple[int, int, int, bool, bool] | None:
    """Inspect PE, subsystem, CLR metadata and DLL image kind from one handle."""
    if type(inspect_clr) is not bool:
        raise TypeError("inspect_clr must be bool")
    source.seek(0, os.SEEK_END)
    file_size = source.tell()
    source.seek(0)
    dos_header = source.read(64)
    identity: tuple[int, int, int, bool, bool] | None = None
    if len(dos_header) >= 64 and dos_header[:2] == b"MZ":
        pe_offset = int.from_bytes(dos_header[0x3C:0x40], "little")
        if 0x40 <= pe_offset <= file_size - 24:
            source.seek(pe_offset)
            pe_header = source.read(24)
            if len(pe_header) == 24 and pe_header[:4] == b"PE\x00\x00":
                machine = int.from_bytes(pe_header[4:6], "little")
                section_count = int.from_bytes(pe_header[6:8], "little")
                optional_header_size = int.from_bytes(pe_header[20:22], "little")
                characteristics = int.from_bytes(pe_header[22:24], "little")
                if (
                    machine != 0
                    and 0 < section_count <= 96
                    and optional_header_size >= 96
                    and characteristics & 0x0002
                    and pe_offset + 24 + optional_header_size + (section_count * 40)
                    <= file_size
                ):
                    optional_header = source.read(optional_header_size)
                    if len(optional_header) == optional_header_size:
                        optional_magic = int.from_bytes(optional_header[:2], "little")
                        if (
                            optional_magic == 0x10B
                            or (
                                optional_magic == 0x20B
                                and optional_header_size >= 112
                            )
                        ):
                            subsystem = int.from_bytes(
                                optional_header[68:70], "little"
                            )
                            has_clr = False
                            if inspect_clr:
                                if optional_magic == 0x10B:
                                    directory_count_offset = 92
                                    directory_table_offset = 96
                                else:
                                    directory_count_offset = 108
                                    directory_table_offset = 112
                                if len(optional_header) >= directory_count_offset + 4:
                                    directory_count = int.from_bytes(
                                        optional_header[
                                            directory_count_offset:directory_count_offset + 4
                                        ],
                                        "little",
                                    )
                                    clr_directory_offset = directory_table_offset + (14 * 8)
                                    if (
                                        directory_count > 14
                                        and len(optional_header) >= clr_directory_offset + 8
                                    ):
                                        clr_rva = int.from_bytes(
                                            optional_header[
                                                clr_directory_offset:clr_directory_offset + 4
                                            ],
                                            "little",
                                        )
                                        clr_size = int.from_bytes(
                                            optional_header[
                                                clr_directory_offset + 4:clr_directory_offset + 8
                                            ],
                                            "little",
                                        )
                                        section_table_offset = (
                                            pe_offset + 24 + optional_header_size
                                        )
                                        section_table_size = section_count * 40
                                        if (
                                            clr_rva != 0
                                            and clr_size == 0x48
                                            and section_table_offset + section_table_size
                                            <= file_size
                                        ):
                                            source.seek(section_table_offset)
                                            section_table = source.read(section_table_size)
                                            if len(section_table) == section_table_size:
                                                clr_offset = _raw_offset_for_pe_section(
                                                    section_table,
                                                    section_count=section_count,
                                                    file_size=file_size,
                                                    rva=clr_rva,
                                                    size=0x48,
                                                )
                                                if clr_offset is not None:
                                                    source.seek(clr_offset)
                                                    clr_header = source.read(0x48)
                                                    if (
                                                        len(clr_header) == 0x48
                                                        and int.from_bytes(
                                                            clr_header[0:4], "little"
                                                        ) == 0x48
                                                    ):
                                                        metadata_rva = int.from_bytes(
                                                            clr_header[8:12], "little"
                                                        )
                                                        metadata_size = int.from_bytes(
                                                            clr_header[12:16], "little"
                                                        )
                                                        metadata_offset = (
                                                            _raw_offset_for_pe_section(
                                                                section_table,
                                                                section_count=section_count,
                                                                file_size=file_size,
                                                                rva=metadata_rva,
                                                                size=metadata_size,
                                                            )
                                                            if metadata_rva != 0
                                                            and metadata_size >= 4
                                                            else None
                                                        )
                                                        if metadata_offset is not None:
                                                            source.seek(metadata_offset)
                                                            has_clr = (
                                                                source.read(4) == b"BSJB"
                                                            )
                            identity = (
                                machine,
                                optional_magic,
                                subsystem,
                                has_clr,
                                bool(characteristics & 0x2000),
                            )


    return identity


def _inspect_windows_pe_identity(
    path: Path,
    *,
    label: str,
    inspect_clr: bool = False,
) -> tuple[int, int, int, bool, bool] | None:
    """Inspect one stable pathname/handle identity for PE, CLR and DLL image kind."""
    if type(inspect_clr) is not bool:
        raise TypeError("inspect_clr must be bool")
    before = _safe_lstat(path, label=label)
    if not stat.S_ISREG(before.st_mode):
        return None

    source = None
    try:
        source = path.open("rb")
        opened = os.fstat(source.fileno())
        if not stat.S_ISREG(opened.st_mode) or _reparse(opened):
            _fail(f"{label} must remain a regular non-reparse file")
        if not _same_file_snapshot(before, opened):
            _fail(f"{label} changed while being opened")

        identity = _inspect_windows_pe_stream(
            source,
            inspect_clr=inspect_clr,
        )
        after_read = os.fstat(source.fileno())
        after_path = _safe_lstat(path, label=label)
        if (
            not _same_file_snapshot(opened, after_read)
            or not _same_file_snapshot(after_read, after_path)
        ):
            _fail(f"{label} changed while being read")
        return identity
    except Version2PackagePreflightError:
        raise
    except OSError as exc:
        _fail(f"{label} cannot be read: {type(exc).__name__}")
    finally:
        if source is not None:
            source.close()


def _has_windows_pe_structure(path: Path) -> bool:
    """Recognize the bounded PE structure used by package validation and hygiene."""
    return _inspect_windows_pe_identity(
        path,
        label="package PE image",
    ) is not None


def _has_windows_clr_descriptor(path: Path) -> bool:
    """Require a file-backed CLR header and metadata root for managed assemblies."""
    identity = _inspect_windows_pe_identity(
        path,
        label="managed CLR assembly",
        inspect_clr=True,
    )
    return identity is not None and identity[3]


def _validate_windows_pe_executable(
    path: Path,
    *,
    label: str,
    expected_machine: int | None = None,
    expected_optional_magic: int | None = None,
    require_clr: bool = False,
    expected_subsystem: int | None = None,
    expected_dll: bool | None = None,
) -> None:
    """Require one stable PE identity plus requested CPU/managed-runtime contract."""
    if expected_machine is not None:
        if type(expected_machine) is not int or not 0 < expected_machine <= 0xFFFF:
            raise TypeError("expected_machine must be a positive 16-bit integer or null")
    if expected_optional_magic is not None:
        if expected_optional_magic not in {0x10B, 0x20B}:
            raise TypeError("expected_optional_magic must be PE32, PE32+, or null")
    if type(require_clr) is not bool:
        raise TypeError("require_clr must be bool")
    if expected_subsystem is not None:
        if type(expected_subsystem) is not int or not 0 < expected_subsystem <= 0xFFFF:
            raise TypeError(
                "expected_subsystem must be a positive 16-bit integer or null"
            )
    if expected_dll is not None and type(expected_dll) is not bool:
        raise TypeError("expected_dll must be bool or null")

    identity = _inspect_windows_pe_identity(
        path,
        label=label,
        inspect_clr=require_clr,
    )
    if identity is None:
        _fail(f"{label} is not a valid Windows PE executable")
    (
        actual_machine,
        actual_optional_magic,
        actual_subsystem,
        has_clr,
        actual_dll,
    ) = identity
    if expected_machine is not None and actual_machine != expected_machine:
        _fail(
            f"{label} has unexpected Windows PE machine "
            f"0x{actual_machine:04x}; expected 0x{expected_machine:04x}"
        )
    if (
        expected_optional_magic is not None
        and actual_optional_magic != expected_optional_magic
    ):
        _fail(
            f"{label} has unexpected Windows PE optional magic "
            f"0x{actual_optional_magic:04x}; "
            f"expected 0x{expected_optional_magic:04x}"
        )
    if (
        expected_subsystem is not None
        and actual_subsystem != expected_subsystem
    ):
        _fail(
            f"{label} has unexpected Windows PE subsystem "
            f"0x{actual_subsystem:04x}; expected 0x{expected_subsystem:04x}"
        )
    if require_clr and not has_clr:
        _fail(f"{label} is not a managed CLR assembly")
    if expected_dll is not None and actual_dll is not expected_dll:
        actual_kind = "DLL" if actual_dll else "EXE"
        expected_kind = "DLL" if expected_dll else "EXE"
        _fail(
            f"{label} has unexpected Windows PE image kind "
            f"{actual_kind}; expected {expected_kind}"
        )


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
        text = _read_stable_bytes_file(
            provenance_path,
            label="sound provenance notice",
            max_bytes=_MAX_SOUND_INVENTORY_BYTES,
        ).decode("utf-8-sig", errors="strict")
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


def _sound_inventory_sha256(value: object, *, label: str) -> str:
    if not isinstance(value, str) or not _SHA256_RE.fullmatch(value):
        _fail(f"{label} SHA-256 is invalid")
    return value


def _sound_inventory_file_token(value: object) -> str:
    if not isinstance(value, str) or not value or "\\" in value or "\x00" in value:
        _fail("sound inventory file path is invalid")
    token = _relative_token(value, label="sound inventory file path")
    path = PurePosixPath(token)
    if len(path.parts) < 2 or path.parts[0] != "library":
        _fail("sound inventory file must be under library")
    if path.suffix.casefold() != ".wav":
        _fail("sound inventory entry is not WAV")
    return token


def _validate_sound_inventory(
    root: Path,
    package_inventory: tuple[str, ...],
) -> None:
    variants_relative = (
        _REQUIRED_SOUND_ROOT / DEFAULT_SOUND_VARIANTS_MANIFEST
    ).as_posix()
    layers_relative = (
        _REQUIRED_SOUND_ROOT / DEFAULT_SOUND_LAYERS_MANIFEST
    ).as_posix()
    has_variants = variants_relative in package_inventory
    has_source = _REQUIRED_SOUND_INVENTORY in package_inventory
    has_notice = _REQUIRED_SOUND_INVENTORY_NOTICE in package_inventory

    if not has_source and not has_notice:
        if has_variants:
            _fail("packaged sound variants require canonical sound inventory")
        return
    if not has_source or not has_notice:
        _fail("packaged sound inventory and audit notice must both be present")

    source_path = _require_package_file(
        root,
        package_inventory,
        _REQUIRED_SOUND_INVENTORY,
        label="packaged sound inventory",
    )
    notice_path = _require_package_file(
        root,
        package_inventory,
        _REQUIRED_SOUND_INVENTORY_NOTICE,
        label="sound inventory audit notice",
    )
    try:
        source_doc = _json_no_duplicates(
            _read_stable_bytes_file(
                source_path,
                label="packaged sound inventory",
                max_bytes=_MAX_SOUND_INVENTORY_BYTES,
            ).decode("utf-8-sig", errors="strict"),
            label="packaged sound inventory",
        )
        notice_doc = _json_no_duplicates(
            _read_stable_bytes_file(
                notice_path,
                label="sound inventory audit notice",
                max_bytes=_MAX_SOUND_INVENTORY_BYTES,
            ).decode("utf-8-sig", errors="strict"),
            label="sound inventory audit notice",
        )
    except Version2PackagePreflightError:
        raise
    except (OSError, UnicodeError) as exc:
        _fail(f"sound inventory is unreadable: {type(exc).__name__}")
    if source_doc != notice_doc:
        _fail("packaged sound inventory does not match audit notice")

    required_root = {
        "schema_version",
        "source",
        "license_id",
        "creator",
        "file_count",
        "source_inventory_sha256",
        "files",
    }
    optional_archive = {"source_archive_sha256", "source_archive_bytes"}
    keys = set(source_doc)
    if not required_root.issubset(keys) or not keys.issubset(required_root | optional_archive):
        _fail("sound inventory root contract is invalid")
    archive_keys = keys & optional_archive
    if archive_keys and archive_keys != optional_archive:
        _fail("sound inventory archive identity is incomplete")
    if (
        type(source_doc.get("schema_version")) is not int
        or source_doc.get("schema_version") != _SOUND_INVENTORY_SCHEMA_VERSION
    ):
        _fail("sound inventory schema is invalid")
    if source_doc.get("source") != _USER_SOUND_SOURCE:
        _fail("sound inventory source identity is invalid")
    if source_doc.get("license_id") != _USER_SOUND_LICENSE_ID:
        _fail("sound inventory license identity is invalid")
    if source_doc.get("creator") != _USER_SOUND_CREATOR:
        _fail("sound inventory creator identity is invalid")

    file_count = source_doc.get("file_count")
    files = source_doc.get("files")
    if type(file_count) is not int or file_count != _USER_SOUND_EXPECTED_WAV_COUNT:
        _fail("sound inventory file count is invalid")
    if not isinstance(files, list) or len(files) != file_count:
        _fail("sound inventory files list is invalid")
    declared_inventory_sha = _sound_inventory_sha256(
        source_doc.get("source_inventory_sha256"),
        label="sound inventory source",
    )
    if declared_inventory_sha != _USER_SOUND_EXPECTED_INVENTORY_SHA256:
        _fail("sound inventory does not match approved source identity")

    by_path: dict[str, dict[str, object]] = {}
    normalized_files: list[dict[str, object]] = []
    total_bytes = 0
    expected_fields = {
        "file",
        "sha256",
        "bytes",
        "channels",
        "sample_width_bytes",
        "sample_rate",
        "frames",
        "duration_seconds",
        "compression",
    }
    for entry in files:
        if not isinstance(entry, dict) or set(entry) != expected_fields:
            _fail("sound inventory entry contract is invalid")
        file_name = _sound_inventory_file_token(entry.get("file"))
        folded = file_name.casefold()
        if folded in by_path:
            _fail("sound inventory contains duplicate file paths")
        digest = _sound_inventory_sha256(entry.get("sha256"), label="sound inventory file")

        byte_count = entry.get("bytes")
        channels = entry.get("channels")
        sample_width = entry.get("sample_width_bytes")
        sample_rate = entry.get("sample_rate")
        frames = entry.get("frames")
        duration = entry.get("duration_seconds")
        compression = entry.get("compression")
        if (
            type(byte_count) is not int
            or byte_count < 45
            or byte_count > _MAX_SOUND_FILE_BYTES
            or type(channels) is not int
            or not 1 <= channels <= 64
            or type(sample_width) is not int
            or not 1 <= sample_width <= 8
            or type(sample_rate) is not int
            or not 1 <= sample_rate <= 768000
            or type(frames) is not int
            or frames < 1
            or isinstance(duration, bool)
            or not isinstance(duration, (int, float))
            or duration <= 0
            or not isinstance(compression, str)
            or not compression
            or len(compression) > 32
        ):
            _fail("sound inventory audio metadata is invalid")
        if abs(float(duration) - round(frames / sample_rate, 6)) > 0.000001:
            _fail("sound inventory duration metadata is invalid")

        package_relative = (
            _REQUIRED_SOUND_ROOT / PurePosixPath(file_name)
        ).as_posix()
        asset = _require_package_file(
            root,
            package_inventory,
            package_relative,
            label="inventory-bound sound asset",
            min_bytes=45,
        )
        try:
            snapshot, actual_digest = _snapshot_regular_file(
                asset,
                label="inventory-bound sound asset",
                max_bytes=_MAX_SOUND_FILE_BYTES,
            )
            with snapshot:
                snapshot.seek(0, os.SEEK_END)
                actual_size = snapshot.tell()
                snapshot.seek(0)
                if actual_size != byte_count:
                    _fail("sound inventory byte size mismatch")
                if actual_digest != digest:
                    _fail("sound inventory SHA-256 mismatch")
                with wave.open(snapshot, "rb") as reader:
                    actual_channels = reader.getnchannels()
                    actual_sample_width = reader.getsampwidth()
                    actual_sample_rate = reader.getframerate()
                    actual_frames = reader.getnframes()
                    actual_compression = reader.getcomptype()
                    frame_bytes = reader.readframes(actual_frames)
        except Version2PackagePreflightError:
            raise
        except (OSError, EOFError, wave.Error) as exc:
            _fail(f"sound inventory WAV is unreadable: {type(exc).__name__}")
        if (
            actual_channels != channels
            or actual_sample_width != sample_width
            or actual_sample_rate != sample_rate
            or actual_frames != frames
            or actual_compression != compression
        ):
            _fail("sound inventory WAV metadata mismatch")
        if len(frame_bytes) != actual_frames * actual_channels * actual_sample_width:
            _fail("sound inventory WAV is truncated")

        total_bytes += byte_count
        if total_bytes > _MAX_SOUND_LIBRARY_WAV_BYTES:
            _fail("sound inventory library byte limit exceeded")
        normalized = dict(entry)
        normalized["file"] = file_name
        normalized["sha256"] = digest
        normalized_files.append(normalized)
        by_path[folded] = normalized

    library_prefix = (_REQUIRED_SOUND_ROOT / "library").as_posix() + "/"
    actual_library_wavs = {
        relative.casefold()
        for relative in package_inventory
        if relative.startswith(library_prefix)
        and PurePosixPath(relative).suffix.casefold() == ".wav"
    }
    expected_library_wavs = {
        (_REQUIRED_SOUND_ROOT / PurePosixPath(str(item["file"]))).as_posix().casefold()
        for item in normalized_files
    }
    if actual_library_wavs != expected_library_wavs:
        _fail("sound inventory does not exactly cover packaged WAV library")

    fingerprint_rows = []
    for item in sorted(normalized_files, key=lambda current: str(current["file"]).casefold()):
        source_relative = str(item["file"]).removeprefix("library/")
        fingerprint_rows.append(
            f'{source_relative}\0{item["sha256"]}\n'.encode("utf-8")
        )
    calculated_inventory_sha = hashlib.sha256(b"".join(fingerprint_rows)).hexdigest()
    if (
        calculated_inventory_sha != declared_inventory_sha
        or calculated_inventory_sha != _USER_SOUND_EXPECTED_INVENTORY_SHA256
    ):
        _fail("sound inventory fingerprint mismatch")

    if archive_keys:
        _sound_inventory_sha256(
            source_doc.get("source_archive_sha256"),
            label="sound inventory source archive",
        )
        archive_bytes = source_doc.get("source_archive_bytes")
        if type(archive_bytes) is not int or archive_bytes < 1:
            _fail("sound inventory source archive size is invalid")

    product_dir = root / _PRODUCT_ROOT
    try:
        resolver = PackagedSoundAssetResolver(product_dir)
        manifest = resolver.load_manifest()
        variants = resolver.load_variant_catalog()
        layers = resolver.load_layer_catalog()
    except Exception as exc:
        _fail(f"packaged sound catalog is invalid: {type(exc).__name__}")
    runtime_paths = {
        *manifest.files.values(),
        *(option.path for options in variants.values() for option in options),
        *(
            path
            for by_variant in layers.values()
            for sequence in by_variant.values()
            for path in sequence
        ),
    }
    sound_root = product_dir / DEFAULT_SOUND_RELATIVE_DIR
    sound_root_resolved = sound_root.resolve()
    for path in runtime_paths:
        try:
            relative = path.resolve().relative_to(sound_root_resolved).as_posix()
        except (OSError, ValueError):
            _fail("runtime sound asset escapes canonical inventory")
        token = _sound_inventory_file_token(relative).casefold()
        entry = by_path.get(token)
        if entry is None:
            _fail("runtime sound asset is absent from canonical inventory")
        if (
            entry["compression"] != "NONE"
            or entry["sample_width_bytes"] not in {1, 2}
        ):
            _fail("runtime sound asset must be uncompressed 8-bit or 16-bit PCM")

    if layers_relative in package_inventory and not has_variants:
        # Layer-only legacy packs are allowed only when they do not opt into
        # the full user-pack inventory contract.
        _fail("inventory-bound sound layers require the variant catalog")


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

def validate_winforms_accessibility_app_config(path: Path) -> None:
    """Require the packaged WinForms accessibility switches to remain enabled."""

    try:
        payload = _read_stable_bytes_file(
            path,
            label="WinForms accessibility app-config",
            max_bytes=_MAX_APPCONFIG_BYTES,
        )
    except OSError as exc:
        _fail(f"WinForms accessibility app-config is unreadable: {type(exc).__name__}")
    if not payload or len(payload) > _MAX_APPCONFIG_BYTES:
        _fail("WinForms accessibility app-config size is invalid")
    try:
        text = payload.decode("utf-8-sig")
    except UnicodeError as exc:
        _fail(f"WinForms accessibility app-config must be UTF-8: {type(exc).__name__}")

    # ElementTree receives decoded text below, so it does not enforce that an
    # XML encoding declaration agrees with the actual packaged bytes.  A .NET
    # config loader reads the file as bytes and does honor that declaration.
    # Reject contradictory declarations here so preflight cannot approve UTF-8
    # bytes that claim to be UTF-16 (or another encoding) at runtime.
    declaration = re.match(r"\A<\?xml\s+[^?]*\?>", text, flags=re.IGNORECASE)
    if declaration is not None:
        declared_encoding = re.search(
            r"\bencoding\s*=\s*(['\"])([^'\"]+)\1",
            declaration.group(0),
            flags=re.IGNORECASE,
        )
        if (
            declared_encoding is not None
            and declared_encoding.group(2).casefold() != "utf-8"
        ):
            _fail(
                "WinForms accessibility app-config XML declaration must declare UTF-8"
            )

    upper = text.upper()
    if "<!DOCTYPE" in upper or "<!ENTITY" in upper:
        _fail("WinForms accessibility app-config must not contain DTD or entities")
    try:
        root = ET.fromstring(text)
    except ET.ParseError as exc:
        _fail(f"WinForms accessibility app-config is invalid XML: {type(exc).__name__}")
    if root.tag != "configuration":
        _fail("WinForms accessibility app-config root is invalid")

    runtime_nodes = root.findall("runtime")
    if len(runtime_nodes) != 1:
        _fail("WinForms accessibility app-config must contain exactly one runtime element")
    runtime = runtime_nodes[0]
    switch_nodes = runtime.findall("AppContextSwitchOverrides")
    if len(switch_nodes) != 1:
        _fail(
            "WinForms accessibility app-config must contain exactly one "
            "AppContextSwitchOverrides element"
        )
    node = switch_nodes[0]
    if (
        (runtime.text is not None and runtime.text.strip())
        or any(child.tail is not None and child.tail.strip() for child in runtime)
    ):
        _fail(
            "WinForms accessibility app-config runtime must not contain mixed text"
        )
    if set(node.attrib) != {"value"}:
        _fail("WinForms accessibility app-config switch attributes are invalid")
    if list(node) or (node.text is not None and node.text.strip()):
        _fail(
            "WinForms accessibility app-config AppContextSwitchOverrides "
            "must not contain child content"
        )
    value = node.attrib.get("value", "")
    parsed: dict[str, str] = {}
    for raw_entry in value.split(";"):
        entry = raw_entry.strip()
        if not entry:
            continue
        if "=" not in entry:
            _fail("WinForms accessibility app-config switch entry is invalid")
        name, setting = (part.strip() for part in entry.split("=", 1))
        if not name or name in parsed:
            _fail("WinForms accessibility app-config switch names must be unique")
        parsed[name] = setting.casefold()

    expected_switches = set(_WINFORMS_ACCESSIBILITY_SWITCHES)
    actual_switches = set(parsed)
    missing = sorted(expected_switches - actual_switches)
    if missing:
        _fail("WinForms accessibility app-config is missing required accessibility switches")
    unexpected = sorted(actual_switches - expected_switches)
    if unexpected:
        _fail("WinForms accessibility app-config contains unexpected accessibility switches")
    if any(parsed[name] != "false" for name in _WINFORMS_ACCESSIBILITY_SWITCHES):
        _fail("WinForms accessibility app-config must disable all legacy accessibility switches")


def _validate_required_runtime_resources(
    root: Path,
    inventory: tuple[str, ...],
    limits: PackageLimits,
) -> None:
    product_executable = _require_package_file(
        root,
        inventory,
        "AccessibleChess/AccessibleChess.exe",
        label="packaged AccessibleChess executable",
        min_bytes=64,
    )
    _validate_windows_pe_executable(
        product_executable,
        label="packaged AccessibleChess executable",
        expected_machine=0x8664,
        expected_optional_magic=0x20B,
        expected_subsystem=0x0002,
        expected_dll=False,
    )

    app_config = _require_package_file(
        root,
        inventory,
        _REQUIRED_WINFORMS_APPCONFIG,
        label="WinForms accessibility app-config",
    )
    validate_winforms_accessibility_app_config(app_config)

    for relative in _REQUIRED_DESKTOP_RUNTIME_FILES:
        runtime_binary = _require_package_file(
            root,
            inventory,
            relative,
            label=f"packaged desktop runtime {relative}",
            min_bytes=64,
        )
        _validate_windows_pe_executable(
            runtime_binary,
            label=f"packaged desktop runtime {relative}",
            expected_machine=(
                0x8664
                if relative in _REQUIRED_AMD64_DESKTOP_RUNTIME_FILES
                else 0x014C
                if relative in _REQUIRED_I386_MANAGED_DESKTOP_RUNTIME_FILES
                else None
            ),
            expected_optional_magic=(
                0x20B
                if relative in _REQUIRED_AMD64_DESKTOP_RUNTIME_FILES
                else 0x10B
                if relative in _REQUIRED_I386_MANAGED_DESKTOP_RUNTIME_FILES
                else None
            ),
            require_clr=relative in _REQUIRED_MANAGED_DESKTOP_RUNTIME_FILES,
        )

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
        expected_machine=0x8664,
        expected_optional_magic=0x20B,
        expected_dll=False,
    )

    manifest_path = _require_package_file(
        root,
        inventory,
        _REQUIRED_SOUND_MANIFEST,
        label="packaged sound manifest",
    )
    try:
        manifest_text = _read_stable_bytes_file(
            manifest_path,
            label="packaged sound manifest",
            max_bytes=64 * 1024,
        ).decode("utf-8-sig", errors="strict")
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

    for event in SoundEvent:
        value = mapping.get(event.value)
        if not isinstance(value, str) or not value:
            _fail(f"packaged sound manifest entry is invalid: {event.value}")
        token = _relative_token(value, label="sound asset path")
        # Multiple semantic outcomes may intentionally share one neutral WAV.
        # Provenance remains event-specific and is verified below against the
        # selected manifest path and bytes, so aliases cannot bypass integrity.
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
            snapshot, _ = _snapshot_regular_file(
                sound_path,
                label=f"packaged sound asset {event.value}",
                max_bytes=_MAX_SOUND_FILE_BYTES,
            )
            with snapshot:
                with wave.open(snapshot, "rb") as reader:
                    if (
                        reader.getcomptype() != "NONE"
                        or reader.getsampwidth() not in {1, 2}
                        or reader.getframerate() <= 0
                        or reader.getnframes() <= 0
                    ):
                        _fail(
                            f"packaged sound asset is not usable 8-bit/16-bit PCM: {event.value}"
                        )
        except Version2PackagePreflightError:
            raise
        except (OSError, EOFError, wave.Error) as exc:
            _fail(f"packaged sound asset is invalid: {event.value} ({type(exc).__name__})")

    _validate_sound_provenance(root, inventory, mapping)
    _validate_sound_inventory(root, inventory)

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
        notice = _read_stable_bytes_file(
            notice_path,
            label="Stockfish GPL notice",
            max_bytes=64 * 1024,
        ).decode("utf-8-sig", errors="strict").casefold()
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
    snapshot, _ = _snapshot_regular_file(
        path,
        label="release manifest",
        max_bytes=_MAX_RELEASE_MANIFEST_BYTES,
    )
    try:
        with snapshot:
            payload = snapshot.read(_MAX_RELEASE_MANIFEST_BYTES + 1)
    except OSError as exc:
        _fail(f"release manifest is unreadable: {type(exc).__name__}")
    if len(payload) > _MAX_RELEASE_MANIFEST_BYTES:
        _fail("release manifest exceeds byte limit")
    try:
        text = payload.decode("utf-8-sig", errors="strict")
    except UnicodeError as exc:
        _fail(f"release manifest is unreadable: {type(exc).__name__}")
    data = _json_no_duplicates(
        text,
        label="release manifest",
        max_object_members=_RELEASE_MANIFEST_MAX_OBJECT_MEMBERS,
        max_key_chars=_RELEASE_MANIFEST_MAX_KEY_CHARS,
    )

    required = {
        "manifest_schema": V2_PACKAGE_MANIFEST_SCHEMA_VERSION,
        "product": "Accessible Chess",
        "package_profile": V2_PACKAGE_PROFILE,
        "human_tested": False,
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


def _checksums(
    root: Path,
    inventory: tuple[str, ...],
    limits: PackageLimits,
) -> tuple[dict[str, str], str]:
    path = root / CHECKSUMS_NAME
    info = _safe_lstat(path, label="checksum inventory")
    if not stat.S_ISREG(info.st_mode):
        _fail("checksum inventory must be a file")
    try:
        payload = _read_stable_bytes_file(
            path,
            label="checksum inventory",
            max_bytes=limits.max_member_bytes,
        )
        lines = payload.decode("utf-8-sig", errors="strict").splitlines()
    except Version2PackagePreflightError:
        raise
    except (OSError, UnicodeError) as exc:
        _fail(f"checksum inventory is unreadable: {type(exc).__name__}")

    authority_sha256 = hashlib.sha256(payload).hexdigest()

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
    return result, authority_sha256


def _revalidate_checksums(
    root: Path,
    checksums: dict[str, str],
    checksum_authority_sha256: str,
) -> None:
    """Require the validated package bytes to remain unchanged through the final gate."""
    if _sha256(root / CHECKSUMS_NAME) != checksum_authority_sha256:
        _fail("checksum inventory changed during package validation")
    for relative, expected_digest in checksums.items():
        actual = _sha256(root.joinpath(*PurePosixPath(relative).parts))
        if actual != expected_digest:
            _fail(f"package file changed during validation: {relative}")


def _scan_text_hygiene(root: Path, inventory: tuple[str, ...], limits: PackageLimits) -> None:
    # max_text_scan_bytes is the streaming read bound, never an exemption.
    chunk_size = min(limits.max_text_scan_bytes, 1024 * 1024)
    overlap_bytes = 512
    for relative in inventory:
        path = root.joinpath(*PurePosixPath(relative).parts)
        tail = b""
        source = None
        try:
            before = _safe_lstat(path, label="package hygiene file")
            if not stat.S_ISREG(before.st_mode):
                _fail("package hygiene file must be a regular file")
            source = path.open("rb")
            opened = os.fstat(source.fileno())
            if not stat.S_ISREG(opened.st_mode) or _reparse(opened):
                _fail("package hygiene file must remain a regular non-reparse file")
            if not _same_file_snapshot(before, opened):
                _fail("package hygiene file changed while being opened")

            # A PE image can legitimately contain compiler/debug build paths. Do
            # not classify those embedded binary strings as package text. The PE
            # decision and the hygiene scan intentionally share this exact open
            # handle so a pathname swap cannot make them describe different bytes.
            is_pe_binary = (
                PurePosixPath(relative).suffix.casefold() in _WINDOWS_PE_BINARY_SUFFIXES
                and _inspect_windows_pe_stream(source) is not None
            )
            source.seek(0)
            while True:
                block = source.read(chunk_size)
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

            after_read = os.fstat(source.fileno())
            after_path = _safe_lstat(path, label="package hygiene file")
            if (
                not _same_file_snapshot(opened, after_read)
                or not _same_file_snapshot(after_read, after_path)
            ):
                _fail("package hygiene file changed while being scanned")
        except Version2PackagePreflightError:
            raise
        except OSError as exc:
            _fail(f"package hygiene scan failed: {type(exc).__name__}")
        finally:
            if source is not None:
                source.close()


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
    checksums, checksum_authority_sha256 = _checksums(root, inventory, limits)
    _scan_text_hygiene(root, inventory, limits)
    _revalidate_checksums(root, checksums, checksum_authority_sha256)
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
        is_directory = info.is_dir()
        if file_type == stat.S_IFLNK:
            _fail("ZIP symbolic links are forbidden")
        if file_type not in {0, stat.S_IFREG, stat.S_IFDIR}:
            _fail("ZIP special files are forbidden")
        if is_directory and file_type == stat.S_IFREG:
            _fail("ZIP directory member has conflicting regular-file mode")
        if not is_directory and file_type == stat.S_IFDIR:
            _fail("ZIP file member has conflicting directory mode")
        if info.flag_bits & 0x1:
            _fail("encrypted ZIP members are forbidden")
        _register_zip_topology(
            token,
            is_dir=is_directory,
            files=topology_files,
            directories=topology_directories,
            label="Version 2 ZIP",
        )
        if not is_directory:
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
