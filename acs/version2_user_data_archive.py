from __future__ import annotations

"""Production Section-37 user-data archive and restart-safe publication.

This module is deliberately a byte-preservation layer.  It reuses the canonical
Version-2 upgrade inventory to discover durable files and never interprets chess,
Classroom, Media, Agent, or Library semantics.  Library snapshotting delegates to
the live AcsDatabase backup API when the application is running.

Restore/import is never published over open durable writers.  The native action
only validates and stages an archive.  Startup applies it before Settings/ACSDB
writers open by publishing a fully prepared sibling directory, with an external
journal and an exact old-root directory retained until the normal V2 upgrader
accepts the imported state.
"""

from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from collections.abc import Callable
import hashlib
import json
import os
import re
import secrets
import shutil
import stat
import tempfile
import zipfile

from .acsdb import AcsDatabase
from .settings import Settings
from .version2_upgrade import (
    UpgradeLimits,
    UserDataLayout,
    Version2UpgradeCoordinator,
    Version2UpgradeError,
    _UpgradeLock,
    _fsync_dir,
    _relative,
    _relative_token,
)


ARCHIVE_SCHEMA_VERSION = 1
_ARCHIVE_MANIFEST = "manifest.json"
_ARCHIVE_DATA_PREFIX = "data/"
_MAX_MANIFEST_BYTES = 16 * 1024 * 1024
_ARCHIVE_KINDS = frozenset({"backup", "portable"})
_EXPORT_SUFFIXES = frozenset({".acsbackup", ".acsdata"})
_CONTROL_MARKER = ".section37-portability-control"

_SECRET_WORDS = frozenset(
    {
        "auth",
        "authentication",
        "cookie",
        "cookies",
        "credential",
        "credentials",
        "oauth",
        "password",
        "passwords",
        "secret",
        "secrets",
        "token",
        "tokens",
        "apikey",
        "api-key",
        "privatekey",
        "private-key",
    }
)


class Version2UserDataArchiveError(RuntimeError):
    pass


@dataclass(frozen=True, slots=True)
class ArchiveEntry:
    path: str
    size: int
    sha256: str


@dataclass(frozen=True, slots=True)
class ArchiveReceipt:
    kind: str
    file_count: int
    total_bytes: int
    archive_sha256: str


@dataclass(frozen=True, slots=True)
class ValidatedArchive:
    kind: str
    settings_name: str
    library_name: str
    entries: tuple[ArchiveEntry, ...]


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while True:
            block = handle.read(1024 * 1024)
            if not block:
                break
            digest.update(block)
    return digest.hexdigest()


def _exact_directory(path: Path, label: str) -> os.stat_result:
    try:
        info = path.lstat()
    except OSError as exc:
        raise Version2UserDataArchiveError(f"{label} is unavailable") from exc
    if stat.S_ISLNK(info.st_mode) or not stat.S_ISDIR(info.st_mode):
        raise Version2UserDataArchiveError(f"{label} must be a real directory")
    if getattr(info, "st_file_attributes", 0) & getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0):
        raise Version2UserDataArchiveError(f"{label} must not be a reparse point")
    return info


def _exact_regular(path: Path, label: str) -> os.stat_result:
    try:
        info = path.lstat()
    except OSError as exc:
        raise Version2UserDataArchiveError(f"{label} is unavailable") from exc
    if stat.S_ISLNK(info.st_mode) or not stat.S_ISREG(info.st_mode):
        raise Version2UserDataArchiveError(f"{label} must be a real regular file")
    if getattr(info, "st_file_attributes", 0) & getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0):
        raise Version2UserDataArchiveError(f"{label} must not be a reparse point")
    return info


def _path_identity(info: os.stat_result) -> tuple[int, int]:
    return int(info.st_dev), int(info.st_ino)


def _private_file(path: Path) -> None:
    try:
        os.chmod(path, 0o600)
    except OSError:
        if os.name != "nt":
            raise


def _portable_secret_path(relative: str) -> bool:
    token = PurePosixPath(relative)
    for part in token.parts:
        folded = part.casefold()
        stem = folded.rsplit(".", 1)[0]
        words = tuple(word for word in re.split(r"[^a-z0-9]+", stem) if word)
        if any(word in _SECRET_WORDS for word in words):
            return True
        if stem.startswith(("oauth", "token", "credential", "secret", "password", "cookie", "apikey", "privatekey")):
            return True
    return False


def _portable_export_path(relative: str) -> bool:
    if _portable_secret_path(relative):
        return False
    suffix = PurePosixPath(relative).suffix.casefold()
    if suffix in _EXPORT_SUFFIXES:
        return False
    if PurePosixPath(relative).name == _CONTROL_MARKER:
        return False
    return True


def _pending_path(layout: UserDataLayout) -> Path:
    return layout.root.parent / f".{layout.root.name}.section37-pending.acsdata"


def _journal_path(layout: UserDataLayout) -> Path:
    return layout.root.parent / f".{layout.root.name}.section37-import-journal.json"


def _write_json_atomic(path: Path, value: dict[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, raw = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=str(path.parent))
    temp = Path(raw)
    try:
        with os.fdopen(fd, "wb") as handle:
            payload = (
                json.dumps(
                    value,
                    ensure_ascii=False,
                    sort_keys=True,
                    separators=(",", ":"),
                    allow_nan=False,
                )
                + "\n"
            ).encode("utf-8")
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        _private_file(temp)
        os.replace(temp, path)
        _fsync_dir(path.parent)
    finally:
        if temp.exists():
            temp.unlink()


def _read_json_object(path: Path, label: str) -> dict[str, object]:
    _exact_regular(path, label)
    try:
        raw = path.read_bytes()
        if len(raw) > _MAX_MANIFEST_BYTES:
            raise Version2UserDataArchiveError(f"{label} is too large")

        def unique(pairs: list[tuple[str, object]]) -> dict[str, object]:
            result: dict[str, object] = {}
            for key, value in pairs:
                if key in result:
                    raise Version2UserDataArchiveError(f"{label} contains duplicate keys")
                result[key] = value
            return result

        value = json.loads(raw.decode("utf-8"), object_pairs_hook=unique)
    except Version2UserDataArchiveError:
        raise
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise Version2UserDataArchiveError(f"{label} is invalid") from exc
    if type(value) is not dict:
        raise Version2UserDataArchiveError(f"{label} must be an object")
    return value


def _write_source_to_zip(
    archive: zipfile.ZipFile,
    member_name: str,
    source: Path,
    *,
    max_bytes: int,
) -> tuple[int, str]:
    before_path = _exact_regular(source, "user-data source")
    digest = hashlib.sha256()
    total = 0
    with source.open("rb") as source_handle:
        opened = os.fstat(source_handle.fileno())
        if not os.path.samestat(before_path, opened):
            raise Version2UserDataArchiveError("user-data source changed before archive read")
        info = zipfile.ZipInfo(member_name)
        info.compress_type = zipfile.ZIP_STORED
        info.external_attr = 0o600 << 16
        with archive.open(info, "w", force_zip64=True) as target:
            while True:
                block = source_handle.read(1024 * 1024)
                if not block:
                    break
                total += len(block)
                if total > max_bytes:
                    raise Version2UserDataArchiveError("user-data archive exceeds byte limit")
                digest.update(block)
                target.write(block)
        after_open = os.fstat(source_handle.fileno())
    after_path = _exact_regular(source, "user-data source")
    if (
        not os.path.samestat(opened, after_open)
        or not os.path.samestat(after_open, after_path)
        or int(opened.st_size) != int(after_open.st_size)
        or int(getattr(opened, "st_mtime_ns", 0)) != int(getattr(after_open, "st_mtime_ns", 0))
    ):
        raise Version2UserDataArchiveError("user-data source changed during archive read")
    if total != int(after_open.st_size):
        raise Version2UserDataArchiveError("user-data source length changed during archive read")
    return total, digest.hexdigest()


class Version2UserDataArchiveService:
    """Create and stage bounded user-data archives over canonical V2 inventory."""

    def __init__(
        self,
        layout: UserDataLayout,
        *,
        live_database: AcsDatabase | None = None,
        limits: UpgradeLimits = UpgradeLimits(),
    ) -> None:
        if not isinstance(layout, UserDataLayout):
            raise TypeError("layout must be UserDataLayout")
        if live_database is not None and not isinstance(live_database, AcsDatabase):
            raise TypeError("live_database must be AcsDatabase or None")
        if not isinstance(limits, UpgradeLimits):
            raise TypeError("limits must be UpgradeLimits")
        self.layout = layout
        self.live_database = live_database
        self.limits = limits

    def _inventory(self) -> tuple[Path, ...]:
        coordinator = Version2UpgradeCoordinator(self.layout, limits=self.limits)
        coordinator._ensure_roots()
        with _UpgradeLock(self.layout.lock_path) as upgrade_lock:
            coordinator._active_upgrade_lock = upgrade_lock
            try:
                coordinator._assert_upgrade_lock()
                return coordinator._files()
            finally:
                coordinator._active_upgrade_lock = None

    def _library_snapshot(self) -> Path | None:
        if self.live_database is None or not self.layout.library_path.exists():
            return None
        self.layout.backup_root.mkdir(parents=True, exist_ok=True)
        destination = self.layout.backup_root / (
            f".section37-library-{secrets.token_hex(8)}.acsdb"
        )
        self.live_database.backup_to(destination)
        return destination

    def create_archive(self, destination: str | Path, *, kind: str) -> ArchiveReceipt:
        if kind not in _ARCHIVE_KINDS:
            raise ValueError("archive kind must be backup or portable")
        destination = Path(destination)
        if destination.exists() or destination.is_symlink():
            info = destination.lstat()
            if stat.S_ISDIR(info.st_mode) or stat.S_ISLNK(info.st_mode):
                raise Version2UserDataArchiveError("archive destination is not a regular file")
        destination.parent.mkdir(parents=True, exist_ok=True)
        inventory = self._inventory()
        if kind == "portable":
            inventory = tuple(
                path
                for path in inventory
                if _portable_export_path(_relative(self.layout.root, path))
            )

        fd, raw_temp = tempfile.mkstemp(
            prefix=f".{destination.name}.",
            suffix=".tmp",
            dir=str(destination.parent),
        )
        os.close(fd)
        temp = Path(raw_temp)
        library_snapshot: Path | None = None
        entries: list[ArchiveEntry] = []
        total = 0
        try:
            temp.unlink()
            library_snapshot = self._library_snapshot()
            with zipfile.ZipFile(
                temp,
                "w",
                compression=zipfile.ZIP_STORED,
                allowZip64=True,
            ) as archive:
                for source in inventory:
                    relative = _relative(self.layout.root, source)
                    actual = (
                        library_snapshot
                        if relative == self.layout.library_name
                        and library_snapshot is not None
                        else source
                    )
                    size, digest = _write_source_to_zip(
                        archive,
                        _ARCHIVE_DATA_PREFIX + relative,
                        actual,
                        max_bytes=self.limits.max_bytes,
                    )
                    total += size
                    if total > self.limits.max_bytes:
                        raise Version2UserDataArchiveError(
                            "user-data archive exceeds byte limit"
                        )
                    entries.append(ArchiveEntry(relative, size, digest))
                manifest = {
                    "schema_version": ARCHIVE_SCHEMA_VERSION,
                    "kind": kind,
                    "settings_name": self.layout.settings_name,
                    "library_name": self.layout.library_name,
                    "entries": [
                        {
                            "path": entry.path,
                            "size": entry.size,
                            "sha256": entry.sha256,
                        }
                        for entry in entries
                    ],
                }
                manifest_bytes = (
                    json.dumps(
                        manifest,
                        ensure_ascii=False,
                        sort_keys=True,
                        separators=(",", ":"),
                        allow_nan=False,
                    )
                    + "\n"
                ).encode("utf-8")
                if len(manifest_bytes) > _MAX_MANIFEST_BYTES:
                    raise Version2UserDataArchiveError("archive manifest is too large")
                info = zipfile.ZipInfo(_ARCHIVE_MANIFEST)
                info.compress_type = zipfile.ZIP_STORED
                info.external_attr = 0o600 << 16
                archive.writestr(info, manifest_bytes)
            _private_file(temp)
            with temp.open("rb") as handle:
                os.fsync(handle.fileno())
            validate_user_data_archive(
                temp,
                expected_kind=kind,
                limits=self.limits,
                settings_name=self.layout.settings_name,
                library_name=self.layout.library_name,
            )
            os.replace(temp, destination)
            _fsync_dir(destination.parent)
            return ArchiveReceipt(
                kind,
                len(entries),
                total,
                _sha256_file(destination),
            )
        except Version2UserDataArchiveError:
            raise
        except (OSError, zipfile.BadZipFile, Version2UpgradeError) as exc:
            raise Version2UserDataArchiveError("user-data archive could not be created") from exc
        finally:
            if temp.exists():
                try:
                    temp.unlink()
                except OSError:
                    pass
            if library_snapshot is not None and library_snapshot.exists():
                try:
                    library_snapshot.unlink()
                except OSError:
                    pass

    def stage_import(self, source: str | Path, *, expected_kind: str) -> ArchiveReceipt:
        source = Path(source)
        validated = validate_user_data_archive(
            source,
            expected_kind=expected_kind,
            limits=self.limits,
            settings_name=self.layout.settings_name,
            library_name=self.layout.library_name,
        )
        pending = _pending_path(self.layout)
        if pending.exists() or pending.is_symlink():
            raise Version2UserDataArchiveError(
                "another user-data restore/import is already scheduled"
            )
        pending.parent.mkdir(parents=True, exist_ok=True)
        fd, raw_temp = tempfile.mkstemp(
            prefix=f".{pending.name}.",
            suffix=".tmp",
            dir=str(pending.parent),
        )
        temp = Path(raw_temp)
        try:
            with source.open("rb") as src, os.fdopen(fd, "wb") as dst:
                while True:
                    block = src.read(1024 * 1024)
                    if not block:
                        break
                    dst.write(block)
                dst.flush()
                os.fsync(dst.fileno())
            _private_file(temp)
            validate_user_data_archive(
                temp,
                expected_kind=expected_kind,
                limits=self.limits,
                settings_name=self.layout.settings_name,
                library_name=self.layout.library_name,
            )
            os.replace(temp, pending)
            _fsync_dir(pending.parent)
            return ArchiveReceipt(
                validated.kind,
                len(validated.entries),
                sum(entry.size for entry in validated.entries),
                _sha256_file(pending),
            )
        except Version2UserDataArchiveError:
            raise
        except OSError as exc:
            raise Version2UserDataArchiveError("user-data archive could not be staged") from exc
        finally:
            if temp.exists():
                try:
                    temp.unlink()
                except OSError:
                    pass


def validate_user_data_archive(
    source: str | Path,
    *,
    expected_kind: str | None = None,
    limits: UpgradeLimits = UpgradeLimits(),
    settings_name: str | None = None,
    library_name: str | None = None,
) -> ValidatedArchive:
    source = Path(source)
    _exact_regular(source, "user-data archive")
    try:
        with zipfile.ZipFile(source, "r", allowZip64=True) as archive:
            infos = archive.infolist()
            names = [info.filename for info in infos]
            if len(names) != len(set(names)):
                raise Version2UserDataArchiveError("archive contains duplicate members")
            if _ARCHIVE_MANIFEST not in names:
                raise Version2UserDataArchiveError("archive manifest is missing")
            if any(info.is_dir() for info in infos):
                raise Version2UserDataArchiveError("archive directory members are not canonical")
            if any(info.compress_type != zipfile.ZIP_STORED for info in infos):
                raise Version2UserDataArchiveError("archive compression is not canonical")
            manifest_info = archive.getinfo(_ARCHIVE_MANIFEST)
            if manifest_info.file_size > _MAX_MANIFEST_BYTES:
                raise Version2UserDataArchiveError("archive manifest is too large")
            raw = archive.read(_ARCHIVE_MANIFEST)

            def unique(pairs: list[tuple[str, object]]) -> dict[str, object]:
                result: dict[str, object] = {}
                for key, value in pairs:
                    if key in result:
                        raise Version2UserDataArchiveError(
                            "archive manifest contains duplicate keys"
                        )
                    result[key] = value
                return result

            manifest = json.loads(raw.decode("utf-8"), object_pairs_hook=unique)
            if type(manifest) is not dict or set(manifest) != {
                "schema_version",
                "kind",
                "settings_name",
                "library_name",
                "entries",
            }:
                raise Version2UserDataArchiveError("archive manifest envelope is invalid")
            if manifest["schema_version"] != ARCHIVE_SCHEMA_VERSION:
                raise Version2UserDataArchiveError("archive schema is unsupported")
            kind = manifest["kind"]
            if type(kind) is not str or kind not in _ARCHIVE_KINDS:
                raise Version2UserDataArchiveError("archive kind is invalid")
            if expected_kind is not None and kind != expected_kind:
                raise Version2UserDataArchiveError("archive kind does not match requested operation")
            manifest_settings = manifest["settings_name"]
            manifest_library = manifest["library_name"]
            if type(manifest_settings) is not str or type(manifest_library) is not str:
                raise Version2UserDataArchiveError("archive canonical filenames are invalid")
            if settings_name is not None and manifest_settings != settings_name:
                raise Version2UserDataArchiveError("archive settings filename does not match this installation")
            if library_name is not None and manifest_library != library_name:
                raise Version2UserDataArchiveError("archive Library filename does not match this installation")
            entries_raw = manifest["entries"]
            if type(entries_raw) is not list or len(entries_raw) > limits.max_files:
                raise Version2UserDataArchiveError("archive entry collection is invalid")
            entries: list[ArchiveEntry] = []
            seen: set[str] = set()
            total = 0
            expected_members = {_ARCHIVE_MANIFEST}
            for raw_entry in entries_raw:
                if type(raw_entry) is not dict or set(raw_entry) != {"path", "size", "sha256"}:
                    raise Version2UserDataArchiveError("archive entry is invalid")
                relative = raw_entry["path"]
                size = raw_entry["size"]
                digest = raw_entry["sha256"]
                if type(relative) is not str or "\\" in relative:
                    raise Version2UserDataArchiveError("archive data path is invalid")
                try:
                    canonical = _relative_token(relative)
                except Version2UpgradeError as exc:
                    raise Version2UserDataArchiveError("archive data path is invalid") from exc
                if canonical != relative:
                    raise Version2UserDataArchiveError("archive data path is not canonical")
                folded = relative.casefold()
                if folded in seen:
                    raise Version2UserDataArchiveError("archive data paths collide")
                seen.add(folded)
                if kind == "portable" and not _portable_export_path(relative):
                    raise Version2UserDataArchiveError(
                        "portable archive contains non-portable credential/control data"
                    )
                if type(size) is not int or size < 0:
                    raise Version2UserDataArchiveError("archive entry size is invalid")
                if (
                    type(digest) is not str
                    or len(digest) != 64
                    or any(ch not in "0123456789abcdef" for ch in digest)
                ):
                    raise Version2UserDataArchiveError("archive entry checksum is invalid")
                total += size
                if total > limits.max_bytes:
                    raise Version2UserDataArchiveError("archive exceeds byte limit")
                member_name = _ARCHIVE_DATA_PREFIX + relative
                expected_members.add(member_name)
                try:
                    info = archive.getinfo(member_name)
                except KeyError as exc:
                    raise Version2UserDataArchiveError("archive data member is missing") from exc
                if info.file_size != size:
                    raise Version2UserDataArchiveError("archive data member size mismatch")
                actual = hashlib.sha256()
                read_total = 0
                with archive.open(info, "r") as handle:
                    while True:
                        block = handle.read(1024 * 1024)
                        if not block:
                            break
                        read_total += len(block)
                        if read_total > size:
                            raise Version2UserDataArchiveError("archive data member exceeds declared size")
                        actual.update(block)
                if read_total != size or actual.hexdigest() != digest:
                    raise Version2UserDataArchiveError("archive data member checksum mismatch")
                entries.append(ArchiveEntry(relative, size, digest))
            if set(names) != expected_members:
                raise Version2UserDataArchiveError("archive contains undeclared members")
            if tuple(entry.path.casefold() for entry in entries) != tuple(
                sorted((entry.path.casefold() for entry in entries))
            ):
                raise Version2UserDataArchiveError("archive entries are not in canonical order")
            return ValidatedArchive(
                kind,
                manifest_settings,
                manifest_library,
                tuple(entries),
            )
    except Version2UserDataArchiveError:
        raise
    except (OSError, UnicodeError, json.JSONDecodeError, zipfile.BadZipFile) as exc:
        raise Version2UserDataArchiveError("user-data archive is invalid") from exc


def _copy_regular(source: Path, destination: Path) -> None:
    before = _exact_regular(source, "preserved local data")
    destination.parent.mkdir(parents=True, exist_ok=True)
    with source.open("rb") as src, destination.open("xb") as dst:
        opened = os.fstat(src.fileno())
        if not os.path.samestat(before, opened):
            raise Version2UserDataArchiveError("preserved local data changed before copy")
        while True:
            block = src.read(1024 * 1024)
            if not block:
                break
            dst.write(block)
        dst.flush()
        os.fsync(dst.fileno())
        after = os.fstat(src.fileno())
    current = _exact_regular(source, "preserved local data")
    if not os.path.samestat(opened, after) or not os.path.samestat(after, current):
        raise Version2UserDataArchiveError("preserved local data changed during copy")
    _private_file(destination)


def _extract_archive_to_stage(
    archive_path: Path,
    validated: ValidatedArchive,
    stage: Path,
) -> None:
    with zipfile.ZipFile(archive_path, "r", allowZip64=True) as archive:
        for entry in validated.entries:
            destination = stage / Path(*PurePosixPath(entry.path).parts)
            destination.parent.mkdir(parents=True, exist_ok=True)
            info = archive.getinfo(_ARCHIVE_DATA_PREFIX + entry.path)
            digest = hashlib.sha256()
            total = 0
            with archive.open(info, "r") as src, destination.open("xb") as dst:
                while True:
                    block = src.read(1024 * 1024)
                    if not block:
                        break
                    total += len(block)
                    if total > entry.size:
                        raise Version2UserDataArchiveError("archive member exceeded validated size")
                    digest.update(block)
                    dst.write(block)
                dst.flush()
                os.fsync(dst.fileno())
            _private_file(destination)
            if total != entry.size or digest.hexdigest() != entry.sha256:
                raise Version2UserDataArchiveError("archive member changed during extraction")


def _validate_staged_canonical_state(stage: Path, validated: ValidatedArchive) -> None:
    settings = stage / validated.settings_name
    if settings.exists():
        try:
            candidate = Settings(settings)
            candidate.export_json()
        except Exception as exc:
            raise Version2UserDataArchiveError("imported Settings state is invalid") from exc
    library = stage / validated.library_name
    if library.exists():
        database: AcsDatabase | None = None
        try:
            database = AcsDatabase(library)
            database.verify_integrity()
        except Exception as exc:
            raise Version2UserDataArchiveError("imported Library state is invalid") from exc
        finally:
            if database is not None:
                database.close()


def _safe_remove_tree(path: Path) -> None:
    if not path.exists() and not path.is_symlink():
        return
    _exact_directory(path, "Section-37 transaction directory")
    shutil.rmtree(path)


def _recover_interrupted_transaction(layout: UserDataLayout) -> None:
    journal_path = _journal_path(layout)
    if not journal_path.exists() and not journal_path.is_symlink():
        return
    journal = _read_json_object(journal_path, "Section-37 import journal")
    if set(journal) != {
        "schema_version",
        "phase",
        "old_name",
        "stage_name",
        "published_dev",
        "published_ino",
    } or journal.get("schema_version") != 1:
        raise Version2UserDataArchiveError("Section-37 import journal is invalid")
    phase = journal.get("phase")
    old_name = journal.get("old_name")
    stage_name = journal.get("stage_name")
    if (
        phase not in {"prepared", "old_moved", "published"}
        or type(old_name) is not str
        or type(stage_name) is not str
        or "/" in old_name
        or "\\" in old_name
        or "/" in stage_name
        or "\\" in stage_name
    ):
        raise Version2UserDataArchiveError("Section-37 import journal identity is invalid")
    parent = layout.root.parent
    old = parent / old_name
    stage = parent / stage_name

    if phase == "prepared":
        if old.exists() or old.is_symlink():
            raise Version2UserDataArchiveError("unexpected rollback directory during import recovery")
        _safe_remove_tree(stage)
    elif phase == "old_moved":
        if layout.root.exists() or layout.root.is_symlink():
            raise Version2UserDataArchiveError("unexpected live root during import recovery")
        _exact_directory(old, "Section-37 rollback directory")
        _safe_remove_tree(stage)
        os.replace(old, layout.root)
        _fsync_dir(parent)
    else:
        root_info = _exact_directory(layout.root, "imported user-data root")
        expected = (journal.get("published_dev"), journal.get("published_ino"))
        if expected != _path_identity(root_info):
            raise Version2UserDataArchiveError(
                "published user-data root identity changed before recovery"
            )
        _exact_directory(old, "Section-37 rollback directory")
        failed = parent / f".{layout.root.name}.section37-recovered-{secrets.token_hex(6)}"
        os.replace(layout.root, failed)
        try:
            os.replace(old, layout.root)
            _fsync_dir(parent)
        except BaseException:
            if not layout.root.exists() and failed.exists():
                os.replace(failed, layout.root)
            raise
        _safe_remove_tree(failed)
        _safe_remove_tree(stage)
    try:
        journal_path.unlink()
    except OSError as exc:
        raise Version2UserDataArchiveError("Section-37 import journal could not be cleared") from exc
    _fsync_dir(parent)


class PendingUserDataTransaction:
    def __init__(
        self,
        layout: UserDataLayout,
        *,
        old: Path,
        published_identity: tuple[int, int],
    ) -> None:
        self.layout = layout
        self.old = old
        self.published_identity = published_identity
        self._finished = False

    def commit(self) -> None:
        if self._finished:
            raise RuntimeError("user-data transaction is already finished")
        root_info = _exact_directory(self.layout.root, "imported user-data root")
        if _path_identity(root_info) != self.published_identity:
            raise Version2UserDataArchiveError(
                "imported user-data root identity changed before commit"
            )
        _safe_remove_tree(self.old)
        pending = _pending_path(self.layout)
        journal = _journal_path(self.layout)
        if pending.exists():
            pending.unlink()
        if journal.exists():
            journal.unlink()
        _fsync_dir(self.layout.root.parent)
        self._finished = True

    def rollback(self) -> None:
        if self._finished:
            raise RuntimeError("user-data transaction is already finished")
        root_info = _exact_directory(self.layout.root, "imported user-data root")
        if _path_identity(root_info) != self.published_identity:
            raise Version2UserDataArchiveError(
                "imported user-data root identity changed before rollback"
            )
        parent = self.layout.root.parent
        failed = parent / f".{self.layout.root.name}.section37-failed-{secrets.token_hex(6)}"
        os.replace(self.layout.root, failed)
        try:
            _exact_directory(self.old, "Section-37 rollback directory")
            os.replace(self.old, self.layout.root)
            _fsync_dir(parent)
        except BaseException:
            if not self.layout.root.exists() and failed.exists():
                os.replace(failed, self.layout.root)
            raise
        _safe_remove_tree(failed)
        pending = _pending_path(self.layout)
        journal = _journal_path(self.layout)
        if pending.exists():
            pending.unlink()
        if journal.exists():
            journal.unlink()
        _fsync_dir(parent)
        self._finished = True


def begin_pending_user_data_transaction(
    layout: UserDataLayout,
    *,
    limits: UpgradeLimits = UpgradeLimits(),
) -> PendingUserDataTransaction | None:
    if not isinstance(layout, UserDataLayout):
        raise TypeError("layout must be UserDataLayout")
    _recover_interrupted_transaction(layout)
    pending = _pending_path(layout)
    if not pending.exists() and not pending.is_symlink():
        return None
    validated = validate_user_data_archive(
        pending,
        limits=limits,
        settings_name=layout.settings_name,
        library_name=layout.library_name,
    )
    parent = layout.root.parent
    parent.mkdir(parents=True, exist_ok=True)
    if not layout.root.exists() and not layout.root.is_symlink():
        layout.root.mkdir()
        _fsync_dir(parent)
    _exact_directory(layout.root, "Version-2 user-data root")

    nonce = secrets.token_hex(8)
    stage = parent / f".{layout.root.name}.section37-stage-{nonce}"
    old = parent / f".{layout.root.name}.section37-old-{nonce}"
    if stage.exists() or stage.is_symlink() or old.exists() or old.is_symlink():
        raise Version2UserDataArchiveError("Section-37 transaction identifier collision")
    stage.mkdir()
    _private_file(pending)

    try:
        if validated.kind == "portable":
            coordinator = Version2UpgradeCoordinator(layout, limits=limits)
            coordinator._ensure_roots()
            for source in coordinator._files():
                relative = _relative(layout.root, source)
                if _portable_secret_path(relative):
                    _copy_regular(
                        source,
                        stage / Path(*PurePosixPath(relative).parts),
                    )
        _extract_archive_to_stage(pending, validated, stage)
        _validate_staged_canonical_state(stage, validated)
        marker = stage / _CONTROL_MARKER
        marker.write_text(nonce + "\n", encoding="utf-8")
        _private_file(marker)
        _fsync_dir(stage)

        journal = {
            "schema_version": 1,
            "phase": "prepared",
            "old_name": old.name,
            "stage_name": stage.name,
            "published_dev": None,
            "published_ino": None,
        }
        _write_json_atomic(_journal_path(layout), journal)
        os.replace(layout.root, old)
        _fsync_dir(parent)
        journal["phase"] = "old_moved"
        _write_json_atomic(_journal_path(layout), journal)
        os.replace(stage, layout.root)
        _fsync_dir(parent)

        published_info = _exact_directory(layout.root, "imported user-data root")
        marker = layout.root / _CONTROL_MARKER
        try:
            marker_value = marker.read_text(encoding="utf-8")
        except OSError as exc:
            raise Version2UserDataArchiveError("import publication marker is unavailable") from exc
        if marker_value != nonce + "\n":
            raise Version2UserDataArchiveError("import publication marker mismatch")
        marker.unlink()
        _fsync_dir(layout.root)
        published_info = _exact_directory(layout.root, "imported user-data root")
        journal["phase"] = "published"
        journal["published_dev"], journal["published_ino"] = _path_identity(published_info)
        _write_json_atomic(_journal_path(layout), journal)
        return PendingUserDataTransaction(
            layout,
            old=old,
            published_identity=_path_identity(published_info),
        )
    except BaseException:
        # If publication already reached a journaled phase, the next startup has
        # enough external evidence to recover.  Before publication, clean only
        # the private stage we just created.
        if stage.exists() and not old.exists() and layout.root.exists():
            try:
                _safe_remove_tree(stage)
            except Exception:
                pass
        raise


class Version2UserDataHost:
    """Owner-thread handler bound to the canonical Version2Application data actions."""

    def __init__(
        self,
        layout: UserDataLayout,
        database: AcsDatabase,
        dialogs: object,
        *,
        language_provider: Callable[[], object],
    ) -> None:
        if not isinstance(layout, UserDataLayout):
            raise TypeError("layout must be UserDataLayout")
        if not isinstance(database, AcsDatabase):
            raise TypeError("database must be AcsDatabase")
        for name in ("save_user_data_archive", "open_user_data_archive"):
            if not callable(getattr(dialogs, name, None)):
                raise TypeError(f"user-data dialogs must expose {name}")
        if not callable(language_provider):
            raise TypeError("language_provider must be callable")
        self.layout = layout
        self.database = database
        self.dialogs = dialogs
        self.language_provider = language_provider

    def _uk(self) -> bool:
        value = self.language_provider()
        raw = getattr(value, "value", value)
        return str(raw).lower() in {"uk", "ua", "ukrainian"}

    def _announcement(self, en: str, uk: str) -> str:
        return uk if self._uk() else en

    def __call__(self, action: str, payload: dict[str, object]) -> dict[str, object]:
        if payload:
            raise ValueError("user-data actions accept no browser-supplied path or payload")
        service = Version2UserDataArchiveService(
            self.layout,
            live_database=self.database,
        )
        if action in {"data.backup", "data.export"}:
            kind = "backup" if action == "data.backup" else "portable"
            destination = self.dialogs.save_user_data_archive(kind)
            if destination is None:
                return {
                    "ok": False,
                    "cancelled": True,
                    "announcement": self._announcement(
                        "User-data operation cancelled.",
                        "Операцію з даними користувача скасовано.",
                    ),
                }
            try:
                receipt = service.create_archive(destination, kind=kind)
            except Exception as exc:
                raise Version2UserDataArchiveError(
                    "user-data export/backup failed without changing durable state"
                ) from exc
            return {
                "ok": True,
                "kind": receipt.kind,
                "file_count": receipt.file_count,
                "announcement": self._announcement(
                    "User-data archive saved.",
                    "Архів даних користувача збережено.",
                ),
            }

        if action in {"data.restore", "data.import"}:
            kind = "backup" if action == "data.restore" else "portable"
            source = self.dialogs.open_user_data_archive(kind)
            if source is None:
                return {
                    "ok": False,
                    "cancelled": True,
                    "announcement": self._announcement(
                        "User-data operation cancelled.",
                        "Операцію з даними користувача скасовано.",
                    ),
                }
            try:
                receipt = service.stage_import(source, expected_kind=kind)
            except Exception as exc:
                raise Version2UserDataArchiveError(
                    "user-data restore/import validation failed; current data was not changed"
                ) from exc
            return {
                "ok": True,
                "kind": receipt.kind,
                "restart_required": True,
                "announcement": self._announcement(
                    "User data validated. Restart Accessible Chess to apply it safely.",
                    "Дані перевірено. Перезапустіть Accessible Chess, щоб безпечно застосувати їх.",
                ),
            }
        raise ValueError("unsupported user-data action")


__all__ = [
    "ARCHIVE_SCHEMA_VERSION",
    "ArchiveEntry",
    "ArchiveReceipt",
    "PendingUserDataTransaction",
    "ValidatedArchive",
    "Version2UserDataArchiveError",
    "Version2UserDataArchiveService",
    "Version2UserDataHost",
    "begin_pending_user_data_transaction",
    "validate_user_data_archive",
]
