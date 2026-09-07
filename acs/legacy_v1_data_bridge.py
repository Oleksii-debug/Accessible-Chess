from __future__ import annotations

"""Bridge shipped Stage1/V1 data beside AccessibleChess.exe into the V2 user root.

Historical RC3 evidence proves the frozen application stored settings and the
legacy schema0 Library under ``<exe-dir>/data``. Version 2 uses the canonical
``UserDataLayout`` root instead. This module bridges only that exact topology.
It never scans for arbitrary SQLite files, never mutates the V1 source, and
never overwrites a populated V2 target.
"""

from dataclasses import dataclass
import hashlib
import json
import os
from pathlib import Path
import stat
import tempfile
from typing import Callable

from .legacy_library_migration import LegacyLibraryMigrationResult, migrate_legacy_library
from .version2_upgrade import UserDataLayout, Version2UpgradeBusy, Version2UpgradeError, _UpgradeLock


_BRIDGE_MARKER = ".v1-legacy-bridge.json"
_MARKER_SCHEMA = 1


class LegacyV1BridgeError(Version2UpgradeError):
    pass


@dataclass(frozen=True, slots=True)
class LegacyV1BridgeReport:
    status: str
    source_data_root: str
    settings_copied: bool
    library_converted: bool
    library_games: int


def _regular_file(path: Path, label: str) -> bool:
    if not path.exists() and not path.is_symlink():
        return False
    info = path.lstat()
    reparse = bool(getattr(info, "st_file_attributes", 0) & 0x400)
    if stat.S_ISLNK(info.st_mode) or reparse or not stat.S_ISREG(info.st_mode):
        raise LegacyV1BridgeError(f"{label} must be a direct regular file")
    return True


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _copy_no_clobber(source: Path, destination: Path) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    if destination.exists() or destination.is_symlink():
        if _regular_file(destination, "canonical settings") and _sha256(destination) == _sha256(source):
            return
        raise LegacyV1BridgeError("canonical settings already contain different data")
    fd, raw = tempfile.mkstemp(prefix=f".{destination.name}.", suffix=".bridge.tmp", dir=destination.parent)
    temp = Path(raw)
    try:
        with source.open("rb") as src, os.fdopen(fd, "wb") as dst:
            fd = -1
            while True:
                block = src.read(1024 * 1024)
                if not block:
                    break
                dst.write(block)
            dst.flush()
            os.fsync(dst.fileno())
        try:
            os.link(temp, destination)
        except FileExistsError as exc:
            raise LegacyV1BridgeError("canonical settings appeared during bridge") from exc
    finally:
        if fd >= 0:
            os.close(fd)
        if temp.exists():
            temp.unlink()


def _write_marker(path: Path, payload: dict[str, object]) -> None:
    if path.exists() or path.is_symlink():
        raise LegacyV1BridgeError("legacy bridge marker already exists unexpectedly")
    raw = (json.dumps(payload, ensure_ascii=False, sort_keys=True, indent=2) + "\n").encode("utf-8")
    fd, name = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=path.parent)
    temp = Path(name)
    try:
        with os.fdopen(fd, "wb") as handle:
            fd = -1
            handle.write(raw)
            handle.flush()
            os.fsync(handle.fileno())
        try:
            os.link(temp, path)
        except FileExistsError as exc:
            raise LegacyV1BridgeError("legacy bridge marker raced with another writer") from exc
    finally:
        if fd >= 0:
            os.close(fd)
        if temp.exists():
            temp.unlink()


def _read_marker(path: Path, source_root: Path) -> LegacyV1BridgeReport | None:
    if not path.exists() and not path.is_symlink():
        return None
    if not _regular_file(path, "legacy bridge marker"):
        return None
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:
        raise LegacyV1BridgeError("legacy bridge marker is unreadable") from exc
    if not isinstance(raw, dict) or raw.get("schema_version") != _MARKER_SCHEMA or raw.get("status") != "materialized":
        raise LegacyV1BridgeError("legacy bridge marker is invalid")
    if raw.get("source_data_root") != str(source_root):
        raise LegacyV1BridgeError("legacy bridge marker belongs to a different V1 source")
    games = raw.get("library_games", 0)
    if type(games) is not int or games < 0:
        raise LegacyV1BridgeError("legacy bridge marker library count is invalid")
    return LegacyV1BridgeReport("already_materialized", str(source_root), False, False, games)


def bridge_legacy_v1_data(
    executable_dir: str | Path,
    layout: UserDataLayout | None = None,
    *,
    library_converter: Callable[[str | Path, str | Path], LegacyLibraryMigrationResult] = migrate_legacy_library,
) -> LegacyV1BridgeReport:
    """Materialize exact shipped V1 data into the canonical V2 root, fail-closed.

    The caller must pass the trusted directory that contained the shipped
    ``AccessibleChess.exe``. Only its direct ``data/settings.json`` and
    ``data/library.acsdb`` children are considered. Source files stay untouched.
    All canonical-target conflicts are authenticated before the first mutation,
    so a conflicting Library cannot leave a partially copied settings file.
    """
    exe_root = Path(executable_dir)
    source_root = exe_root / "data"
    settings_source = source_root / "settings.json"
    library_source = source_root / "library.acsdb"
    has_settings = _regular_file(settings_source, "legacy settings")
    has_library = _regular_file(library_source, "legacy library")
    if not has_settings and not has_library:
        return LegacyV1BridgeReport("no_legacy_data", str(source_root), False, False, 0)

    target = UserDataLayout.from_environment() if layout is None else layout
    target.root.mkdir(parents=True, exist_ok=True)
    marker_path = target.root / _BRIDGE_MARKER

    with _UpgradeLock(target.lock_path):
        existing = _read_marker(marker_path, source_root)
        if existing is not None:
            return existing

        # Authenticate all current targets before modifying either one. A target
        # created after this preflight is still rejected by no-clobber publish.
        settings_destination_existed = target.settings_path.exists() or target.settings_path.is_symlink()
        if has_settings and settings_destination_existed:
            if not _regular_file(target.settings_path, "canonical settings") or _sha256(target.settings_path) != _sha256(settings_source):
                raise LegacyV1BridgeError("canonical settings already contain different data")
        if has_library and (target.library_path.exists() or target.library_path.is_symlink()):
            raise LegacyV1BridgeError("canonical library already exists; refusing legacy overwrite")

        settings_copied = False
        library_converted = False
        library_games = 0

        if has_settings:
            before = _sha256(settings_source)
            _copy_no_clobber(settings_source, target.settings_path)
            if _sha256(settings_source) != before:
                raise LegacyV1BridgeError("legacy settings changed during bridge")
            settings_copied = not settings_destination_existed

        if has_library:
            before = _sha256(library_source)
            try:
                result = library_converter(library_source, target.library_path)
            except (LegacyV1BridgeError, Version2UpgradeBusy):
                raise
            except Exception as exc:
                raise LegacyV1BridgeError("legacy library conversion failed") from exc
            if _sha256(library_source) != before:
                raise LegacyV1BridgeError("legacy library changed during conversion")
            library_converted = True
            library_games = result.games

        payload = {
            "schema_version": _MARKER_SCHEMA,
            "status": "materialized",
            "source_data_root": str(source_root),
            "settings_sha256": _sha256(settings_source) if has_settings else None,
            "library_sha256": _sha256(library_source) if has_library else None,
            "library_games": library_games,
        }
        _write_marker(marker_path, payload)
        return LegacyV1BridgeReport(
            "materialized",
            str(source_root),
            settings_copied,
            library_converted,
            library_games,
        )
