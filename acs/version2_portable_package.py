from __future__ import annotations

"""Portable outer package for the already-qualified Version 2 Windows payload.

This module does not compile the product and does not own chess, PGN, Library or
user-data semantics.  It accepts one canonical package that already passed
``version2_package_preflight``, moves its immutable product payload under ``App/``,
adds the tiny native root launcher and exactly two owner-supplied DOCX files, and
regenerates a deterministic outer manifest/checksum/archive.

The launcher redirects LOCALAPPDATA for the child.  The existing application
therefore remains the sole user-data/Library authority, including the verified
``release-content/user-library-seed`` import seam.  No ACSDB is copied or mutated
by this packaging layer.
"""

from dataclasses import dataclass
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import shutil
import stat
import tempfile
import zipfile

from .version2_package_assembler import (
    _FIXED_ZIP_TIMESTAMP,
    _copy_file,
    _copy_tree,
    _path_entry_exists,
    _publish_directory_no_replace,
    _require_notice_payload,
    _safe_info,
    _sha40,
    _sha256,
    _write_checksums,
)
from .version2_package_preflight import (
    CHECKSUMS_NAME,
    MANIFEST_NAME,
    V2_PACKAGE_MANIFEST_SCHEMA_VERSION,
    V2_PACKAGE_PROFILE,
    validate_version2_package_tree,
)


PORTABLE_PACKAGE_PROFILE = "accessible-chess-v2-windows-portable-oneclick-v1"
PORTABLE_LAUNCHER_NAME = "AccessibleChess.exe"
PORTABLE_APP_DIR = "App"
PORTABLE_DATA_DIR = "data"
PORTABLE_LAUNCH_REPORT = "launch-report.txt"
_PORTABLE_MANIFEST_KEYS = frozenset(
    {
        "manifest_schema",
        "product",
        "package_profile",
        "source_package_profile",
        "integration_sha",
        "launcher",
        "application_directory",
        "application_executable",
        "package_local_appdata",
        "launch_report",
        "word_documents",
        "human_tested",
        "nvda_verified",
    }
)
_PORTABLE_ROOT_DIRECTORIES = frozenset({PORTABLE_APP_DIR, "THIRD_PARTY_NOTICES"})
_COPY_CHUNK_BYTES = 1024 * 1024


class Version2PortablePackageError(RuntimeError):
    pass


@dataclass(frozen=True, slots=True)
class Version2PortablePackageReport:
    package_root: Path
    integration_sha: str
    inventory: tuple[str, ...]
    total_bytes: int
    archive_path: Path | None = None
    archive_sha256: str | None = None

    def as_dict(self) -> dict[str, object]:
        return {
            "package_root": str(self.package_root),
            "integration_sha": self.integration_sha,
            "inventory_count": len(self.inventory),
            "total_bytes": self.total_bytes,
            "archive_path": None if self.archive_path is None else str(self.archive_path),
            "archive_sha256": self.archive_sha256,
            "human_tested": False,
            "nvda_verified": False,
            "result": "PASS",
        }


def _fail(message: str) -> None:
    raise Version2PortablePackageError(message)


def _portable_docx_name(path: Path) -> str:
    name = path.name
    if (
        not name
        or name != name.strip()
        or name in {".", ".."}
        or len(name) > 255
        or "/" in name
        or "\\" in name
        or ":" in name
        or any(ord(character) < 32 or ord(character) == 0x7F for character in name)
        or not name.casefold().endswith(".docx")
    ):
        _fail("portable Word document filename is unsafe")
    return name


def _launcher_identity(path: Path) -> None:
    info = _safe_info(path, label="portable launcher", directory=False)
    if info.st_size < 1024 or info.st_size > 1024 * 1024:
        _fail("portable launcher byte size is outside the accepted native-launcher envelope")
    try:
        with path.open("rb") as handle:
            if handle.read(2) != b"MZ":
                _fail("portable launcher is not a Windows PE executable")
    except Version2PortablePackageError:
        raise
    except OSError as exc:
        _fail(f"portable launcher cannot be read: {type(exc).__name__}")


def _strict_json_bytes(payload: bytes) -> dict[str, object]:
    def unique_pairs(items):
        result: dict[str, object] = {}
        for key, value in items:
            if key in result:
                _fail("portable release manifest contains duplicate keys")
            result[key] = value
        return result

    try:
        decoded = payload.decode("utf-8", errors="strict")
        value = json.loads(decoded, object_pairs_hook=unique_pairs)
    except Version2PortablePackageError:
        raise
    except (UnicodeDecodeError, json.JSONDecodeError, TypeError, ValueError) as exc:
        _fail(f"portable release manifest is invalid: {type(exc).__name__}")
    if not isinstance(value, dict):
        _fail("portable release manifest must be an object")
    return value


def _manifest(root: Path) -> dict[str, object]:
    path = root / MANIFEST_NAME
    info = _safe_info(path, label="portable release manifest", directory=False)
    if info.st_size <= 0 or info.st_size > 1024 * 1024:
        _fail("portable release manifest byte size is invalid")
    try:
        payload = path.read_bytes()
    except OSError as exc:
        _fail(f"portable release manifest cannot be read: {type(exc).__name__}")
    value = _strict_json_bytes(payload)
    if set(value) != _PORTABLE_MANIFEST_KEYS:
        _fail("portable release manifest contract is invalid")
    return value


def _validate_root_topology(root: Path, documents: tuple[str, ...]) -> None:
    allowed_files = {
        PORTABLE_LAUNCHER_NAME.casefold(),
        MANIFEST_NAME.casefold(),
        CHECKSUMS_NAME.casefold(),
        *(name.casefold() for name in documents),
    }
    allowed_directories = {name.casefold() for name in _PORTABLE_ROOT_DIRECTORIES}
    seen: set[str] = set()
    try:
        entries = tuple(root.iterdir())
    except OSError as exc:
        _fail(f"portable package root cannot be enumerated: {type(exc).__name__}")
    for entry in entries:
        folded = entry.name.casefold()
        if folded in seen:
            _fail("portable package root contains case-colliding entries")
        seen.add(folded)
        info = _safe_info(entry, label="portable package root entry")
        if stat.S_ISDIR(info.st_mode):
            if folded not in allowed_directories:
                _fail("portable package root contains an unexpected directory")
            continue
        if stat.S_ISREG(info.st_mode):
            if folded not in allowed_files:
                _fail("portable package root contains an unexpected file")
            continue
        _fail("portable package root entry must be a regular file or directory")


def _relative_files(root: Path) -> tuple[str, ...]:
    result: list[str] = []
    try:
        for path in root.rglob("*"):
            info = _safe_info(path, label="portable package entry")
            if stat.S_ISDIR(info.st_mode):
                continue
            if not stat.S_ISREG(info.st_mode):
                _fail("portable package entry must be a regular file")
            result.append(PurePosixPath(*path.relative_to(root).parts).as_posix())
    except Version2PortablePackageError:
        raise
    except (OSError, ValueError) as exc:
        _fail(f"portable package inventory failed: {type(exc).__name__}")
    if len({item.casefold() for item in result}) != len(result):
        _fail("portable package contains case-colliding paths")
    return tuple(sorted(result, key=str.casefold))


def _checksum_inventory(root: Path, inventory: tuple[str, ...]) -> None:
    checksum_path = root / CHECKSUMS_NAME
    _safe_info(checksum_path, label="portable checksums", directory=False)
    try:
        text = checksum_path.read_text(encoding="utf-8", errors="strict")
    except (OSError, UnicodeError) as exc:
        _fail(f"portable checksums cannot be read: {type(exc).__name__}")
    expected_files = tuple(item for item in inventory if item != CHECKSUMS_NAME)
    seen: dict[str, str] = {}
    for raw in text.splitlines():
        if len(raw) < 67 or raw[64:66] != "  ":
            _fail("portable checksum line is malformed")
        digest = raw[:64].casefold()
        relative = raw[66:]
        if len(digest) != 64 or any(char not in "0123456789abcdef" for char in digest):
            _fail("portable checksum digest is invalid")
        pure = PurePosixPath(relative)
        if (
            not relative
            or pure.is_absolute()
            or any(part in {"", ".", ".."} for part in pure.parts)
            or relative == CHECKSUMS_NAME
        ):
            _fail("portable checksum path is invalid")
        folded = relative.casefold()
        if folded in seen:
            _fail("portable checksum inventory contains a duplicate path")
        seen[folded] = digest
    if set(seen) != {item.casefold() for item in expected_files}:
        _fail("portable checksum inventory does not match package files")
    for relative in expected_files:
        path = root.joinpath(*PurePosixPath(relative).parts)
        if _sha256(path) != seen[relative.casefold()]:
            _fail("portable package checksum verification failed")


def validate_portable_oneclick_tree(
    package_root: str | Path,
    *,
    expected_integration_sha: str,
    require_user_seed: bool = False,
) -> Version2PortablePackageReport:
    root = Path(package_root)
    sha = _sha40(expected_integration_sha)
    _safe_info(root, label="portable package root", directory=True)

    # Mutable user state and launcher diagnostics must be created only at runtime.
    if _path_entry_exists(root / PORTABLE_DATA_DIR, label="portable data directory"):
        _fail("portable package must not bundle mutable user data")
    if _path_entry_exists(root / PORTABLE_LAUNCH_REPORT, label="portable launch report"):
        _fail("portable package must not bundle a stale launch report")

    app = root / PORTABLE_APP_DIR
    notices = root / "THIRD_PARTY_NOTICES"
    _safe_info(app, label="portable App directory", directory=True)
    _safe_info(notices, label="portable notices directory", directory=True)
    _require_notice_payload(notices)
    _launcher_identity(root / PORTABLE_LAUNCHER_NAME)
    _launcher_identity(app / "AccessibleChess.exe")

    value = _manifest(root)
    if (
        value["manifest_schema"] != V2_PACKAGE_MANIFEST_SCHEMA_VERSION
        or value["product"] != "Accessible Chess"
        or value["package_profile"] != PORTABLE_PACKAGE_PROFILE
        or value["source_package_profile"] != V2_PACKAGE_PROFILE
        or value["integration_sha"] != sha
        or value["launcher"] != PORTABLE_LAUNCHER_NAME
        or value["application_directory"] != PORTABLE_APP_DIR
        or value["application_executable"] != "App/AccessibleChess.exe"
        or value["package_local_appdata"] != "data/AccessibleChess"
        or value["launch_report"] != PORTABLE_LAUNCH_REPORT
        or value["human_tested"] is not False
        or value["nvda_verified"] is not False
    ):
        _fail("portable release manifest identity is invalid")

    documents = value["word_documents"]
    if not isinstance(documents, list) or len(documents) != 2:
        _fail("portable package must declare exactly two Word documents")
    if any(type(name) is not str for name in documents):
        _fail("portable Word document manifest is invalid")
    doc_names = tuple(str(name) for name in documents)
    if len({name.casefold() for name in doc_names}) != 2:
        _fail("portable Word document names must be distinct")
    for name in doc_names:
        _portable_docx_name(Path(name))
        _safe_info(root / name, label="portable Word document", directory=False)

    root_docx = tuple(
        path.name
        for path in root.iterdir()
        if path.is_file() and path.name.casefold().endswith(".docx")
    )
    if {name.casefold() for name in root_docx} != {name.casefold() for name in doc_names}:
        _fail("portable package root must contain exactly the declared two Word documents")
    _validate_root_topology(root, doc_names)

    if require_user_seed:
        seed = app / "release-content" / "user-library-seed"
        _safe_info(seed, label="portable owner Library seed", directory=True)
        _safe_info(seed / "manifest.json", label="portable owner Library seed manifest", directory=False)

    inventory = _relative_files(root)
    _checksum_inventory(root, inventory)
    total_bytes = 0
    for relative in inventory:
        path = root.joinpath(*PurePosixPath(relative).parts)
        total_bytes += _safe_info(path, label="portable package file", directory=False).st_size
    return Version2PortablePackageReport(
        package_root=root,
        integration_sha=sha,
        inventory=inventory,
        total_bytes=total_bytes,
    )


def _write_portable_manifest(root: Path, integration_sha: str, documents: tuple[str, str]) -> None:
    value = {
        "manifest_schema": V2_PACKAGE_MANIFEST_SCHEMA_VERSION,
        "product": "Accessible Chess",
        "package_profile": PORTABLE_PACKAGE_PROFILE,
        "source_package_profile": V2_PACKAGE_PROFILE,
        "integration_sha": integration_sha,
        "launcher": PORTABLE_LAUNCHER_NAME,
        "application_directory": PORTABLE_APP_DIR,
        "application_executable": "App/AccessibleChess.exe",
        "package_local_appdata": "data/AccessibleChess",
        "launch_report": PORTABLE_LAUNCH_REPORT,
        "word_documents": list(documents),
        "human_tested": False,
        "nvda_verified": False,
    }
    try:
        (root / MANIFEST_NAME).write_text(
            json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
            newline="\n",
        )
    except OSError as exc:
        _fail(f"portable release manifest could not be written: {type(exc).__name__}")


def _regular_relative_files(root: Path, *, label: str) -> tuple[str, ...]:
    result: list[str] = []
    for path in root.rglob("*"):
        info = _safe_info(path, label=label)
        if stat.S_ISDIR(info.st_mode):
            continue
        if not stat.S_ISREG(info.st_mode):
            _fail(f"{label} contains a non-regular file")
        result.append(PurePosixPath(*path.relative_to(root).parts).as_posix())
    if len({item.casefold() for item in result}) != len(result):
        _fail(f"{label} contains case-colliding paths")
    return tuple(sorted(result, key=str.casefold))


def _assert_tree_copy_equal(source: Path, destination: Path, *, label: str) -> None:
    source_files = _regular_relative_files(source, label=label)
    destination_files = _regular_relative_files(destination, label=label)
    if tuple(name.casefold() for name in source_files) != tuple(
        name.casefold() for name in destination_files
    ):
        _fail(f"{label} inventory changed while building portable package")
    destination_by_name = {name.casefold(): name for name in destination_files}
    for source_name in source_files:
        destination_name = destination_by_name[source_name.casefold()]
        left = source.joinpath(*PurePosixPath(source_name).parts)
        right = destination.joinpath(*PurePosixPath(destination_name).parts)
        if _sha256(left) != _sha256(right):
            _fail(f"{label} bytes changed while building portable package")


def assemble_portable_oneclick_tree(
    canonical_package_root: str | Path,
    launcher_exe: str | Path,
    word_documents: tuple[str | Path, str | Path],
    output_root: str | Path,
    *,
    integration_sha: str,
    require_user_seed: bool = False,
) -> Version2PortablePackageReport:
    sha = _sha40(integration_sha)
    canonical = Path(canonical_package_root)
    launcher = Path(launcher_exe)
    output = Path(output_root)
    if not isinstance(word_documents, tuple) or len(word_documents) != 2:
        raise TypeError("word_documents must be an exact two-item tuple")
    documents = tuple(Path(item) for item in word_documents)

    # The inner payload must already satisfy the canonical package authority.
    validate_version2_package_tree(canonical, expected_integration_sha=sha)
    _launcher_identity(launcher)
    names = tuple(_portable_docx_name(path) for path in documents)
    if len({name.casefold() for name in names}) != 2:
        _fail("portable Word documents must have distinct filenames")
    for path in documents:
        _safe_info(path, label="portable Word document source", directory=False)

    if _path_entry_exists(output, label="portable package output"):
        _fail("portable package output must not already exist")
    try:
        output.parent.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        _fail(f"portable package output parent cannot be prepared: {type(exc).__name__}")

    staged = Path(tempfile.mkdtemp(prefix=f".{output.name}.portable-", dir=output.parent))
    try:
        _copy_file(launcher, staged / PORTABLE_LAUNCHER_NAME, label="portable launcher")
        _copy_tree(canonical / "AccessibleChess", staged / PORTABLE_APP_DIR, label="canonical product payload")
        _copy_tree(canonical / "THIRD_PARTY_NOTICES", staged / "THIRD_PARTY_NOTICES", label="canonical notices payload")
        for source, name in zip(documents, names, strict=True):
            _copy_file(source, staged / name, label="portable Word document")

        _assert_tree_copy_equal(canonical / "AccessibleChess", staged / PORTABLE_APP_DIR, label="canonical product payload")
        _assert_tree_copy_equal(canonical / "THIRD_PARTY_NOTICES", staged / "THIRD_PARTY_NOTICES", label="canonical notices payload")
        _write_portable_manifest(staged, sha, (names[0], names[1]))
        _write_checksums(staged)
        report = validate_portable_oneclick_tree(
            staged,
            expected_integration_sha=sha,
            require_user_seed=require_user_seed,
        )
        _publish_directory_no_replace(staged, output)
        return Version2PortablePackageReport(
            package_root=output,
            integration_sha=report.integration_sha,
            inventory=report.inventory,
            total_bytes=report.total_bytes,
        )
    finally:
        shutil.rmtree(staged, ignore_errors=True)


def write_portable_oneclick_zip(
    package_root: str | Path,
    zip_path: str | Path,
    *,
    expected_integration_sha: str,
    require_user_seed: bool = False,
) -> Version2PortablePackageReport:
    root = Path(package_root)
    target = Path(zip_path)
    report = validate_portable_oneclick_tree(
        root,
        expected_integration_sha=expected_integration_sha,
        require_user_seed=require_user_seed,
    )
    if _path_entry_exists(target, label="portable ZIP output"):
        _fail("portable ZIP output must not already exist")
    try:
        target.parent.mkdir(parents=True, exist_ok=True)
        root_resolved = root.resolve(strict=True)
        target_parent = target.parent.resolve(strict=True)
    except (OSError, RuntimeError) as exc:
        _fail(f"portable ZIP output cannot be prepared: {type(exc).__name__}")
    try:
        target_parent.relative_to(root_resolved)
    except ValueError:
        pass
    else:
        _fail("portable ZIP output must be outside the package tree")

    fd, temporary_name = tempfile.mkstemp(prefix=f".{target.name}.", suffix=".tmp", dir=target.parent)
    os.close(fd)
    temporary = Path(temporary_name)
    try:
        temporary.unlink()
        with zipfile.ZipFile(temporary, "x", compression=zipfile.ZIP_DEFLATED, compresslevel=9, allowZip64=True) as archive:
            for relative in report.inventory:
                source = root.joinpath(*PurePosixPath(relative).parts)
                info = zipfile.ZipInfo(relative, date_time=_FIXED_ZIP_TIMESTAMP)
                info.compress_type = zipfile.ZIP_DEFLATED
                info.create_system = 3
                info.external_attr = (stat.S_IFREG | 0o644) << 16
                with source.open("rb") as source_handle, archive.open(info, "w", force_zip64=True) as target_handle:
                    shutil.copyfileobj(source_handle, target_handle, length=_COPY_CHUNK_BYTES)

        with zipfile.ZipFile(temporary, "r") as archive:
            infos = archive.infolist()
            names = tuple(item.filename for item in infos)
            if names != report.inventory or len({name.casefold() for name in names}) != len(names):
                _fail("portable ZIP inventory changed during archive publication")
            if archive.testzip() is not None:
                _fail("portable ZIP CRC readback failed")
            for relative in report.inventory:
                digest = hashlib.sha256()
                with archive.open(relative, "r") as handle:
                    for block in iter(lambda: handle.read(_COPY_CHUNK_BYTES), b""):
                        digest.update(block)
                source = root.joinpath(*PurePosixPath(relative).parts)
                if digest.hexdigest() != _sha256(source):
                    _fail("portable ZIP byte readback failed")

        try:
            os.link(temporary, target)
            temporary.unlink()
        except OSError as exc:
            _fail(f"portable ZIP could not be published without replacement: {type(exc).__name__}")
        archive_sha = _sha256(target)
        return Version2PortablePackageReport(
            package_root=root,
            integration_sha=report.integration_sha,
            inventory=report.inventory,
            total_bytes=report.total_bytes,
            archive_path=target,
            archive_sha256=archive_sha,
        )
    finally:
        try:
            temporary.unlink()
        except FileNotFoundError:
            pass


__all__ = [
    "PORTABLE_APP_DIR",
    "PORTABLE_DATA_DIR",
    "PORTABLE_LAUNCHER_NAME",
    "PORTABLE_LAUNCH_REPORT",
    "PORTABLE_PACKAGE_PROFILE",
    "Version2PortablePackageError",
    "Version2PortablePackageReport",
    "assemble_portable_oneclick_tree",
    "validate_portable_oneclick_tree",
    "write_portable_oneclick_zip",
]
