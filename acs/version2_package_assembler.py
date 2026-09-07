from __future__ import annotations

"""Fail-closed assembly of a prepared Version 2 Windows product payload.

This module owns only the filesystem boundary between an already built product
folder and the canonical Version 2 package tree/ZIP.  It does not compile the
Windows executable, download engines, invent release authority, or publish an
artifact.  Every assembled tree and archive is accepted only through the
canonical :mod:`acs.version2_package_preflight` validator.
"""

from dataclasses import dataclass
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import shutil
import stat
import tempfile
from types import MappingProxyType
from typing import Mapping
import zipfile

from .acsdb import ACSDB_SCHEMA_VERSION
from .settings import SCHEMA_VERSION as SETTINGS_SCHEMA_VERSION
from .version2_package_preflight import (
    CHECKSUMS_NAME,
    MANIFEST_NAME,
    V2_PACKAGE_MANIFEST_SCHEMA_VERSION,
    V2_PACKAGE_PROFILE,
    Version2PackagePreflightReport,
    validate_version2_package_tree,
    validate_version2_package_zip,
)
from .version2_upgrade import UPGRADE_JOURNAL_SCHEMA_VERSION


_ALLOWED_DIAGNOSTICS = frozenset(
    {
        "native-menu-self-diagnostic.json",
        "packaged-uia-strict-summary.json",
    }
)
_FIXED_ZIP_TIMESTAMP = (1980, 1, 1, 0, 0, 0)


class Version2PackageAssemblyError(RuntimeError):
    """Raised when candidate assembly cannot be completed atomically."""


@dataclass(frozen=True, slots=True)
class Version2PackageAssemblyReport:
    package_root: Path
    tree_report: Version2PackagePreflightReport
    archive_path: Path | None = None
    archive_report: Version2PackagePreflightReport | None = None

    def as_dict(self) -> dict[str, object]:
        return {
            "package_root": str(self.package_root),
            "integration_sha": self.tree_report.integration_sha,
            "inventory_count": len(self.tree_report.inventory),
            "total_bytes": self.tree_report.total_bytes,
            "checksums_verified": self.tree_report.checksums_verified,
            "archive_path": None if self.archive_path is None else str(self.archive_path),
            "archive_sha256": (
                None if self.archive_report is None else self.archive_report.archive_sha256
            ),
            "nvda_verified": False,
            "result": "PASS",
        }


def _fail(message: str) -> None:
    raise Version2PackageAssemblyError(message)


def _sha40(value: object) -> str:
    if type(value) is not str:
        _fail("integration_sha must be a 40-hex commit")
    token = value.strip().casefold()
    if len(token) != 40 or any(char not in "0123456789abcdef" for char in token):
        _fail("integration_sha must be a 40-hex commit")
    return token


def _reparse(info: os.stat_result) -> bool:
    flag = getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400)
    return bool(getattr(info, "st_file_attributes", 0) & flag)


def _safe_info(path: Path, *, label: str, directory: bool | None = None) -> os.stat_result:
    try:
        info = path.lstat()
    except OSError as exc:
        _fail(f"{label} cannot be inspected: {type(exc).__name__}")
    if stat.S_ISLNK(info.st_mode) or _reparse(info):
        _fail(f"{label} must not be a symlink or reparse point")
    if directory is True and not stat.S_ISDIR(info.st_mode):
        _fail(f"{label} must be a directory")
    if directory is False and not stat.S_ISREG(info.st_mode):
        _fail(f"{label} must be a regular file")
    return info


def _copy_tree(source: Path, destination: Path, *, label: str) -> None:
    _safe_info(source, label=label, directory=True)
    destination.mkdir(parents=True, exist_ok=False)
    try:
        walker = os.walk(source, topdown=True, followlinks=False)
        for dirpath, dirnames, filenames in walker:
            current = Path(dirpath)
            relative = current.relative_to(source)
            target_current = destination.joinpath(*relative.parts)
            for name in dirnames:
                source_dir = current / name
                _safe_info(source_dir, label=label, directory=True)
                target_current.joinpath(name).mkdir(exist_ok=False)
            for name in filenames:
                source_file = current / name
                _safe_info(source_file, label=label, directory=False)
                target_file = target_current / name
                shutil.copyfile(source_file, target_file, follow_symlinks=False)
                try:
                    shutil.copystat(source_file, target_file, follow_symlinks=False)
                except OSError:
                    # Metadata preservation is non-authoritative. File bytes and
                    # the later canonical checksum/preflight are authoritative.
                    pass
    except Version2PackageAssemblyError:
        raise
    except (OSError, ValueError) as exc:
        _fail(f"{label} could not be copied: {type(exc).__name__}")


def _copy_file(source: Path, destination: Path, *, label: str) -> None:
    _safe_info(source, label=label, directory=False)
    try:
        shutil.copyfile(source, destination, follow_symlinks=False)
    except OSError as exc:
        _fail(f"{label} could not be copied: {type(exc).__name__}")


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    try:
        with path.open("rb") as handle:
            for block in iter(lambda: handle.read(1024 * 1024), b""):
                digest.update(block)
    except OSError as exc:
        _fail(f"package file cannot be hashed: {type(exc).__name__}")
    return digest.hexdigest()


def _write_manifest(root: Path, integration_sha: str) -> None:
    manifest = {
        "manifest_schema": V2_PACKAGE_MANIFEST_SCHEMA_VERSION,
        "product": "Accessible Chess",
        "package_profile": V2_PACKAGE_PROFILE,
        "integration_sha": integration_sha,
        "nvda_verified": False,
        "upgrade_from_version1": True,
        "upgrade_journal_schema": UPGRADE_JOURNAL_SCHEMA_VERSION,
        "settings_schema": SETTINGS_SCHEMA_VERSION,
        "acsdb_schema": ACSDB_SCHEMA_VERSION,
        "user_data_bundled": False,
        "raw_source_bundled": False,
        "optional_external_backends_bundled": False,
    }
    try:
        (root / MANIFEST_NAME).write_text(
            json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
            newline="\n",
        )
    except OSError as exc:
        _fail(f"release manifest could not be written: {type(exc).__name__}")


def _relative_files(root: Path) -> tuple[str, ...]:
    result: list[str] = []
    try:
        for path in root.rglob("*"):
            info = _safe_info(path, label="assembled package entry")
            if stat.S_ISDIR(info.st_mode):
                continue
            if not stat.S_ISREG(info.st_mode):
                _fail("assembled package entry must be a regular file")
            relative = PurePosixPath(*path.relative_to(root).parts).as_posix()
            if relative != CHECKSUMS_NAME:
                result.append(relative)
    except Version2PackageAssemblyError:
        raise
    except (OSError, ValueError) as exc:
        _fail(f"assembled package inventory failed: {type(exc).__name__}")
    return tuple(sorted(result, key=str.casefold))


def _write_checksums(root: Path) -> None:
    lines = [
        f"{_sha256(root.joinpath(*PurePosixPath(relative).parts))}  {relative}"
        for relative in _relative_files(root)
    ]
    try:
        (root / CHECKSUMS_NAME).write_text(
            "\n".join(lines) + "\n",
            encoding="utf-8",
            newline="\n",
        )
    except OSError as exc:
        _fail(f"checksum inventory could not be written: {type(exc).__name__}")


def _diagnostics(value: Mapping[str, str | Path] | None) -> Mapping[str, Path]:
    if value is None:
        return MappingProxyType({})
    if not isinstance(value, Mapping):
        raise TypeError("diagnostic_files must be a mapping or None")
    normalized: dict[str, Path] = {}
    for name, source in value.items():
        if type(name) is not str or name not in _ALLOWED_DIAGNOSTICS:
            _fail("diagnostic file name is not allowed in the Version 2 package")
        if name in normalized:
            _fail("diagnostic file names must be unique")
        normalized[name] = Path(source)
    return MappingProxyType(normalized)


def assemble_version2_package_tree(
    prepared_product_dir: str | Path,
    third_party_notices_dir: str | Path,
    output_root: str | Path,
    *,
    integration_sha: str,
    diagnostic_files: Mapping[str, str | Path] | None = None,
) -> Version2PackageAssemblyReport:
    """Atomically assemble and validate one canonical Version 2 package tree."""

    sha = _sha40(integration_sha)
    product = Path(prepared_product_dir)
    notices = Path(third_party_notices_dir)
    output = Path(output_root)
    diagnostics = _diagnostics(diagnostic_files)

    _safe_info(product, label="prepared product directory", directory=True)
    _safe_info(notices, label="third-party notices directory", directory=True)
    if output.exists():
        _fail("package output must not already exist")
    try:
        output.parent.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        _fail(f"package output parent cannot be prepared: {type(exc).__name__}")

    holder = Path(tempfile.mkdtemp(prefix=".accessible-chess-v2-assemble-", dir=output.parent))
    staged = holder / "package"
    try:
        staged.mkdir()
        _copy_tree(product, staged / "AccessibleChess", label="prepared product directory")
        _copy_tree(notices, staged / "THIRD_PARTY_NOTICES", label="third-party notices directory")
        for name, source in diagnostics.items():
            _copy_file(source, staged / name, label="release diagnostic evidence")
        _write_manifest(staged, sha)
        _write_checksums(staged)
        report = validate_version2_package_tree(
            staged,
            expected_integration_sha=sha,
        )
        try:
            staged.rename(output)
        except OSError as exc:
            _fail(f"validated package could not be published atomically: {type(exc).__name__}")
        return Version2PackageAssemblyReport(package_root=output, tree_report=report)
    finally:
        shutil.rmtree(holder, ignore_errors=True)


def write_version2_package_zip(
    package_root: str | Path,
    zip_path: str | Path,
    *,
    expected_integration_sha: str,
) -> Version2PackagePreflightReport:
    """Create one deterministic archive and accept it only after readback."""

    sha = _sha40(expected_integration_sha)
    root = Path(package_root)
    target = Path(zip_path)
    tree_report = validate_version2_package_tree(root, expected_integration_sha=sha)
    if target.exists():
        _fail("Version 2 ZIP output must not already exist")
    try:
        target.parent.mkdir(parents=True, exist_ok=True)
        root_resolved = root.resolve(strict=True)
        target_parent = target.parent.resolve(strict=True)
    except (OSError, RuntimeError) as exc:
        _fail(f"Version 2 ZIP output cannot be prepared: {type(exc).__name__}")
    try:
        target_parent.relative_to(root_resolved)
    except ValueError:
        pass
    else:
        _fail("Version 2 ZIP output must be outside the package tree")

    fd, temporary_name = tempfile.mkstemp(
        prefix=f".{target.name}.",
        suffix=".tmp",
        dir=target.parent,
    )
    os.close(fd)
    temporary = Path(temporary_name)
    try:
        temporary.unlink()
        with zipfile.ZipFile(
            temporary,
            mode="x",
            compression=zipfile.ZIP_DEFLATED,
            compresslevel=9,
            allowZip64=True,
        ) as archive:
            for relative in tree_report.inventory:
                source = root.joinpath(*PurePosixPath(relative).parts)
                _safe_info(source, label="package archive source", directory=False)
                info = zipfile.ZipInfo(relative, date_time=_FIXED_ZIP_TIMESTAMP)
                info.compress_type = zipfile.ZIP_DEFLATED
                info.create_system = 3
                info.external_attr = (stat.S_IFREG | 0o644) << 16
                try:
                    archive.writestr(info, source.read_bytes(), compress_type=zipfile.ZIP_DEFLATED, compresslevel=9)
                except OSError as exc:
                    _fail(f"package archive source could not be read: {type(exc).__name__}")
        report = validate_version2_package_zip(
            temporary,
            expected_integration_sha=sha,
        )
        try:
            os.replace(temporary, target)
        except OSError as exc:
            _fail(f"validated Version 2 ZIP could not be published atomically: {type(exc).__name__}")
        return report
    finally:
        try:
            temporary.unlink(missing_ok=True)
        except OSError:
            pass
