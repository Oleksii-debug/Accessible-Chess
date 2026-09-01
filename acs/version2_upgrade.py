from __future__ import annotations

"""Crash-recoverable Version 1 -> Version 2 user-data upgrade orchestration.

This module coordinates existing Settings and ACSDB migrations. It does not own
ACSDB schema changes and it does not build or publish a Windows candidate.
"""

from dataclasses import dataclass
from datetime import datetime, timezone
import errno
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import secrets
import shutil
import sqlite3
import stat
import tempfile
from typing import Callable, Mapping

from .acsdb import ACSDB_SCHEMA_VERSION, AcsDatabase
from .settings import SCHEMA_VERSION as SETTINGS_SCHEMA_VERSION, Settings


UPGRADE_JOURNAL_SCHEMA_VERSION = 2
_BACKUP_MANIFEST_SCHEMA_VERSION = 2
_PHASES = {"prepared", "migrating", "verifying", "committed", "rolled_back"}
_CONTROL_NAMES = {".v2-upgrade.lock", ".v2-upgrade-state.json"}
_DB_SIDECARS = ("-wal", "-shm", "-journal")
_WIN_BAD = set('<>:"/\\|?*')
_WIN_RESERVED = {
    "CON", "PRN", "AUX", "NUL",
    *(f"COM{i}" for i in range(1, 10)),
    *(f"LPT{i}" for i in range(1, 10)),
}


class Version2UpgradeError(RuntimeError):
    pass


class Version2UpgradeBusy(Version2UpgradeError):
    pass


class Version2UpgradeRecoveryError(Version2UpgradeError):
    pass


class _DuplicateJsonKeyError(ValueError):
    pass


def _unique_json_object(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise _DuplicateJsonKeyError(key)
        result[key] = value
    return result


@dataclass(frozen=True, slots=True)
class UpgradeLimits:
    max_files: int = 100_000
    max_bytes: int = 64 * 1024 * 1024 * 1024

    def __post_init__(self) -> None:
        if type(self.max_files) is not int or self.max_files < 1:
            raise ValueError("max_files must be a positive integer")
        if type(self.max_bytes) is not int or self.max_bytes < 1:
            raise ValueError("max_bytes must be a positive integer")


@dataclass(frozen=True, slots=True)
class UserDataLayout:
    root: Path
    settings_name: str = "settings.json"
    library_name: str = "library.acsdb"

    def __post_init__(self) -> None:
        object.__setattr__(self, "root", Path(self.root))
        _portable_component(self.settings_name, "settings filename")
        _portable_component(self.library_name, "library filename")

    @classmethod
    def from_environment(
        cls,
        *,
        environ: Mapping[str, str] | None = None,
        home: Path | None = None,
    ) -> "UserDataLayout":
        env = os.environ if environ is None else environ
        local = env.get("LOCALAPPDATA")
        root = (
            Path(local) / "AccessibleChess"
            if local
            else (Path.home() if home is None else Path(home)) / ".accessible-chess"
        )
        return cls(root)

    @property
    def settings_path(self) -> Path:
        return self.root / self.settings_name

    @property
    def library_path(self) -> Path:
        return self.root / self.library_name

    @property
    def lock_path(self) -> Path:
        return self.root / ".v2-upgrade.lock"

    @property
    def journal_path(self) -> Path:
        return self.root / ".v2-upgrade-state.json"

    @property
    def backup_root(self) -> Path:
        return self.root.parent / f"{self.root.name}.upgrade-backups"


@dataclass(frozen=True, slots=True)
class Version2UpgradeReport:
    upgrade_id: str
    status: str
    backup_name: str
    settings_migrated: bool
    library_migrated: bool
    preserved_files: int
    target_settings_schema: int
    target_acsdb_schema: int
    recovered_interrupted_upgrade: bool = False

    def as_dict(self) -> dict[str, object]:
        return {
            "upgrade_id": self.upgrade_id,
            "status": self.status,
            "backup_name": self.backup_name,
            "settings_migrated": self.settings_migrated,
            "library_migrated": self.library_migrated,
            "preserved_files": self.preserved_files,
            "target_settings_schema": self.target_settings_schema,
            "target_acsdb_schema": self.target_acsdb_schema,
            "recovered_interrupted_upgrade": self.recovered_interrupted_upgrade,
        }


def _portable_component(value: str, label: str) -> str:
    if not isinstance(value, str) or not value or value in {".", ".."}:
        raise ValueError(f"{label} must be non-empty portable text")
    if value[-1] in {" ", "."} or any(ord(c) < 32 or c in _WIN_BAD for c in value):
        raise ValueError(f"{label} is not Windows-portable")
    if value.split(".", 1)[0].upper() in _WIN_RESERVED:
        raise ValueError(f"{label} uses a reserved Windows name")
    return value


def _relative_token(value: str, label: str = "data path") -> str:
    if not isinstance(value, str) or not value or "\x00" in value:
        raise Version2UpgradeError(f"{label} must be non-empty text")
    normalized = value.replace("\\", "/")
    token = PurePosixPath(normalized)
    if (
        token.is_absolute()
        or normalized.startswith("/")
        or (
            len(normalized) >= 2
            and normalized[1] == ":"
            and normalized[0].isalpha()
        )
        or any(part in {"", ".", ".."} for part in token.parts)
    ):
        raise Version2UpgradeError(f"{label} is unsafe")
    try:
        for part in token.parts:
            _portable_component(part, label)
    except ValueError as exc:
        raise Version2UpgradeError(str(exc)) from exc
    if token.as_posix() != normalized:
        raise Version2UpgradeError(f"{label} is not canonical")
    return normalized


def _relative(root: Path, path: Path) -> str:
    try:
        return _relative_token(
            PurePosixPath(*path.relative_to(root).parts).as_posix()
        )
    except ValueError as exc:
        raise Version2UpgradeError("user-data entry escapes the canonical root") from exc


def _reparse(info: os.stat_result) -> bool:
    flag = getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400)
    return bool(getattr(info, "st_file_attributes", 0) & flag)


def _safe_stat(path: Path, label: str) -> os.stat_result:
    info = path.lstat()
    if stat.S_ISLNK(info.st_mode) or _reparse(info):
        raise Version2UpgradeError(f"{label} must not be a symlink or reparse point")
    return info


def _dir_chain(
    root: Path,
    directory: Path,
    *,
    create: bool = False,
) -> tuple[tuple[int, int], ...]:
    try:
        parts = directory.relative_to(root).parts
    except ValueError as exc:
        raise Version2UpgradeError("data directory escapes the canonical user root") from exc
    current = root
    identities: list[tuple[int, int]] = []
    for part in ("", *parts):
        if part:
            current /= part
        if not current.exists() and not current.is_symlink():
            if not create:
                raise Version2UpgradeError("user-data parent directory disappeared")
            current.mkdir()
        info = _safe_stat(current, "user-data parent directory")
        if not stat.S_ISDIR(info.st_mode):
            raise Version2UpgradeError("user-data parent must be a directory")
        identities.append((int(info.st_dev), int(info.st_ino)))
    return tuple(identities)


def _fsync_dir(path: Path) -> None:
    flags = os.O_RDONLY | getattr(os, "O_DIRECTORY", 0)
    try:
        fd = os.open(path, flags)
    except OSError as exc:
        if os.name == "nt" or exc.errno in {errno.EACCES, errno.EINVAL, errno.ENOTSUP}:
            return
        raise
    try:
        try:
            os.fsync(fd)
        except OSError as exc:
            if os.name != "nt" and exc.errno not in {errno.EINVAL, errno.ENOTSUP}:
                raise
    finally:
        os.close(fd)


def _atomic_bytes(path: Path, payload: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists() or path.is_symlink():
        info = _safe_stat(path, "atomic write target")
        if stat.S_ISDIR(info.st_mode):
            raise Version2UpgradeError("atomic write target must be a file")
    fd, raw = tempfile.mkstemp(
        prefix=f".{path.name}.", suffix=".tmp", dir=str(path.parent)
    )
    temp = Path(raw)
    try:
        with os.fdopen(fd, "wb") as handle:
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temp, path)
        _fsync_dir(path.parent)
    finally:
        if temp.exists():
            temp.unlink()


def _atomic_json(path: Path, value: Mapping[str, object]) -> None:
    _atomic_bytes(
        path,
        (
            json.dumps(dict(value), ensure_ascii=False, sort_keys=True, indent=2)
            + "\n"
        ).encode("utf-8"),
    )


def _hash(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _stable_copy(source: Path, destination: Path) -> tuple[int, str]:
    before = _safe_stat(source, "user-data source")
    if not stat.S_ISREG(before.st_mode):
        raise Version2UpgradeError("user-data source must be a regular file")
    before_id = (
        before.st_dev,
        before.st_ino,
        before.st_size,
        getattr(before, "st_mtime_ns", 0),
    )
    destination.parent.mkdir(parents=True, exist_ok=True)
    fd, raw = tempfile.mkstemp(
        prefix=f".{destination.name}.", suffix=".tmp", dir=str(destination.parent)
    )
    temp = Path(raw)
    digest = hashlib.sha256()
    source_fd = -1
    try:
        # Low-level os.open/os.read is subject to CRT text translation on
        # Windows unless O_BINARY is explicit. Upgrade backups and restores must
        # preserve arbitrary user bytes (including CRLF and 0x1A) exactly.
        flags = (
            os.O_RDONLY
            | getattr(os, "O_NOFOLLOW", 0)
            | getattr(os, "O_BINARY", 0)
        )
        source_fd = os.open(source, flags)
        opened = os.fstat(source_fd)
        opened_id = (
            opened.st_dev,
            opened.st_ino,
            opened.st_size,
            getattr(opened, "st_mtime_ns", 0),
        )
        if opened_id != before_id:
            raise Version2UpgradeError("user-data source changed before backup copy")
        with os.fdopen(fd, "wb") as target:
            fd = -1
            while True:
                block = os.read(source_fd, 1024 * 1024)
                if not block:
                    break
                target.write(block)
                digest.update(block)
            target.flush()
            os.fsync(target.fileno())
        after = _safe_stat(source, "user-data source")
        after_id = (
            after.st_dev,
            after.st_ino,
            after.st_size,
            getattr(after, "st_mtime_ns", 0),
        )
        if after_id != before_id:
            raise Version2UpgradeError("user-data source changed during backup copy")
        os.replace(temp, destination)
        _fsync_dir(destination.parent)
        return int(after.st_size), digest.hexdigest()
    finally:
        if source_fd >= 0:
            os.close(source_fd)
        if fd >= 0:
            os.close(fd)
        if temp.exists():
            temp.unlink()


def _canonical_library_schema(connection: sqlite3.Connection) -> int:
    """Delegate all ACSDB structural validation to the canonical D07 owner."""
    try:
        raw_row = connection.execute("PRAGMA user_version").fetchone()
        raw_version = raw_row[0] if raw_row is not None else None
        return AcsDatabase._check_sqlite_integrity(connection)
    except RuntimeError as exc:
        if type(raw_version) is int and raw_version > ACSDB_SCHEMA_VERSION:
            raise Version2UpgradeError(
                "library schema is newer than this Version 2 build"
            ) from exc
        if raw_version == 0:
            raise Version2UpgradeError(
                "unversioned legacy library requires an explicit D07 migration"
            ) from exc
        raise Version2UpgradeError("library validation failed") from exc
    except sqlite3.DatabaseError as exc:
        raise Version2UpgradeError("library validation failed") from exc


def _is_sha256(value: object) -> bool:
    return (
        isinstance(value, str)
        and len(value) == 64
        and all(c in "0123456789abcdef" for c in value)
    )


def _sqlite_state_sha256(connection: sqlite3.Connection) -> str:
    """Hash logical SQLite state without copying D07 schema knowledge."""
    digest = hashlib.sha256()
    row = connection.execute("PRAGMA user_version").fetchone()
    version = row[0] if row is not None else None
    marker = f"user_version={version!r}".encode("utf-8")
    digest.update(len(marker).to_bytes(8, "big"))
    digest.update(marker)
    for statement in connection.iterdump():
        raw = statement.encode("utf-8")
        digest.update(len(raw).to_bytes(8, "big"))
        digest.update(raw)
    return digest.hexdigest()


def _library_state_sha256(path: Path) -> str:
    connection = None
    try:
        connection = sqlite3.connect(
            path.resolve(strict=True).as_uri() + "?mode=ro",
            uri=True,
            timeout=0.0,
        )
        connection.execute("PRAGMA busy_timeout=0")
        _canonical_library_schema(connection)
        return _sqlite_state_sha256(connection)
    except Version2UpgradeError:
        raise
    except (OSError, sqlite3.DatabaseError) as exc:
        raise Version2UpgradeError("library state validation failed") from exc
    finally:
        if connection is not None:
            connection.close()


def _sqlite_backup(
    source: Path, destination: Path
) -> tuple[int, str, int, str]:
    info = _safe_stat(source, "library source")
    if not stat.S_ISREG(info.st_mode):
        raise Version2UpgradeError("library source must be a regular file")
    destination.parent.mkdir(parents=True, exist_ok=True)
    fd, raw = tempfile.mkstemp(
        prefix=f".{destination.name}.", suffix=".tmp", dir=str(destination.parent)
    )
    os.close(fd)
    temp = Path(raw)
    lock = reader = target = None
    try:
        try:
            # Separate connections avoid sqlite3.Connection.backup stalling on
            # a source connection that itself owns BEGIN IMMEDIATE.
            lock = sqlite3.connect(str(source), timeout=0.0)
            lock.execute("PRAGMA busy_timeout=0")
            lock.execute("BEGIN IMMEDIATE")
            reader = sqlite3.connect(
                source.resolve(strict=True).as_uri() + "?mode=ro",
                uri=True,
                timeout=0.0,
            )
            reader.execute("PRAGMA busy_timeout=0")
            version = _canonical_library_schema(reader)
            state_digest = _sqlite_state_sha256(reader)
            target = sqlite3.connect(str(temp))
            reader.backup(target)
            target.commit()
            if _canonical_library_schema(target) != version:
                raise Version2UpgradeError("library backup schema mismatch")
            if _sqlite_state_sha256(target) != state_digest:
                raise Version2UpgradeError("library backup logical-state mismatch")
        except sqlite3.DatabaseError as exc:
            raise Version2UpgradeError("library backup could not be validated") from exc
        finally:
            if target is not None:
                target.close()
            if reader is not None:
                reader.close()
            if lock is not None:
                if lock.in_transaction:
                    lock.rollback()
                lock.close()
        # Windows CRT rejects fsync() on a read-only descriptor. Open the
        # completed SQLite snapshot read/write so the durability flush works on
        # Windows as well as POSIX before the atomic replace.
        with temp.open("r+b") as handle:
            os.fsync(handle.fileno())
        os.replace(temp, destination)
        _fsync_dir(destination.parent)
        return (
            destination.stat().st_size,
            _hash(destination),
            version,
            state_digest,
        )
    finally:
        if temp.exists():
            temp.unlink()


class _UpgradeLock:
    def __init__(self, path: Path) -> None:
        self.path = path
        self.handle = None

    def __enter__(self) -> "_UpgradeLock":
        self.path.parent.mkdir(parents=True, exist_ok=True)
        if self.path.exists() or self.path.is_symlink():
            _safe_stat(self.path, "upgrade lock")
        self.handle = self.path.open("a+b")
        if self.handle.seek(0, os.SEEK_END) == 0:
            self.handle.write(b"\0")
            self.handle.flush()
        self.handle.seek(0)
        try:
            if os.name == "nt":
                import msvcrt
                msvcrt.locking(self.handle.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl
                fcntl.flock(self.handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except (OSError, BlockingIOError) as exc:
            self.handle.close()
            self.handle = None
            raise Version2UpgradeBusy("another Version 2 upgrade is active") from exc
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        if self.handle is None:
            return
        try:
            self.handle.seek(0)
            if os.name == "nt":
                import msvcrt
                msvcrt.locking(self.handle.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                import fcntl
                fcntl.flock(self.handle.fileno(), fcntl.LOCK_UN)
        finally:
            self.handle.close()
            self.handle = None


class Version2UpgradeCoordinator:
    """Run before Version 2 opens normal settings/library services."""

    def __init__(
        self,
        layout: UserDataLayout | None = None,
        *,
        database_factory: Callable[[str | Path], object] = AcsDatabase,
        settings_factory: Callable[[str | Path], Settings] = Settings,
        limits: UpgradeLimits = UpgradeLimits(),
        phase_hook: Callable[[str], None] | None = None,
    ) -> None:
        self.layout = UserDataLayout.from_environment() if layout is None else layout
        if not isinstance(self.layout, UserDataLayout):
            raise TypeError("layout must be UserDataLayout")
        if not callable(database_factory) or not callable(settings_factory):
            raise TypeError("upgrade factories must be callable")
        if not isinstance(limits, UpgradeLimits):
            raise TypeError("limits must be UpgradeLimits")
        if phase_hook is not None and not callable(phase_hook):
            raise TypeError("phase_hook must be callable")
        self.database_factory = database_factory
        self.settings_factory = settings_factory
        self.limits = limits
        self.phase_hook = phase_hook
        self._owned_states: dict[str, str] = {}
        self._last_backup: Path | None = None
        self._last_manifest: dict[str, object] | None = None

    def _notify(self, phase: str) -> None:
        if self.phase_hook is not None:
            self.phase_hook(phase)

    def _ensure_roots(self) -> None:
        for path, label in (
            (self.layout.root, "user-data root"),
            (self.layout.backup_root, "upgrade backup root"),
        ):
            if path.exists() or path.is_symlink():
                info = _safe_stat(path, label)
                if not stat.S_ISDIR(info.st_mode):
                    raise Version2UpgradeError(f"{label} must be a directory")
            else:
                path.mkdir(parents=True, exist_ok=True)

    def _files(self) -> tuple[Path, ...]:
        files: list[Path] = []
        seen: set[str] = set()
        total = 0
        for path in sorted(
            self.layout.root.rglob("*"),
            key=lambda p: PurePosixPath(*p.relative_to(self.layout.root).parts)
            .as_posix()
            .casefold(),
        ):
            relative = _relative(self.layout.root, path)
            if PurePosixPath(relative).parts[0] in _CONTROL_NAMES:
                continue
            folded = relative.casefold()
            if folded in seen:
                raise Version2UpgradeError(
                    "user-data paths collide on Windows case-folding"
                )
            seen.add(folded)
            info = _safe_stat(path, "user-data entry")
            if stat.S_ISDIR(info.st_mode):
                continue
            if not stat.S_ISREG(info.st_mode):
                raise Version2UpgradeError(
                    "user-data root contains a non-regular entry"
                )
            if relative in {
                self.layout.library_name + suffix for suffix in _DB_SIDECARS
            }:
                continue
            files.append(path)
            total += int(info.st_size)
            if len(files) > self.limits.max_files:
                raise Version2UpgradeError(
                    "user-data backup exceeds file-count limit"
                )
            if total > self.limits.max_bytes:
                raise Version2UpgradeError("user-data backup exceeds byte limit")
        return tuple(files)

    def _create_backup(self, upgrade_id: str) -> tuple[Path, dict[str, object]]:
        final = self.layout.backup_root / upgrade_id
        temp = self.layout.backup_root / f".{upgrade_id}.tmp-{secrets.token_hex(4)}"
        if final.exists() or final.is_symlink():
            raise Version2UpgradeError("upgrade backup identifier collision")
        temp.mkdir()
        data = temp / "data"
        data.mkdir()
        entries: list[dict[str, object]] = []
        library_schema = None
        try:
            for source in self._files():
                relative = _relative(self.layout.root, source)
                destination = data.joinpath(*PurePosixPath(relative).parts)
                chain = _dir_chain(self.layout.root, source.parent)
                state_digest = None
                if relative == self.layout.library_name:
                    size, digest, library_schema, state_digest = _sqlite_backup(
                        source, destination
                    )
                else:
                    size, digest = _stable_copy(source, destination)
                    if relative == self.layout.settings_name:
                        state_digest = digest
                if _dir_chain(self.layout.root, source.parent) != chain:
                    raise Version2UpgradeError(
                        "user-data parent directory changed during backup copy"
                    )
                entry: dict[str, object] = {
                    "path": relative,
                    "size": size,
                    "sha256": digest,
                }
                if state_digest is not None:
                    entry["state_sha256"] = state_digest
                entries.append(entry)
            manifest = {
                "schema_version": _BACKUP_MANIFEST_SCHEMA_VERSION,
                "upgrade_id": upgrade_id,
                "created_at": datetime.now(timezone.utc).isoformat(
                    timespec="seconds"
                ),
                "settings_name": self.layout.settings_name,
                "library_name": self.layout.library_name,
                "library_schema_before": library_schema,
                "entries": entries,
            }
            _atomic_json(temp / "manifest.json", manifest)
            os.replace(temp, final)
            _fsync_dir(self.layout.backup_root)
            self._last_backup = final
            self._last_manifest = manifest
            return final, manifest
        finally:
            if temp.exists():
                shutil.rmtree(temp, ignore_errors=True)

    def _write_phase(
        self,
        upgrade_id: str,
        phase: str,
        *,
        recovered: bool,
        error_code: str | None = None,
        notify: bool = True,
    ) -> None:
        if phase not in _PHASES:
            raise ValueError("invalid upgrade phase")
        payload: dict[str, object] = {
            "schema_version": UPGRADE_JOURNAL_SCHEMA_VERSION,
            "upgrade_id": upgrade_id,
            "backup_name": upgrade_id,
            "phase": phase,
            "target_settings_schema": SETTINGS_SCHEMA_VERSION,
            "target_acsdb_schema": ACSDB_SCHEMA_VERSION,
            "recovered_interrupted_upgrade": recovered,
            "owned_states": dict(self._owned_states),
            "updated_at": datetime.now(timezone.utc).isoformat(
                timespec="seconds"
            ),
        }
        if error_code is not None:
            payload["error_code"] = error_code
        _atomic_json(self.layout.journal_path, payload)
        if notify:
            self._notify(phase)

    def _read_json(self, path: Path, label: str) -> dict[str, object]:
        try:
            info = _safe_stat(path, label)
            if not stat.S_ISREG(info.st_mode):
                raise Version2UpgradeRecoveryError(f"{label} must be a file")
            value = json.loads(
                path.read_text(encoding="utf-8"),
                object_pairs_hook=_unique_json_object,
            )
        except _DuplicateJsonKeyError as exc:
            raise Version2UpgradeRecoveryError(
                f"{label} contains duplicate JSON keys"
            ) from exc
        except (OSError, UnicodeError, json.JSONDecodeError) as exc:
            raise Version2UpgradeRecoveryError(f"{label} is unreadable") from exc
        if not isinstance(value, dict):
            raise Version2UpgradeRecoveryError(f"{label} must be an object")
        return value

    def _journal(self) -> dict[str, object]:
        raw = self._read_json(self.layout.journal_path, "upgrade journal")
        schema_version = raw.get("schema_version")
        phase = raw.get("phase")
        if (
            type(schema_version) is not int
            or schema_version != UPGRADE_JOURNAL_SCHEMA_VERSION
            or not isinstance(phase, str)
            or phase not in _PHASES
        ):
            raise Version2UpgradeRecoveryError("invalid upgrade journal")
        upgrade_id = raw.get("upgrade_id")
        backup_name = raw.get("backup_name")
        if (
            not isinstance(upgrade_id, str)
            or not isinstance(backup_name, str)
            or backup_name != upgrade_id
        ):
            raise Version2UpgradeRecoveryError("upgrade journal identity mismatch")
        if (
            type(raw.get("target_settings_schema")) is not int
            or raw.get("target_settings_schema") != SETTINGS_SCHEMA_VERSION
            or type(raw.get("target_acsdb_schema")) is not int
            or raw.get("target_acsdb_schema") != ACSDB_SCHEMA_VERSION
        ):
            raise Version2UpgradeRecoveryError(
                "upgrade journal target schema mismatch"
            )
        if type(raw.get("recovered_interrupted_upgrade")) is not bool:
            raise Version2UpgradeRecoveryError("invalid upgrade journal metadata")
        updated_at = raw.get("updated_at")
        if not isinstance(updated_at, str) or not updated_at:
            raise Version2UpgradeRecoveryError("invalid upgrade journal metadata")
        if "error_code" in raw and (
            not isinstance(raw["error_code"], str) or not raw["error_code"]
        ):
            raise Version2UpgradeRecoveryError("invalid upgrade journal metadata")
        owned_states = raw.get("owned_states")
        if not isinstance(owned_states, dict):
            raise Version2UpgradeRecoveryError(
                "invalid upgrade journal ownership metadata"
            )
        allowed_owned = {self.layout.settings_name, self.layout.library_name}
        if any(
            not isinstance(name, str)
            or name not in allowed_owned
            or not _is_sha256(digest)
            for name, digest in owned_states.items()
        ):
            raise Version2UpgradeRecoveryError(
                "invalid upgrade journal ownership metadata"
            )
        try:
            _portable_component(upgrade_id, "upgrade identifier")
        except ValueError as exc:
            raise Version2UpgradeRecoveryError(str(exc)) from exc
        return raw

    def _manifest(self, upgrade_id: str) -> tuple[Path, dict[str, object]]:
        backup = self.layout.backup_root / upgrade_id
        try:
            info = _safe_stat(backup, "upgrade backup directory")
        except (OSError, Version2UpgradeError) as exc:
            raise Version2UpgradeRecoveryError(
                "upgrade backup directory is missing"
            ) from exc
        if not stat.S_ISDIR(info.st_mode):
            raise Version2UpgradeRecoveryError(
                "upgrade backup directory is missing"
            )
        raw = self._read_json(backup / "manifest.json", "upgrade backup manifest")
        schema_version = raw.get("schema_version")
        entries = raw.get("entries")
        library_schema = raw.get("library_schema_before")
        if (
            type(schema_version) is not int
            or schema_version != _BACKUP_MANIFEST_SCHEMA_VERSION
            or not isinstance(raw.get("upgrade_id"), str)
            or raw.get("upgrade_id") != upgrade_id
            or not isinstance(raw.get("settings_name"), str)
            or raw.get("settings_name") != self.layout.settings_name
            or not isinstance(raw.get("library_name"), str)
            or raw.get("library_name") != self.layout.library_name
            or not isinstance(raw.get("created_at"), str)
            or not raw.get("created_at")
            or not isinstance(entries, list)
            or not (
                library_schema is None
                or (type(library_schema) is int and library_schema >= 0)
            )
        ):
            raise Version2UpgradeRecoveryError(
                "upgrade backup manifest identity or schema metadata is invalid"
            )
        seen: set[str] = set()
        total = 0
        library_entry_seen = False
        for item in entries:
            if not isinstance(item, dict):
                raise Version2UpgradeRecoveryError(
                    "upgrade backup entry is invalid"
                )
            raw_path = item.get("path")
            if not isinstance(raw_path, str):
                raise Version2UpgradeRecoveryError(
                    "upgrade backup entry metadata is invalid"
                )
            try:
                path = _relative_token(raw_path, "upgrade backup path")
            except Version2UpgradeError as exc:
                raise Version2UpgradeRecoveryError(
                    "upgrade backup entry metadata is invalid"
                ) from exc
            size, digest = item.get("size"), item.get("sha256")
            if (
                path.casefold() in seen
                or type(size) is not int
                or size < 0
                or not isinstance(digest, str)
                or len(digest) != 64
                or any(c not in "0123456789abcdef" for c in digest)
            ):
                raise Version2UpgradeRecoveryError(
                    "upgrade backup entry metadata is invalid"
                )
            if path.casefold() in {
                self.layout.settings_name.casefold(),
                self.layout.library_name.casefold(),
            } and not _is_sha256(item.get("state_sha256")):
                raise Version2UpgradeRecoveryError(
                    "upgrade backup tracked-state metadata is invalid"
                )
            seen.add(path.casefold())
            library_entry_seen = library_entry_seen or (
                path.casefold() == self.layout.library_name.casefold()
            )
            total += size
            if len(seen) > self.limits.max_files or total > self.limits.max_bytes:
                raise Version2UpgradeRecoveryError(
                    "upgrade backup exceeds recovery limits"
                )
            candidate = backup / "data" / Path(*PurePosixPath(path).parts)
            try:
                candidate_info = _safe_stat(candidate, "upgrade backup file")
            except (OSError, Version2UpgradeError) as exc:
                raise Version2UpgradeRecoveryError(
                    "upgrade backup checksum mismatch"
                ) from exc
            if (
                not stat.S_ISREG(candidate_info.st_mode)
                or candidate_info.st_size != size
                or _hash(candidate) != digest
            ):
                raise Version2UpgradeRecoveryError(
                    "upgrade backup checksum mismatch"
                )
        if library_entry_seen != (library_schema is not None):
            raise Version2UpgradeRecoveryError(
                "upgrade backup manifest library schema metadata is inconsistent"
            )
        return backup, raw

    def _manifest_tracked_entry(
        self, manifest: Mapping[str, object], name: str
    ) -> dict[str, object] | None:
        entries = manifest.get("entries")
        if not isinstance(entries, list):
            raise Version2UpgradeRecoveryError(
                "backup manifest entries are unavailable"
            )
        folded = name.casefold()
        for item in entries:
            if (
                isinstance(item, dict)
                and str(item.get("path", "")).casefold() == folded
            ):
                return item
        return None

    def _tracked_state_sha256(self, name: str) -> str | None:
        if name not in {self.layout.settings_name, self.layout.library_name}:
            raise ValueError("unknown tracked upgrade path")
        path = self.layout.root / name
        if not path.exists() and not path.is_symlink():
            return None
        info = _safe_stat(path, "tracked user data")
        if not stat.S_ISREG(info.st_mode):
            raise Version2UpgradeError("tracked user data must be a file")
        if name == self.layout.library_name:
            return _library_state_sha256(path)
        return _hash(path)

    def _assert_tracked_original(
        self, manifest: Mapping[str, object], name: str
    ) -> None:
        entry = self._manifest_tracked_entry(manifest, name)
        current = self._tracked_state_sha256(name)
        if entry is None:
            if current is not None:
                raise Version2UpgradeError(
                    "tracked user data changed after the upgrade snapshot"
                )
            return
        original = entry.get("state_sha256")
        if not _is_sha256(original) or current != original:
            raise Version2UpgradeError(
                "tracked user data changed after the upgrade snapshot"
            )

    def _plan_owned_state(
        self,
        upgrade_id: str,
        phase: str,
        name: str,
        state_digest: str,
        *,
        recovered: bool,
    ) -> None:
        if not _is_sha256(state_digest):
            raise Version2UpgradeError("invalid upgrader-owned state digest")
        self._owned_states[name] = state_digest
        # Persist the exact state the upgrader is authorized to publish before
        # publication. Recovery can then distinguish original, our publication,
        # and any later external V1 write without guessing.
        self._write_phase(
            upgrade_id,
            phase,
            recovered=recovered,
            notify=False,
        )

    def _clear_library_sidecars(self) -> None:
        for suffix in _DB_SIDECARS:
            sidecar = Path(str(self.layout.library_path) + suffix)
            if not sidecar.exists() and not sidecar.is_symlink():
                continue
            info = _safe_stat(sidecar, "library sidecar")
            if not stat.S_ISREG(info.st_mode):
                raise Version2UpgradeRecoveryError(
                    "library sidecar is not a regular file"
                )
            sidecar.unlink()

    def _prepare_library_publication(self, expected_original: str) -> None:
        """Normalize a quiescent live SQLite file before atomic publication.

        The logical state must still equal the pre-upgrade snapshot. A zero-timeout
        checkpoint/IMMEDIATE probe converts ordinary closed WAL state into a
        self-contained main database while failing closed on an active writer.
        """
        if not _is_sha256(expected_original):
            raise Version2UpgradeError(
                "library backup tracked-state metadata is invalid"
            )
        connection = None
        try:
            connection = sqlite3.connect(
                str(self.layout.library_path), timeout=0.0
            )
            connection.execute("PRAGMA busy_timeout=0")
            _canonical_library_schema(connection)
            if _sqlite_state_sha256(connection) != expected_original:
                raise Version2UpgradeError(
                    "tracked user data changed after the upgrade snapshot"
                )
            mode_row = connection.execute("PRAGMA journal_mode").fetchone()
            mode = str(mode_row[0]).casefold() if mode_row else ""
            if mode == "wal":
                checkpoint = connection.execute(
                    "PRAGMA wal_checkpoint(TRUNCATE)"
                ).fetchone()
                if checkpoint and int(checkpoint[0]) != 0:
                    raise Version2UpgradeBusy(
                        "library is busy during upgrade publication"
                    )
            connection.execute("BEGIN IMMEDIATE")
            if _sqlite_state_sha256(connection) != expected_original:
                connection.rollback()
                raise Version2UpgradeError(
                    "tracked user data changed after the upgrade snapshot"
                )
            connection.rollback()
        except Version2UpgradeError:
            raise
        except sqlite3.OperationalError as exc:
            raise Version2UpgradeBusy(
                "library is busy during upgrade publication"
            ) from exc
        except sqlite3.DatabaseError as exc:
            raise Version2UpgradeError(
                "library publication validation failed"
            ) from exc
        finally:
            if connection is not None:
                connection.close()

        if _library_state_sha256(self.layout.library_path) != expected_original:
            raise Version2UpgradeError(
                "tracked user data changed after the upgrade snapshot"
            )
        # No writer held the SQLite write lock and WAL has been checkpointed.
        # Remove now-stale sidecars before replacing the main file so they cannot
        # be replayed against the migrated publication.
        self._clear_library_sidecars()

    def _restore(self, upgrade_id: str) -> int:
        backup, manifest = self._manifest(upgrade_id)
        journal = self._journal()
        if journal.get("upgrade_id") != upgrade_id:
            raise Version2UpgradeRecoveryError(
                "upgrade recovery identity mismatch"
            )
        owned_raw = journal.get("owned_states")
        assert isinstance(owned_raw, dict)
        owned_states = {str(k): str(v) for k, v in owned_raw.items()}

        actions: dict[str, str] = {}
        # Authorize every destructive action before changing either tracked path.
        for name in (self.layout.settings_name, self.layout.library_name):
            entry = self._manifest_tracked_entry(manifest, name)
            try:
                current = self._tracked_state_sha256(name)
            except Exception as exc:
                raise Version2UpgradeRecoveryError(
                    "tracked recovery state cannot be authenticated"
                ) from exc
            owned = owned_states.get(name)
            if entry is None:
                if current is None:
                    actions[name] = "noop"
                elif owned is not None and current == owned:
                    actions[name] = "delete"
                else:
                    raise Version2UpgradeRecoveryError(
                        "tracked user data changed outside this upgrade"
                    )
                continue
            original = entry.get("state_sha256")
            if not _is_sha256(original):
                raise Version2UpgradeRecoveryError(
                    "upgrade backup tracked-state metadata is invalid"
                )
            if current == original or (owned is not None and current == owned):
                # Re-copy even an unchanged original so rollback readback remains
                # an explicit, testable durability operation.
                actions[name] = "restore"
            else:
                raise Version2UpgradeRecoveryError(
                    "tracked user data changed outside this upgrade"
                )

        restored = 0
        for name in (self.layout.settings_name, self.layout.library_name):
            action = actions[name]
            entry = self._manifest_tracked_entry(manifest, name)
            destination = self.layout.root / name
            if action == "noop":
                continue
            if name == self.layout.library_name:
                self._clear_library_sidecars()
            if action == "delete":
                if destination.exists() or destination.is_symlink():
                    info = _safe_stat(
                        destination, "upgrade-created tracked data"
                    )
                    if not stat.S_ISREG(info.st_mode):
                        raise Version2UpgradeRecoveryError(
                            "upgrade-created tracked data is not a file"
                        )
                    destination.unlink()
                continue
            assert entry is not None
            relative = str(entry["path"])
            source = backup / "data" / Path(*PurePosixPath(relative).parts)
            chain = _dir_chain(
                self.layout.root, destination.parent, create=True
            )
            size, digest = _stable_copy(source, destination)
            if _dir_chain(self.layout.root, destination.parent) != chain:
                raise Version2UpgradeRecoveryError(
                    "user-data parent directory changed during recovery"
                )
            if size != entry["size"] or digest != entry["sha256"]:
                raise Version2UpgradeRecoveryError(
                    "upgrade backup changed during recovery"
                )
            try:
                if self._tracked_state_sha256(name) != entry.get(
                    "state_sha256"
                ):
                    raise Version2UpgradeRecoveryError(
                        "tracked recovery readback mismatch"
                    )
            except Version2UpgradeRecoveryError:
                raise
            except Exception as exc:
                raise Version2UpgradeRecoveryError(
                    "tracked recovery readback validation failed"
                ) from exc
            restored += 1

        _fsync_dir(self.layout.root)
        try:
            settings_entry = self._manifest_tracked_entry(
                manifest, self.layout.settings_name
            )
            if settings_entry is not None:
                candidate = self.settings_factory(
                    self.layout.root / ".settings.recovery-readback"
                )
                candidate.import_json(
                    self.layout.settings_path.read_text(encoding="utf-8"),
                    persist=False,
                )
            library_entry = self._manifest_tracked_entry(
                manifest, self.layout.library_name
            )
            if library_entry is not None:
                connection = sqlite3.connect(
                    self.layout.library_path.resolve(strict=True).as_uri()
                    + "?mode=ro",
                    uri=True,
                    timeout=0.0,
                )
                try:
                    connection.execute("PRAGMA busy_timeout=0")
                    restored_schema = _canonical_library_schema(connection)
                finally:
                    connection.close()
                if restored_schema != manifest.get("library_schema_before"):
                    raise Version2UpgradeRecoveryError(
                        "tracked library recovery readback schema mismatch"
                    )
        except Version2UpgradeRecoveryError:
            raise
        except Exception as exc:
            raise Version2UpgradeRecoveryError(
                "tracked recovery readback validation failed"
            ) from exc
        return restored

    def _recover_locked(self) -> bool:
        if (
            not self.layout.journal_path.exists()
            and not self.layout.journal_path.is_symlink()
        ):
            return False
        journal = self._journal()
        if journal["phase"] in {"committed", "rolled_back"}:
            return False
        upgrade_id = str(journal["upgrade_id"])
        owned = journal.get("owned_states")
        assert isinstance(owned, dict)
        self._owned_states = {str(k): str(v) for k, v in owned.items()}
        self._restore(upgrade_id)
        self._write_phase(
            upgrade_id,
            "rolled_back",
            recovered=True,
            error_code="INTERRUPTED_UPGRADE_RECOVERED",
        )
        return True

    def recover_interrupted(self) -> bool:
        self._ensure_roots()
        with _UpgradeLock(self.layout.lock_path):
            return self._recover_locked()

    def _settings_need(self) -> bool:
        path = self.layout.settings_path
        if not path.exists() and not path.is_symlink():
            return False
        info = _safe_stat(path, "settings file")
        if not stat.S_ISREG(info.st_mode):
            raise Version2UpgradeError("settings path must be a file")
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
            if not isinstance(raw, dict):
                raise ValueError
            candidate = self.settings_factory(
                path.parent / f".{path.name}.upgrade-check"
            )
            warnings = candidate.import_json(json.dumps(raw), persist=False)
        except Exception as exc:
            raise Version2UpgradeError("settings validation failed") from exc
        schema = raw.get("schema_version")
        if schema is None:
            return True
        if isinstance(schema, bool) or not isinstance(schema, int):
            raise Version2UpgradeError("settings schema version is invalid")
        if schema > SETTINGS_SCHEMA_VERSION:
            raise Version2UpgradeError(
                "settings schema is newer than this Version 2 build"
            )
        return schema < SETTINGS_SCHEMA_VERSION or bool(warnings)

    def _library_schema(self) -> int | None:
        path = self.layout.library_path
        if not path.exists() and not path.is_symlink():
            return None
        info = _safe_stat(path, "library file")
        if not stat.S_ISREG(info.st_mode):
            raise Version2UpgradeError("library path must be a file")
        connection = None
        try:
            connection = sqlite3.connect(
                path.resolve(strict=True).as_uri() + "?mode=ro",
                uri=True,
                timeout=0.0,
            )
            connection.execute("PRAGMA busy_timeout=0")
            return _canonical_library_schema(connection)
        except Version2UpgradeError:
            raise
        except sqlite3.DatabaseError as exc:
            raise Version2UpgradeError("library validation failed") from exc
        finally:
            if connection is not None:
                connection.close()

    def _needs_upgrade(self) -> bool:
        settings_need = self._settings_need()
        schema = self._library_schema()
        if schema is not None and schema > ACSDB_SCHEMA_VERSION:
            raise Version2UpgradeError(
                "library schema is newer than this Version 2 build"
            )
        return settings_need or (
            schema is not None and schema < ACSDB_SCHEMA_VERSION
        )

    def _migrate_settings(
        self,
        manifest: Mapping[str, object] | None = None,
        upgrade_id: str | None = None,
        *,
        recovered: bool = False,
    ) -> bool:
        if not self._settings_need():
            return False
        path = self.layout.settings_path
        try:
            candidate = self.settings_factory(
                path.parent / f".{path.name}.upgrade-validate"
            )
            candidate.import_json(
                path.read_text(encoding="utf-8"), persist=False
            )
            payload = (candidate.export_json() + "\n").encode("utf-8")
        except Exception as exc:
            raise Version2UpgradeError(
                "settings migration validation failed"
            ) from exc
        if manifest is None:
            manifest = self._last_manifest
        if manifest is not None:
            self._assert_tracked_original(
                manifest, self.layout.settings_name
            )
        expected = hashlib.sha256(payload).hexdigest()
        if upgrade_id is not None:
            if manifest is None:
                raise ValueError(
                    "upgrade manifest is required with an upgrade identifier"
                )
            self._plan_owned_state(
                upgrade_id,
                "migrating",
                self.layout.settings_name,
                expected,
                recovered=recovered,
            )
            self._assert_tracked_original(
                manifest, self.layout.settings_name
            )
        _atomic_bytes(path, payload)
        if _hash(path) != expected:
            raise Version2UpgradeError(
                "settings migration publication verification failed"
            )
        return True

    def _migrate_library(
        self,
        backup: Path | None = None,
        manifest: Mapping[str, object] | None = None,
        upgrade_id: str | None = None,
        *,
        recovered: bool = False,
    ) -> bool:
        before = self._library_schema()
        if before is None or before == ACSDB_SCHEMA_VERSION:
            return False
        if before > ACSDB_SCHEMA_VERSION:
            raise Version2UpgradeError(
                "library schema is newer than this Version 2 build"
            )
        if backup is None:
            backup = self._last_backup
        if manifest is None:
            manifest = self._last_manifest
        if backup is None or manifest is None:
            raise ValueError(
                "a pre-migration backup is required for library migration"
            )
        entry = self._manifest_tracked_entry(
            manifest, self.layout.library_name
        )
        if entry is None:
            raise Version2UpgradeError(
                "library backup entry is unavailable for migration"
            )
        original_state = entry.get("state_sha256")
        if not _is_sha256(original_state):
            raise Version2UpgradeError(
                "library backup tracked-state metadata is invalid"
            )

        work = self.layout.backup_root / (
            f".{upgrade_id}.library-work-{secrets.token_hex(4)}.acsdb"
        )
        publish = self.layout.backup_root / (
            f".{upgrade_id}.library-publish-{secrets.token_hex(4)}.acsdb"
        )
        source = backup / "data" / self.layout.library_name
        database = None
        try:
            size, digest = _stable_copy(source, work)
            if size != entry["size"] or digest != entry["sha256"]:
                raise Version2UpgradeError(
                    "library migration source backup changed"
                )
            database = self.database_factory(work)
            schema = getattr(database, "schema_version", None)
            if schema is not None and schema != ACSDB_SCHEMA_VERSION:
                raise Version2UpgradeError(
                    "library migration did not reach the target schema"
                )
            close = getattr(database, "close", None)
            if callable(close):
                close()
            database = None

            _, _, publish_schema, publish_state = _sqlite_backup(work, publish)
            if publish_schema != ACSDB_SCHEMA_VERSION:
                raise Version2UpgradeError(
                    "library migration did not reach the target schema"
                )

            self._assert_tracked_original(
                manifest, self.layout.library_name
            )
            self._prepare_library_publication(str(original_state))
            if upgrade_id is not None:
                self._plan_owned_state(
                    upgrade_id,
                    "migrating",
                    self.layout.library_name,
                    publish_state,
                    recovered=recovered,
                )
            # Close the compare/publication window as much as the filesystem
            # permits: re-authenticate immediately before atomic replacement.
            self._assert_tracked_original(
                manifest, self.layout.library_name
            )
            self._prepare_library_publication(str(original_state))
            os.replace(publish, self.layout.library_path)
            _fsync_dir(self.layout.root)
            if (
                self._library_schema() != ACSDB_SCHEMA_VERSION
                or self._tracked_state_sha256(self.layout.library_name)
                != publish_state
            ):
                raise Version2UpgradeError(
                    "library migration publication verification failed"
                )
            return True
        finally:
            if database is not None:
                close = getattr(database, "close", None)
                if callable(close):
                    close()
            for candidate in (work, publish):
                for path in (
                    candidate,
                    *(Path(str(candidate) + suffix) for suffix in _DB_SIDECARS),
                ):
                    if path.exists() or path.is_symlink():
                        try:
                            info = _safe_stat(path, "library migration temporary")
                            if stat.S_ISREG(info.st_mode):
                                path.unlink()
                        except Exception:
                            pass

    def _verify(self, backup: Path, manifest: Mapping[str, object]) -> int:
        if self.layout.settings_path.exists():
            try:
                raw = json.loads(
                    self.layout.settings_path.read_text(encoding="utf-8")
                )
                if (
                    not isinstance(raw, dict)
                    or raw.get("schema_version") != SETTINGS_SCHEMA_VERSION
                ):
                    raise ValueError
                candidate = self.settings_factory(
                    self.layout.root / ".settings.upgrade-readback"
                )
                candidate.import_json(json.dumps(raw), persist=False)
            except Exception as exc:
                raise Version2UpgradeError(
                    "migrated settings readback validation failed"
                ) from exc
        schema = self._library_schema()
        if schema is not None and schema != ACSDB_SCHEMA_VERSION:
            raise Version2UpgradeError(
                "library readback schema verification failed"
            )
        preserved = 0
        entries = manifest.get("entries")
        if not isinstance(entries, list):
            raise Version2UpgradeError("backup manifest entries are unavailable")
        for item in entries:
            assert isinstance(item, dict)
            relative = str(item["path"])
            if relative in {self.layout.settings_name, self.layout.library_name}:
                continue
            current = self.layout.root / Path(*PurePosixPath(relative).parts)
            info = _safe_stat(current, "preserved user-data file")
            if (
                not stat.S_ISREG(info.st_mode)
                or info.st_size != item["size"]
                or _hash(current) != item["sha256"]
            ):
                raise Version2UpgradeError(
                    "preserved user-data file changed during upgrade"
                )
            preserved += 1
        return preserved

    def _already_current(
        self, recovered: bool
    ) -> Version2UpgradeReport:
        upgrade_id, backup_name = "current", ""
        if (
            self.layout.journal_path.exists()
            or self.layout.journal_path.is_symlink()
        ):
            journal = self._journal()
            if journal["phase"] == "committed":
                upgrade_id = str(journal["upgrade_id"])
                backup_name = str(journal["backup_name"])
        preserved = sum(
            1
            for path in self._files()
            if _relative(self.layout.root, path)
            not in {self.layout.settings_name, self.layout.library_name}
        )
        return Version2UpgradeReport(
            upgrade_id,
            "already_current",
            backup_name,
            False,
            False,
            preserved,
            SETTINGS_SCHEMA_VERSION,
            ACSDB_SCHEMA_VERSION,
            recovered,
        )

    def run(self) -> Version2UpgradeReport:
        self._ensure_roots()
        with _UpgradeLock(self.layout.lock_path):
            recovered = self._recover_locked()
            if not self._needs_upgrade():
                return self._already_current(recovered)
            upgrade_id = (
                datetime.now(timezone.utc).strftime("v2-%Y%m%dT%H%M%SZ-")
                + secrets.token_hex(4)
            )
            backup, manifest = self._create_backup(upgrade_id)
            self._owned_states = {}
            self._write_phase(
                upgrade_id, "prepared", recovered=recovered
            )
            try:
                self._write_phase(
                    upgrade_id, "migrating", recovered=recovered
                )
                settings_migrated = self._migrate_settings(
                    manifest, upgrade_id, recovered=recovered
                )
                self._notify("settings-migrated")
                library_migrated = self._migrate_library(
                    backup, manifest, upgrade_id, recovered=recovered
                )
                self._notify("library-migrated")
                self._write_phase(
                    upgrade_id, "verifying", recovered=recovered
                )
                preserved = self._verify(backup, manifest)
                self._write_phase(
                    upgrade_id, "committed", recovered=recovered
                )
            except Exception as exc:
                try:
                    self._restore(upgrade_id)
                    self._write_phase(
                        upgrade_id,
                        "rolled_back",
                        recovered=recovered,
                        error_code=type(exc).__name__,
                    )
                except Exception as recovery_exc:
                    raise Version2UpgradeRecoveryError(
                        "Version 2 upgrade failed and automatic recovery also failed"
                    ) from recovery_exc
                raise Version2UpgradeError(
                    "Version 2 upgrade failed; original user data was restored"
                ) from exc
            return Version2UpgradeReport(
                upgrade_id,
                "upgraded",
                upgrade_id,
                settings_migrated,
                library_migrated,
                preserved,
                SETTINGS_SCHEMA_VERSION,
                ACSDB_SCHEMA_VERSION,
                recovered,
            )