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
_CONTROL_NAMES = {
    ".v2-upgrade.lock",
    ".v2-upgrade-state.json",
    "profile.json.lock",
    "gametree-resume.json.lock",
    "book-progress.json.lock",
    "sound-profile.json.lock",
    "sound-packs.lock",
}
_CONTROL_NAME_KEYS = frozenset(name.casefold() for name in _CONTROL_NAMES)
_DERIVED_ROOT_DIRECTORIES = {
    ".gametree-resume-discard",
    "sound-cache",
}
_DERIVED_ROOT_DIRECTORY_KEYS = frozenset(
    name.casefold() for name in _DERIVED_ROOT_DIRECTORIES
)
_EDUCATION_WORKSPACE_LOCK_DIRECTORY = ".education-workspace.json.lock"


def _is_generated_root_runtime_file(relative_path: PurePosixPath) -> bool:
    """Return whether a root file is exact crash residue from a canonical writer."""
    if len(relative_path.parts) != 1:
        return False
    name = relative_path.parts[0].casefold()

    generated_shapes = (
        ("gametree-resume.json.", ".tmp"),
        ("gametree-resume.json.cas-", ".bak"),
        (".book-progress.json.bak.", ".tmp"),
        (".book-progress.json.", ".tmp"),
    )
    for prefix, suffix in generated_shapes:
        if not name.startswith(prefix) or not name.endswith(suffix):
            continue
        token = name[len(prefix) : -len(suffix)]
        if _is_tempfile_token(token):
            return True
    return False


def _is_generated_training_progress_file(relative_path: PurePosixPath) -> bool:
    """Classify only canonical TrainingProgressStore lock/temp filenames."""
    if (
        len(relative_path.parts) != 2
        or relative_path.parts[0].casefold() != "training-progress"
    ):
        return False
    name = relative_path.parts[1].casefold()
    if not name.startswith("."):
        return False
    remainder = name[1:]
    if len(remainder) < 64:
        return False
    digest, tail = remainder[:64], remainder[64:]
    if any(character not in "0123456789abcdef" for character in digest):
        return False
    if tail == ".json.lock":
        return True
    if not tail.startswith(".json.") or not tail.endswith(".tmp"):
        return False
    unique = tail[len(".json.") : -len(".tmp")]
    return _is_tempfile_token(unique)


_TEMPFILE_TOKEN_CHARACTERS = frozenset(
    "abcdefghijklmnopqrstuvwxyz0123456789_"
)
# CPython's tempfile._RandomNameSequence, used by every canonical mkstemp
# writer classified here, emits exactly eight characters from this alphabet.
# Keep the classifier tied to the shipped writer grammar so preservation-backed
# near-misses are never discarded merely because they look temp-like.
_TEMPFILE_TOKEN_LENGTH = 8
_HEX_CHARACTERS = frozenset("0123456789abcdef")


def _is_tempfile_token(value: str) -> bool:
    return len(value) == _TEMPFILE_TOKEN_LENGTH and all(
        character in _TEMPFILE_TOKEN_CHARACTERS for character in value
    )


def _is_generated_education_workspace_file(
    relative_path: PurePosixPath,
) -> bool:
    """Classify crash residue from the current EducationWorkspaceStore writer."""
    if len(relative_path.parts) != 1:
        return False
    name = relative_path.parts[0].casefold()
    prefix = ".education-workspace.json."
    if not name.startswith(prefix) or not name.endswith(".tmp"):
        return False
    token = name[len(prefix) : -len(".tmp")]
    return _is_tempfile_token(token)


def _upgrade_publication_guard_target(
    relative_path: PurePosixPath,
    *,
    settings_name: str,
    library_name: str,
) -> str | None:
    """Return the exact tracked target named by a publication-guard candidate."""
    if len(relative_path.parts) != 1:
        return None
    name = relative_path.parts[0].casefold()
    for target_name in (settings_name, library_name):
        target = target_name.casefold()
        prefix = f".{target}.publish-guard-"
        if not name.startswith(prefix):
            continue
        token = name[len(prefix) :]
        if len(token) == 12 and all(
            character in _HEX_CHARACTERS for character in token
        ):
            return target_name
    return None


def _is_upgrade_publication_guard_file(
    relative_path: PurePosixPath,
    *,
    settings_name: str,
    library_name: str,
) -> bool:
    """Classify exact publication-guard filename grammar."""
    return (
        _upgrade_publication_guard_target(
            relative_path,
            settings_name=settings_name,
            library_name=library_name,
        )
        is not None
    )


def _is_upgrade_generated_root_runtime_file(
    relative_path: PurePosixPath,
    *,
    settings_name: str,
    library_name: str,
) -> bool:
    """Classify exact-root residue created by Settings or the upgrade owner."""
    if len(relative_path.parts) != 1:
        return False

    name = relative_path.parts[0].casefold()
    settings = settings_name.casefold()

    # Settings.save() owns one fixed sibling temporary pathname.
    if name == f"{settings}.tmp":
        return True

    # The upgrade owner's atomic byte writer uses tempfile.mkstemp with
    # ".<target>.<token>.tmp".  The upgrade journal itself already starts
    # with a dot, so its temporary path begins with two dots.
    for target in (settings, ".v2-upgrade-state.json"):
        prefix = f".{target}."
        if name.startswith(prefix) and name.endswith(".tmp"):
            token = name[len(prefix) : -len(".tmp")]
            if _is_tempfile_token(token):
                return True

    return _is_upgrade_publication_guard_file(
        relative_path,
        settings_name=settings_name,
        library_name=library_name,
    )


def _generated_runtime_file_is_authenticated_hardlink(
    path: Path,
    metadata: os.stat_result,
    relative_path: PurePosixPath,
    *,
    root: Path,
    settings_name: str,
    library_name: str,
) -> bool:
    """Authenticate a writer-owned hardlink against its canonical target."""
    if len(relative_path.parts) != 1:
        return False
    name = relative_path.parts[0].casefold()
    target_name: str | None = None

    gametree_prefix = "gametree-resume.json.cas-"
    if name.startswith(gametree_prefix) and name.endswith(".bak"):
        token = name[len(gametree_prefix) : -len(".bak")]
        if _is_tempfile_token(token):
            target_name = "gametree-resume.json"

    settings = settings_name.casefold()
    library = library_name.casefold()
    if target_name is None:
        for target, canonical_name in (
            (settings, settings_name),
            (library, library_name),
        ):
            prefix = f".{target}.publish-guard-"
            if not name.startswith(prefix):
                continue
            token = name[len(prefix) :]
            if len(token) == 12 and all(
                character in _HEX_CHARACTERS for character in token
            ):
                target_name = canonical_name
                break

    if target_name is None:
        return False
    target_path = root / target_name
    try:
        target_metadata = _safe_stat(
            target_path,
            "generated hardlink canonical target",
        )
    except FileNotFoundError:
        return False
    if not stat.S_ISREG(target_metadata.st_mode):
        return False
    try:
        return os.path.samestat(metadata, target_metadata)
    except (AttributeError, OSError):
        return (
            metadata.st_dev,
            metadata.st_ino,
        ) == (
            target_metadata.st_dev,
            target_metadata.st_ino,
        )


_DB_SIDECARS = ("-wal", "-shm", "-journal")
_MAX_RECOVERY_JSON_BYTES = 8 * 1024 * 1024
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


class _UpgradeLockLost(Version2UpgradeError):
    """The coordinator no longer owns the canonical upgrade-lock pathname."""


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


def _same_file_identity(first: os.stat_result, second: os.stat_result) -> bool:
    try:
        return os.path.samestat(first, second)
    except (AttributeError, OSError):
        return (first.st_dev, first.st_ino) == (second.st_dev, second.st_ino)


def _stat_identity(info: os.stat_result) -> tuple[int, int]:
    return int(info.st_dev), int(info.st_ino)


def _remove_exact_regular_file(
    path: Path,
    *,
    label: str,
    expected_identity: tuple[int, int] | None = None,
) -> None:
    """Remove only the exact regular inode observed at an owned pathname.

    Move the pathname to a randomized same-directory quarantine first. If a
    substitution wins the inspect->rename race, the foreign bytes are preserved
    at that quarantine path and the operation fails closed instead of unlinking
    them. Only a quarantined inode with the authenticated identity is deleted.
    """
    try:
        before = _safe_stat(path, label)
    except OSError as exc:
        raise Version2UpgradeError(f"{label} could not be inspected safely") from exc
    if not stat.S_ISREG(before.st_mode):
        raise Version2UpgradeError(f"{label} must be a regular file")
    identity = _stat_identity(before)
    if expected_identity is not None and identity != expected_identity:
        raise Version2UpgradeError(f"{label} changed unexpectedly")

    quarantine: Path | None = None
    for _ in range(8):
        candidate = path.parent / (
            f".{path.name}.remove-quarantine-{secrets.token_hex(8)}"
        )
        if candidate.exists() or candidate.is_symlink():
            continue
        quarantine = candidate
        break
    if quarantine is None:
        raise Version2UpgradeError(f"{label} quarantine could not be allocated")

    try:
        os.replace(path, quarantine)
    except OSError as exc:
        raise Version2UpgradeError(f"{label} could not be quarantined safely") from exc

    moved = _safe_stat(quarantine, f"{label} quarantine")
    if not stat.S_ISREG(moved.st_mode) or _stat_identity(moved) != identity:
        raise Version2UpgradeError(f"{label} changed during removal")

    try:
        quarantine.unlink()
    except OSError as exc:
        raise Version2UpgradeError(f"{label} could not be removed safely") from exc
    _fsync_dir(path.parent)


def _require_published_temp_identity(
    path: Path,
    expected: os.stat_result | None,
    *,
    label: str,
) -> None:
    """Require a published pathname to remain the exact prepared private inode."""
    try:
        current = os.lstat(path)
    except OSError as exc:
        raise Version2UpgradeError(
            f"{label} changed before durability confirmation"
        ) from exc
    if (
        stat.S_ISLNK(current.st_mode)
        or _reparse(current)
        or not stat.S_ISREG(current.st_mode)
        or int(getattr(current, "st_nlink", 1)) != 1
        or expected is None
        or not _same_file_identity(expected, current)
    ):
        raise Version2UpgradeError(
            f"{label} changed before durability confirmation"
        )


def _require_directory_identity(
    path: Path,
    expected: os.stat_result | None,
    *,
    label: str,
) -> os.stat_result:
    """Require one staging pathname to remain the exact owned directory inode."""
    try:
        current = os.lstat(path)
    except OSError as exc:
        raise Version2UpgradeError(
            f"{label} changed unexpectedly"
        ) from exc
    if (
        stat.S_ISLNK(current.st_mode)
        or _reparse(current)
        or not stat.S_ISDIR(current.st_mode)
        or expected is None
        or not _same_file_identity(expected, current)
    ):
        raise Version2UpgradeError(
            f"{label} changed unexpectedly"
        )
    return current


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
    temp: Path | None = Path(raw)
    temp_identity: os.stat_result | None = None
    try:
        created = os.fstat(fd)
        if (
            not stat.S_ISREG(created.st_mode)
            or int(getattr(created, "st_nlink", 1)) != 1
        ):
            raise Version2UpgradeError(
                "atomic write temporary file must be private"
            )
        stream = os.fdopen(fd, "wb")
        fd = -1
        with stream as handle:
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
            prepared = os.fstat(handle.fileno())
            if (
                not stat.S_ISREG(prepared.st_mode)
                or int(getattr(prepared, "st_nlink", 1)) != 1
                or not _same_file_identity(created, prepared)
            ):
                raise Version2UpgradeError(
                    "atomic write temporary file changed while being prepared"
                )
            temp_identity = prepared

        assert temp is not None
        try:
            current = os.lstat(temp)
        except OSError as exc:
            raise Version2UpgradeError(
                "atomic write temporary file changed before publication"
            ) from exc
        if (
            stat.S_ISLNK(current.st_mode)
            or _reparse(current)
            or not stat.S_ISREG(current.st_mode)
            or int(getattr(current, "st_nlink", 1)) != 1
            or temp_identity is None
            or not _same_file_identity(temp_identity, current)
        ):
            raise Version2UpgradeError(
                "atomic write temporary file changed before publication"
            )
        os.replace(temp, path)
        temp = None
        _require_published_temp_identity(
            path,
            temp_identity,
            label="atomic write publication",
        )
        _fsync_dir(path.parent)
        _require_published_temp_identity(
            path,
            temp_identity,
            label="atomic write publication",
        )
    finally:
        if fd >= 0:
            try:
                os.close(fd)
            except OSError:
                pass
        # Never unlink an object merely because it occupies our old temporary
        # pathname. Remove only the exact private inode created by this writer.
        if temp is not None and temp_identity is not None:
            try:
                current = os.lstat(temp)
            except OSError:
                current = None
            if (
                current is not None
                and stat.S_ISREG(current.st_mode)
                and not stat.S_ISLNK(current.st_mode)
                and not _reparse(current)
                and int(getattr(current, "st_nlink", 1)) == 1
                and _same_file_identity(temp_identity, current)
            ):
                try:
                    _remove_exact_regular_file(
                        temp,
                        label="atomic write temporary file",
                        expected_identity=_stat_identity(temp_identity),
                    )
                except Version2UpgradeError:
                    pass


@dataclass(frozen=True, slots=True)
class _PublicationGuard:
    path: Path
    identity: tuple[int, int]


def _require_publication_guard(guard: _PublicationGuard) -> os.stat_result:
    try:
        info = _safe_stat(guard.path, "tracked publication guard")
    except OSError as exc:
        raise Version2UpgradeError(
            "tracked publication guard changed unexpectedly"
        ) from exc
    if (
        not stat.S_ISREG(info.st_mode)
        or _stat_identity(info) != guard.identity
    ):
        raise Version2UpgradeError(
            "tracked publication guard changed unexpectedly"
        )
    return info


def _publication_guard_hash(guard: _PublicationGuard) -> str:
    """Hash one exact guarded inode through a stable descriptor.

    Pathname identity is authenticated before and after the descriptor read.
    Content stability is proved from descriptor observations only: pathname
    stat and descriptor fstat timestamps are not cross-compared because
    Windows exposes different/deprecated st_ctime semantics for those
    interfaces. A second descriptor-bound hash makes same-size writes visible
    even when filesystem timestamp granularity is too coarse to move mtime.
    """
    _require_publication_guard(guard)
    flags = (
        os.O_RDONLY
        | getattr(os, "O_NOFOLLOW", 0)
        | getattr(os, "O_BINARY", 0)
    )
    descriptor = -1
    try:
        descriptor = os.open(guard.path, flags)
        opened = os.fstat(descriptor)
        if (
            not stat.S_ISREG(opened.st_mode)
            or _stat_identity(opened) != guard.identity
        ):
            raise Version2UpgradeError(
                "tracked publication guard changed unexpectedly"
            )
        opened_state = (
            int(opened.st_size),
            int(getattr(opened, "st_mtime_ns", 0)),
        )

        first = hashlib.sha256()
        while True:
            block = os.read(descriptor, 1024 * 1024)
            if not block:
                break
            first.update(block)
        after_first = os.fstat(descriptor)
        if (
            _stat_identity(after_first) != guard.identity
            or (
                int(after_first.st_size),
                int(getattr(after_first, "st_mtime_ns", 0)),
            )
            != opened_state
        ):
            raise Version2UpgradeError(
                "tracked publication guard changed unexpectedly"
            )

        os.lseek(descriptor, 0, os.SEEK_SET)
        second = hashlib.sha256()
        while True:
            block = os.read(descriptor, 1024 * 1024)
            if not block:
                break
            second.update(block)
        after_second = os.fstat(descriptor)
        if (
            _stat_identity(after_second) != guard.identity
            or (
                int(after_second.st_size),
                int(getattr(after_second, "st_mtime_ns", 0)),
            )
            != opened_state
            or second.digest() != first.digest()
        ):
            raise Version2UpgradeError(
                "tracked publication guard changed unexpectedly"
            )
    except Version2UpgradeError:
        raise
    except OSError as exc:
        raise Version2UpgradeError(
            "tracked publication guard could not be authenticated"
        ) from exc
    finally:
        if descriptor >= 0:
            os.close(descriptor)
    _require_publication_guard(guard)
    return first.hexdigest()


def _remove_publication_guard(guard: _PublicationGuard) -> None:
    """Remove only the exact guard inode that this upgrader created."""
    # Once a guard has been created, disappearance/substitution is itself a
    # coordination failure. Quarantine-before-delete prevents a last-moment
    # pathname swap from turning guard cleanup into deletion of foreign bytes.
    _require_publication_guard(guard)
    try:
        _remove_exact_regular_file(
            guard.path,
            label="tracked publication guard",
            expected_identity=guard.identity,
        )
    except Version2UpgradeError as exc:
        raise Version2UpgradeError(
            "tracked publication guard could not be removed safely"
        ) from exc


def _publication_guard(path: Path) -> _PublicationGuard:
    """Keep the authenticated pre-publication inode reachable across replace.

    A legitimate writer can race after the last semantic re-authentication but
    before the atomic name replacement. A same-filesystem hard link preserves
    that exact inode so an in-place writer cannot be silently discarded by the
    upgrader's replace. If the platform/filesystem cannot provide this guard,
    publication fails closed rather than widening the data-loss window.
    """
    info = _safe_stat(path, "tracked publication target")
    if not stat.S_ISREG(info.st_mode):
        raise Version2UpgradeError("tracked publication target must be a file")
    target_identity = _stat_identity(info)
    for _ in range(8):
        guard_path = path.parent / (
            f".{path.name}.publish-guard-{secrets.token_hex(6)}"
        )
        try:
            os.link(path, guard_path)
        except FileExistsError:
            continue
        except OSError as exc:
            raise Version2UpgradeBusy(
                "tracked publication cannot be protected safely"
            ) from exc
        try:
            guard_info = _safe_stat(guard_path, "tracked publication guard")
            current_info = _safe_stat(path, "tracked publication target")
            if (
                not stat.S_ISREG(guard_info.st_mode)
                or not stat.S_ISREG(current_info.st_mode)
                or _stat_identity(guard_info) != target_identity
                or _stat_identity(current_info) != target_identity
            ):
                raise Version2UpgradeBusy(
                    "tracked publication changed while guard was created"
                )
            return _PublicationGuard(guard_path, target_identity)
        except Exception:
            # Never clean up a pathname that another actor replaced after the
            # hard link was created. Only the exact inode we linked is ours.
            if guard_path.exists() or guard_path.is_symlink():
                try:
                    cleanup_info = _safe_stat(
                        guard_path, "tracked publication guard"
                    )
                    if (
                        stat.S_ISREG(cleanup_info.st_mode)
                        and _stat_identity(cleanup_info) == target_identity
                    ):
                        _remove_exact_regular_file(
                            guard_path,
                            label="tracked publication guard",
                            expected_identity=target_identity,
                        )
                except (OSError, Version2UpgradeError):
                    pass
            raise
    raise Version2UpgradeBusy("tracked publication guard could not be allocated")


def _atomic_json(path: Path, value: Mapping[str, object]) -> None:
    _atomic_bytes(
        path,
        (
            json.dumps(dict(value), ensure_ascii=False, sort_keys=True, indent=2)
            + "\n"
        ).encode("utf-8"),
    )


def _read_exact_regular_bytes(
    path: Path,
    *,
    label: str,
    max_bytes: int | None = None,
) -> bytes:
    """Read one exact regular inode through a descriptor-bound snapshot."""
    before = _safe_stat(path, label)
    if not stat.S_ISREG(before.st_mode):
        raise Version2UpgradeError(f"{label} must be a regular file")
    if max_bytes is not None and (
        type(max_bytes) is not int
        or max_bytes < 0
        or int(before.st_size) > max_bytes
    ):
        raise Version2UpgradeError(f"{label} exceeds the read limit")

    flags = (
        os.O_RDONLY
        | getattr(os, "O_NOFOLLOW", 0)
        | getattr(os, "O_BINARY", 0)
    )
    descriptor = -1
    chunks: list[bytes] = []
    total = 0
    try:
        descriptor = os.open(path, flags)
        opened = os.fstat(descriptor)
        if (
            not stat.S_ISREG(opened.st_mode)
            or not _same_file_identity(before, opened)
        ):
            raise Version2UpgradeError(f"{label} changed while opening")
        opened_state = (
            int(opened.st_size),
            int(getattr(opened, "st_mtime_ns", 0)),
        )

        while True:
            block = os.read(descriptor, 1024 * 1024)
            if not block:
                break
            total += len(block)
            if max_bytes is not None and total > max_bytes:
                raise Version2UpgradeError(f"{label} exceeds the read limit")
            chunks.append(block)

        after = os.fstat(descriptor)
        if (
            not _same_file_identity(opened, after)
            or (
                int(after.st_size),
                int(getattr(after, "st_mtime_ns", 0)),
            )
            != opened_state
        ):
            raise Version2UpgradeError(f"{label} changed while being read")
    except Version2UpgradeError:
        raise
    except OSError as exc:
        raise Version2UpgradeError(f"{label} could not be read safely") from exc
    finally:
        if descriptor >= 0:
            os.close(descriptor)

    current = _safe_stat(path, label)
    if (
        not stat.S_ISREG(current.st_mode)
        or not _same_file_identity(opened, current)
    ):
        raise Version2UpgradeError(f"{label} changed while being read")
    return b"".join(chunks)


def _hash(path: Path, *, label: str = "hashed file") -> str:
    before = _safe_stat(path, label)
    if not stat.S_ISREG(before.st_mode):
        raise Version2UpgradeError(f"{label} must be a regular file")

    flags = (
        os.O_RDONLY
        | getattr(os, "O_NOFOLLOW", 0)
        | getattr(os, "O_BINARY", 0)
    )
    descriptor = -1
    digest = hashlib.sha256()
    try:
        descriptor = os.open(path, flags)
        opened = os.fstat(descriptor)
        if (
            not stat.S_ISREG(opened.st_mode)
            or not _same_file_identity(before, opened)
        ):
            raise Version2UpgradeError(f"{label} changed while opening")
        opened_state = (
            int(opened.st_size),
            int(getattr(opened, "st_mtime_ns", 0)),
        )
        while True:
            block = os.read(descriptor, 1024 * 1024)
            if not block:
                break
            digest.update(block)
        after = os.fstat(descriptor)
        if (
            not _same_file_identity(opened, after)
            or (
                int(after.st_size),
                int(getattr(after, "st_mtime_ns", 0)),
            )
            != opened_state
        ):
            raise Version2UpgradeError(f"{label} changed while being hashed")
    except Version2UpgradeError:
        raise
    except OSError as exc:
        raise Version2UpgradeError(f"{label} could not be hashed safely") from exc
    finally:
        if descriptor >= 0:
            os.close(descriptor)

    current = _safe_stat(path, label)
    if (
        not stat.S_ISREG(current.st_mode)
        or not _same_file_identity(opened, current)
    ):
        raise Version2UpgradeError(f"{label} changed while being hashed")
    return digest.hexdigest()


def _stable_copy(
    source: Path,
    destination: Path,
    *,
    expected_size: int | None = None,
    expected_sha256: str | None = None,
) -> tuple[int, str]:
    if expected_size is not None and (
        type(expected_size) is not int or expected_size < 0
    ):
        raise ValueError("expected copy size is invalid")
    if expected_sha256 is not None and (
        type(expected_sha256) is not str
        or len(expected_sha256) != 64
        or any(character not in "0123456789abcdef" for character in expected_sha256)
    ):
        raise ValueError("expected copy digest is invalid")
    before = _safe_stat(source, "user-data source")
    if not stat.S_ISREG(before.st_mode):
        raise Version2UpgradeError("user-data source must be a regular file")
    before_id = (
        before.st_dev,
        before.st_ino,
        before.st_size,
        getattr(before, "st_mtime_ns", 0),
    )
    if expected_size is not None and int(before.st_size) != expected_size:
        raise Version2UpgradeError("user-data source size does not match expected copy")
    destination.parent.mkdir(parents=True, exist_ok=True)
    fd, raw = tempfile.mkstemp(
        prefix=f".{destination.name}.", suffix=".tmp", dir=str(destination.parent)
    )
    temp: Path | None = Path(raw)
    temp_identity: os.stat_result | None = None
    digest = hashlib.sha256()
    source_fd = -1
    try:
        created = os.fstat(fd)
        temp_identity = created
        if (
            not stat.S_ISREG(created.st_mode)
            or int(getattr(created, "st_nlink", 1)) != 1
        ):
            raise Version2UpgradeError(
                "backup copy temporary file must be private"
            )

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
        stream = os.fdopen(fd, "wb")
        fd = -1
        with stream as target:
            while True:
                block = os.read(source_fd, 1024 * 1024)
                if not block:
                    break
                target.write(block)
                digest.update(block)
            target.flush()
            os.fsync(target.fileno())
            prepared = os.fstat(target.fileno())
            if (
                not stat.S_ISREG(prepared.st_mode)
                or int(getattr(prepared, "st_nlink", 1)) != 1
                or not _same_file_identity(created, prepared)
            ):
                raise Version2UpgradeError(
                    "backup copy temporary file changed while being prepared"
                )
            temp_identity = prepared
        after = _safe_stat(source, "user-data source")
        after_id = (
            after.st_dev,
            after.st_ino,
            after.st_size,
            getattr(after, "st_mtime_ns", 0),
        )
        if after_id != before_id:
            raise Version2UpgradeError("user-data source changed during backup copy")

        copied_digest = digest.hexdigest()
        if expected_size is not None and int(after.st_size) != expected_size:
            raise Version2UpgradeError(
                "user-data source size does not match expected copy"
            )
        if expected_sha256 is not None and copied_digest != expected_sha256:
            raise Version2UpgradeError(
                "user-data source digest does not match expected copy"
            )

        assert temp is not None
        try:
            current = os.lstat(temp)
        except OSError as exc:
            raise Version2UpgradeError(
                "backup copy temporary file changed before publication"
            ) from exc
        if (
            stat.S_ISLNK(current.st_mode)
            or _reparse(current)
            or not stat.S_ISREG(current.st_mode)
            or int(getattr(current, "st_nlink", 1)) != 1
            or temp_identity is None
            or not _same_file_identity(temp_identity, current)
        ):
            raise Version2UpgradeError(
                "backup copy temporary file changed before publication"
            )
        os.replace(temp, destination)
        temp = None
        _require_published_temp_identity(
            destination,
            temp_identity,
            label="backup copy publication",
        )
        _fsync_dir(destination.parent)
        _require_published_temp_identity(
            destination,
            temp_identity,
            label="backup copy publication",
        )
        return int(after.st_size), copied_digest
    finally:
        if source_fd >= 0:
            os.close(source_fd)
        if fd >= 0:
            os.close(fd)
        if temp is not None and temp_identity is not None:
            try:
                current = os.lstat(temp)
            except OSError:
                current = None
            if (
                current is not None
                and stat.S_ISREG(current.st_mode)
                and not stat.S_ISLNK(current.st_mode)
                and not _reparse(current)
                and int(getattr(current, "st_nlink", 1)) == 1
                and _same_file_identity(temp_identity, current)
            ):
                try:
                    _remove_exact_regular_file(
                        temp,
                        label="backup copy temporary file",
                        expected_identity=_stat_identity(temp_identity),
                    )
                except Version2UpgradeError:
                    pass


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


def _library_state_sha256(
    path: Path,
    *,
    schema_validator: Callable[[sqlite3.Connection], int] = _canonical_library_schema,
) -> str:
    before = _safe_stat(path, "library state source")
    if not stat.S_ISREG(before.st_mode):
        raise Version2UpgradeError("library state source must be a regular file")

    def require_path_identity() -> None:
        current = _safe_stat(path, "library state source")
        if (
            not stat.S_ISREG(current.st_mode)
            or not _same_file_identity(before, current)
        ):
            raise Version2UpgradeError(
                "library state source changed during validation"
            )

    connection = None
    try:
        resolved = path.resolve(strict=True)
        require_path_identity()
        connection = sqlite3.connect(
            resolved.as_uri() + "?mode=ro",
            uri=True,
            timeout=0.0,
        )
        require_path_identity()
        connection.execute("PRAGMA busy_timeout=0")
        schema_validator(connection)
        require_path_identity()
        digest = _sqlite_state_sha256(connection)
        require_path_identity()
        return digest
    except Version2UpgradeError:
        raise
    except (OSError, sqlite3.DatabaseError) as exc:
        raise Version2UpgradeError("library state validation failed") from exc
    finally:
        if connection is not None:
            connection.close()


def _sqlite_backup(
    source: Path,
    destination: Path,
    *,
    schema_validator: Callable[[sqlite3.Connection], int] = _canonical_library_schema,
) -> tuple[int, str, int, str]:
    info = _safe_stat(source, "library source")
    if not stat.S_ISREG(info.st_mode):
        raise Version2UpgradeError("library source must be a regular file")
    destination.parent.mkdir(parents=True, exist_ok=True)

    def require_source_identity() -> None:
        current = _safe_stat(source, "library source")
        if (
            not stat.S_ISREG(current.st_mode)
            or not _same_file_identity(info, current)
        ):
            raise Version2UpgradeError("library source changed during backup")

    # Do not hand SQLite a pre-created temporary pathname. sqlite3.connect()
    # would reopen that name independently of mkstemp's authenticated inode,
    # allowing a substituted file to become the backup target. Build the
    # consistent SQLite snapshot in memory, serialize the validated database,
    # then publish those bytes through the already identity-bound atomic writer.
    #
    # Keep BEGIN IMMEDIATE alive through durable backup publication. Releasing
    # the writer lock after serialization but before _atomic_bytes() would allow
    # a cooperative SQLite writer to commit to the same source inode while this
    # function still returned success for the older snapshot.
    lock = reader = target = None
    serialized: bytes | None = None
    version: int | None = None
    state_digest: str | None = None
    try:
        try:
            # Separate connections avoid sqlite3.Connection.backup stalling on
            # a source connection that itself owns BEGIN IMMEDIATE.
            lock = sqlite3.connect(str(source), timeout=0.0)
            lock.execute("PRAGMA busy_timeout=0")
            lock.execute("BEGIN IMMEDIATE")
            require_source_identity()
            reader = sqlite3.connect(
                source.resolve(strict=True).as_uri() + "?mode=ro",
                uri=True,
                timeout=0.0,
            )
            reader.execute("PRAGMA busy_timeout=0")
            require_source_identity()
            version = schema_validator(reader)
            state_digest = _sqlite_state_sha256(reader)
            require_source_identity()
            target = sqlite3.connect(":memory:")
            reader.backup(target)
            target.commit()
            if schema_validator(target) != version:
                raise Version2UpgradeError("library backup schema mismatch")
            if _sqlite_state_sha256(target) != state_digest:
                raise Version2UpgradeError("library backup logical-state mismatch")
            require_source_identity()
            serialize = getattr(target, "serialize", None)
            if not callable(serialize):
                raise Version2UpgradeError(
                    "library backup serialization is unavailable"
                )
            serialized = serialize()
            if type(serialized) is not bytes or not serialized:
                raise Version2UpgradeError(
                    "library backup serialization produced invalid bytes"
                )
        except sqlite3.DatabaseError as exc:
            raise Version2UpgradeError("library backup could not be validated") from exc
        finally:
            if target is not None:
                target.close()
                target = None
            if reader is not None:
                reader.close()
                reader = None

        if serialized is None or version is None or state_digest is None:
            raise Version2UpgradeError("library backup serialization is unavailable")
        if lock is None or not lock.in_transaction:
            raise Version2UpgradeError(
                "library backup writer lock was lost before publication"
            )

        require_source_identity()
        _atomic_bytes(destination, serialized)
        # A non-cooperating process can replace a pathname despite SQLite
        # transaction discipline on platforms that permit rename of open files.
        # Rebind source identity after publication and again after validation.
        require_source_identity()
        if (
            _library_state_sha256(
                destination,
                schema_validator=schema_validator,
            )
            != state_digest
        ):
            raise Version2UpgradeError("library backup publication validation failed")
        require_source_identity()
        return (
            len(serialized),
            hashlib.sha256(serialized).hexdigest(),
            version,
            state_digest,
        )
    except OSError as exc:
        raise Version2UpgradeError("library backup could not be published") from exc
    finally:
        if lock is not None:
            try:
                if lock.in_transaction:
                    lock.rollback()
            finally:
                lock.close()


class _UpgradeLock:
    def __init__(self, path: Path) -> None:
        self.path = path
        self.handle = None

    @staticmethod
    def _identity(info: os.stat_result) -> tuple[int, int]:
        return int(info.st_dev), int(info.st_ino)

    @staticmethod
    def _require_private_regular(info: os.stat_result) -> None:
        if (
            stat.S_ISLNK(info.st_mode)
            or _reparse(info)
            or not stat.S_ISREG(info.st_mode)
            or int(getattr(info, "st_nlink", 1)) != 1
        ):
            raise Version2UpgradeError(
                "upgrade lock must be one private regular file"
            )

    def _require_current_handle(self) -> os.stat_result:
        assert self.handle is not None
        opened = os.fstat(self.handle.fileno())
        try:
            self._require_private_regular(opened)
        except Version2UpgradeError as exc:
            raise _UpgradeLockLost(
                "upgrade lock ownership was lost"
            ) from exc
        try:
            current = os.lstat(self.path)
        except OSError as exc:
            raise _UpgradeLockLost(
                "upgrade lock ownership was lost"
            ) from exc
        try:
            self._require_private_regular(current)
        except Version2UpgradeError as exc:
            raise _UpgradeLockLost(
                "upgrade lock ownership was lost"
            ) from exc
        if self._identity(opened) != self._identity(current):
            raise _UpgradeLockLost(
                "upgrade lock ownership was lost"
            )
        return opened

    def assert_current(self) -> None:
        self._require_current_handle()

    def _open_handle(self):
        try:
            before = os.lstat(self.path)
        except FileNotFoundError:
            before = None
        except OSError as exc:
            raise Version2UpgradeError(
                "upgrade lock could not be inspected"
            ) from exc
        if before is not None:
            self._require_private_regular(before)

        flags = os.O_RDWR
        flags |= getattr(os, "O_BINARY", 0)
        flags |= getattr(os, "O_NOINHERIT", 0)
        flags |= getattr(os, "O_CLOEXEC", 0)
        flags |= getattr(os, "O_NOFOLLOW", 0)
        flags |= getattr(os, "O_NONBLOCK", 0)
        if before is None:
            # A missing lock pathname must be exclusively created by this
            # upgrader. Otherwise a non-cooperating process can create an
            # arbitrary file in the lstat -> open window and have it adopted
            # (and potentially initialized) as our coordination inode.
            flags |= os.O_CREAT | os.O_EXCL
        try:
            descriptor = os.open(self.path, flags, 0o600)
        except OSError as exc:
            raise Version2UpgradeError(
                "upgrade lock could not be opened safely"
            ) from exc

        try:
            handle = os.fdopen(descriptor, "r+b")
            self.handle = handle
            try:
                opened = self._require_current_handle()
            except _UpgradeLockLost as exc:
                raise Version2UpgradeError(
                    "upgrade lock changed while opening"
                ) from exc
            if before is not None and self._identity(before) != self._identity(opened):
                raise Version2UpgradeError(
                    "upgrade lock changed while opening"
                )
            return handle
        except BaseException:
            if self.handle is not None:
                self.handle.close()
                self.handle = None
            else:
                os.close(descriptor)
            raise

    def __enter__(self) -> "_UpgradeLock":
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._open_handle()
        assert self.handle is not None
        try:
            opened = self._require_current_handle()
            if opened.st_size == 0:
                self.handle.seek(0)
                self.handle.write(b"\0")
                self.handle.flush()
                self._require_current_handle()
            self.handle.seek(0)
            try:
                if os.name == "nt":
                    import msvcrt
                    msvcrt.locking(self.handle.fileno(), msvcrt.LK_NBLCK, 1)
                else:
                    import fcntl
                    fcntl.flock(
                        self.handle.fileno(),
                        fcntl.LOCK_EX | fcntl.LOCK_NB,
                    )
            except (OSError, BlockingIOError) as exc:
                raise Version2UpgradeBusy(
                    "another Version 2 upgrade is active"
                ) from exc
            self._require_current_handle()
            return self
        except BaseException:
            self.handle.close()
            self.handle = None
            raise

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
        self._active_upgrade_lock: _UpgradeLock | None = None

    def _assert_upgrade_lock(self) -> None:
        if self._active_upgrade_lock is not None:
            self._active_upgrade_lock.assert_current()

    def _validate_library_schema(self, connection: sqlite3.Connection) -> int:
        """Validate one Library connection for this coordinator instance."""
        return _canonical_library_schema(connection)

    def _notify(self, phase: str) -> None:
        self._assert_upgrade_lock()
        if self.phase_hook is not None:
            self.phase_hook(phase)
        self._assert_upgrade_lock()

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
            relative_path = PurePosixPath(relative)
            if (
                len(relative_path.parts) == 1
                and relative_path.parts[0].casefold()
                == _EDUCATION_WORKSPACE_LOCK_DIRECTORY
            ):
                # EducationWorkspaceStore owns this exact root directory as its
                # live publication lock (mkdir/rmdir). Do not migrate while a
                # peer save is active. A regular file with the same spelling is
                # not writer control state and remains preservation-backed.
                lock_info = _safe_stat(path, "education workspace lock")
                if stat.S_ISDIR(lock_info.st_mode):
                    raise Version2UpgradeBusy(
                        "education workspace store is busy during upgrade"
                    )
            if relative.casefold() in _CONTROL_NAME_KEYS:
                # A canonical control *file* is writer-owned and excluded only
                # after authenticating it as one private regular inode. A
                # directory that merely has the same name cannot be a lock or
                # journal file; preserve its descendants as user data. Symlinks,
                # reparse points, and special objects still fail closed through
                # _safe_stat/the regular-file boundary.
                control_info = _safe_stat(path, "user-data control entry")
                if not stat.S_ISDIR(control_info.st_mode):
                    if not stat.S_ISREG(control_info.st_mode):
                        raise Version2UpgradeError(
                            "user-data control entry must be a regular file"
                        )
                    if int(getattr(control_info, "st_nlink", 1)) == 1:
                        continue
                    # A hard-linked regular file cannot be authenticated as
                    # private writer control state. Preserve that exact inode
                    # as ordinary user data instead of either excluding it or
                    # failing the entire backup merely because its pathname
                    # resembles a control file.
            # Derived runtime/control subtrees are not preservation-backed user
            # state. Exclude only descendants of exact root runtime directories.
            # The root object itself is still validated below, so a regular file
            # using one of these names remains user data and a symlink/reparse
            # point still fails closed.
            if (
                len(relative_path.parts) > 1
                and relative_path.parts[0].casefold()
                in _DERIVED_ROOT_DIRECTORY_KEYS
            ):
                # Even disposable runtime descendants remain inside the trusted
                # user-data filesystem boundary.  Authenticate the actual
                # directory entry before excluding it so a canonical cache/guard
                # pathname cannot hide a symlink or reparse alias.
                info = _safe_stat(path, "derived runtime entry")
                if not (
                    stat.S_ISREG(info.st_mode) or stat.S_ISDIR(info.st_mode)
                ):
                    raise Version2UpgradeError(
                        "derived runtime entry must be a regular file or directory"
                    )
                continue
            # Atomic GameTree/Book-progress writers may leave these exact-root
            # temporary files behind only after abrupt process death. They are
            # internal publication residue, not preservation-backed user data.
            # Nested lookalikes and non-matching near names remain ordinary data.
            private_generated_runtime = (
                _is_generated_root_runtime_file(relative_path)
                or _is_generated_training_progress_file(relative_path)
                or _is_generated_education_workspace_file(relative_path)
            )
            upgrade_generated_runtime = _is_upgrade_generated_root_runtime_file(
                relative_path,
                settings_name=self.layout.settings_name,
                library_name=self.layout.library_name,
            )
            publication_guard_target = _upgrade_publication_guard_target(
                relative_path,
                settings_name=self.layout.settings_name,
                library_name=self.layout.library_name,
            )
            publication_guard = publication_guard_target is not None
            if private_generated_runtime or upgrade_generated_runtime:
                # Filename grammar identifies ownership, but it does not prove
                # filesystem identity. Canonical writer temps/locks are created
                # as private inodes and may be excluded only while st_nlink=1.
                # Publication guards are different: exclude one only while it is
                # still the same hard-linked inode as the tracked Settings or
                # Library pathname named by the guard. A private lookalike, an
                # unrelated hard link, or a stale guard whose target was already
                # replaced can contain preservation-worthy user bytes.
                generated_info = _safe_stat(path, "generated runtime entry")
                if stat.S_ISREG(generated_info.st_mode):
                    link_count = int(getattr(generated_info, "st_nlink", 1))
                    if publication_guard:
                        target_path = self.layout.root / publication_guard_target
                        try:
                            target_info = target_path.lstat()
                        except OSError:
                            target_info = None
                        if (
                            target_info is not None
                            and stat.S_ISREG(target_info.st_mode)
                            and not stat.S_ISLNK(target_info.st_mode)
                            and not _reparse(target_info)
                            and link_count >= 2
                            and os.path.samestat(generated_info, target_info)
                        ):
                            continue
                    elif (
                        link_count == 1
                        or _generated_runtime_file_is_authenticated_hardlink(
                            path,
                            generated_info,
                            relative_path,
                            root=self.layout.root,
                            settings_name=self.layout.settings_name,
                            library_name=self.layout.library_name,
                        )
                    ):
                        continue
                    # A hard-linked temp/lock-shaped regular file cannot be an
                    # authentic private writer residue. Preserve it as ordinary
                    # user data instead of silently dropping an aliased inode.
                # A directory merely happens to have a generated filename; it
                # is not writer residue. Let the ordinary path logic below
                # preserve its descendants. Other special objects also fall
                # through and are rejected by the normal non-regular boundary.
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
                    "user-data backup exceeds file count limit"
                )
            if total > self.limits.max_bytes:
                raise Version2UpgradeError("user-data backup exceeds byte limit")
        return tuple(files)

    def _create_backup(self, upgrade_id: str) -> tuple[Path, dict[str, object]]:
        self._assert_upgrade_lock()
        final = self.layout.backup_root / upgrade_id
        temp = self.layout.backup_root / f".{upgrade_id}.tmp-{secrets.token_hex(4)}"
        if final.exists() or final.is_symlink():
            raise Version2UpgradeError("upgrade backup identifier collision")
        temp.mkdir()
        temp_identity = _require_directory_identity(
            temp,
            os.lstat(temp),
            label="upgrade backup staging directory",
        )
        data = temp / "data"
        data.mkdir()
        data_identity = _require_directory_identity(
            data,
            os.lstat(data),
            label="upgrade backup data directory",
        )
        published = False

        def require_staging() -> None:
            self._assert_upgrade_lock()
            _require_directory_identity(
                temp,
                temp_identity,
                label="upgrade backup staging directory",
            )
            _require_directory_identity(
                data,
                data_identity,
                label="upgrade backup data directory",
            )

        entries: list[dict[str, object]] = []
        library_schema = None
        try:
            for source in self._files():
                require_staging()
                relative = _relative(self.layout.root, source)
                destination = data.joinpath(*PurePosixPath(relative).parts)
                chain = _dir_chain(self.layout.root, source.parent)
                state_digest = None
                if relative == self.layout.library_name:
                    size, digest, library_schema, state_digest = _sqlite_backup(
                        source,
                        destination,
                        schema_validator=self._validate_library_schema,
                    )
                else:
                    size, digest = _stable_copy(source, destination)
                    if relative == self.layout.settings_name:
                        state_digest = digest
                require_staging()
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
            require_staging()
            _atomic_json(temp / "manifest.json", manifest)
            require_staging()
            # The initial collision check is not publication authority: refuse a
            # destination that appeared while the backup was being prepared.
            if final.exists() or final.is_symlink():
                raise Version2UpgradeError("upgrade backup identifier collision")
            require_staging()
            os.replace(temp, final)
            published = True
            _require_directory_identity(
                final,
                temp_identity,
                label="upgrade backup publication",
            )
            _fsync_dir(self.layout.backup_root)
            _require_directory_identity(
                final,
                temp_identity,
                label="upgrade backup publication",
            )
            self._assert_upgrade_lock()
            self._last_backup = final
            self._last_manifest = manifest
            return final, manifest
        finally:
            if not published and (temp.exists() or temp.is_symlink()):
                # Never recursively delete a pathname another actor substituted
                # for our staging directory. Cleanup is permitted only while the
                # top-level staging inode is still exactly the directory we made.
                try:
                    _require_directory_identity(
                        temp,
                        temp_identity,
                        label="upgrade backup staging directory",
                    )
                except Version2UpgradeError:
                    pass
                else:
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
        self._assert_upgrade_lock()
        _atomic_json(self.layout.journal_path, payload)
        self._assert_upgrade_lock()
        if notify:
            self._notify(phase)

    def _read_json(self, path: Path, label: str) -> dict[str, object]:
        try:
            payload = _read_exact_regular_bytes(
                path,
                label=label,
                max_bytes=_MAX_RECOVERY_JSON_BYTES,
            )
            value = json.loads(
                payload.decode("utf-8"),
                object_pairs_hook=_unique_json_object,
            )
        except _DuplicateJsonKeyError as exc:
            raise Version2UpgradeRecoveryError(
                f"{label} contains duplicate JSON keys"
            ) from exc
        except (
            OSError,
            UnicodeError,
            json.JSONDecodeError,
            Version2UpgradeError,
        ) as exc:
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
            backup_identity = _safe_stat(backup, "upgrade backup directory")
        except (OSError, Version2UpgradeError) as exc:
            raise Version2UpgradeRecoveryError(
                "upgrade backup directory is missing"
            ) from exc
        if not stat.S_ISDIR(backup_identity.st_mode):
            raise Version2UpgradeRecoveryError(
                "upgrade backup directory is missing"
            )

        data = backup / "data"
        try:
            data_identity = _safe_stat(data, "upgrade backup data directory")
        except (OSError, Version2UpgradeError) as exc:
            raise Version2UpgradeRecoveryError(
                "upgrade backup data directory is missing"
            ) from exc
        if not stat.S_ISDIR(data_identity.st_mode):
            raise Version2UpgradeRecoveryError(
                "upgrade backup data directory is missing"
            )

        def require_backup_tree() -> None:
            try:
                _require_directory_identity(
                    backup,
                    backup_identity,
                    label="upgrade backup directory",
                )
                _require_directory_identity(
                    data,
                    data_identity,
                    label="upgrade backup data directory",
                )
            except Version2UpgradeError as exc:
                raise Version2UpgradeRecoveryError(
                    "upgrade backup directory changed during recovery"
                ) from exc

        require_backup_tree()
        raw = self._read_json(backup / "manifest.json", "upgrade backup manifest")
        require_backup_tree()
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
            require_backup_tree()
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
            candidate = data / Path(*PurePosixPath(path).parts)
            try:
                candidate_info = _safe_stat(candidate, "upgrade backup file")
            except (OSError, Version2UpgradeError) as exc:
                raise Version2UpgradeRecoveryError(
                    "upgrade backup checksum mismatch"
                ) from exc
            try:
                candidate_digest = _hash(
                    candidate,
                    label="upgrade backup file",
                )
            except Version2UpgradeError as exc:
                raise Version2UpgradeRecoveryError(
                    "upgrade backup checksum mismatch"
                ) from exc
            require_backup_tree()
            if (
                not stat.S_ISREG(candidate_info.st_mode)
                or candidate_info.st_size != size
                or candidate_digest != digest
            ):
                raise Version2UpgradeRecoveryError(
                    "upgrade backup checksum mismatch"
                )
        require_backup_tree()
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

    def _tracked_state_snapshot(
        self,
        name: str,
    ) -> tuple[str | None, tuple[int, int] | None]:
        if name not in {self.layout.settings_name, self.layout.library_name}:
            raise ValueError("unknown tracked upgrade path")
        path = self.layout.root / name
        if not path.exists() and not path.is_symlink():
            return None, None
        before = _safe_stat(path, "tracked user data")
        if not stat.S_ISREG(before.st_mode):
            raise Version2UpgradeError("tracked user data must be a file")
        identity = _stat_identity(before)
        if name == self.layout.library_name:
            state = _library_state_sha256(
                path, schema_validator=self._validate_library_schema
            )
        else:
            state = _hash(path, label="tracked user data")
        after = _safe_stat(path, "tracked user data")
        if (
            not stat.S_ISREG(after.st_mode)
            or _stat_identity(after) != identity
        ):
            raise Version2UpgradeError(
                "tracked user data changed during state authentication"
            )
        return state, identity

    def _tracked_state_sha256(self, name: str) -> str | None:
        state, _identity = self._tracked_state_snapshot(name)
        return state

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

    def _clear_library_sidecars(
        self,
        *,
        expected_library_identity: tuple[int, int] | None = None,
    ) -> None:
        def require_library_identity() -> None:
            if expected_library_identity is None:
                return
            try:
                current = _safe_stat(
                    self.layout.library_path,
                    "library sidecar owner",
                )
            except OSError as exc:
                raise Version2UpgradeRecoveryError(
                    "library changed during sidecar cleanup"
                ) from exc
            if (
                not stat.S_ISREG(current.st_mode)
                or _stat_identity(current) != expected_library_identity
            ):
                raise Version2UpgradeRecoveryError(
                    "library changed during sidecar cleanup"
                )

        require_library_identity()
        for suffix in _DB_SIDECARS:
            require_library_identity()
            sidecar = Path(str(self.layout.library_path) + suffix)
            if not sidecar.exists() and not sidecar.is_symlink():
                continue
            info = _safe_stat(sidecar, "library sidecar")
            if not stat.S_ISREG(info.st_mode):
                raise Version2UpgradeRecoveryError(
                    "library sidecar is not a regular file"
                )
            try:
                _remove_exact_regular_file(
                    sidecar,
                    label="library sidecar",
                    expected_identity=_stat_identity(info),
                )
            except Version2UpgradeError as exc:
                raise Version2UpgradeRecoveryError(
                    "library sidecar changed during removal"
                ) from exc
            require_library_identity()
        require_library_identity()

    def _prepare_library_publication(
        self,
        expected_original: str,
        *,
        expected_identity: tuple[int, int] | None = None,
    ) -> None:
        """Normalize a quiescent live SQLite file before atomic publication.

        The logical state must still equal the pre-upgrade snapshot. A zero-timeout
        checkpoint/IMMEDIATE probe converts ordinary closed WAL state into a
        self-contained main database while failing closed on an active writer.
        """
        if not _is_sha256(expected_original):
            raise Version2UpgradeError(
                "library backup tracked-state metadata is invalid"
            )
        path = self.layout.library_path
        try:
            before = _safe_stat(path, "library publication target")
        except OSError as exc:
            raise Version2UpgradeError(
                "library publication target could not be inspected"
            ) from exc
        if not stat.S_ISREG(before.st_mode):
            raise Version2UpgradeError(
                "library publication target must be a regular file"
            )
        if (
            expected_identity is not None
            and _stat_identity(before) != expected_identity
        ):
            raise Version2UpgradeError(
                "library publication target changed after recovery authorization"
            )

        def require_target_identity() -> None:
            try:
                current = _safe_stat(path, "library publication target")
            except OSError as exc:
                raise Version2UpgradeError(
                    "library publication target changed during preparation"
                ) from exc
            if (
                not stat.S_ISREG(current.st_mode)
                or not _same_file_identity(before, current)
            ):
                raise Version2UpgradeError(
                    "library publication target changed during preparation"
                )

        connection = None
        try:
            require_target_identity()
            connection = sqlite3.connect(str(path), timeout=0.0)
            require_target_identity()
            connection.execute("PRAGMA busy_timeout=0")
            self._validate_library_schema(connection)
            require_target_identity()
            if _sqlite_state_sha256(connection) != expected_original:
                raise Version2UpgradeError(
                    "tracked user data changed after the upgrade snapshot"
                )
            require_target_identity()
            mode_row = connection.execute("PRAGMA journal_mode").fetchone()
            mode = str(mode_row[0]).casefold() if mode_row else ""
            if mode == "wal":
                checkpoint = connection.execute(
                    "PRAGMA wal_checkpoint(TRUNCATE)"
                ).fetchone()
                require_target_identity()
                if checkpoint and int(checkpoint[0]) != 0:
                    raise Version2UpgradeBusy(
                        "library is busy during upgrade publication"
                    )
                # A basename-specific WAL created in the final replace window
                # cannot be retained by a hard-link guard on the main file.
                # Persist DELETE mode while the database is quiescent so a
                # subsequent legitimate writer commits to the guarded inode.
                mode_row = connection.execute(
                    "PRAGMA journal_mode=DELETE"
                ).fetchone()
                require_target_identity()
                if not mode_row or str(mode_row[0]).casefold() != "delete":
                    raise Version2UpgradeBusy(
                        "library journal mode could not be normalized safely"
                    )
            connection.execute("BEGIN IMMEDIATE")
            require_target_identity()
            if _sqlite_state_sha256(connection) != expected_original:
                connection.rollback()
                raise Version2UpgradeError(
                    "tracked user data changed after the upgrade snapshot"
                )
            require_target_identity()
            connection.rollback()
            require_target_identity()
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

        require_target_identity()
        if (
            _library_state_sha256(
                path,
                schema_validator=self._validate_library_schema,
            )
            != expected_original
        ):
            raise Version2UpgradeError(
                "tracked user data changed after the upgrade snapshot"
            )
        require_target_identity()
        # No writer held the SQLite write lock and WAL has been checkpointed.
        # Remove now-stale sidecars only while the canonical main-file pathname
        # is still the exact inode normalized above.
        self._clear_library_sidecars(
            expected_library_identity=_stat_identity(before),
        )
        require_target_identity()

    def _restore(self, upgrade_id: str) -> int:
        self._assert_upgrade_lock()
        backup, manifest = self._manifest(upgrade_id)
        self._assert_upgrade_lock()
        journal = self._journal()
        if journal.get("upgrade_id") != upgrade_id:
            raise Version2UpgradeRecoveryError(
                "upgrade recovery identity mismatch"
            )
        owned_raw = journal.get("owned_states")
        assert isinstance(owned_raw, dict)
        owned_states = {str(k): str(v) for k, v in owned_raw.items()}

        actions: dict[str, str] = {}
        authorized_states: dict[str, str | None] = {}
        authorized_identities: dict[str, tuple[int, int] | None] = {}

        # First pass remains all-or-nothing authorization: prove that both
        # tracked paths are either original, upgrader-owned, or absent exactly
        # as the journal permits before recovery mutates either one.
        for name in (self.layout.settings_name, self.layout.library_name):
            entry = self._manifest_tracked_entry(manifest, name)
            try:
                current, current_identity = self._tracked_state_snapshot(name)
            except Exception as exc:
                raise Version2UpgradeRecoveryError(
                    "tracked recovery state cannot be authenticated"
                ) from exc
            authorized_states[name] = current
            authorized_identities[name] = current_identity
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
                actions[name] = "restore"
            else:
                raise Version2UpgradeRecoveryError(
                    "tracked user data changed outside this upgrade"
                )

        def guarded_state(name: str, guard: _PublicationGuard) -> str:
            if name == self.layout.library_name:
                return _library_state_sha256(
                    guard.path,
                    schema_validator=self._validate_library_schema,
                )
            return _publication_guard_hash(guard)

        restored = 0
        for name in (self.layout.settings_name, self.layout.library_name):
            self._assert_upgrade_lock()
            action = actions[name]
            entry = self._manifest_tracked_entry(manifest, name)
            destination = self.layout.root / name
            authorized = authorized_states[name]
            authorized_identity = authorized_identities[name]
            if action == "noop":
                continue
            if authorized is None or authorized_identity is None:
                raise Version2UpgradeRecoveryError(
                    "tracked recovery authorization disappeared"
                )

            # A Library restore/delete must first collapse any quiescent WAL
            # state into the exact authenticated main inode. This also blocks a
            # canonical writer through BEGIN IMMEDIATE before sidecars are
            # removed.
            if name == self.layout.library_name:
                try:
                    self._prepare_library_publication(
                        authorized,
                        expected_identity=authorized_identity,
                    )
                except Version2UpgradeError as exc:
                    raise Version2UpgradeRecoveryError(
                        "tracked Library changed before recovery publication"
                    ) from exc

            try:
                immediate, immediate_identity = self._tracked_state_snapshot(name)
            except Exception as exc:
                raise Version2UpgradeRecoveryError(
                    "tracked recovery state cannot be re-authenticated"
                ) from exc
            if (
                immediate != authorized
                or immediate_identity != authorized_identity
            ):
                raise Version2UpgradeRecoveryError(
                    "tracked user data identity changed before recovery publication"
                )

            guard: _PublicationGuard | None = None
            preserve_guard = False
            try:
                guard = _publication_guard(destination)
                current_state, current_identity = self._tracked_state_snapshot(name)
                if (
                    guard.identity != authorized_identity
                    or guarded_state(name, guard) != authorized
                    or current_state != authorized
                    or current_identity != authorized_identity
                ):
                    raise Version2UpgradeRecoveryError(
                        "tracked user data identity changed before recovery publication"
                    )

                if action == "delete":
                    _remove_exact_regular_file(
                        destination,
                        label="upgrade-created tracked data",
                        expected_identity=guard.identity,
                    )
                    # The canonical pathname is now gone, but the exact old
                    # inode remains reachable through the guard. An in-place
                    # writer racing the final window therefore remains visible.
                    if guarded_state(name, guard) != authorized:
                        os.replace(guard.path, destination)
                        guard = None
                        _fsync_dir(destination.parent)
                        raise Version2UpgradeRecoveryError(
                            "tracked user data changed during recovery deletion"
                        )
                    _remove_publication_guard(guard)
                    guard = None
                    continue

                assert action == "restore"
                assert entry is not None
                relative = str(entry["path"])
                source = backup / "data" / Path(*PurePosixPath(relative).parts)
                chain = _dir_chain(
                    self.layout.root, destination.parent, create=True
                )
                size, digest = _stable_copy(
                    source,
                    destination,
                    expected_size=int(entry["size"]),
                    expected_sha256=str(entry["sha256"]),
                )
                if _dir_chain(self.layout.root, destination.parent) != chain:
                    preserve_guard = True
                    raise Version2UpgradeRecoveryError(
                        "user-data parent directory changed during recovery"
                    )
                if size != entry["size"] or digest != entry["sha256"]:
                    preserve_guard = True
                    raise Version2UpgradeRecoveryError(
                        "upgrade backup changed during recovery"
                    )

                if guarded_state(name, guard) != authorized:
                    # A legitimate in-place writer reached the old inode after
                    # final authorization but before our replace. Its exact bytes
                    # win over rollback: restore that guarded inode and fail.
                    _require_publication_guard(guard)
                    os.replace(guard.path, destination)
                    guard = None
                    _fsync_dir(destination.parent)
                    raise Version2UpgradeRecoveryError(
                        "tracked user data changed during recovery publication"
                    )

                try:
                    restored_state = self._tracked_state_sha256(name)
                except Exception as exc:
                    preserve_guard = True
                    raise Version2UpgradeRecoveryError(
                        "tracked recovery readback validation failed"
                    ) from exc
                if restored_state != entry.get("state_sha256"):
                    preserve_guard = True
                    raise Version2UpgradeRecoveryError(
                        "tracked recovery readback mismatch"
                    )

                _remove_publication_guard(guard)
                guard = None
                restored += 1
            except Version2UpgradeRecoveryError:
                if guard is not None:
                    try:
                        current = _safe_stat(
                            destination, "tracked recovery publication target"
                        )
                        target_is_guarded = (
                            stat.S_ISREG(current.st_mode)
                            and _stat_identity(current) == guard.identity
                        )
                    except (OSError, Version2UpgradeError):
                        target_is_guarded = False
                    if not target_is_guarded:
                        preserve_guard = True
                raise
            except Version2UpgradeError as exc:
                if guard is not None:
                    try:
                        current = _safe_stat(
                            destination, "tracked recovery publication target"
                        )
                        target_is_guarded = (
                            stat.S_ISREG(current.st_mode)
                            and _stat_identity(current) == guard.identity
                        )
                    except (OSError, Version2UpgradeError):
                        target_is_guarded = False
                    if not target_is_guarded:
                        preserve_guard = True
                raise Version2UpgradeRecoveryError(
                    "tracked recovery publication failed"
                ) from exc
            finally:
                if guard is not None and not preserve_guard:
                    try:
                        _remove_publication_guard(guard)
                    except Version2UpgradeError as exc:
                        raise Version2UpgradeRecoveryError(
                            "tracked recovery guard cleanup failed"
                        ) from exc

        self._assert_upgrade_lock()
        _fsync_dir(self.layout.root)
        self._assert_upgrade_lock()
        try:
            settings_entry = self._manifest_tracked_entry(
                manifest, self.layout.settings_name
            )
            if settings_entry is not None:
                settings_payload = _read_exact_regular_bytes(
                    self.layout.settings_path,
                    label="recovered settings readback",
                    max_bytes=_MAX_RECOVERY_JSON_BYTES,
                )
                candidate = self.settings_factory(
                    self.layout.root / ".settings.recovery-readback"
                )
                candidate.import_json(
                    settings_payload.decode("utf-8"),
                    persist=False,
                )
            library_entry = self._manifest_tracked_entry(
                manifest, self.layout.library_name
            )
            if library_entry is not None:
                restored_schema = self._library_schema()
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
        self._assert_upgrade_lock()
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
        self._assert_upgrade_lock()
        return True

    def recover_interrupted(self) -> bool:
        self._ensure_roots()
        with _UpgradeLock(self.layout.lock_path) as upgrade_lock:
            self._active_upgrade_lock = upgrade_lock
            try:
                self._assert_upgrade_lock()
                return self._recover_locked()
            finally:
                self._active_upgrade_lock = None

    def _settings_need(self) -> bool:
        path = self.layout.settings_path
        if not path.exists() and not path.is_symlink():
            return False
        info = _safe_stat(path, "settings file")
        if not stat.S_ISREG(info.st_mode):
            raise Version2UpgradeError("settings path must be a file")
        try:
            payload = _read_exact_regular_bytes(
                path,
                label="settings file",
                max_bytes=_MAX_RECOVERY_JSON_BYTES,
            )
            raw = json.loads(payload.decode("utf-8"))
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

        def require_library_identity() -> None:
            current = _safe_stat(path, "library file")
            if (
                not stat.S_ISREG(current.st_mode)
                or not _same_file_identity(info, current)
            ):
                raise Version2UpgradeError(
                    "library file changed during validation"
                )

        connection = None
        try:
            resolved = path.resolve(strict=True)
            require_library_identity()
            connection = sqlite3.connect(
                resolved.as_uri() + "?mode=ro",
                uri=True,
                timeout=0.0,
            )
            require_library_identity()
            connection.execute("PRAGMA busy_timeout=0")
            schema = self._validate_library_schema(connection)
            require_library_identity()
            return schema
        except Version2UpgradeError:
            raise
        except (OSError, sqlite3.DatabaseError) as exc:
            raise Version2UpgradeError("library validation failed") from exc
        finally:
            if connection is not None:
                connection.close()

    def _needs_upgrade(self) -> bool:
        self._assert_upgrade_lock()
        settings_need = self._settings_need()
        schema = self._library_schema()
        self._assert_upgrade_lock()
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
        self._assert_upgrade_lock()
        if not self._settings_need():
            return False
        path = self.layout.settings_path
        try:
            source_payload = _read_exact_regular_bytes(
                path,
                label="settings migration source",
                max_bytes=_MAX_RECOVERY_JSON_BYTES,
            )
            candidate = self.settings_factory(
                path.parent / f".{path.name}.upgrade-validate"
            )
            candidate.import_json(
                source_payload.decode("utf-8"), persist=False
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
        original_state: str | None = None
        if manifest is not None:
            entry = self._manifest_tracked_entry(
                manifest, self.layout.settings_name
            )
            if entry is None or not _is_sha256(entry.get("state_sha256")):
                raise Version2UpgradeError(
                    "settings backup tracked-state metadata is invalid"
                )
            original_state = str(entry["state_sha256"])
        if upgrade_id is not None:
            if manifest is None or original_state is None:
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

        self._assert_upgrade_lock()
        guard: _PublicationGuard | None = None
        preserve_guard = False
        try:
            if original_state is not None:
                guard = _publication_guard(path)
                if (
                    _publication_guard_hash(guard) != original_state
                    or _hash(path, label="settings publication target") != original_state
                ):
                    raise Version2UpgradeError(
                        "tracked user data changed during settings publication"
                    )
            _atomic_bytes(path, payload)
            if (
                guard is not None
                and _publication_guard_hash(guard) != original_state
            ):
                # A writer changed the old inode after our final authentication.
                # Put those exact user bytes back before failing closed.
                _require_publication_guard(guard)
                os.replace(guard.path, path)
                guard = None
                _fsync_dir(path.parent)
                raise Version2UpgradeError(
                    "tracked user data changed during settings publication"
                )
            if _hash(path, label="settings publication target") != expected:
                raise Version2UpgradeError(
                    "settings migration publication verification failed"
                )
            self._assert_upgrade_lock()
            return True
        except BaseException:
            if guard is not None:
                # If failure happened after the canonical pathname stopped
                # naming the exact guarded old inode, keep that old inode
                # reachable as recovery evidence. This includes an atomic writer
                # that correctly detected candidate substitution after replace.
                try:
                    current = _safe_stat(path, "settings publication target")
                    target_is_old_inode = (
                        stat.S_ISREG(current.st_mode)
                        and _stat_identity(current) == guard.identity
                    )
                except (OSError, Version2UpgradeError):
                    target_is_old_inode = False
                if not target_is_old_inode:
                    preserve_guard = True
            raise
        finally:
            if guard is not None and not preserve_guard:
                _remove_publication_guard(guard)

    def _migrate_library(
        self,
        backup: Path | None = None,
        manifest: Mapping[str, object] | None = None,
        upgrade_id: str | None = None,
        *,
        recovered: bool = False,
    ) -> bool:
        self._assert_upgrade_lock()
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
        work_identity: os.stat_result | None = None
        publish_identity: os.stat_result | None = None
        try:
            size, digest = _stable_copy(source, work)
            work_identity = os.lstat(work)
            _require_published_temp_identity(
                work,
                work_identity,
                label="library migration work file",
            )
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
            _require_published_temp_identity(
                work,
                work_identity,
                label="library migration work file",
            )

            _, _, publish_schema, publish_state = _sqlite_backup(
                work,
                publish,
                schema_validator=self._validate_library_schema,
            )
            publish_identity = os.lstat(publish)
            _require_published_temp_identity(
                publish,
                publish_identity,
                label="library migration publication candidate",
            )
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

            # Re-authenticate the exact publish inode and logical state
            # immediately before touching the canonical Library pathname.
            _require_published_temp_identity(
                publish,
                publish_identity,
                label="library migration publication candidate",
            )
            if (
                _library_state_sha256(
                    publish,
                    schema_validator=self._validate_library_schema,
                )
                != publish_state
            ):
                raise Version2UpgradeError(
                    "library migration publication candidate changed"
                )
            _require_published_temp_identity(
                publish,
                publish_identity,
                label="library migration publication candidate",
            )

            self._assert_upgrade_lock()
            guard: _PublicationGuard | None = _publication_guard(
                self.layout.library_path
            )
            candidate_published = False
            preserve_guard = False
            try:
                assert guard is not None
                _require_publication_guard(guard)
                guard_state = _library_state_sha256(
                    guard.path,
                    schema_validator=self._validate_library_schema,
                )
                _require_publication_guard(guard)
                if (
                    guard_state != original_state
                    or _library_state_sha256(
                        self.layout.library_path,
                        schema_validator=self._validate_library_schema,
                    )
                    != original_state
                ):
                    raise Version2UpgradeError(
                        "tracked user data changed during library publication"
                    )
                _require_published_temp_identity(
                    publish,
                    publish_identity,
                    label="library migration publication candidate",
                )
                os.replace(publish, self.layout.library_path)
                candidate_published = True
                try:
                    # Accept success only if the canonical pathname now names
                    # the exact private inode that _sqlite_backup authenticated.
                    _require_published_temp_identity(
                        self.layout.library_path,
                        publish_identity,
                        label="library migration publication",
                    )
                    _fsync_dir(self.layout.root)
                    _require_published_temp_identity(
                        self.layout.library_path,
                        publish_identity,
                        label="library migration publication",
                    )
                    _require_publication_guard(guard)
                    guard_state = _library_state_sha256(
                        guard.path,
                        schema_validator=self._validate_library_schema,
                    )
                    _require_publication_guard(guard)
                    if guard_state != original_state:
                        # Preserve a writer that committed to the authenticated
                        # old inode after final re-authentication but before the
                        # replace. That writer's exact inode wins.
                        _require_publication_guard(guard)
                        os.replace(guard.path, self.layout.library_path)
                        guard = None
                        _fsync_dir(self.layout.root)
                        raise Version2UpgradeError(
                            "tracked user data changed during library publication"
                        )
                    if (
                        self._library_schema() != ACSDB_SCHEMA_VERSION
                        or self._tracked_state_sha256(self.layout.library_name)
                        != publish_state
                    ):
                        # The old authenticated inode remains reachable through
                        # the guard. Do not discard that recovery evidence when
                        # the new candidate becomes ambiguous after replacement.
                        preserve_guard = True
                        raise Version2UpgradeError(
                            "library migration publication verification failed"
                        )
                    self._assert_upgrade_lock()
                    return True
                except BaseException:
                    if candidate_published and guard is not None:
                        # A post-replace failure makes ownership of the canonical
                        # pathname ambiguous. Keep the exact old inode reachable;
                        # later recovery can distinguish this stale guard from
                        # active generated state by inode relationship.
                        preserve_guard = True
                    raise
            finally:
                if guard is not None and not preserve_guard:
                    _remove_publication_guard(guard)
        finally:
            if database is not None:
                close = getattr(database, "close", None)
                if callable(close):
                    close()
            for candidate, expected_identity in (
                (work, work_identity),
                (publish, publish_identity),
            ):
                # Main temporary files are removed only while their path still
                # names the exact inode created by this migration. A substituted
                # pathname may contain user-owned bytes and must be preserved.
                if candidate.exists() or candidate.is_symlink():
                    try:
                        _require_published_temp_identity(
                            candidate,
                            expected_identity,
                            label="library migration temporary",
                        )
                        assert expected_identity is not None
                        _remove_exact_regular_file(
                            candidate,
                            label="library migration temporary",
                            expected_identity=_stat_identity(expected_identity),
                        )
                    except Exception:
                        pass
                for suffix in _DB_SIDECARS:
                    path = Path(str(candidate) + suffix)
                    if path.exists() or path.is_symlink():
                        try:
                            info = _safe_stat(path, "library migration temporary")
                            if stat.S_ISREG(info.st_mode):
                                _remove_exact_regular_file(
                                    path,
                                    label="library migration temporary",
                                    expected_identity=_stat_identity(info),
                                )
                        except Exception:
                            pass

    def _verify(self, backup: Path, manifest: Mapping[str, object]) -> int:
        self._assert_upgrade_lock()
        if self.layout.settings_path.exists():
            try:
                settings_payload = _read_exact_regular_bytes(
                    self.layout.settings_path,
                    label="migrated settings readback",
                    max_bytes=_MAX_RECOVERY_JSON_BYTES,
                )
                raw = json.loads(settings_payload.decode("utf-8"))
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
                or _hash(
                    current,
                    label="preserved user-data file",
                ) != item["sha256"]
            ):
                raise Version2UpgradeError(
                    "preserved user-data file changed during upgrade"
                )
            preserved += 1
        self._assert_upgrade_lock()
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
        with _UpgradeLock(self.layout.lock_path) as upgrade_lock:
            self._active_upgrade_lock = upgrade_lock
            try:
                self._assert_upgrade_lock()
                recovered = self._recover_locked()
                self._assert_upgrade_lock()
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
                    self._assert_upgrade_lock()
                except _UpgradeLockLost as exc:
                    # Never mutate tracked data or journal under an inode we no
                    # longer own. Leave the nonterminal journal/backups intact;
                    # a later process can acquire the then-canonical lock and
                    # run normal authenticated recovery.
                    raise Version2UpgradeRecoveryError(
                        "Version 2 upgrade lock identity was lost; "
                        "automatic recovery was not attempted"
                    ) from exc
                except Exception as exc:
                    try:
                        self._assert_upgrade_lock()
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
            finally:
                self._active_upgrade_lock = None
