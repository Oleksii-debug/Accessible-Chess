from __future__ import annotations

"""Bind the packaged P0-F W2 starter Library/PGN payload to the final V2 UI.

The package qualification lineage materializes an immutable four-file W2 bundle
beside ``AccessibleChess.exe`` under ``release-content/w2-starter``. This layer
only discovers and validates that already-qualified payload and exposes explicit
user actions through the existing Library/PGN authorities. It never silently
imports sample games, never downloads content at runtime, and does not introduce
a second PGN parser, database schema or persistence authority.
"""

from collections.abc import Mapping
import hashlib
import json
import os
from pathlib import Path
import sqlite3
import stat
import sys
import tempfile

from .acsdb import ACSDB_SCHEMA_VERSION
from .full_product_ui_shell import UILanguage
from .library_import_service import LibraryImportService
from .pgn_document import PgnDocumentSession
from .pgn_workspace import PgnWorkspace
from .version2_starter_content_application import Version2StarterContentApplication


_EXPECTED_FILES = frozenset(
    {"starter_uk.pgn", "stress_uk.pgn", "sample_library.acsdb", "manifest.json"}
)
_REQUIRED_PAYLOAD_FILES = ("starter_uk.pgn", "stress_uk.pgn", "sample_library.acsdb")
_STARTER_ACTION = "library.open_packaged_starter_pgn"
_STRESS_ACTION = "library.open_packaged_stress_pgn"
_LIBRARY_ACTION = "library.import_packaged_sample_library"

_LABELS = {
    UILanguage.UA: {
        "starter": "Відкрити вбудовані 240 навчальних партій",
        "stress": "Відкрити вбудований великий PGN (1200 партій)",
        "sample_library": "Додати вбудовану стартову бібліотеку (240 партій)",
        "starter_opened": "Вбудовані навчальні партії відкрито.",
        "stress_opened": "Вбудований великий PGN відкрито.",
        "library_imported": "Вбудовану стартову бібліотеку додано. Партій: {count}.",
        "library_reused": "Вбудована стартова бібліотека вже додана. Партій: {count}.",
    },
    UILanguage.EN: {
        "starter": "Open the built-in 240-game starter PGN",
        "stress": "Open the built-in large PGN (1200 games)",
        "sample_library": "Add the built-in starter library (240 games)",
        "starter_opened": "Built-in starter games opened.",
        "stress_opened": "Built-in large PGN opened.",
        "library_imported": "Built-in starter library added. Games: {count}.",
        "library_reused": "Built-in starter library is already added. Games: {count}.",
    },
}


def _is_reparse(info: os.stat_result) -> bool:
    flag = getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400)
    return bool(getattr(info, "st_file_attributes", 0) & flag)


def _safe_directory(path: Path) -> None:
    try:
        info = path.lstat()
    except OSError as exc:
        raise RuntimeError("packaged starter content root cannot be inspected") from exc
    if stat.S_ISLNK(info.st_mode) or _is_reparse(info) or not stat.S_ISDIR(info.st_mode):
        raise RuntimeError("packaged starter content root must be a regular directory")


def _safe_file(path: Path, *, label: str) -> os.stat_result:
    try:
        info = path.lstat()
    except OSError as exc:
        raise RuntimeError(f"{label} cannot be inspected") from exc
    if stat.S_ISLNK(info.st_mode) or _is_reparse(info) or not stat.S_ISREG(info.st_mode):
        raise RuntimeError(f"{label} must be a regular non-reparse file")
    return info


def _same_file_identity(left: os.stat_result, right: os.stat_result) -> bool:
    """Compare stable file identity where the host exposes one.

    Windows/POSIX Python normally supplies ``st_dev`` and ``st_ino``. Some
    unusual filesystems may report a zero inode; in that case byte identity is
    still enforced by the manifest hash below rather than inventing an identity.
    """

    left_ino = getattr(left, "st_ino", 0)
    right_ino = getattr(right, "st_ino", 0)
    if left_ino and right_ino:
        return (getattr(left, "st_dev", None), left_ino) == (
            getattr(right, "st_dev", None),
            right_ino,
        )
    return True


def _sha256(path: Path) -> str:
    _safe_file(path, label="packaged starter content file")
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _load_manifest(root: Path) -> dict[str, object]:
    _safe_directory(root)
    try:
        entries = tuple(root.iterdir())
    except OSError as exc:
        raise RuntimeError("packaged starter content inventory cannot be read") from exc
    actual = {entry.name for entry in entries}
    if actual != _EXPECTED_FILES:
        raise RuntimeError("packaged starter content file inventory is invalid")
    for entry in entries:
        _safe_file(entry, label="packaged starter content entry")

    manifest_path = root / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    if not isinstance(manifest, dict) or manifest.get("schema_version") != 3:
        raise RuntimeError("packaged starter content manifest schema is invalid")
    if manifest.get("runtime_network_required") is not False:
        raise RuntimeError("packaged starter content must not require runtime network access")

    counts = manifest.get("counts")
    if not isinstance(counts, dict):
        raise RuntimeError("packaged starter content counts are unavailable")
    starter_count = counts.get("starter_games")
    stress_count = counts.get("stress_games")
    if type(starter_count) is not int or starter_count < 200:
        raise RuntimeError("packaged starter content has fewer than 200 starter games")
    if type(stress_count) is not int or stress_count <= starter_count:
        raise RuntimeError("packaged starter stress corpus is not larger than the starter corpus")

    source = manifest.get("starter_source")
    if not isinstance(source, dict) or source.get("license_id") != "CC0-1.0":
        raise RuntimeError("packaged starter source license is invalid")
    if source.get("selected_games") != starter_count:
        raise RuntimeError("packaged starter source count does not match the manifest")

    files = manifest.get("files")
    if not isinstance(files, dict) or set(files) != set(_REQUIRED_PAYLOAD_FILES):
        raise RuntimeError("packaged starter content payload manifest is invalid")
    for name in _REQUIRED_PAYLOAD_FILES:
        metadata = files.get(name)
        path = root / name
        info = _safe_file(path, label="packaged starter content payload")
        if not isinstance(metadata, Mapping):
            raise RuntimeError("packaged starter content file metadata is invalid")
        expected_hash = metadata.get("sha256")
        expected_bytes = metadata.get("bytes")
        if type(expected_hash) is not str or len(expected_hash) != 64:
            raise RuntimeError("packaged starter content hash metadata is invalid")
        if type(expected_bytes) is not int or expected_bytes < 1:
            raise RuntimeError("packaged starter content byte metadata is invalid")
        if info.st_size != expected_bytes or _sha256(path) != expected_hash.casefold():
            raise RuntimeError(f"packaged starter content integrity failed for {name}")
    return manifest


def _verified_payload_bytes(
    root: Path,
    manifest: Mapping[str, object],
    name: str,
    *,
    label: str,
) -> bytes:
    """Read exactly the bytes pinned by the already-validated manifest.

    Startup discovery proves the package was intact when the application was
    composed. User actions can happen much later, so never trust the pathname
    again merely because it still resolves to a regular file. Bind each action to
    one opened handle, verify the bytes actually consumed, and reject a pathname
    replacement observed before/after that read.
    """

    files = manifest.get("files")
    metadata = files.get(name) if isinstance(files, Mapping) else None
    if not isinstance(metadata, Mapping):
        raise RuntimeError(f"{label} metadata is unavailable")
    expected_hash = metadata.get("sha256")
    expected_bytes = metadata.get("bytes")
    if type(expected_hash) is not str or len(expected_hash) != 64:
        raise RuntimeError(f"{label} hash metadata is invalid")
    if type(expected_bytes) is not int or expected_bytes < 1:
        raise RuntimeError(f"{label} byte metadata is invalid")

    path = root / name
    before = _safe_file(path, label=label)
    try:
        with path.open("rb") as handle:
            opened = os.fstat(handle.fileno())
            if _is_reparse(opened) or not stat.S_ISREG(opened.st_mode):
                raise RuntimeError(f"{label} opened object is not a regular file")
            if not _same_file_identity(before, opened):
                raise RuntimeError(f"{label} changed before verified read")
            payload = handle.read(expected_bytes + 1)
            opened_after = os.fstat(handle.fileno())
    except RuntimeError:
        raise
    except OSError as exc:
        raise RuntimeError(f"{label} cannot be read") from exc

    after = _safe_file(path, label=label)
    if not _same_file_identity(opened, opened_after) or not _same_file_identity(opened, after):
        raise RuntimeError(f"{label} changed during verified read")
    if len(payload) != expected_bytes:
        raise RuntimeError(f"{label} byte length does not match the manifest")
    if hashlib.sha256(payload).hexdigest() != expected_hash.casefold():
        raise RuntimeError(f"{label} bytes do not match the manifest")
    return payload


def _default_bundle_root() -> Path:
    return Path(sys.executable).resolve().parent / "release-content" / "w2-starter"


class Version2PackagedStarterApplication(Version2StarterContentApplication):
    """Expose qualified packaged W2 content without mutating it in place."""

    def __init__(self, *args, packaged_starter_root: str | Path | None = None, **kwargs) -> None:
        explicit = packaged_starter_root is not None
        root = Path(packaged_starter_root) if explicit else _default_bundle_root()
        self._packaged_starter_root: Path | None = None
        self._packaged_starter_manifest: dict[str, object] | None = None
        if root.exists():
            self._packaged_starter_manifest = _load_manifest(root)
            self._packaged_starter_root = root
        elif explicit:
            raise RuntimeError("packaged starter content root is missing")
        super().__init__(*args, **kwargs)

    def _starter_library_actions(self) -> tuple[dict[str, object], ...]:
        if self._packaged_starter_root is None:
            return ()
        labels = _LABELS[self.shell.language]
        return (
            {"action": _STARTER_ACTION, "label": labels["starter"], "enabled": True},
            {"action": _STRESS_ACTION, "label": labels["stress"], "enabled": True},
            {"action": _LIBRARY_ACTION, "label": labels["sample_library"], "enabled": True},
        )

    def _decorate_library_snapshot(self, snapshot: Mapping[str, object]) -> dict[str, object]:
        result = dict(snapshot)
        actions = list(result.get("actions", ()))
        actions.extend(self._starter_library_actions())
        result["actions"] = tuple(actions)
        manifest = self._packaged_starter_manifest
        if manifest is not None:
            counts = manifest["counts"]
            result["packaged_starter_content"] = {
                "available": True,
                "starter_games": counts["starter_games"],
                "stress_games": counts["stress_games"],
                "network_required": False,
                "prebuilt_library": True,
            }
        return result

    def _open_packaged_pgn(self, *, stress: bool) -> dict[str, object]:
        root = self._packaged_starter_root
        manifest = self._packaged_starter_manifest
        if root is None or manifest is None:
            raise ValueError("packaged starter content is unavailable")
        name = "stress_uk.pgn" if stress else "starter_uk.pgn"
        payload = _verified_payload_bytes(root, manifest, name, label="packaged starter PGN")
        try:
            text = payload.decode("utf-8")
        except UnicodeDecodeError as exc:
            raise RuntimeError("packaged starter PGN is not valid UTF-8") from exc
        # Packaged starter files are immutable release content. Build a clean
        # canonical workspace without retaining a writable source fingerprint:
        # simply opening bundled content must not look like an unsaved edit, but
        # any later edit still requires the existing explicit Save As workflow.
        workspace = PgnWorkspace.from_text(text)
        session = PgnDocumentSession(workspace, saved_digest=workspace.content_digest)
        self.set_document(session)
        labels = _LABELS[self.shell.language]
        return {
            "kind": "status",
            "payload": {
                "announcement": labels["stress_opened" if stress else "starter_opened"],
                "focus_target": "pgn-game-list",
            },
        }

    def _packaged_sample_games(self):
        root = self._packaged_starter_root
        manifest = self._packaged_starter_manifest
        if root is None or manifest is None:
            raise ValueError("packaged starter content is unavailable")
        counts = manifest.get("counts")
        if not isinstance(counts, Mapping):
            raise RuntimeError("packaged starter content counts are unavailable")
        expected_count = counts.get("starter_games")
        if type(expected_count) is not int or expected_count < 200:
            raise RuntimeError("packaged starter Library count is invalid")

        payload = _verified_payload_bytes(
            root,
            manifest,
            "sample_library.acsdb",
            label="packaged starter Library",
        )
        with tempfile.TemporaryDirectory(prefix="accessible-chess-packaged-library-") as raw:
            snapshot = Path(raw) / "sample_library.acsdb"
            try:
                with snapshot.open("xb") as handle:
                    handle.write(payload)
                    handle.flush()
                    os.fsync(handle.fileno())
            except OSError as exc:
                raise RuntimeError("verified packaged starter Library snapshot cannot be created") from exc

            uri = snapshot.resolve(strict=True).as_uri() + "?mode=ro&immutable=1"
            connection = sqlite3.connect(uri, uri=True)
            try:
                quick = connection.execute("PRAGMA quick_check").fetchone()
                if quick is None or str(quick[0]).casefold() != "ok":
                    raise RuntimeError("packaged starter Library integrity check failed")
                schema = int(connection.execute("PRAGMA user_version").fetchone()[0])
                if schema != ACSDB_SCHEMA_VERSION:
                    raise RuntimeError("packaged starter Library schema is unsupported")
                rows = connection.execute("SELECT pgn_text FROM games ORDER BY id").fetchall()
            finally:
                connection.close()
        if len(rows) != expected_count:
            raise RuntimeError("packaged starter Library game count does not match the manifest")
        text = "\n\n".join(str(row[0]) for row in rows)
        workspace = PgnWorkspace.from_text(text)
        if workspace.game_count != expected_count:
            raise RuntimeError("packaged starter Library PGN rows are inconsistent")
        return workspace.games()

    def _import_packaged_sample_library(self) -> dict[str, object]:
        root = self._packaged_starter_root
        manifest = self._packaged_starter_manifest
        if root is None or manifest is None:
            raise ValueError("packaged starter content is unavailable")
        metadata = manifest["files"]["sample_library.acsdb"]
        if not isinstance(metadata, Mapping):
            raise RuntimeError("packaged starter Library metadata is invalid")
        source_sha256 = metadata.get("sha256")
        if type(source_sha256) is not str:
            raise RuntimeError("packaged starter Library hash is invalid")

        games = self._packaged_sample_games()
        result = LibraryImportService(self.database).import_games(
            games,
            source_name="Accessible Chess built-in starter library",
            source_format="acsdb",
            source_sha256=source_sha256,
        )
        self.shell.open_route("library")
        rendered = self.library.projection.reset_filters()
        payload = dict(rendered.payload)
        snapshot = payload.get("snapshot")
        if isinstance(snapshot, Mapping):
            payload["snapshot"] = self._decorate_library_snapshot(snapshot)
        labels = _LABELS[self.shell.language]
        payload["announcement"] = labels[
            "library_reused" if result.reused else "library_imported"
        ].format(count=result.game_count)
        return {"kind": rendered.kind, "payload": payload}

    def browser_command(self, area, command, payload=None):
        self._assert_thread()
        if area == "library" and command in {_STARTER_ACTION, _STRESS_ACTION, _LIBRARY_ACTION}:
            try:
                if payload not in (None, {}):
                    raise ValueError("packaged starter content action accepts no payload")
                if command == _LIBRARY_ACTION:
                    return self._import_packaged_sample_library()
                return self._open_packaged_pgn(stress=command == _STRESS_ACTION)
            except Exception:
                return self._error()
        return super().browser_command(area, command, payload)

    def snapshot(self) -> dict[str, object]:
        result = super().snapshot()
        library = result.get("library")
        if isinstance(library, Mapping):
            result["library"] = self._decorate_library_snapshot(library)
        return result


__all__ = ["Version2PackagedStarterApplication"]