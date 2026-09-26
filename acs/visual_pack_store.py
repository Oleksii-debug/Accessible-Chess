from __future__ import annotations

"""Fail-closed local storage for provider-neutral visual asset packs."""

from dataclasses import dataclass
import base64
import hashlib
import json
import os
from pathlib import Path
import shutil
import stat
import tempfile
from typing import Any, Mapping

from .visual_preferences import (
    BoardVisualPreferences,
    VisualPackKind,
    VisualPackManifest,
    stable_id,
    stable_version,
)

MAX_VISUAL_MANIFEST_BYTES = 64 * 1024
MAX_VISUAL_ASSET_BYTES = 4 * 1024 * 1024
MAX_VISUAL_PACK_BYTES = 24 * 1024 * 1024
MAX_WEBVIEW_VISUAL_ASSET_BYTES = 256 * 1024
_BUILT_IN_ID = "classic"
_MANIFEST_NAME = "manifest.json"


class VisualPackStoreError(ValueError):
    pass


@dataclass(frozen=True, slots=True)
class VisualPackCatalogEntry:
    pack_id: str
    version: str
    kind: VisualPackKind
    title: str
    license_id: str
    author: str
    provenance: str
    compatible: bool
    usable: bool
    latest_installed: bool
    reason: str = ""


@dataclass(frozen=True, slots=True)
class EffectiveVisualPreferences:
    requested: BoardVisualPreferences
    effective_board_theme_id: str
    effective_piece_theme_id: str
    board_fallback_used: bool
    piece_fallback_used: bool


def _duplicates(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for key, value in pairs:
        if key in out:
            raise VisualPackStoreError(f"duplicate JSON key: {key}")
        out[key] = value
    return out


def _canonical_json(payload: Mapping[str, object]) -> bytes:
    try:
        return (
            json.dumps(
                payload,
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
                allow_nan=False,
            )
            + "\n"
        ).encode("utf-8")
    except (TypeError, ValueError, UnicodeEncodeError) as exc:
        raise VisualPackStoreError(
            "visual pack metadata cannot be serialized"
        ) from exc


def _decode_json(data: bytes, label: str) -> Mapping[str, object]:
    if len(data) > MAX_VISUAL_MANIFEST_BYTES:
        raise VisualPackStoreError(f"{label} exceeds the resource limit")

    def reject_constant(_: str):
        raise VisualPackStoreError(f"{label} contains non-finite JSON")

    try:
        value = json.loads(
            data.decode("utf-8"),
            object_pairs_hook=_duplicates,
            parse_constant=reject_constant,
        )
    except (UnicodeDecodeError, json.JSONDecodeError, RecursionError) as exc:
        raise VisualPackStoreError(f"{label} is invalid JSON") from exc
    if not isinstance(value, Mapping) or any(
        type(key) is not str for key in value
    ):
        raise VisualPackStoreError(f"{label} must be a JSON object")
    return value


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _image_mime(path: str, data: bytes) -> str:
    suffix = Path(path).suffix.lower()
    if suffix == ".png":
        if not data.startswith(b"\x89PNG\r\n\x1a\n"):
            raise VisualPackStoreError("visual PNG asset has an invalid signature")
        return "image/png"
    if suffix in {".jpg", ".jpeg"}:
        if not data.startswith(b"\xff\xd8\xff"):
            raise VisualPackStoreError("visual JPEG asset has an invalid signature")
        return "image/jpeg"
    if suffix == ".webp":
        if len(data) < 12 or data[:4] != b"RIFF" or data[8:12] != b"WEBP":
            raise VisualPackStoreError("visual WebP asset has an invalid signature")
        return "image/webp"
    raise VisualPackStoreError("visual asset type is not renderable")


def _reparse(metadata: os.stat_result) -> bool:
    flag = getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0)
    return bool(
        flag
        and getattr(metadata, "st_file_attributes", 0) & flag
    )


def _real_dir(path: Path, label: str) -> None:
    try:
        metadata = path.lstat()
    except FileNotFoundError as exc:
        raise VisualPackStoreError(f"{label} is unavailable") from exc
    if (
        stat.S_ISLNK(metadata.st_mode)
        or _reparse(metadata)
        or not stat.S_ISDIR(metadata.st_mode)
    ):
        raise VisualPackStoreError(f"{label} is not a real directory")


def _regular(path: Path, label: str) -> os.stat_result:
    try:
        metadata = path.lstat()
    except FileNotFoundError as exc:
        raise VisualPackStoreError(f"{label} is missing") from exc
    if (
        stat.S_ISLNK(metadata.st_mode)
        or _reparse(metadata)
        or not stat.S_ISREG(metadata.st_mode)
    ):
        raise VisualPackStoreError(f"{label} is not a regular file")
    return metadata


def _version_key(value: str) -> tuple[int, int, int, int, str]:
    core, separator, prerelease = stable_version(value).partition("-")
    major, minor, patch = (int(item) for item in core.split("."))
    return (
        major,
        minor,
        patch,
        0 if separator else 1,
        prerelease,
    )


class VisualPackStore:
    """Versioned visual-pack catalog with atomic local publication."""

    def __init__(self, root: str | Path) -> None:
        if not isinstance(root, (str, Path)):
            raise TypeError(
                "visual pack root must be a filesystem path"
            )
        self.root = Path(root).expanduser()
        if str(self.root) in {"", "."}:
            raise ValueError(
                "visual pack root must identify a dedicated directory"
            )

    @staticmethod
    def _kind(value: VisualPackKind | str) -> VisualPackKind:
        if isinstance(value, VisualPackKind):
            return value
        if type(value) is not str:
            raise TypeError(
                "visual pack kind must be text or VisualPackKind"
            )
        try:
            return VisualPackKind(value)
        except ValueError as exc:
            raise ValueError(
                "unsupported visual pack kind"
            ) from exc

    def _path(
        self,
        kind: VisualPackKind,
        pack_id: str,
        version: str,
    ) -> Path:
        return (
            self.root
            / kind.value
            / stable_id(pack_id, "pack_id")
            / stable_version(version)
        )

    def _parent(
        self,
        kind: VisualPackKind,
        pack_id: str,
    ) -> Path:
        identity = stable_id(pack_id, "pack_id")
        self.root.mkdir(parents=True, exist_ok=True)
        _real_dir(self.root, "visual pack root")
        kind_root = self.root / kind.value
        kind_root.mkdir(exist_ok=True)
        _real_dir(kind_root, "visual pack kind directory")
        parent = kind_root / identity
        parent.mkdir(exist_ok=True)
        _real_dir(parent, "visual pack identity directory")
        return parent

    @staticmethod
    def _payloads(
        manifest: VisualPackManifest,
        payloads: Mapping[str, bytes],
    ) -> dict[str, bytes]:
        if not isinstance(payloads, Mapping) or any(
            type(key) is not str for key in payloads
        ):
            raise TypeError(
                "visual pack payloads must be a path-to-bytes mapping"
            )
        expected = {
            spec.path
            for spec in manifest.assets.values()
        }
        if set(payloads) != expected:
            raise VisualPackStoreError(
                "visual pack payload paths do not match the manifest"
            )
        by_path = {
            spec.path: spec
            for spec in manifest.assets.values()
        }
        out: dict[str, bytes] = {}
        total = 0
        for path in sorted(payloads):
            data = payloads[path]
            if type(data) is not bytes:
                raise TypeError(
                    "visual pack payload must be immutable bytes"
                )
            if len(data) > MAX_VISUAL_ASSET_BYTES:
                raise VisualPackStoreError(
                    "visual pack asset exceeds the resource limit"
                )
            total += len(data)
            if total > MAX_VISUAL_PACK_BYTES:
                raise VisualPackStoreError(
                    "visual pack exceeds the resource limit"
                )
            if _sha256(data) != by_path[path].sha256:
                raise VisualPackStoreError(
                    "visual pack asset checksum mismatch"
                )
            _image_mime(path, data)
            out[path] = data
        return out

    @staticmethod
    def _write(path: Path, data: bytes) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("xb") as handle:
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())

    def install(
        self,
        manifest: VisualPackManifest,
        payloads: Mapping[str, bytes],
    ) -> Path:
        if not isinstance(manifest, VisualPackManifest):
            raise TypeError(
                "manifest must be VisualPackManifest"
            )
        if manifest.pack_id == _BUILT_IN_ID:
            raise VisualPackStoreError(
                "the built-in visual pack id is reserved"
            )
        if not manifest.compatible:
            raise VisualPackStoreError(
                "visual pack is incompatible with this product"
            )
        checked = self._payloads(manifest, payloads)
        parent = self._parent(
            manifest.kind,
            manifest.pack_id,
        )
        destination = (
            parent
            / stable_version(manifest.version)
        )

        if destination.exists():
            existing = self.load_manifest(
                manifest.kind,
                manifest.pack_id,
                manifest.version,
            )
            if (
                existing.as_dict() == manifest.as_dict()
                and self.verify(existing)
            ):
                return destination
            raise VisualPackStoreError(
                "visual pack version already exists with different content"
            )

        staging = Path(
            tempfile.mkdtemp(
                prefix=f".{manifest.pack_id}-{manifest.version}-",
                dir=str(parent),
            )
        )
        try:
            for relative, data in checked.items():
                self._write(staging / relative, data)
            manifest_data = _canonical_json(
                manifest.as_dict()
            )
            if len(manifest_data) > MAX_VISUAL_MANIFEST_BYTES:
                raise VisualPackStoreError(
                    "visual pack manifest exceeds the resource limit"
                )
            self._write(
                staging / _MANIFEST_NAME,
                manifest_data,
            )
            try:
                os.replace(staging, destination)
            except OSError as exc:
                if destination.exists():
                    raise VisualPackStoreError(
                        "visual pack install lost an atomic publication race"
                    ) from exc
                raise VisualPackStoreError(
                    "visual pack could not be published atomically"
                ) from exc
            staging = Path()
            return destination
        finally:
            if (
                str(staging) not in {"", "."}
                and staging.exists()
            ):
                shutil.rmtree(
                    staging,
                    ignore_errors=True,
                )

    def load_manifest(
        self,
        kind: VisualPackKind | str,
        pack_id: str,
        version: str,
    ) -> VisualPackManifest:
        selected = self._kind(kind)
        version = stable_version(version)
        destination = self._path(
            selected,
            pack_id,
            version,
        )
        _real_dir(
            destination,
            "visual pack directory",
        )
        manifest_path = destination / _MANIFEST_NAME
        if (
            _regular(
                manifest_path,
                "visual pack manifest",
            ).st_size
            > MAX_VISUAL_MANIFEST_BYTES
        ):
            raise VisualPackStoreError(
                "visual pack manifest exceeds the resource limit"
            )
        try:
            payload = _decode_json(
                manifest_path.read_bytes(),
                "visual pack manifest",
            )
            manifest = VisualPackManifest.from_dict(
                payload
            )
        except OSError as exc:
            raise VisualPackStoreError(
                "visual pack manifest could not be read"
            ) from exc
        except (TypeError, ValueError) as exc:
            raise VisualPackStoreError(
                "visual pack manifest is invalid"
            ) from exc
        if (
            manifest.kind is not selected
            or manifest.pack_id
            != stable_id(pack_id, "pack_id")
            or manifest.version != version
        ):
            raise VisualPackStoreError(
                "visual pack path identity does not match its manifest"
            )
        return manifest

    @staticmethod
    def _topology(
        destination: Path,
        manifest: VisualPackManifest,
    ) -> None:
        expected_files = {
            _MANIFEST_NAME,
            *(
                spec.path
                for spec in manifest.assets.values()
            ),
        }
        expected_dirs: set[str] = set()
        for relative in expected_files:
            parts = Path(relative).parts[:-1]
            for index in range(1, len(parts) + 1):
                expected_dirs.add(
                    Path(*parts[:index]).as_posix()
                )

        files_seen: set[str] = set()
        dirs_seen: set[str] = set()
        for current, dirs, files in os.walk(
            destination,
            topdown=True,
            followlinks=False,
        ):
            current_path = Path(current)
            for name in dirs:
                child = current_path / name
                _real_dir(
                    child,
                    "visual pack directory",
                )
                dirs_seen.add(
                    child.relative_to(
                        destination
                    ).as_posix()
                )
            for name in files:
                child = current_path / name
                _regular(
                    child,
                    "visual pack file",
                )
                files_seen.add(
                    child.relative_to(
                        destination
                    ).as_posix()
                )
        if (
            files_seen != expected_files
            or dirs_seen != expected_dirs
        ):
            raise VisualPackStoreError(
                "visual pack contains undeclared filesystem content"
            )

    def verify(
        self,
        manifest: VisualPackManifest,
    ) -> bool:
        destination = self._path(
            manifest.kind,
            manifest.pack_id,
            manifest.version,
        )
        _real_dir(
            destination,
            "visual pack directory",
        )
        self._topology(
            destination,
            manifest,
        )
        for spec in manifest.assets.values():
            path = destination / spec.path
            if (
                _regular(
                    path,
                    "visual pack asset",
                ).st_size
                > MAX_VISUAL_ASSET_BYTES
            ):
                raise VisualPackStoreError(
                    "visual pack asset exceeds the resource limit"
                )
            try:
                data = path.read_bytes()
            except OSError as exc:
                raise VisualPackStoreError(
                    "visual pack asset could not be read"
                ) from exc
            if _sha256(data) != spec.sha256:
                raise VisualPackStoreError(
                    "visual pack asset checksum mismatch"
                )
        return True

    def versions(
        self,
        kind: VisualPackKind | str,
        pack_id: str,
    ) -> tuple[str, ...]:
        selected = self._kind(kind)
        parent = (
            self.root
            / selected.value
            / stable_id(pack_id, "pack_id")
        )
        if not parent.exists():
            return ()
        _real_dir(
            parent,
            "visual pack identity directory",
        )
        result: list[str] = []
        for child in parent.iterdir():
            try:
                _real_dir(
                    child,
                    "visual pack version directory",
                )
                manifest = self.load_manifest(
                    selected,
                    pack_id,
                    child.name,
                )
                if (
                    manifest.compatible
                    and self.verify(manifest)
                ):
                    result.append(
                        manifest.version
                    )
            except (
                OSError,
                TypeError,
                ValueError,
                VisualPackStoreError,
            ):
                continue
        return tuple(
            sorted(
                result,
                key=_version_key,
            )
        )

    def latest_usable_manifest(
        self,
        kind: VisualPackKind | str,
        pack_id: str,
    ) -> VisualPackManifest | None:
        versions = self.versions(
            kind,
            pack_id,
        )
        if not versions:
            return None
        return self.load_manifest(
            self._kind(kind),
            pack_id,
            versions[-1],
        )

    def catalog(
        self,
    ) -> tuple[VisualPackCatalogEntry, ...]:
        entries = [
            VisualPackCatalogEntry(
                _BUILT_IN_ID,
                "0.0.0",
                kind,
                "Built-in classic",
                "Project",
                "Accessible Chess",
                "Bundled with Accessible Chess",
                True,
                True,
                True,
            )
            for kind in (
                VisualPackKind.BOARD,
                VisualPackKind.PIECES,
            )
        ]
        if not self.root.exists():
            return tuple(entries)
        _real_dir(
            self.root,
            "visual pack root",
        )
        for kind in (
            VisualPackKind.BOARD,
            VisualPackKind.PIECES,
        ):
            kind_root = (
                self.root / kind.value
            )
            if not kind_root.exists():
                continue
            try:
                _real_dir(
                    kind_root,
                    "visual pack kind directory",
                )
            except VisualPackStoreError:
                continue
            for identity in sorted(
                kind_root.iterdir(),
                key=lambda item: item.name.casefold(),
            ):
                try:
                    pack_id = stable_id(
                        identity.name,
                        "pack_id",
                    )
                    _real_dir(
                        identity,
                        "visual pack identity directory",
                    )
                except (
                    TypeError,
                    ValueError,
                    VisualPackStoreError,
                ):
                    continue
                usable_versions = self.versions(
                    kind,
                    pack_id,
                )
                latest = (
                    usable_versions[-1]
                    if usable_versions
                    else None
                )
                for version_dir in sorted(
                    identity.iterdir(),
                    key=lambda item: item.name.casefold(),
                ):
                    try:
                        version = stable_version(
                            version_dir.name
                        )
                        manifest = self.load_manifest(
                            kind,
                            pack_id,
                            version,
                        )
                        compatible = (
                            manifest.compatible
                        )
                        usable = False
                        reason = "incompatible" if not compatible else "damaged"
                        if compatible:
                            try:
                                usable = self.verify(manifest)
                            except VisualPackStoreError:
                                usable = False
                            else:
                                reason = ""
                        entries.append(
                            VisualPackCatalogEntry(
                                manifest.pack_id,
                                manifest.version,
                                manifest.kind,
                                manifest.title,
                                manifest.license_id,
                                manifest.author,
                                manifest.provenance,
                                compatible,
                                usable,
                                (
                                    usable
                                    and manifest.version
                                    == latest
                                ),
                                reason,
                            )
                        )
                    except (
                        OSError,
                        TypeError,
                        ValueError,
                        VisualPackStoreError,
                    ):
                        continue
        return tuple(entries)

    def resolve_asset(
        self,
        kind: VisualPackKind | str,
        pack_id: str,
        asset_id: str,
    ) -> Path | None:
        if (
            stable_id(
                pack_id,
                "pack_id",
            )
            == _BUILT_IN_ID
        ):
            return None
        manifest = self.latest_usable_manifest(
            kind,
            pack_id,
        )
        if manifest is None:
            return None
        spec = manifest.assets.get(
            stable_id(
                asset_id,
                "visual asset id",
            )
        )
        if spec is None:
            return None
        path = (
            self._path(
                manifest.kind,
                manifest.pack_id,
                manifest.version,
            )
            / spec.path
        )
        try:
            if (
                _regular(
                    path,
                    "visual pack asset",
                ).st_size
                > MAX_VISUAL_ASSET_BYTES
            ):
                return None
            if (
                _sha256(path.read_bytes())
                != spec.sha256
            ):
                return None
        except (
            OSError,
            VisualPackStoreError,
        ):
            return None
        return path

    def resolve_asset_data_url(
        self,
        kind: VisualPackKind | str,
        pack_id: str,
        asset_id: str,
    ) -> str | None:
        """Return one verified bounded raster asset as a WebView-safe data URL."""

        path = self.resolve_asset(kind, pack_id, asset_id)
        if path is None:
            return None
        try:
            metadata = _regular(path, "visual pack asset")
            if metadata.st_size > MAX_WEBVIEW_VISUAL_ASSET_BYTES:
                return None
            data = path.read_bytes()
            mime = _image_mime(path.as_posix(), data)
        except (OSError, VisualPackStoreError):
            return None
        return f"data:{mime};base64,{base64.b64encode(data).decode('ascii')}"

    def effective_preferences(
        self,
        preferences: BoardVisualPreferences,
    ) -> EffectiveVisualPreferences:
        if not isinstance(
            preferences,
            BoardVisualPreferences,
        ):
            raise TypeError(
                "preferences must be BoardVisualPreferences"
            )
        board = preferences.board_theme_id
        pieces = preferences.piece_theme_id
        board_ok = (
            board == _BUILT_IN_ID
            or self.latest_usable_manifest(
                VisualPackKind.BOARD,
                board,
            )
            is not None
        )
        pieces_ok = (
            pieces == _BUILT_IN_ID
            or self.latest_usable_manifest(
                VisualPackKind.PIECES,
                pieces,
            )
            is not None
        )
        effective_board = (
            board
            if board_ok
            else _BUILT_IN_ID
        )
        effective_pieces = (
            pieces
            if pieces_ok
            else _BUILT_IN_ID
        )
        return EffectiveVisualPreferences(
            preferences,
            effective_board,
            effective_pieces,
            effective_board != board,
            effective_pieces != pieces,
        )

    def uninstall(
        self,
        kind: VisualPackKind | str,
        pack_id: str,
        version: str,
    ) -> bool:
        selected = self._kind(kind)
        identity = stable_id(
            pack_id,
            "pack_id",
        )
        version = stable_version(
            version
        )
        if identity == _BUILT_IN_ID:
            raise VisualPackStoreError(
                "the built-in visual pack cannot be uninstalled"
            )
        destination = self._path(
            selected,
            identity,
            version,
        )
        if not destination.exists():
            return False
        # Removal must remain available for a damaged installed pack. The
        # validated kind/id/version path is authoritative for deletion; requiring
        # a parseable manifest or good asset digest here would make corruption
        # impossible to recover through the store. Refuse only non-real package
        # roots, then remove exactly that bounded version directory.
        _real_dir(
            destination,
            "visual pack directory",
        )
        try:
            shutil.rmtree(
                destination
            )
        except OSError as exc:
            raise VisualPackStoreError(
                "visual pack could not be uninstalled"
            ) from exc
        return True


class VisualPreferencesStore:
    """Atomic persistence for presentation-only visual preferences."""

    def __init__(
        self,
        path: str | Path,
    ) -> None:
        if not isinstance(
            path,
            (str, Path),
        ):
            raise TypeError(
                "visual preference path must be a filesystem path"
            )
        self.path = Path(
            path
        ).expanduser()
        if str(self.path) in {"", "."}:
            raise ValueError(
                "visual preference path must identify a file"
            )

    def load(
        self,
    ) -> BoardVisualPreferences | None:
        if not self.path.exists():
            return None
        if (
            _regular(
                self.path,
                "visual preference file",
            ).st_size
            > MAX_VISUAL_MANIFEST_BYTES
        ):
            raise VisualPackStoreError(
                "visual preference file exceeds the resource limit"
            )
        try:
            payload = _decode_json(
                self.path.read_bytes(),
                "visual preference file",
            )
        except OSError as exc:
            raise VisualPackStoreError(
                "visual preference file could not be read"
            ) from exc
        if set(payload) != {
            "schema_version",
            "preferences",
        }:
            raise VisualPackStoreError(
                "visual preference envelope fields are invalid"
            )
        if (
            type(
                payload["schema_version"]
            )
            is not int
            or payload["schema_version"]
            != 1
        ):
            raise VisualPackStoreError(
                "unsupported visual preference schema_version"
            )
        raw = payload[
            "preferences"
        ]
        if not isinstance(
            raw,
            Mapping,
        ):
            raise VisualPackStoreError(
                "visual preference payload must be an object"
            )
        try:
            return (
                BoardVisualPreferences.from_dict(
                    raw
                )
            )
        except (
            TypeError,
            ValueError,
        ) as exc:
            raise VisualPackStoreError(
                "visual preferences are invalid"
            ) from exc

    def load_or_default(
        self,
    ) -> BoardVisualPreferences:
        try:
            return (
                self.load()
                or BoardVisualPreferences()
            )
        except VisualPackStoreError:
            return BoardVisualPreferences()

    def save(
        self,
        preferences: BoardVisualPreferences,
    ) -> None:
        if not isinstance(
            preferences,
            BoardVisualPreferences,
        ):
            raise TypeError(
                "preferences must be BoardVisualPreferences"
            )
        data = _canonical_json(
            {
                "schema_version": 1,
                "preferences": (
                    preferences.as_dict()
                ),
            }
        )
        self.path.parent.mkdir(
            parents=True,
            exist_ok=True,
        )
        fd, raw_path = tempfile.mkstemp(
            prefix=f".{self.path.name}.",
            suffix=".tmp",
            dir=str(
                self.path.parent
            ),
        )
        temporary = Path(
            raw_path
        )
        try:
            with os.fdopen(
                fd,
                "wb",
            ) as handle:
                handle.write(
                    data
                )
                handle.flush()
                os.fsync(
                    handle.fileno()
                )
            os.replace(
                temporary,
                self.path,
            )
            temporary = Path()
        except OSError as exc:
            raise VisualPackStoreError(
                "visual preferences could not be saved atomically"
            ) from exc
        finally:
            if (
                str(temporary)
                not in {"", "."}
                and temporary.exists()
            ):
                temporary.unlink()
