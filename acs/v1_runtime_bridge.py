from __future__ import annotations

"""Bridge shipped Stage1/V1 executable-local user data into the V2 user root.

Stage1 RC3 stored persistent data beside the frozen executable under ``data/``.
Version 2 uses :class:`~acs.version2_upgrade.UserDataLayout`, normally
``%LOCALAPPDATA%/AccessibleChess`` on Windows.  This module is the narrow
orchestration seam between those two proven topologies.

The legacy source is never rewritten.  A durable source backup and fully
validated V2 candidates are prepared before any canonical V2 pathname is
published.  Publication is no-clobber and restartable under the existing V2
upgrade lock.  The D07 legacy Library converter remains the sole owner of
schema-0 recognition and PGN/GameTree conversion.
"""

from dataclasses import dataclass
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import secrets
import shutil
import sqlite3
import stat
from typing import Callable, Mapping

from .legacy_library_migration import (
    LegacyLibraryMigrationResult,
    migrate_legacy_library,
)
from .settings import Settings
from .version2_upgrade import (
    UserDataLayout,
    Version2UpgradeBusy,
    Version2UpgradeError,
    _UpgradeLock,
    _atomic_json,
    _fsync_dir,
    _hash,
    _library_state_sha256,
    _safe_stat,
    _sqlite_state_sha256,
    _stable_copy,
    _unique_json_object,
)


_BRIDGE_SCHEMA_VERSION = 1
_PHASES = {"prepared", "settings_published", "library_published", "committed"}
_JOURNAL_NAME = ".v1-runtime-bridge-state.json"
_COMPLETED_NAME = ".v1-runtime-bridge-completed.json"
_BACKUP_NAME_RE = re.compile(
    r"\Av1-\d{8}T\d{6}Z-[0-9a-f]{8}-legacy-runtime\Z"
)
_IMMUTABLE_RECORD_FIELDS = (
    "schema_version",
    "bridge_id",
    "backup_name",
    "legacy_root",
    "source_identities",
    "candidate_identities",
    "has_settings",
    "has_library",
    "library_result",
)


class V1RuntimeBridgeError(Version2UpgradeError):
    """Fail-closed V1 executable-local -> V2 user-root bridge failure."""


@dataclass(frozen=True, slots=True)
class V1RuntimeBridgeReport:
    status: str
    bridge_id: str
    backup_name: str
    settings_imported: bool
    library_imported: bool
    recovered: bool
    legacy_root: str
    library_result: LegacyLibraryMigrationResult | None = None


def _sha256_bytes(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def _validate_backup_name(value: object, bridge_id: object, label: str) -> str:
    if (
        not isinstance(value, str)
        or not isinstance(bridge_id, str)
        or not bridge_id
        or _BACKUP_NAME_RE.fullmatch(value) is None
        or value != f"{bridge_id}-legacy-runtime"
    ):
        raise V1RuntimeBridgeError(f"{label} is invalid")
    return value


def _require_regular(path: Path, label: str) -> os.stat_result:
    try:
        info = _safe_stat(path, label)
    except FileNotFoundError as exc:
        raise V1RuntimeBridgeError(f"{label} is unavailable") from exc
    if not stat.S_ISREG(info.st_mode):
        raise V1RuntimeBridgeError(f"{label} must be a regular file")
    return info


def _require_directory(path: Path, label: str) -> os.stat_result:
    try:
        info = _safe_stat(path, label)
    except FileNotFoundError as exc:
        raise V1RuntimeBridgeError(f"{label} is unavailable") from exc
    if not stat.S_ISDIR(info.st_mode):
        raise V1RuntimeBridgeError(f"{label} must be a directory")
    return info


def _legacy_root_from_executable(executable: str | Path) -> Path:
    if not isinstance(executable, (str, Path)):
        raise TypeError("executable must be a filesystem path")
    path = Path(executable)
    _require_regular(path, "legacy executable")
    try:
        resolved = path.resolve(strict=True)
    except OSError as exc:
        raise V1RuntimeBridgeError("legacy executable could not be resolved safely") from exc
    return resolved.parent / "data"


def _load_json(path: Path, label: str) -> dict[str, object]:
    try:
        raw = json.loads(
            path.read_text(encoding="utf-8"),
            object_pairs_hook=_unique_json_object,
        )
    except Exception as exc:
        raise V1RuntimeBridgeError(f"{label} is invalid") from exc
    if not isinstance(raw, dict):
        raise V1RuntimeBridgeError(f"{label} is invalid")
    return raw


def _legacy_sqlite_state(path: Path) -> str:
    _require_regular(path, "legacy library")
    lock = reader = None
    try:
        lock = sqlite3.connect(str(path), timeout=0.0)
        lock.execute("PRAGMA busy_timeout=0")
        lock.execute("BEGIN IMMEDIATE")
        reader = sqlite3.connect(
            path.resolve(strict=True).as_uri() + "?mode=ro",
            uri=True,
            timeout=0.0,
        )
        reader.execute("PRAGMA busy_timeout=0")
        return _sqlite_state_sha256(reader)
    except sqlite3.DatabaseError as exc:
        raise Version2UpgradeBusy("legacy library is busy or unreadable") from exc
    finally:
        if reader is not None:
            reader.close()
        if lock is not None:
            if lock.in_transaction:
                lock.rollback()
            lock.close()


def _backup_legacy_sqlite(source: Path, destination: Path) -> tuple[int, str, str]:
    """Create a consistent schema-agnostic SQLite backup and return identities."""
    _require_regular(source, "legacy library")
    destination.parent.mkdir(parents=True, exist_ok=True)
    temp = destination.with_name(f".{destination.name}.bridge-{secrets.token_hex(6)}.tmp")
    lock = reader = target = None
    try:
        lock = sqlite3.connect(str(source), timeout=0.0)
        lock.execute("PRAGMA busy_timeout=0")
        lock.execute("BEGIN IMMEDIATE")
        reader = sqlite3.connect(
            source.resolve(strict=True).as_uri() + "?mode=ro",
            uri=True,
            timeout=0.0,
        )
        reader.execute("PRAGMA busy_timeout=0")
        before_state = _sqlite_state_sha256(reader)
        target = sqlite3.connect(str(temp))
        reader.backup(target)
        target.commit()
        if _sqlite_state_sha256(target) != before_state:
            raise V1RuntimeBridgeError("legacy library backup logical state mismatch")
        target.close()
        target = None
        reader.close()
        reader = None
        if lock.in_transaction:
            lock.rollback()
        lock.close()
        lock = None
        with temp.open("r+b") as handle:
            os.fsync(handle.fileno())
        os.replace(temp, destination)
        _fsync_dir(destination.parent)
        return destination.stat().st_size, _hash(destination), before_state
    except (sqlite3.DatabaseError, OSError) as exc:
        raise V1RuntimeBridgeError("legacy library backup failed") from exc
    finally:
        if target is not None:
            target.close()
        if reader is not None:
            reader.close()
        if lock is not None:
            if lock.in_transaction:
                lock.rollback()
            lock.close()
        if temp.exists():
            try:
                temp.unlink()
            except OSError:
                pass


def _settings_candidate(source: Path, destination: Path) -> tuple[str, bytes]:
    try:
        text = source.read_text(encoding="utf-8")
        candidate = Settings(destination)
        candidate.import_json(text, persist=False)
        payload = (candidate.export_json() + "\n").encode("utf-8")
    except Exception as exc:
        raise V1RuntimeBridgeError("legacy settings cannot be migrated safely") from exc
    with destination.open("wb") as handle:
        handle.write(payload)
        handle.flush()
        os.fsync(handle.fileno())
    _fsync_dir(destination.parent)
    return _sha256_bytes(payload), payload


def _publish_no_clobber(source: Path, destination: Path, label: str) -> None:
    if destination.exists() or destination.is_symlink():
        raise V1RuntimeBridgeError(f"{label} destination already exists")
    try:
        os.link(source, destination)
    except FileExistsError as exc:
        raise V1RuntimeBridgeError(f"{label} destination was created concurrently") from exc
    except OSError as exc:
        raise V1RuntimeBridgeError(
            f"{label} cannot be published atomically on this filesystem"
        ) from exc
    _fsync_dir(destination.parent)


def _rollback_published_hardlink(source: Path, destination: Path, label: str) -> None:
    """Remove only the exact hard-link created by this bridge after failed verification."""

    try:
        if not destination.exists() and not destination.is_symlink():
            return
        # Refuse to unlink a pathname that a concurrent actor replaced after our
        # no-clobber publication.  A bridge rollback owns only its own hard-link.
        if not os.path.samefile(source, destination):
            raise V1RuntimeBridgeError(
                f"{label} publication changed before rollback"
            )
        destination.unlink()
        _fsync_dir(destination.parent)
    except V1RuntimeBridgeError:
        raise
    except OSError as exc:
        raise V1RuntimeBridgeError(f"{label} publication rollback failed") from exc


class V1RuntimeBridgeCoordinator:
    """Restartable, source-preserving bridge for the exact shipped V1 topology."""

    def __init__(
        self,
        layout: UserDataLayout,
        executable: str | Path,
        *,
        phase_hook: Callable[[str], None] | None = None,
    ) -> None:
        self.layout = layout
        self.executable = Path(executable)
        self.phase_hook = phase_hook

    @property
    def journal_path(self) -> Path:
        return self.layout.backup_root / _JOURNAL_NAME

    @property
    def completed_path(self) -> Path:
        return self.layout.backup_root / _COMPLETED_NAME

    def _notify(self, phase: str) -> None:
        if self.phase_hook is not None:
            self.phase_hook(phase)

    def _ensure_roots(self) -> None:
        self.layout.root.mkdir(parents=True, exist_ok=True)
        self.layout.backup_root.mkdir(parents=True, exist_ok=True)
        _require_directory(self.layout.root, "Version 2 user-data root")
        _require_directory(self.layout.backup_root, "Version 2 upgrade backup root")

    def _source_paths(self, legacy_root: Path) -> dict[str, Path]:
        if not legacy_root.exists() and not legacy_root.is_symlink():
            return {}
        _require_directory(legacy_root, "legacy data directory")
        result: dict[str, Path] = {}
        settings = legacy_root / self.layout.settings_name
        library = legacy_root / self.layout.library_name
        if settings.exists() or settings.is_symlink():
            _require_regular(settings, "legacy settings")
            result["settings"] = settings
        if library.exists() or library.is_symlink():
            _require_regular(library, "legacy library")
            result["library"] = library
        return result

    def _verify_manifest_binding(
        self, record: Mapping[str, object], label: str
    ) -> None:
        backup_name = _validate_backup_name(
            record.get("backup_name"), record.get("bridge_id"), label
        )
        backup = self.layout.backup_root / backup_name
        _require_directory(backup, "V1 runtime bridge backup")
        manifest_path = backup / "manifest.json"
        _require_regular(manifest_path, "V1 runtime bridge backup manifest")
        manifest = _load_json(manifest_path, "V1 runtime bridge backup manifest")
        if manifest.get("phase") != "prepared":
            raise V1RuntimeBridgeError("V1 runtime bridge backup manifest is invalid")
        if type(record.get("has_settings")) is not bool or type(record.get("has_library")) is not bool:
            raise V1RuntimeBridgeError(f"{label} is invalid")
        if record.get("library_result") is not None and not isinstance(record.get("library_result"), dict):
            raise V1RuntimeBridgeError(f"{label} is invalid")
        for key in _IMMUTABLE_RECORD_FIELDS:
            if manifest.get(key) != record.get(key):
                raise V1RuntimeBridgeError(
                    "V1 runtime bridge durable state does not match its backup manifest"
                )

    def _completed(
        self, legacy_root: Path, sources: Mapping[str, Path]
    ) -> V1RuntimeBridgeReport | None:
        if not self.completed_path.exists() and not self.completed_path.is_symlink():
            return None
        _require_regular(self.completed_path, "V1 runtime bridge completion marker")
        marker = _load_json(self.completed_path, "V1 runtime bridge completion marker")
        if marker.get("schema_version") != _BRIDGE_SCHEMA_VERSION:
            raise V1RuntimeBridgeError("V1 runtime bridge completion marker is unsupported")
        if marker.get("legacy_root") != str(legacy_root):
            raise V1RuntimeBridgeError("V1 runtime bridge completion marker belongs to another source")
        identities = marker.get("source_identities")
        if not isinstance(identities, dict):
            raise V1RuntimeBridgeError("V1 runtime bridge completion marker is invalid")
        self._verify_manifest_binding(marker, "V1 runtime bridge completion marker")

        if bool(marker.get("has_settings")):
            if not self.layout.settings_path.is_file():
                raise V1RuntimeBridgeError("completed V2 settings are missing")
            if "settings" not in sources:
                raise V1RuntimeBridgeError(
                    "legacy settings disappeared after the completed V2 migration"
                )
            expected = identities.get("settings_sha256")
            if not isinstance(expected, str) or _hash(sources["settings"]) != expected:
                raise V1RuntimeBridgeError(
                    "legacy settings changed after the completed V2 migration"
                )
        if bool(marker.get("has_library")):
            if not self.layout.library_path.is_file():
                raise V1RuntimeBridgeError("completed V2 library is missing")
            if "library" not in sources:
                raise V1RuntimeBridgeError(
                    "legacy library disappeared after the completed V2 migration"
                )
            expected = identities.get("library_state_sha256")
            if (
                not isinstance(expected, str)
                or _legacy_sqlite_state(sources["library"]) != expected
            ):
                raise V1RuntimeBridgeError(
                    "legacy library changed after the completed V2 migration"
                )

        return V1RuntimeBridgeReport(
            status="already_migrated",
            bridge_id=str(marker.get("bridge_id", "")),
            backup_name=str(marker.get("backup_name", "")),
            settings_imported=bool(marker.get("has_settings")),
            library_imported=bool(marker.get("has_library")),
            recovered=False,
            legacy_root=str(legacy_root),
            library_result=None,
        )

    def _new_journal(
        self,
        legacy_root: Path,
        sources: Mapping[str, Path],
    ) -> dict[str, object]:
        for kind, target in (
            ("settings", self.layout.settings_path),
            ("library", self.layout.library_path),
        ):
            if kind in sources and (target.exists() or target.is_symlink()):
                raise V1RuntimeBridgeError(
                    f"Version 2 {kind} already exists; legacy bridge will not overwrite it"
                )

        bridge_id = (
            datetime.now(timezone.utc).strftime("v1-%Y%m%dT%H%M%SZ-")
            + secrets.token_hex(4)
        )
        backup_name = f"{bridge_id}-legacy-runtime"
        backup = self.layout.backup_root / backup_name
        legacy_backup = backup / "legacy"
        candidates = backup / "candidates"
        legacy_backup.mkdir(parents=True)
        candidates.mkdir()
        _fsync_dir(backup)

        source_identities: dict[str, object] = {}
        candidate_identities: dict[str, object] = {}
        library_result: dict[str, object] | None = None

        try:
            if "settings" in sources:
                source = sources["settings"]
                size, digest = _stable_copy(
                    source, legacy_backup / self.layout.settings_name
                )
                source_identities["settings_size"] = size
                source_identities["settings_sha256"] = digest
                settings_digest, _ = _settings_candidate(
                    legacy_backup / self.layout.settings_name,
                    candidates / self.layout.settings_name,
                )
                candidate_identities["settings_sha256"] = settings_digest

            if "library" in sources:
                source = sources["library"]
                size, digest, state = _backup_legacy_sqlite(
                    source, legacy_backup / self.layout.library_name
                )
                source_identities["library_size"] = size
                source_identities["library_sha256"] = digest
                source_identities["library_state_sha256"] = state
                result = migrate_legacy_library(
                    legacy_backup / self.layout.library_name,
                    candidates / self.layout.library_name,
                )
                candidate_identities["library_state_sha256"] = _library_state_sha256(
                    candidates / self.layout.library_name
                )
                library_result = {
                    "legacy_rows": result.legacy_rows,
                    "sources": result.sources,
                    "games": result.games,
                    "warning_games": result.warning_games,
                    "import_attempts": result.import_attempts,
                    "schema_version": result.schema_version,
                }
        except Exception as exc:
            shutil.rmtree(backup, ignore_errors=True)
            if isinstance(exc, V1RuntimeBridgeError):
                raise
            raise V1RuntimeBridgeError(
                "legacy runtime data could not be prepared safely"
            ) from exc

        journal: dict[str, object] = {
            "schema_version": _BRIDGE_SCHEMA_VERSION,
            "bridge_id": bridge_id,
            "backup_name": backup_name,
            "legacy_root": str(legacy_root),
            "phase": "prepared",
            "source_identities": source_identities,
            "candidate_identities": candidate_identities,
            "has_settings": "settings" in sources,
            "has_library": "library" in sources,
            "library_result": library_result,
        }
        _atomic_json(backup / "manifest.json", journal)
        _atomic_json(self.journal_path, journal)
        self._notify("prepared")
        return journal

    def _journal(self) -> dict[str, object]:
        _require_regular(self.journal_path, "V1 runtime bridge journal")
        journal = _load_json(self.journal_path, "V1 runtime bridge journal")
        if journal.get("schema_version") != _BRIDGE_SCHEMA_VERSION:
            raise V1RuntimeBridgeError("V1 runtime bridge journal is unsupported")
        if journal.get("phase") not in _PHASES:
            raise V1RuntimeBridgeError("V1 runtime bridge journal phase is invalid")
        for key in ("bridge_id", "backup_name", "legacy_root"):
            if not isinstance(journal.get(key), str) or not journal[key]:
                raise V1RuntimeBridgeError("V1 runtime bridge journal is invalid")
        if not isinstance(journal.get("source_identities"), dict):
            raise V1RuntimeBridgeError("V1 runtime bridge journal is invalid")
        if not isinstance(journal.get("candidate_identities"), dict):
            raise V1RuntimeBridgeError("V1 runtime bridge journal is invalid")
        self._verify_manifest_binding(journal, "V1 runtime bridge journal")
        return journal

    def _verify_sources(
        self,
        legacy_root: Path,
        sources: Mapping[str, Path],
        journal: Mapping[str, object],
    ) -> None:
        if journal.get("legacy_root") != str(legacy_root):
            raise V1RuntimeBridgeError("interrupted bridge belongs to another legacy root")
        identities = journal["source_identities"]
        assert isinstance(identities, dict)
        if bool(journal.get("has_settings")):
            if "settings" not in sources:
                raise V1RuntimeBridgeError("legacy settings disappeared during migration")
            expected = identities.get("settings_sha256")
            if not isinstance(expected, str) or _hash(sources["settings"]) != expected:
                raise V1RuntimeBridgeError("legacy settings changed during migration")
        if bool(journal.get("has_library")):
            if "library" not in sources:
                raise V1RuntimeBridgeError("legacy library disappeared during migration")
            expected = identities.get("library_state_sha256")
            if (
                not isinstance(expected, str)
                or _legacy_sqlite_state(sources["library"]) != expected
            ):
                raise V1RuntimeBridgeError("legacy library changed during migration")

    def _candidate_paths(self, journal: Mapping[str, object]) -> tuple[Path, Path]:
        backup = self.layout.backup_root / str(journal["backup_name"])
        _require_directory(backup, "V1 runtime bridge backup")
        candidates = backup / "candidates"
        _require_directory(candidates, "V1 runtime bridge candidates")
        return (
            candidates / self.layout.settings_name,
            candidates / self.layout.library_name,
        )

    def _advance(
        self,
        journal: dict[str, object],
        legacy_root: Path,
        sources: Mapping[str, Path],
    ) -> V1RuntimeBridgeReport:
        self._verify_sources(legacy_root, sources, journal)
        settings_candidate, library_candidate = self._candidate_paths(journal)
        candidate_ids = journal["candidate_identities"]
        assert isinstance(candidate_ids, dict)

        recovered = journal.get("phase") != "prepared"
        has_settings = bool(journal.get("has_settings"))
        has_library = bool(journal.get("has_library"))

        if has_settings:
            expected = candidate_ids.get("settings_sha256")
            if not isinstance(expected, str):
                raise V1RuntimeBridgeError("settings candidate identity is invalid")
            _require_regular(settings_candidate, "V2 settings candidate")
            if _hash(settings_candidate) != expected:
                raise V1RuntimeBridgeError("V2 settings candidate changed")
            if self.layout.settings_path.exists() or self.layout.settings_path.is_symlink():
                _require_regular(self.layout.settings_path, "published V2 settings")
                if _hash(self.layout.settings_path) != expected:
                    raise V1RuntimeBridgeError(
                        "Version 2 settings collision during legacy bridge"
                    )
            else:
                _publish_no_clobber(
                    settings_candidate, self.layout.settings_path, "Version 2 settings"
                )
                try:
                    published_settings_ok = _hash(self.layout.settings_path) == expected
                except Exception as exc:
                    _rollback_published_hardlink(
                        settings_candidate, self.layout.settings_path, "Version 2 settings"
                    )
                    raise V1RuntimeBridgeError(
                        "published V2 settings verification failed"
                    ) from exc
                if not published_settings_ok:
                    _rollback_published_hardlink(
                        settings_candidate, self.layout.settings_path, "Version 2 settings"
                    )
                    raise V1RuntimeBridgeError("published V2 settings verification failed")
            if journal.get("phase") == "prepared":
                journal["phase"] = "settings_published"
                _atomic_json(self.journal_path, journal)
                self._notify("settings-published")

        self._verify_sources(legacy_root, sources, journal)

        if has_library:
            expected = candidate_ids.get("library_state_sha256")
            if not isinstance(expected, str):
                raise V1RuntimeBridgeError("library candidate identity is invalid")
            _require_regular(library_candidate, "V2 library candidate")
            if _library_state_sha256(library_candidate) != expected:
                raise V1RuntimeBridgeError("V2 library candidate changed")
            if self.layout.library_path.exists() or self.layout.library_path.is_symlink():
                _require_regular(self.layout.library_path, "published V2 library")
                if _library_state_sha256(self.layout.library_path) != expected:
                    raise V1RuntimeBridgeError(
                        "Version 2 library collision during legacy bridge"
                    )
            else:
                _publish_no_clobber(
                    library_candidate, self.layout.library_path, "Version 2 library"
                )
                try:
                    published_library_ok = (
                        _library_state_sha256(self.layout.library_path) == expected
                    )
                except Exception as exc:
                    _rollback_published_hardlink(
                        library_candidate, self.layout.library_path, "Version 2 library"
                    )
                    raise V1RuntimeBridgeError(
                        "published V2 library verification failed"
                    ) from exc
                if not published_library_ok:
                    _rollback_published_hardlink(
                        library_candidate, self.layout.library_path, "Version 2 library"
                    )
                    raise V1RuntimeBridgeError("published V2 library verification failed")
            if journal.get("phase") in {"prepared", "settings_published"}:
                journal["phase"] = "library_published"
                _atomic_json(self.journal_path, journal)
                self._notify("library-published")

        self._verify_sources(legacy_root, sources, journal)
        journal["phase"] = "committed"
        _atomic_json(self.journal_path, journal)
        marker = dict(journal)
        _atomic_json(self.completed_path, marker)
        self._notify("committed")
        try:
            self.journal_path.unlink()
            _fsync_dir(self.layout.backup_root)
        except OSError as exc:
            raise V1RuntimeBridgeError(
                "V1 runtime bridge committed but journal cleanup failed"
            ) from exc

        raw_result = journal.get("library_result")
        result: LegacyLibraryMigrationResult | None = None
        if isinstance(raw_result, dict):
            try:
                result = LegacyLibraryMigrationResult(
                    legacy_rows=int(raw_result["legacy_rows"]),
                    sources=int(raw_result["sources"]),
                    games=int(raw_result["games"]),
                    warning_games=int(raw_result["warning_games"]),
                    import_attempts=int(raw_result["import_attempts"]),
                    schema_version=int(raw_result["schema_version"]),
                )
            except Exception as exc:
                raise V1RuntimeBridgeError("library result evidence is invalid") from exc

        return V1RuntimeBridgeReport(
            status="migrated",
            bridge_id=str(journal["bridge_id"]),
            backup_name=str(journal["backup_name"]),
            settings_imported=has_settings,
            library_imported=has_library,
            recovered=recovered,
            legacy_root=str(legacy_root),
            library_result=result,
        )

    def run(self) -> V1RuntimeBridgeReport:
        legacy_root = _legacy_root_from_executable(self.executable)
        self._ensure_roots()
        with _UpgradeLock(self.layout.lock_path):
            sources = self._source_paths(legacy_root)
            if self.journal_path.exists() or self.journal_path.is_symlink():
                journal = self._journal()
                return self._advance(journal, legacy_root, sources)
            completed = self._completed(legacy_root, sources)
            if completed is not None:
                return completed
            if not sources:
                return V1RuntimeBridgeReport(
                    status="no_legacy_data",
                    bridge_id="",
                    backup_name="",
                    settings_imported=False,
                    library_imported=False,
                    recovered=False,
                    legacy_root=str(legacy_root),
                    library_result=None,
                )
            journal = self._new_journal(legacy_root, sources)
            return self._advance(journal, legacy_root, sources)