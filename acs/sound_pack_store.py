from __future__ import annotations

"""Fail-closed local persistence for downloaded sound packs.

SoundPackManager remains provider-neutral. This adapter treats
DownloadedSoundPack.payload_ref as a staging directory and independently proves
its exact filesystem topology, sizes, media signatures and SHA-256 digests before
publishing a version. A version is immutable after publication. Updating a pack
publishes a new version directory first and only then atomically replaces a tiny
active-version pointer.
"""

from contextlib import contextmanager
from dataclasses import dataclass
import errno
import hashlib
import json
import os
from pathlib import Path
import stat
import tempfile
import threading
from typing import Iterator, Mapping

from .sound_pack_catalog import (
    DEFAULT_MAX_SOUND_PACK_BYTES,
    DownloadedSoundPack,
    SoundAssetDigest,
    SoundPackInstalledAudit,
    SoundPackRightsEvidence,
)
from .sound_profiles import (
    SoundPackManifest,
    _safe_audio_path,
    _semantic_version_key,
    _stable_id,
    _stable_version,
)


SOUND_PACK_STORE_SCHEMA_VERSION = 1
SOUND_PACK_INTEGRITY_SCHEMA_VERSION = 2
_MANIFEST_NAME = "manifest.json"
_INTEGRITY_NAME = "integrity.json"
_RIGHTS_NAME = "rights.json"
_ACTIVE_NAME = "active.json"
_MAX_METADATA_BYTES = 128 * 1024
_MAX_SOUND_PACK_TREE_DIRECTORIES = 8192
_MAX_SOUND_PACK_INVENTORY_ENTRIES = 512
_MAX_SOUND_PACK_VERSION_ENTRIES = 256

_PROCESS_MUTATION_LOCKS_GUARD = threading.Lock()
_PROCESS_MUTATION_LOCKS: dict[str, threading.RLock] = {}


def _process_mutation_lock_for(path: Path) -> threading.RLock:
    key = os.path.normcase(os.path.abspath(os.fspath(path)))
    with _PROCESS_MUTATION_LOCKS_GUARD:
        lock = _PROCESS_MUTATION_LOCKS.get(key)
        if lock is None:
            lock = threading.RLock()
            _PROCESS_MUTATION_LOCKS[key] = lock
        return lock


class SoundPackStoreError(ValueError):
    """Stable local sound-pack storage failure."""


@dataclass(frozen=True, slots=True)
class InstalledSoundPack:
    manifest: SoundPackManifest
    version_dir: Path
    digests: Mapping[str, SoundAssetDigest]
    rights_evidence: SoundPackRightsEvidence | None


@dataclass(frozen=True, slots=True)
class SoundPackAssetSnapshot:
    pack_id: str
    version: str
    sound_id: str
    relative_path: str
    content: bytes


def _is_reparse_point(metadata: os.stat_result) -> bool:
    flag = getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0)
    attributes = getattr(metadata, "st_file_attributes", 0)
    return bool(flag and attributes & flag)


def _require_real_dir(path: Path, label: str) -> None:
    try:
        metadata = os.lstat(path)
    except FileNotFoundError as exc:
        raise SoundPackStoreError(f"{label} is unavailable") from exc
    except OSError as exc:
        raise SoundPackStoreError(f"{label} is unavailable") from exc
    if (
        stat.S_ISLNK(metadata.st_mode)
        or _is_reparse_point(metadata)
        or not stat.S_ISDIR(metadata.st_mode)
    ):
        raise SoundPackStoreError(f"{label} is not a real directory")


def _require_real_dir_chain(path: Path, label: str) -> None:
    absolute = Path(os.path.abspath(os.fspath(path)))
    chain = tuple(reversed(absolute.parents)) + (absolute,)
    for directory in chain:
        if not os.path.lexists(directory):
            continue
        try:
            metadata = os.lstat(directory)
        except OSError as exc:
            raise SoundPackStoreError(f"{label} is unavailable") from exc
        if stat.S_ISLNK(metadata.st_mode) or _is_reparse_point(metadata):
            raise SoundPackStoreError(f"{label} is redirected")
        if not stat.S_ISDIR(metadata.st_mode):
            raise SoundPackStoreError(f"{label} is not a real directory")


def _require_regular_file(path: Path, label: str) -> os.stat_result:
    try:
        metadata = os.lstat(path)
    except FileNotFoundError as exc:
        raise SoundPackStoreError(f"{label} is missing") from exc
    except OSError as exc:
        raise SoundPackStoreError(f"{label} is unavailable") from exc
    if (
        stat.S_ISLNK(metadata.st_mode)
        or _is_reparse_point(metadata)
        or not stat.S_ISREG(metadata.st_mode)
    ):
        raise SoundPackStoreError(f"{label} is not a regular file")
    return metadata


def _reject_duplicate_pairs(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise SoundPackStoreError(f"duplicate JSON key: {key}")
        result[key] = value
    return result


def _fsync_directory(path: Path) -> None:
    """Flush a published directory entry before dependent metadata points at it."""

    flags = os.O_RDONLY | getattr(os, "O_DIRECTORY", 0)
    try:
        descriptor = os.open(path, flags)
    except OSError as exc:
        if os.name == "nt" or exc.errno in {
            errno.EACCES,
            errno.EINVAL,
            getattr(errno, "ENOTSUP", errno.EINVAL),
        }:
            return
        raise SoundPackStoreError(
            "sound pack directory could not be synchronized"
        ) from exc
    try:
        try:
            os.fsync(descriptor)
        except OSError as exc:
            if os.name == "nt" or exc.errno in {
                errno.EINVAL,
                getattr(errno, "ENOTSUP", errno.EINVAL),
            }:
                return
            raise SoundPackStoreError(
                "sound pack directory could not be synchronized"
            ) from exc
    finally:
        os.close(descriptor)


def _ensure_real_dir_chain(path: Path, label: str) -> None:
    """Create missing storage directories with durable parent links."""

    absolute = Path(os.path.abspath(os.fspath(path)))
    chain = tuple(reversed(absolute.parents)) + (absolute,)
    for directory in chain:
        if os.path.lexists(directory):
            _require_real_dir(directory, label)
            continue
        parent = directory.parent
        _require_real_dir_chain(parent, label)
        try:
            directory.mkdir(exist_ok=True)
        except OSError as exc:
            raise SoundPackStoreError(f"{label} could not be created") from exc
        _require_real_dir(directory, label)
        _fsync_directory(parent)


def _fsync_directory_tree(root: Path, *, max_directories: int) -> None:
    """Flush staged directory entries bottom-up before publishing the tree."""

    _require_real_dir(root, "sound pack staging tree")
    if (
        isinstance(max_directories, bool)
        or not isinstance(max_directories, int)
        or not 0 <= max_directories <= _MAX_SOUND_PACK_TREE_DIRECTORIES
    ):
        raise SoundPackStoreError(
            "sound pack staging topology exceeds the resource limit"
        )

    directories: list[Path] = [root]
    pending = [root]
    try:
        while pending:
            current_path = pending.pop()
            with os.scandir(current_path) as entries:
                for entry in entries:
                    child = Path(entry.path)
                    metadata = os.lstat(child)
                    if stat.S_ISLNK(metadata.st_mode) or _is_reparse_point(metadata):
                        raise SoundPackStoreError(
                            "sound pack staging tree contains redirected content"
                        )
                    if not stat.S_ISDIR(metadata.st_mode):
                        continue
                    directories.append(child)
                    if len(directories) - 1 > max_directories:
                        raise SoundPackStoreError(
                            "sound pack staging topology exceeds the resource limit"
                        )
                    pending.append(child)
    except SoundPackStoreError:
        raise
    except OSError as exc:
        raise SoundPackStoreError(
            "sound pack staging tree could not be synchronized"
        ) from exc

    for directory in reversed(directories):
        _fsync_directory(directory)


def _canonical_json(payload: Mapping[str, object]) -> bytes:
    try:
        encoded = (
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
        raise SoundPackStoreError("sound pack metadata cannot be serialized") from exc
    if len(encoded) > _MAX_METADATA_BYTES:
        raise SoundPackStoreError("sound pack metadata exceeds the resource limit")
    return encoded


def _decode_json(raw: bytes, label: str) -> Mapping[str, object]:
    if len(raw) > _MAX_METADATA_BYTES:
        raise SoundPackStoreError(f"{label} exceeds the resource limit")

    def reject_constant(_: str) -> None:
        raise SoundPackStoreError(f"{label} contains non-finite JSON")

    try:
        value = json.loads(
            raw.decode("utf-8"),
            object_pairs_hook=_reject_duplicate_pairs,
            parse_constant=reject_constant,
        )
    except SoundPackStoreError:
        raise
    except (UnicodeDecodeError, json.JSONDecodeError, RecursionError) as exc:
        raise SoundPackStoreError(f"{label} is invalid JSON") from exc
    if not isinstance(value, Mapping) or any(type(key) is not str for key in value):
        raise SoundPackStoreError(f"{label} must be a JSON object")
    return value


def _expected_directories(files: set[str]) -> set[str]:
    expected: set[str] = set()
    for relative in files:
        parts = Path(relative).parts[:-1]
        for index in range(1, len(parts) + 1):
            expected.add(Path(*parts[:index]).as_posix())
    return expected


def _scan_exact_tree(
    root: Path,
    label: str,
    *,
    max_files: int,
    max_directories: int,
) -> tuple[set[str], set[str]]:
    _require_real_dir(root, label)
    if (
        isinstance(max_files, bool)
        or not isinstance(max_files, int)
        or max_files < 0
        or isinstance(max_directories, bool)
        or not isinstance(max_directories, int)
        or not 0 <= max_directories <= _MAX_SOUND_PACK_TREE_DIRECTORIES
    ):
        raise SoundPackStoreError(f"{label} topology exceeds the resource limit")

    files: set[str] = set()
    directories: set[str] = set()
    pending = [root]
    try:
        while pending:
            current_path = pending.pop()
            with os.scandir(current_path) as entries:
                for entry in entries:
                    child = Path(entry.path)
                    metadata = os.lstat(child)
                    if stat.S_ISLNK(metadata.st_mode) or _is_reparse_point(metadata):
                        raise SoundPackStoreError(f"{label} contains redirected content")
                    relative = child.relative_to(root).as_posix()
                    if stat.S_ISDIR(metadata.st_mode):
                        directories.add(relative)
                        if len(directories) > max_directories:
                            raise SoundPackStoreError(
                                f"{label} topology exceeds the resource limit"
                            )
                        pending.append(child)
                        continue
                    if stat.S_ISREG(metadata.st_mode):
                        files.add(relative)
                        if len(files) > max_files:
                            raise SoundPackStoreError(
                                f"{label} topology exceeds the resource limit"
                            )
                        continue
                    raise SoundPackStoreError(
                        f"{label} contains non-regular filesystem content"
                    )
    except SoundPackStoreError:
        raise
    except OSError as exc:
        raise SoundPackStoreError(f"{label} could not be inspected") from exc
    return files, directories


def _regular_identity(metadata: os.stat_result) -> tuple[int, int, int, int]:
    return (
        int(getattr(metadata, "st_dev", 0)),
        int(getattr(metadata, "st_ino", 0)),
        int(metadata.st_size),
        int(getattr(metadata, "st_mtime_ns", 0)),
    )


def _read_regular_file_bytes(
    path: Path,
    label: str,
    *,
    max_bytes: int,
) -> bytes:
    """Read bounded metadata from the same regular file proven by lstat."""

    before = _require_regular_file(path, label)
    if before.st_size > max_bytes:
        raise SoundPackStoreError(f"{label} exceeds the resource limit")

    flags = os.O_RDONLY
    flags |= getattr(os, "O_BINARY", 0)
    flags |= getattr(os, "O_NOINHERIT", 0)
    flags |= getattr(os, "O_CLOEXEC", 0)
    flags |= getattr(os, "O_NOFOLLOW", 0)
    flags |= getattr(os, "O_NONBLOCK", 0)
    try:
        descriptor = os.open(path, flags)
    except OSError as exc:
        raise SoundPackStoreError(f"{label} could not be opened safely") from exc

    try:
        opened = os.fstat(descriptor)
        if (
            stat.S_ISLNK(opened.st_mode)
            or _is_reparse_point(opened)
            or not stat.S_ISREG(opened.st_mode)
        ):
            raise SoundPackStoreError(f"{label} is not a regular file")
        if _regular_identity(opened) != _regular_identity(before):
            raise SoundPackStoreError(f"{label} changed before secure read")
        if opened.st_size > max_bytes:
            raise SoundPackStoreError(f"{label} exceeds the resource limit")

        chunks: list[bytes] = []
        remaining = opened.st_size
        while remaining:
            try:
                chunk = os.read(descriptor, min(64 * 1024, remaining))
            except OSError as exc:
                raise SoundPackStoreError(f"{label} could not be read") from exc
            if not chunk:
                raise SoundPackStoreError(f"{label} was truncated during secure read")
            remaining -= len(chunk)
            chunks.append(chunk)

        try:
            extra = os.read(descriptor, 1)
        except OSError as exc:
            raise SoundPackStoreError(f"{label} could not be read") from exc
        if extra:
            raise SoundPackStoreError(f"{label} exceeds the resource limit")
        after = os.fstat(descriptor)
        if _regular_identity(after) != _regular_identity(opened):
            raise SoundPackStoreError(f"{label} changed during secure read")
        return b"".join(chunks)
    finally:
        os.close(descriptor)


def _read_verified_asset_bytes(
    path: Path,
    digest: SoundAssetDigest,
) -> bytes:
    """Read one exact installed asset without trusting a verified pathname later."""

    before = _require_regular_file(path, "installed sound asset")
    if before.st_size != digest.size_bytes:
        raise SoundPackStoreError("installed sound asset size mismatch")

    flags = os.O_RDONLY
    flags |= getattr(os, "O_BINARY", 0)
    flags |= getattr(os, "O_NOINHERIT", 0)
    flags |= getattr(os, "O_CLOEXEC", 0)
    flags |= getattr(os, "O_NOFOLLOW", 0)
    flags |= getattr(os, "O_NONBLOCK", 0)
    try:
        descriptor = os.open(path, flags)
    except OSError as exc:
        raise SoundPackStoreError("installed sound asset could not be opened safely") from exc

    try:
        opened = os.fstat(descriptor)
        if (
            stat.S_ISLNK(opened.st_mode)
            or _is_reparse_point(opened)
            or not stat.S_ISREG(opened.st_mode)
        ):
            raise SoundPackStoreError("installed sound asset is not a regular file")
        if _regular_identity(opened) != _regular_identity(before):
            raise SoundPackStoreError("installed sound asset changed before secure read")
        if opened.st_size != digest.size_bytes:
            raise SoundPackStoreError("installed sound asset size mismatch")

        chunks: list[bytes] = []
        remaining = digest.size_bytes
        sha = hashlib.sha256()
        prefix = bytearray()
        while remaining:
            try:
                chunk = os.read(descriptor, min(1024 * 1024, remaining))
            except OSError as exc:
                raise SoundPackStoreError(
                    "installed sound asset could not be read"
                ) from exc
            if not chunk:
                raise SoundPackStoreError("installed sound asset was truncated")
            remaining -= len(chunk)
            sha.update(chunk)
            chunks.append(chunk)
            if len(prefix) < 16:
                prefix.extend(chunk[: 16 - len(prefix)])

        try:
            extra = os.read(descriptor, 1)
        except OSError as exc:
            raise SoundPackStoreError("installed sound asset could not be read") from exc
        if extra:
            raise SoundPackStoreError("installed sound asset exceeds declared size")
        after = os.fstat(descriptor)
        if _regular_identity(after) != _regular_identity(opened):
            raise SoundPackStoreError("installed sound asset changed during secure read")
        if sha.hexdigest() != digest.sha256:
            raise SoundPackStoreError("installed sound asset checksum mismatch")
        _validate_audio_header(digest.path, bytes(prefix))
        return b"".join(chunks)
    finally:
        os.close(descriptor)


def _validate_audio_header(path: str, prefix: bytes) -> None:
    suffix = Path(path).suffix.lower()
    if suffix == ".wav":
        if len(prefix) < 12 or prefix[:4] != b"RIFF" or prefix[8:12] != b"WAVE":
            raise SoundPackStoreError("sound WAV asset has an invalid signature")
        return
    if suffix == ".ogg":
        if not prefix.startswith(b"OggS"):
            raise SoundPackStoreError("sound OGG asset has an invalid signature")
        return
    if suffix == ".mp3":
        if prefix.startswith(b"ID3"):
            return
        if len(prefix) >= 2 and prefix[0] == 0xFF and prefix[1] & 0xE0 == 0xE0:
            return
        raise SoundPackStoreError("sound MP3 asset has an invalid signature")
    raise SoundPackStoreError("unsupported sound asset type")


def _rights_sha256(rights: SoundPackRightsEvidence) -> str:
    if not isinstance(rights, SoundPackRightsEvidence):
        raise TypeError("rights must be SoundPackRightsEvidence")
    return hashlib.sha256(_canonical_json(rights.to_mapping())).hexdigest()


def _integrity_mapping(
    digests: Mapping[str, SoundAssetDigest],
    *,
    rights_sha256: str | None,
) -> dict[str, object]:
    return {
        "schema_version": SOUND_PACK_INTEGRITY_SCHEMA_VERSION,
        "assets": {
            path: {
                "size_bytes": digest.size_bytes,
                "sha256": digest.sha256,
            }
            for path, digest in sorted(digests.items())
        },
        "rights_sha256": rights_sha256,
    }


def _integrity_from_mapping(
    raw: Mapping[str, object],
) -> tuple[dict[str, SoundAssetDigest], str | None, bool]:
    schema = raw.get("schema_version")
    if type(schema) is not int:
        raise SoundPackStoreError("sound pack integrity schema is invalid")
    if schema == 1:
        if set(raw) != {"schema_version", "assets"}:
            raise SoundPackStoreError("sound pack integrity fields are invalid")
        rights_sha256 = None
        rights_binding_supported = False
    elif schema == SOUND_PACK_INTEGRITY_SCHEMA_VERSION:
        if set(raw) != {"schema_version", "assets", "rights_sha256"}:
            raise SoundPackStoreError("sound pack integrity fields are invalid")
        rights_sha256 = raw["rights_sha256"]
        rights_binding_supported = True
        if rights_sha256 is not None:
            if (
                type(rights_sha256) is not str
                or len(rights_sha256) != 64
                or any(ch not in "0123456789abcdef" for ch in rights_sha256)
            ):
                raise SoundPackStoreError(
                    "sound pack rights digest is invalid"
                )
    else:
        raise SoundPackStoreError(
            f"unsupported sound pack integrity schema: {schema}"
        )
    assets = raw["assets"]
    if not isinstance(assets, Mapping) or any(type(key) is not str for key in assets):
        raise SoundPackStoreError("sound pack integrity assets must be an object")
    result: dict[str, SoundAssetDigest] = {}
    for path, value in assets.items():
        if not isinstance(value, Mapping) or set(value) != {"size_bytes", "sha256"}:
            raise SoundPackStoreError("sound pack integrity asset fields are invalid")
        try:
            digest = SoundAssetDigest(
                path=path,
                size_bytes=value["size_bytes"],  # type: ignore[arg-type]
                sha256=value["sha256"],  # type: ignore[arg-type]
            )
        except (TypeError, ValueError) as exc:
            raise SoundPackStoreError("sound pack integrity asset is invalid") from exc
        result[path] = digest
    return result, rights_sha256, rights_binding_supported


class FilesystemSoundPackStore:
    """Versioned atomic local storage implementing SoundPackStoragePort."""

    def __init__(
        self,
        root: str | os.PathLike[str],
        *,
        built_in: Mapping[str, SoundPackManifest] | None = None,
        max_bytes: int = DEFAULT_MAX_SOUND_PACK_BYTES,
    ) -> None:
        if not isinstance(root, (str, os.PathLike)):
            raise TypeError("sound pack root must be path-like")
        self.root = Path(root)
        if str(self.root) in {"", "."}:
            raise ValueError("sound pack root must identify a dedicated directory")
        if isinstance(max_bytes, bool) or not isinstance(max_bytes, int):
            raise TypeError("max_bytes must be an integer")
        if max_bytes <= 0:
            raise ValueError("max_bytes must be positive")
        self.max_bytes = max_bytes
        self._mutation_lock_path = self.root.with_name(self.root.name + ".lock")
        self._process_mutation_lock = _process_mutation_lock_for(
            self._mutation_lock_path
        )

        source = {} if built_in is None else built_in
        if not isinstance(source, Mapping):
            raise TypeError("built_in sound packs must be a mapping")
        normalized: dict[str, SoundPackManifest] = {}
        for raw_id, manifest in source.items():
            if not isinstance(raw_id, str):
                raise TypeError("built_in sound pack ids must be text")
            if not isinstance(manifest, SoundPackManifest):
                raise TypeError("built_in values must be SoundPackManifest")
            pack_id = _stable_id(raw_id, allow_dot=True)
            if manifest.pack_id != pack_id:
                raise ValueError("built_in key must match manifest pack_id")
            if pack_id in normalized:
                raise ValueError("duplicate built-in sound pack id")
            normalized[pack_id] = manifest
        self._built_in = normalized

    @staticmethod
    def _lock_descriptor(descriptor: int) -> None:
        try:
            if os.name == "nt":
                import msvcrt

                os.lseek(descriptor, 0, os.SEEK_SET)
                msvcrt.locking(descriptor, msvcrt.LK_LOCK, 1)
            else:
                import fcntl

                fcntl.flock(descriptor, fcntl.LOCK_EX)
        except OSError as exc:
            raise SoundPackStoreError(
                "sound pack storage mutation lock is unavailable"
            ) from exc

    @staticmethod
    def _unlock_descriptor(descriptor: int) -> None:
        try:
            if os.name == "nt":
                import msvcrt

                os.lseek(descriptor, 0, os.SEEK_SET)
                msvcrt.locking(descriptor, msvcrt.LK_UNLCK, 1)
            else:
                import fcntl

                fcntl.flock(descriptor, fcntl.LOCK_UN)
        except OSError:
            pass

    def _open_mutation_lock_descriptor(self) -> int:
        _require_real_dir_chain(
            self._mutation_lock_path.parent,
            "sound pack storage parent",
        )
        _ensure_real_dir_chain(
            self._mutation_lock_path.parent,
            "sound pack storage parent",
        )
        _require_real_dir_chain(
            self._mutation_lock_path.parent,
            "sound pack storage parent",
        )
        try:
            existing = os.lstat(self._mutation_lock_path)
        except FileNotFoundError:
            existing = None
        except OSError as exc:
            raise SoundPackStoreError(
                "sound pack storage mutation lock is unavailable"
            ) from exc
        if existing is not None:
            _require_regular_file(
                self._mutation_lock_path,
                "sound pack storage mutation lock",
            )

        flags = os.O_RDWR | os.O_CREAT
        flags |= getattr(os, "O_BINARY", 0)
        flags |= getattr(os, "O_NOINHERIT", 0)
        flags |= getattr(os, "O_CLOEXEC", 0)
        flags |= getattr(os, "O_NOFOLLOW", 0)
        flags |= getattr(os, "O_NONBLOCK", 0)
        try:
            descriptor = os.open(self._mutation_lock_path, flags, 0o600)
        except OSError as exc:
            raise SoundPackStoreError(
                "sound pack storage mutation lock is unavailable"
            ) from exc
        try:
            metadata = os.fstat(descriptor)
            if (
                stat.S_ISLNK(metadata.st_mode)
                or _is_reparse_point(metadata)
                or not stat.S_ISREG(metadata.st_mode)
            ):
                raise SoundPackStoreError(
                    "sound pack storage mutation lock is not a regular file"
                )
            if (
                existing is not None
                and _regular_identity(metadata) != _regular_identity(existing)
            ):
                raise SoundPackStoreError(
                    "sound pack storage mutation lock changed before secure open"
                )
            if metadata.st_size == 0:
                os.write(descriptor, b"\0")
                os.fsync(descriptor)
            return descriptor
        except BaseException:
            os.close(descriptor)
            raise

    @contextmanager
    def _exclusive_mutation(self) -> Iterator[None]:
        with self._process_mutation_lock:
            root_boundary = self.root if os.path.lexists(self.root) else self.root.parent
            _require_real_dir_chain(root_boundary, "sound pack storage root")
            descriptor = self._open_mutation_lock_descriptor()
            acquired = False
            try:
                self._lock_descriptor(descriptor)
                acquired = True
                root_boundary = (
                    self.root if os.path.lexists(self.root) else self.root.parent
                )
                _require_real_dir_chain(
                    root_boundary,
                    "sound pack storage root",
                )
                yield
            finally:
                if acquired:
                    self._unlock_descriptor(descriptor)
                os.close(descriptor)

    def _pack_dir(self, pack_id: str) -> Path:
        return self.root / _stable_id(pack_id, allow_dot=True)

    def _version_dir(self, pack_id: str, version: str) -> Path:
        return self._pack_dir(pack_id) / "versions" / _stable_version(version)

    def _ensure_pack_parent(self, pack_id: str) -> tuple[Path, Path]:
        _require_real_dir_chain(self.root.parent, "sound pack storage parent")
        _ensure_real_dir_chain(self.root, "sound pack root")

        pack_dir = self._pack_dir(pack_id)
        _ensure_real_dir_chain(pack_dir, "sound pack identity directory")

        versions = pack_dir / "versions"
        _ensure_real_dir_chain(versions, "sound pack versions directory")
        return pack_dir, versions

    @staticmethod
    def _validate_downloaded(
        downloaded: DownloadedSoundPack,
    ) -> dict[str, SoundAssetDigest]:
        if not isinstance(downloaded, DownloadedSoundPack):
            raise TypeError("downloaded must be DownloadedSoundPack")
        if not isinstance(downloaded.manifest, SoundPackManifest):
            raise TypeError("downloaded manifest must be SoundPackManifest")
        if isinstance(downloaded.total_bytes, bool) or not isinstance(
            downloaded.total_bytes, int
        ):
            raise TypeError("downloaded total_bytes must be an integer")
        if downloaded.total_bytes < 0:
            raise ValueError("downloaded total_bytes cannot be negative")
        if not isinstance(downloaded.assets, Mapping):
            raise TypeError("downloaded assets must be a mapping")

        digests: dict[str, SoundAssetDigest] = {}
        for path, digest in downloaded.assets.items():
            if not isinstance(path, str):
                raise TypeError("downloaded asset keys must be text")
            if not isinstance(digest, SoundAssetDigest):
                raise TypeError(
                    "downloaded assets must contain SoundAssetDigest values"
                )
            safe_path = _safe_audio_path(path)
            if safe_path != digest.path:
                raise ValueError("downloaded asset key must match digest path")
            if safe_path in digests:
                raise ValueError("duplicate normalized downloaded asset path")
            digests[safe_path] = digest

        expected = set(downloaded.manifest.files.values())
        if set(digests) != expected:
            raise SoundPackStoreError(
                "downloaded assets do not exactly cover the manifest"
            )
        if sum(item.size_bytes for item in digests.values()) != downloaded.total_bytes:
            raise SoundPackStoreError(
                "downloaded total size does not match asset metadata"
            )
        return digests

    @staticmethod
    def _source_root(
        downloaded: DownloadedSoundPack,
        digests: Mapping[str, SoundAssetDigest],
    ) -> Path:
        if not isinstance(downloaded.payload_ref, (str, os.PathLike)):
            raise TypeError(
                "downloaded payload_ref must be a staging-directory path"
            )
        source = Path(downloaded.payload_ref)
        _require_real_dir_chain(
            source,
            "downloaded sound pack staging directory",
        )
        expected_files = set(digests)
        expected_directories = _expected_directories(expected_files)
        if len(expected_directories) > _MAX_SOUND_PACK_TREE_DIRECTORIES:
            raise SoundPackStoreError(
                "downloaded sound pack staging topology exceeds the resource limit"
            )
        files, directories = _scan_exact_tree(
            source,
            "downloaded sound pack staging directory",
            max_files=len(expected_files),
            max_directories=len(expected_directories),
        )
        if (
            files != expected_files
            or directories != expected_directories
        ):
            raise SoundPackStoreError(
                "downloaded sound pack staging topology does not match declared assets"
            )
        return source

    @staticmethod
    def _copy_verified(
        source: Path,
        destination: Path,
        digest: SoundAssetDigest,
    ) -> None:
        metadata = _require_regular_file(source, "downloaded sound asset")
        if metadata.st_size != digest.size_bytes:
            raise SoundPackStoreError("downloaded sound asset size mismatch")

        _require_real_dir_chain(
            destination.parent,
            "sound pack destination directory",
        )
        try:
            destination.parent.mkdir(parents=True, exist_ok=True)
        except OSError as exc:
            raise SoundPackStoreError(
                "sound pack destination directory could not be created"
            ) from exc
        _require_real_dir_chain(
            destination.parent,
            "sound pack destination directory",
        )

        flags = os.O_RDONLY
        flags |= getattr(os, "O_BINARY", 0)
        flags |= getattr(os, "O_NOINHERIT", 0)
        flags |= getattr(os, "O_CLOEXEC", 0)
        flags |= getattr(os, "O_NOFOLLOW", 0)
        flags |= getattr(os, "O_NONBLOCK", 0)
        try:
            descriptor = os.open(source, flags)
        except OSError as exc:
            raise SoundPackStoreError(
                "downloaded sound asset could not be opened safely"
            ) from exc

        sha = hashlib.sha256()
        size = 0
        prefix = bytearray()
        try:
            opened = os.fstat(descriptor)
            if (
                stat.S_ISLNK(opened.st_mode)
                or _is_reparse_point(opened)
                or not stat.S_ISREG(opened.st_mode)
            ):
                raise SoundPackStoreError(
                    "downloaded sound asset is not a regular file"
                )
            if _regular_identity(opened) != _regular_identity(metadata):
                raise SoundPackStoreError(
                    "downloaded sound asset changed before secure copy"
                )
            if opened.st_size != digest.size_bytes:
                raise SoundPackStoreError("downloaded sound asset size mismatch")

            try:
                with destination.open("xb") as writer:
                    while True:
                        chunk = os.read(descriptor, 1024 * 1024)
                        if not chunk:
                            break
                        if len(prefix) < 16:
                            prefix.extend(chunk[: 16 - len(prefix)])
                        size += len(chunk)
                        if size > digest.size_bytes:
                            raise SoundPackStoreError(
                                "downloaded sound asset exceeds declared size"
                            )
                        sha.update(chunk)
                        writer.write(chunk)
                    writer.flush()
                    os.fsync(writer.fileno())
            except SoundPackStoreError:
                raise
            except OSError as exc:
                raise SoundPackStoreError(
                    "sound pack asset could not be staged locally"
                ) from exc

            after = os.fstat(descriptor)
            if _regular_identity(after) != _regular_identity(opened):
                raise SoundPackStoreError(
                    "downloaded sound asset changed during secure copy"
                )
        finally:
            os.close(descriptor)

        if size != digest.size_bytes:
            raise SoundPackStoreError("downloaded sound asset size mismatch")
        if sha.hexdigest() != digest.sha256:
            raise SoundPackStoreError("downloaded sound asset checksum mismatch")
        _validate_audio_header(digest.path, bytes(prefix))

    @staticmethod
    def _write_new(path: Path, data: bytes) -> None:
        _require_real_dir_chain(
            path.parent,
            "sound pack metadata directory",
        )
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
        except OSError as exc:
            raise SoundPackStoreError(
                "sound pack metadata directory could not be created"
            ) from exc
        _require_real_dir_chain(
            path.parent,
            "sound pack metadata directory",
        )
        try:
            with path.open("xb") as handle:
                handle.write(data)
                handle.flush()
                os.fsync(handle.fileno())
        except OSError as exc:
            raise SoundPackStoreError(
                "sound pack metadata could not be written"
            ) from exc

    @staticmethod
    def _read_manifest(version_dir: Path) -> SoundPackManifest:
        raw = _read_regular_file_bytes(
            version_dir / _MANIFEST_NAME,
            "sound pack manifest",
            max_bytes=_MAX_METADATA_BYTES,
        )
        try:
            return SoundPackManifest.from_mapping(
                _decode_json(raw, "sound pack manifest")
            )
        except (TypeError, ValueError) as exc:
            raise SoundPackStoreError("sound pack manifest is invalid") from exc

    @staticmethod
    def _read_integrity(
        version_dir: Path,
    ) -> tuple[dict[str, SoundAssetDigest], str | None, bool]:
        raw = _read_regular_file_bytes(
            version_dir / _INTEGRITY_NAME,
            "sound pack integrity metadata",
            max_bytes=_MAX_METADATA_BYTES,
        )
        return _integrity_from_mapping(
            _decode_json(raw, "sound pack integrity metadata")
        )

    @staticmethod
    def _read_rights(
        version_dir: Path,
    ) -> SoundPackRightsEvidence | None:
        path = version_dir / _RIGHTS_NAME
        if not os.path.lexists(path):
            return None
        raw = _read_regular_file_bytes(
            path,
            "sound pack rights evidence",
            max_bytes=_MAX_METADATA_BYTES,
        )
        try:
            return SoundPackRightsEvidence.from_mapping(
                _decode_json(raw, "sound pack rights evidence")
            )
        except (TypeError, ValueError) as exc:
            raise SoundPackStoreError(
                "sound pack rights evidence is invalid"
            ) from exc

    def _verify_version(
        self,
        version_dir: Path,
        *,
        expected_pack_id: str | None = None,
        expected_version: str | None = None,
    ) -> tuple[
        SoundPackManifest,
        dict[str, SoundAssetDigest],
        SoundPackRightsEvidence | None,
    ]:
        _require_real_dir(version_dir, "installed sound pack version")
        manifest = self._read_manifest(version_dir)
        if expected_pack_id is not None and manifest.pack_id != expected_pack_id:
            raise SoundPackStoreError(
                "installed sound pack id does not match its directory"
            )
        if expected_version is not None and manifest.version != expected_version:
            raise SoundPackStoreError(
                "installed sound pack version does not match its directory"
            )

        digests, rights_sha256, rights_binding_supported = self._read_integrity(
            version_dir
        )
        rights_evidence = self._read_rights(version_dir)
        if rights_binding_supported:
            if rights_evidence is None and rights_sha256 is not None:
                raise SoundPackStoreError(
                    "sound pack rights digest has no rights metadata"
                )
            if rights_evidence is not None and rights_sha256 is None:
                raise SoundPackStoreError(
                    "sound pack rights metadata has no integrity binding"
                )
            if (
                rights_evidence is not None
                and rights_sha256 is not None
                and _rights_sha256(rights_evidence) != rights_sha256
            ):
                raise SoundPackStoreError(
                    "sound pack rights evidence checksum mismatch"
                )
        if (
            rights_evidence is not None
            and rights_evidence.license_id != manifest.license_id
        ):
            raise SoundPackStoreError(
                "sound pack rights license does not match manifest"
            )
        expected_assets = set(manifest.files.values())
        if set(digests) != expected_assets:
            raise SoundPackStoreError(
                "installed integrity metadata does not cover manifest assets"
            )

        expected_files = {
            _MANIFEST_NAME,
            _INTEGRITY_NAME,
            *expected_assets,
        }
        if rights_evidence is not None:
            expected_files.add(_RIGHTS_NAME)
        expected_directories = _expected_directories(expected_files)
        if len(expected_directories) > _MAX_SOUND_PACK_TREE_DIRECTORIES:
            raise SoundPackStoreError(
                "installed sound pack topology exceeds the resource limit"
            )
        files, directories = _scan_exact_tree(
            version_dir,
            "installed sound pack version",
            max_files=len(expected_files),
            max_directories=len(expected_directories),
        )
        if (
            files != expected_files
            or directories != expected_directories
        ):
            raise SoundPackStoreError(
                "installed sound pack contains undeclared filesystem content"
            )

        total = 0
        for relative, digest in digests.items():
            path = version_dir / relative
            metadata = _require_regular_file(path, "installed sound asset")
            if metadata.st_size != digest.size_bytes:
                raise SoundPackStoreError(
                    "installed sound asset size mismatch"
                )
            total += digest.size_bytes
            if total > self.max_bytes:
                raise SoundPackStoreError(
                    "installed sound pack exceeds the local size limit"
                )

            _read_verified_asset_bytes(path, digest)
        verified_rights = (
            rights_evidence
            if rights_binding_supported and rights_sha256 is not None
            else None
        )
        return manifest, digests, verified_rights

    @staticmethod
    def _active_payload(pack_id: str, version: str) -> dict[str, object]:
        return {
            "schema_version": SOUND_PACK_STORE_SCHEMA_VERSION,
            "pack_id": pack_id,
            "version": version,
        }

    @staticmethod
    def _read_active(pack_dir: Path) -> tuple[str, str]:
        raw = _decode_json(
            _read_regular_file_bytes(
                pack_dir / _ACTIVE_NAME,
                "sound pack active pointer",
                max_bytes=_MAX_METADATA_BYTES,
            ),
            "sound pack active pointer",
        )
        if set(raw) != {"schema_version", "pack_id", "version"}:
            raise SoundPackStoreError(
                "sound pack active pointer fields are invalid"
            )
        schema = raw["schema_version"]
        if type(schema) is not int or schema != SOUND_PACK_STORE_SCHEMA_VERSION:
            raise SoundPackStoreError(
                f"unsupported sound pack active schema: {schema}"
            )
        try:
            pack_id = _stable_id(raw["pack_id"], allow_dot=True)
            version = _stable_version(raw["version"])
        except (TypeError, ValueError) as exc:
            raise SoundPackStoreError(
                "sound pack active pointer identity is invalid"
            ) from exc
        return pack_id, version

    @staticmethod
    def _publish_active(
        pack_dir: Path,
        pack_id: str,
        version: str,
    ) -> None:
        _require_real_dir(pack_dir, "sound pack identity directory")
        encoded = _canonical_json(
            FilesystemSoundPackStore._active_payload(pack_id, version)
        )
        temp_path: Path | None = None
        try:
            descriptor, temp_name = tempfile.mkstemp(
                prefix=".active-",
                suffix=".tmp",
                dir=pack_dir,
            )
            temp_path = Path(temp_name)
            with os.fdopen(descriptor, "wb") as stream:
                stream.write(encoded)
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temp_path, pack_dir / _ACTIVE_NAME)
            temp_path = None
            _fsync_directory(pack_dir)
            observed = FilesystemSoundPackStore._read_active(pack_dir)
            if observed != (pack_id, version):
                raise SoundPackStoreError(
                    "sound pack active pointer readback did not match publication"
                )
        except OSError as exc:
            raise SoundPackStoreError(
                "sound pack active pointer could not be published atomically"
            ) from exc
        finally:
            if temp_path is not None:
                try:
                    temp_path.unlink(missing_ok=True)
                except OSError:
                    pass

    def install_atomically(self, downloaded: DownloadedSoundPack) -> None:
        digests = self._validate_downloaded(downloaded)
        if downloaded.total_bytes > self.max_bytes:
            raise SoundPackStoreError(
                "downloaded sound pack exceeds the local size limit"
            )
        manifest = downloaded.manifest
        if manifest.pack_id in self._built_in:
            raise SoundPackStoreError("built-in sound pack id is immutable")
        source = self._source_root(downloaded, digests)
        with self._exclusive_mutation():
            self._install_atomically_locked(downloaded, digests, source)

    def _install_atomically_locked(
        self,
        downloaded: DownloadedSoundPack,
        digests: Mapping[str, SoundAssetDigest],
        source: Path,
    ) -> None:
        manifest = downloaded.manifest
        current_version = self.active_version(manifest.pack_id)
        if (
            current_version is not None
            and _semantic_version_key(current_version)
            > _semantic_version_key(manifest.version)
        ):
            raise SoundPackStoreError(
                "sound pack install would roll back the active version"
            )
        pack_dir, versions_dir = self._ensure_pack_parent(manifest.pack_id)
        destination = versions_dir / manifest.version

        if destination.exists():
            existing_manifest, existing_digests, existing_rights = self._verify_version(
                destination,
                expected_pack_id=manifest.pack_id,
                expected_version=manifest.version,
            )
            if (
                existing_manifest != manifest
                or existing_digests != digests
                or existing_rights != downloaded.rights_evidence
            ):
                raise SoundPackStoreError(
                    "sound pack version already exists with different content"
                )
            _fsync_directory(versions_dir)
            self._publish_active(
                pack_dir, manifest.pack_id, manifest.version
            )
            return

        try:
            staging = Path(
                tempfile.mkdtemp(
                    prefix=f".{manifest.pack_id}-{manifest.version}-",
                    dir=versions_dir,
                )
            )
        except OSError as exc:
            raise SoundPackStoreError(
                "sound pack local staging directory could not be created"
            ) from exc

        cleanup = True
        try:
            _require_real_dir(staging, "sound pack local staging directory")
            for relative, digest in sorted(digests.items()):
                self._copy_verified(
                    source / relative,
                    staging / relative,
                    digest,
                )
            self._write_new(
                staging / _MANIFEST_NAME,
                _canonical_json(manifest.to_mapping()),
            )
            self._write_new(
                staging / _INTEGRITY_NAME,
                _canonical_json(
                    _integrity_mapping(
                        digests,
                        rights_sha256=(
                            None
                            if downloaded.rights_evidence is None
                            else _rights_sha256(downloaded.rights_evidence)
                        ),
                    )
                ),
            )
            if downloaded.rights_evidence is not None:
                self._write_new(
                    staging / _RIGHTS_NAME,
                    _canonical_json(downloaded.rights_evidence.to_mapping()),
                )

            staged_manifest, staged_digests, staged_rights = self._verify_version(
                staging,
                expected_pack_id=manifest.pack_id,
                expected_version=manifest.version,
            )
            if (
                staged_manifest != manifest
                or staged_digests != digests
                or staged_rights != downloaded.rights_evidence
            ):
                raise SoundPackStoreError(
                    "locally staged sound pack identity changed"
                )

            # File contents were fsynced as they were written. Flush the staged
            # directory entries bottom-up as well before publishing the complete
            # version directory through one atomic rename.
            _fsync_directory_tree(
                staging,
                max_directories=len(
                    _expected_directories(
                        {
                            _MANIFEST_NAME,
                            _INTEGRITY_NAME,
                            *digests,
                            *(
                                {_RIGHTS_NAME}
                                if downloaded.rights_evidence is not None
                                else set()
                            ),
                        }
                    )
                ),
            )

            try:
                os.replace(staging, destination)
                cleanup = False
            except OSError as exc:
                if destination.exists():
                    try:
                        current_manifest, current_digests, current_rights = self._verify_version(
                            destination,
                            expected_pack_id=manifest.pack_id,
                            expected_version=manifest.version,
                        )
                    except (TypeError, ValueError, SoundPackStoreError):
                        raise SoundPackStoreError(
                            "sound pack install lost an atomic publication race"
                        ) from exc
                    if (
                        current_manifest == manifest
                        and current_digests == digests
                        and current_rights == downloaded.rights_evidence
                    ):
                        _fsync_directory(versions_dir)
                        self._publish_active(
                            pack_dir,
                            manifest.pack_id,
                            manifest.version,
                        )
                        return
                raise SoundPackStoreError(
                    "sound pack version could not be published atomically"
                ) from exc

            # Re-verify through the final pathname after the atomic rename.
            # A staging entry can otherwise be replaced after its pre-publish
            # verification but before rename, leaving active.json pointing at
            # bytes that were never proven under their final identity.
            try:
                published_manifest, published_digests, published_rights = self._verify_version(
                    destination,
                    expected_pack_id=manifest.pack_id,
                    expected_version=manifest.version,
                )
                if (
                    published_manifest != manifest
                    or published_digests != digests
                    or published_rights != downloaded.rights_evidence
                ):
                    raise SoundPackStoreError(
                        "published sound pack identity changed before activation"
                    )
            except (TypeError, ValueError, SoundPackStoreError):
                if os.path.lexists(destination):
                    try:
                        self._remove_without_following(destination)
                        _fsync_directory(versions_dir)
                    except SoundPackStoreError:
                        # Preserve the integrity failure as the primary error.
                        pass
                raise

            # The active pointer may only reference a version after its final,
            # revalidated directory entry crossed the crash-durability boundary.
            _fsync_directory(versions_dir)
            self._publish_active(
                pack_dir, manifest.pack_id, manifest.version
            )
        finally:
            if cleanup and os.path.lexists(staging):
                try:
                    self._remove_without_following(staging)
                except SoundPackStoreError:
                    # Best-effort cleanup must never replace the primary install
                    # failure, and reparse/symlink entries are never traversed.
                    pass

    def _installed_disk_pack(self, pack_id: str) -> InstalledSoundPack:
        identity = _stable_id(pack_id, allow_dot=True)
        _require_real_dir_chain(self.root, "sound pack root")
        pack_dir = self._pack_dir(identity)
        _require_real_dir(pack_dir, "sound pack identity directory")
        active_id, version = self._read_active(pack_dir)
        if active_id != identity:
            raise SoundPackStoreError(
                "sound pack active pointer id does not match directory"
            )
        version_dir = self._version_dir(identity, version)
        manifest, digests, rights_evidence = self._verify_version(
            version_dir,
            expected_pack_id=identity,
            expected_version=version,
        )
        return InstalledSoundPack(
            manifest=manifest,
            version_dir=version_dir,
            digests=digests,
            rights_evidence=rights_evidence,
        )

    def _installed_disk_inventory(self) -> dict[str, InstalledSoundPack]:
        result: dict[str, InstalledSoundPack] = {}
        if not self.root.exists():
            return result
        _require_real_dir_chain(self.root, "sound pack root")
        try:
            with os.scandir(self.root) as children:
                for index, entry in enumerate(children, start=1):
                    if index > _MAX_SOUND_PACK_INVENTORY_ENTRIES:
                        raise SoundPackStoreError(
                            "sound pack inventory exceeds the resource limit"
                        )
                    child = Path(entry.path)
                    try:
                        metadata = os.lstat(child)
                    except OSError:
                        continue
                    if (
                        stat.S_ISLNK(metadata.st_mode)
                        or _is_reparse_point(metadata)
                        or not stat.S_ISDIR(metadata.st_mode)
                    ):
                        continue
                    try:
                        identity = _stable_id(child.name, allow_dot=True)
                    except (TypeError, ValueError):
                        continue
                    if identity != child.name or identity in result:
                        continue
                    try:
                        installed = self._installed_disk_pack(identity)
                    except (TypeError, ValueError, SoundPackStoreError):
                        continue
                    result[identity] = installed
        except SoundPackStoreError:
            raise
        except OSError as exc:
            raise SoundPackStoreError(
                "sound pack root could not be listed"
            ) from exc
        return result

    def installed(self) -> Mapping[str, SoundPackManifest]:
        result = dict(self._built_in)
        for pack_id, installed in self._installed_disk_inventory().items():
            if pack_id not in result:
                result[pack_id] = installed.manifest
        return result

    def installed_audit(self) -> Mapping[str, SoundPackInstalledAudit]:
        """Return manifest and rights from the same verified active-version scan."""

        result = {
            pack_id: SoundPackInstalledAudit(manifest, None)
            for pack_id, manifest in self._built_in.items()
        }
        for pack_id, installed in self._installed_disk_inventory().items():
            if pack_id in result:
                continue
            result[pack_id] = SoundPackInstalledAudit(
                installed.manifest,
                installed.rights_evidence,
            )
        return result

    def active_version(self, pack_id: str) -> str | None:
        identity = _stable_id(pack_id, allow_dot=True)
        if identity in self._built_in:
            return self._built_in[identity].version
        try:
            return self._installed_disk_pack(identity).manifest.version
        except (TypeError, ValueError, SoundPackStoreError):
            return None

    def rights_evidence(
        self,
        pack_id: str,
    ) -> SoundPackRightsEvidence | None:
        """Return version-bound auditable rights for the active verified pack."""

        identity = _stable_id(pack_id, allow_dot=True)
        if identity in self._built_in:
            return None
        try:
            return self._installed_disk_pack(identity).rights_evidence
        except (TypeError, ValueError, SoundPackStoreError):
            return None

    def versions(self, pack_id: str) -> tuple[str, ...]:
        identity = _stable_id(pack_id, allow_dot=True)
        if identity in self._built_in:
            return (self._built_in[identity].version,)
        _require_real_dir_chain(self.root, "sound pack root")
        versions_dir = self._pack_dir(identity) / "versions"
        if not versions_dir.exists():
            return ()
        valid: list[str] = []
        try:
            _require_real_dir(versions_dir, "sound pack versions directory")
            with os.scandir(versions_dir) as candidates:
                for index, entry in enumerate(candidates, start=1):
                    if index > _MAX_SOUND_PACK_VERSION_ENTRIES:
                        raise SoundPackStoreError(
                            "sound pack version inventory exceeds the resource limit"
                        )
                    candidate = Path(entry.path)
                    try:
                        version = _stable_version(candidate.name)
                        self._verify_version(
                            candidate,
                            expected_pack_id=identity,
                            expected_version=version,
                        )
                    except (TypeError, ValueError, SoundPackStoreError):
                        continue
                    valid.append(version)
        except (OSError, SoundPackStoreError):
            return ()
        return tuple(sorted(valid, key=_semantic_version_key))

    def read_asset_snapshot(
        self,
        pack_id: str,
        sound_id: str,
    ) -> SoundPackAssetSnapshot | None:
        """Return integrity-verified bytes from one active installed-pack snapshot."""

        identity = _stable_id(pack_id, allow_dot=True)
        if identity in self._built_in:
            return None
        try:
            requested_sound = _stable_id(sound_id, allow_dot=True)
            installed = self._installed_disk_pack(identity)
            relative = installed.manifest.sound_path(requested_sound)
            digest = installed.digests[relative]
            content = _read_verified_asset_bytes(
                installed.version_dir / relative,
                digest,
            )
            return SoundPackAssetSnapshot(
                pack_id=identity,
                version=installed.manifest.version,
                sound_id=requested_sound,
                relative_path=relative,
                content=content,
            )
        except (
            KeyError,
            TypeError,
            ValueError,
            SoundPackStoreError,
        ):
            return None

    def resolve_asset(
        self,
        pack_id: str,
        sound_id: str,
    ) -> Path | None:
        identity = _stable_id(pack_id, allow_dot=True)
        if identity in self._built_in:
            return None
        try:
            installed = self._installed_disk_pack(identity)
            relative = installed.manifest.sound_path(sound_id)
            path = installed.version_dir / relative
            _require_regular_file(path, "installed sound asset")
            return path
        except (
            KeyError,
            TypeError,
            ValueError,
            SoundPackStoreError,
        ):
            return None

    @staticmethod
    def _remove_without_following(path: Path) -> None:
        try:
            metadata = os.lstat(path)
        except FileNotFoundError:
            return
        except OSError as exc:
            raise SoundPackStoreError(
                "sound pack entry could not be inspected for removal"
            ) from exc

        if stat.S_ISLNK(metadata.st_mode) or _is_reparse_point(metadata):
            try:
                if stat.S_ISDIR(metadata.st_mode):
                    os.rmdir(path)
                else:
                    path.unlink()
            except OSError as exc:
                raise SoundPackStoreError(
                    "sound pack reparse entry could not be removed"
                ) from exc
            return

        if stat.S_ISDIR(metadata.st_mode):
            try:
                children = list(path.iterdir())
            except OSError as exc:
                raise SoundPackStoreError(
                    "sound pack directory could not be listed for removal"
                ) from exc
            for child in children:
                FilesystemSoundPackStore._remove_without_following(child)
            try:
                path.rmdir()
            except OSError as exc:
                raise SoundPackStoreError(
                    "sound pack directory could not be removed"
                ) from exc
            return

        try:
            path.unlink()
        except OSError as exc:
            raise SoundPackStoreError(
                "sound pack file could not be removed"
            ) from exc

    def uninstall(self, pack_id: str) -> None:
        identity = _stable_id(pack_id, allow_dot=True)
        if identity in self._built_in:
            raise SoundPackStoreError("built-in sound pack id is immutable")
        with self._exclusive_mutation():
            self._uninstall_locked(identity)

    def _uninstall_locked(self, pack_id: str) -> None:
        identity = _stable_id(pack_id, allow_dot=True)
        pack_dir = self._pack_dir(identity)
        if not os.path.lexists(pack_dir):
            return
        self._remove_without_following(pack_dir)
        _fsync_directory(self.root)
