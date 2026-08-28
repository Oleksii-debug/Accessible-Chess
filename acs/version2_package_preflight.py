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
import zipfile

from .acsdb import ACSDB_SCHEMA_VERSION
from .settings import SCHEMA_VERSION as SETTINGS_SCHEMA_VERSION
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
        if data.get(field) != expected:
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
    for relative in inventory:
        path = root.joinpath(*PurePosixPath(relative).parts)
        try:
            if path.stat().st_size > limits.max_text_scan_bytes:
                continue
            payload = path.read_bytes()
        except OSError as exc:
            _fail(f"package hygiene scan failed: {type(exc).__name__}")
        if b"\x00" in payload:
            continue
        try:
            text = payload.decode("utf-8-sig")
        except UnicodeDecodeError:
            continue
        if any(pattern.search(text) for pattern in _PRIVATE_PATH_PATTERNS):
            _fail(f"private local path leaked into package text: {relative}")
        if any(pattern.search(text) for pattern in _SECRET_PATTERNS):
            _fail(f"secret-like credential leaked into package text: {relative}")


def validate_version2_package_tree(
    root: str | Path,
    *,
    limits: PackageLimits = PackageLimits(),
) -> Version2PackagePreflightReport:
    if not isinstance(limits, PackageLimits):
        raise TypeError("limits must be PackageLimits")
    root = Path(root)
    inventory, total = _inventory(root, limits)
    _validate_topology(root, inventory)
    integration_sha, _ = _manifest(root)
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
    limits: PackageLimits = PackageLimits(),
) -> Version2PackagePreflightReport:
    if not isinstance(limits, PackageLimits):
        raise TypeError("limits must be PackageLimits")
    path = Path(zip_path)
    info = _safe_lstat(path, label="Version 2 ZIP")
    if not stat.S_ISREG(info.st_mode):
        _fail("Version 2 ZIP must be a regular file")
    if info.st_size > limits.max_archive_bytes:
        _fail("Version 2 ZIP exceeds archive byte limit")
    archive_sha = _sha256(path)

    try:
        with zipfile.ZipFile(path) as archive:
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
                report = validate_version2_package_tree(root, limits=limits)
                if set(report.inventory) != extracted_files:
                    _fail("ZIP readback inventory differs from archive file inventory")
                return replace(report, archive_sha256=archive_sha)
    except Version2PackagePreflightError:
        raise
    except (OSError, zipfile.BadZipFile, zipfile.LargeZipFile) as exc:
        _fail(f"Version 2 ZIP is unreadable or corrupt: {type(exc).__name__}")
