from __future__ import annotations

"""Windows playback adapter for profile-selected sound assets.

Classic semantic events continue to use the incumbent packaged resolver. Custom
packs resolve only through ``FilesystemSoundPackStore``'s integrity-checked
active-version boundary. This module owns no chess-event ordering or profile
persistence.
"""

from contextlib import contextmanager
import hashlib
import io
import logging
import os
from pathlib import Path
import stat
import struct
import sys
import tempfile
import threading
import wave

from .sound_events import SoundEvent
from .sound_pack_store import FilesystemSoundPackStore, SoundPackAssetSnapshot
from .sound_runtime import SoundAssetRequest
from .sound_windows import PackagedSoundAssetResolver


PROFILED_SCALED_SOUND_CACHE_FORMAT_VERSION = 1
_MAX_PROFILED_SOURCE_WAV_BYTES = 32 * 1024 * 1024
_CACHE_LOCKS_GUARD = threading.Lock()
_CACHE_LOCKS: dict[str, threading.RLock] = {}


def _cache_process_lock(path: Path) -> threading.RLock:
    key = os.path.normcase(os.path.abspath(os.fspath(path)))
    with _CACHE_LOCKS_GUARD:
        lock = _CACHE_LOCKS.get(key)
        if lock is None:
            lock = threading.RLock()
            _CACHE_LOCKS[key] = lock
        return lock


def _is_reparse_point(metadata: os.stat_result) -> bool:
    flag = getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0)
    attributes = getattr(metadata, "st_file_attributes", 0)
    return bool(flag and attributes & flag)


def _regular_file_identity(metadata: os.stat_result) -> tuple[int, int, int, int]:
    return (
        int(getattr(metadata, "st_dev", 0)),
        int(getattr(metadata, "st_ino", 0)),
        int(metadata.st_size),
        int(getattr(metadata, "st_mtime_ns", 0)),
    )


def _require_real_cache_directory(path: Path) -> None:
    try:
        metadata = os.lstat(path)
    except OSError as exc:
        raise ValueError("profiled sound cache directory is unavailable") from exc
    if (
        stat.S_ISLNK(metadata.st_mode)
        or _is_reparse_point(metadata)
        or not stat.S_ISDIR(metadata.st_mode)
    ):
        raise ValueError("profiled sound cache is not a real directory")


def _require_real_cache_directory_chain(path: Path) -> None:
    absolute = Path(os.path.abspath(os.fspath(path)))
    chain = tuple(reversed(absolute.parents)) + (absolute,)
    for directory in chain:
        if os.path.lexists(directory):
            _require_real_cache_directory(directory)


def _read_verified_source_bytes(path: Path) -> bytes:
    """Read one bounded WAV from the same regular file proven by lstat."""

    try:
        before = os.lstat(path)
    except OSError as exc:
        raise FileNotFoundError("profiled sound source is unavailable") from exc
    if (
        stat.S_ISLNK(before.st_mode)
        or _is_reparse_point(before)
        or not stat.S_ISREG(before.st_mode)
    ):
        raise ValueError("profiled sound source is not a regular file")
    if before.st_size <= 0 or before.st_size > _MAX_PROFILED_SOURCE_WAV_BYTES:
        raise ValueError("profiled sound source exceeds the resource limit")

    flags = os.O_RDONLY
    flags |= getattr(os, "O_BINARY", 0)
    flags |= getattr(os, "O_NOINHERIT", 0)
    flags |= getattr(os, "O_CLOEXEC", 0)
    flags |= getattr(os, "O_NOFOLLOW", 0)
    flags |= getattr(os, "O_NONBLOCK", 0)
    try:
        descriptor = os.open(path, flags)
    except OSError as exc:
        raise FileNotFoundError(
            "profiled sound source could not be opened safely"
        ) from exc

    try:
        opened = os.fstat(descriptor)
        if (
            stat.S_ISLNK(opened.st_mode)
            or _is_reparse_point(opened)
            or not stat.S_ISREG(opened.st_mode)
            or _regular_file_identity(opened) != _regular_file_identity(before)
        ):
            raise ValueError("profiled sound source changed before secure read")
        remaining = opened.st_size
        chunks: list[bytes] = []
        while remaining:
            try:
                chunk = os.read(descriptor, min(1024 * 1024, remaining))
            except OSError as exc:
                raise OSError("profiled sound source could not be read") from exc
            if not chunk:
                raise ValueError("profiled sound source was truncated")
            remaining -= len(chunk)
            chunks.append(chunk)
        try:
            extra = os.read(descriptor, 1)
        except OSError as exc:
            raise OSError("profiled sound source could not be read") from exc
        if extra:
            raise ValueError("profiled sound source changed during secure read")
        after = os.fstat(descriptor)
        if _regular_file_identity(after) != _regular_file_identity(opened):
            raise ValueError("profiled sound source changed during secure read")
        return b"".join(chunks)
    finally:
        os.close(descriptor)


def _scale_pcm_frames(frames: bytes, sample_width: int, factor: float) -> bytes:
    """Scale little-endian PCM while preserving the WAV sample representation."""

    if sample_width == 1:
        # 8-bit PCM WAV samples are unsigned and centered at 128.
        return bytes(
            max(0, min(255, 128 + int((sample - 128) * factor)))
            for sample in frames
        )
    if sample_width not in {2, 3, 4}:
        raise ValueError("unsupported PCM WAV sample width")
    if len(frames) % sample_width:
        raise ValueError("misaligned PCM WAV frames")

    bits = sample_width * 8
    minimum = -(1 << (bits - 1))
    maximum = (1 << (bits - 1)) - 1
    scaled = bytearray()
    for offset in range(0, len(frames), sample_width):
        sample = int.from_bytes(
            frames[offset : offset + sample_width],
            "little",
            signed=True,
        )
        value = max(minimum, min(maximum, int(sample * factor)))
        scaled.extend(value.to_bytes(sample_width, "little", signed=True))
    return bytes(scaled)


class ProfiledWindowsSoundPlaybackAdapter:
    def __init__(
        self,
        packaged: PackagedSoundAssetResolver,
        installed: FilesystemSoundPackStore,
        *,
        cache_dir: str | Path,
        classic_pack_id: str = "classic",
        logger: logging.Logger | None = None,
    ) -> None:
        if not isinstance(packaged, PackagedSoundAssetResolver):
            raise TypeError("packaged must be PackagedSoundAssetResolver")
        if not isinstance(installed, FilesystemSoundPackStore):
            raise TypeError("installed must be FilesystemSoundPackStore")
        if not isinstance(classic_pack_id, str) or not classic_pack_id.strip():
            raise TypeError("classic_pack_id must be non-empty text")
        self._packaged = packaged
        self._installed = installed
        self._cache_dir = Path(cache_dir)
        self._classic = classic_pack_id.strip()
        self._logger = logger or logging.getLogger(__name__)
        self._play_lock = _cache_process_lock(self._cache_dir)

    def _classic_event(self, request: SoundAssetRequest) -> SoundEvent:
        if request.pack_id != self._classic:
            raise ValueError("request is not for the configured classic pack")
        if request.event_id == "low_time":
            try:
                low_time = SoundEvent("low_time")
            except ValueError:
                # The packaged-sound owner may not yet be present in the current
                # Product base. Preserve the legacy preview-only Tick bridge
                # without inventing a second clock/semantic authority here.
                if not request.preview:
                    raise ValueError(
                        "classic low-time is preview-only until the packaged sound "
                        "authority exposes a distinct low_time event"
                    )
                if request.sound_id not in {"low_time", "tick"}:
                    raise ValueError(
                        "classic low-time preview cannot select an arbitrary asset"
                    )
                return SoundEvent.TICK
            if request.sound_id != "low_time":
                raise ValueError(
                    "classic low-time sound_id must use the canonical low_time asset"
                )
            return low_time
        try:
            event = SoundEvent(request.event_id)
        except ValueError as exc:
            raise ValueError("classic pack does not own this sound event") from exc
        if request.sound_id != request.event_id:
            raise ValueError("classic pack sound_id must equal the semantic event id")
        return event

    def _resolve(
        self,
        request: SoundAssetRequest,
    ) -> tuple[Path | SoundPackAssetSnapshot, str]:
        if request.pack_id == self._classic:
            # Keep the shipped packaged manifest as the sole classic authority.
            event = self._classic_event(request)
            return self._packaged.resolve(event), f"classic-{event.value}"
        manifest = self._installed.installed_manifest(request.pack_id)
        if manifest is None:
            raise FileNotFoundError("selected sound pack is unavailable")
        if request.sound_id not in manifest.files:
            if request.sound_id != request.event_id:
                raise FileNotFoundError("selected sound-pack asset is unavailable")
            try:
                fallback_event = SoundEvent(request.event_id)
            except ValueError as exc:
                raise FileNotFoundError(
                    "selected sound-pack asset is unavailable"
                ) from exc
            return (
                self._packaged.resolve(fallback_event),
                f"classic-fallback-{fallback_event.value}",
            )
        snapshot = self._installed.read_asset_snapshot(
            request.pack_id,
            request.sound_id,
        )
        if snapshot is None:
            # The manifest declared this asset. Missing/unreadable bytes are an
            # integrity failure and must never be masked by classic fallback.
            raise FileNotFoundError("selected sound-pack asset is unavailable")
        if Path(snapshot.relative_path).suffix.casefold() != ".wav":
            raise ValueError("Windows profile playback currently requires WAV assets")
        key = hashlib.sha256(
            f"{request.pack_id}\0{request.sound_id}".encode("utf-8")
        ).hexdigest()[:24]
        return snapshot, f"custom-{key}"

    def play_sound(self, request: SoundAssetRequest) -> None:
        if not isinstance(request, SoundAssetRequest):
            raise TypeError("request must be SoundAssetRequest")
        if sys.platform != "win32":
            raise RuntimeError("profiled Windows sound playback requires win32")
        if request.volume == 0:
            return
        try:
            # Synchronous playback plus cache pruning must be one adapter-level
            # critical section. Otherwise a concurrent pack update/play can prune
            # a content-addressed file after another call resolves it but before
            # winsound opens it.
            with self._exclusive_playback():
                source, cache_key = self._resolve(request)
                if isinstance(source, SoundPackAssetSnapshot):
                    # The store revalidated the exact descriptor bytes against the
                    # active manifest digest. Never reopen its pathname here.
                    playable = self._scaled_bytes(
                        source.content,
                        cache_key,
                        request.volume,
                    )
                else:
                    playable = self._scaled_copy(source, cache_key, request.volume)
                import winsound

                winsound.PlaySound(
                    str(playable),
                    winsound.SND_FILENAME | winsound.SND_NODEFAULT,
                )
        except Exception as exc:
            self._logger.error(
                "profiled sound playback failed pack=%s event=%s error_type=%s",
                request.pack_id,
                request.event_id,
                type(exc).__name__,
            )
            raise

    @property
    def _cache_lock_path(self) -> Path:
        return self._cache_dir / ".playback.lock"

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
            raise RuntimeError("profiled sound cache is busy") from exc

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

    def _open_cache_lock_descriptor(self) -> int:
        path = self._cache_lock_path
        try:
            metadata = os.lstat(path)
        except FileNotFoundError:
            metadata = None
        except OSError as exc:
            raise RuntimeError("profiled sound cache lock is unavailable") from exc
        if metadata is not None:
            reparse_flag = getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0)
            attributes = getattr(metadata, "st_file_attributes", 0)
            if (
                stat.S_ISLNK(metadata.st_mode)
                or bool(reparse_flag and attributes & reparse_flag)
                or not stat.S_ISREG(metadata.st_mode)
            ):
                raise RuntimeError("profiled sound cache lock is not a regular file")

        flags = os.O_RDWR | os.O_CREAT
        flags |= getattr(os, "O_BINARY", 0)
        flags |= getattr(os, "O_NOINHERIT", 0)
        flags |= getattr(os, "O_CLOEXEC", 0)
        flags |= getattr(os, "O_NOFOLLOW", 0)
        flags |= getattr(os, "O_NONBLOCK", 0)
        try:
            descriptor = os.open(path, flags, 0o600)
        except OSError as exc:
            raise RuntimeError("profiled sound cache lock is unavailable") from exc
        try:
            opened = os.fstat(descriptor)
            reparse_flag = getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0)
            attributes = getattr(opened, "st_file_attributes", 0)
            if (
                stat.S_ISLNK(opened.st_mode)
                or bool(reparse_flag and attributes & reparse_flag)
                or not stat.S_ISREG(opened.st_mode)
            ):
                raise RuntimeError("profiled sound cache lock is not a regular file")
            if (
                metadata is not None
                and _regular_file_identity(opened) != _regular_file_identity(metadata)
            ):
                raise RuntimeError(
                    "profiled sound cache lock changed before secure open"
                )
            if opened.st_size == 0:
                os.write(descriptor, b"\0")
                os.fsync(descriptor)
            return descriptor
        except BaseException:
            os.close(descriptor)
            raise

    @contextmanager
    def _exclusive_playback(self):
        with self._play_lock:
            self._ensure_real_cache_dir()
            descriptor = self._open_cache_lock_descriptor()
            acquired = False
            try:
                self._lock_descriptor(descriptor)
                acquired = True
                _require_real_cache_directory_chain(self._cache_dir)
                yield
            finally:
                if acquired:
                    self._unlock_descriptor(descriptor)
                os.close(descriptor)

    def _ensure_real_cache_dir(self) -> None:
        _require_real_cache_directory_chain(self._cache_dir.parent)
        if not os.path.lexists(self._cache_dir):
            self._cache_dir.mkdir(parents=True, exist_ok=True)
        _require_real_cache_directory_chain(self._cache_dir)

    def _scaled_copy(self, source: Path, cache_key: str, volume: int) -> Path:
        """Return an exact, content-addressed scaled WAV snapshot.

        Installed pack updates and release extraction may preserve or move mtimes
        backwards, so timestamp-based cache reuse can serve audio derived from old
        bytes. Read the source exactly once, bind cache identity to those bytes and
        publish the derived WAV atomically.
        """

        self._ensure_real_cache_dir()
        source_bytes = _read_verified_source_bytes(source)
        return self._scaled_bytes(source_bytes, cache_key, volume)

    def _scaled_bytes(
        self,
        source_bytes: bytes,
        cache_key: str,
        volume: int,
    ) -> Path:
        self._ensure_real_cache_dir()
        source_digest = hashlib.sha256(source_bytes).hexdigest()
        destination = self._cache_dir / (
            f"{cache_key}-v{volume}-s{PROFILED_SCALED_SOUND_CACHE_FORMAT_VERSION}-"
            f"{source_digest}.wav"
        )

        with wave.open(io.BytesIO(source_bytes), "rb") as reader:
            params = reader.getparams()
            frames = reader.readframes(reader.getnframes())
        expected_frame_bytes = params.nframes * params.nchannels * params.sampwidth
        if len(frames) != expected_frame_bytes:
            raise ValueError("truncated PCM WAV asset")

        scaled = _scale_pcm_frames(
            frames,
            params.sampwidth,
            volume / 100.0,
        )

        if destination.is_file() and self._cached_scaled_wave_is_valid(
            destination,
            params,
            scaled,
        ):
            self._prune_scaled_variants(destination, cache_key, volume)
            return destination

        descriptor, temporary_name = tempfile.mkstemp(
            dir=self._cache_dir,
            prefix=f".{destination.name}.",
            suffix=".tmp",
        )
        os.close(descriptor)
        temporary = Path(temporary_name)
        try:
            with wave.open(str(temporary), "wb") as writer:
                writer.setparams(params)
                writer.writeframes(scaled)
            os.replace(temporary, destination)
        finally:
            try:
                temporary.unlink()
            except FileNotFoundError:
                pass
            except OSError as exc:
                self._logger.warning(
                    "could not remove temporary profiled sound cache file error_type=%s",
                    type(exc).__name__,
                )

        self._prune_scaled_variants(destination, cache_key, volume)
        return destination

    @staticmethod
    def _cached_scaled_wave_is_valid(
        destination: Path,
        expected_params,
        expected_frames: bytes,
    ) -> bool:
        try:
            before = os.lstat(destination)
            if (
                stat.S_ISLNK(before.st_mode)
                or _is_reparse_point(before)
                or not stat.S_ISREG(before.st_mode)
            ):
                return False
            flags = os.O_RDONLY
            flags |= getattr(os, "O_BINARY", 0)
            flags |= getattr(os, "O_NOINHERIT", 0)
            flags |= getattr(os, "O_CLOEXEC", 0)
            flags |= getattr(os, "O_NOFOLLOW", 0)
            flags |= getattr(os, "O_NONBLOCK", 0)
            descriptor = os.open(destination, flags)
        except OSError:
            return False

        try:
            opened = os.fstat(descriptor)
            if (
                stat.S_ISLNK(opened.st_mode)
                or _is_reparse_point(opened)
                or not stat.S_ISREG(opened.st_mode)
                or _regular_file_identity(opened) != _regular_file_identity(before)
            ):
                return False
            with os.fdopen(descriptor, "rb", closefd=False) as stream:
                with wave.open(stream, "rb") as reader:
                    params = reader.getparams()
                    if params != expected_params:
                        return False
                    frames = reader.readframes(reader.getnframes())
            after = os.fstat(descriptor)
            if _regular_file_identity(after) != _regular_file_identity(opened):
                return False
        except (EOFError, OSError, ValueError, struct.error, wave.Error):
            return False
        finally:
            os.close(descriptor)
        return frames == expected_frames

    def _prune_scaled_variants(
        self,
        destination: Path,
        cache_key: str,
        volume: int,
    ) -> None:
        legacy = self._cache_dir / f"{cache_key}-v{volume}.wav"
        pattern = f"{cache_key}-v{volume}-*.wav"
        for candidate in (legacy, *self._cache_dir.glob(pattern)):
            if candidate == destination:
                continue
            try:
                candidate.unlink()
            except FileNotFoundError:
                continue
            except OSError as exc:
                self._logger.warning(
                    "could not prune stale profiled sound cache file error_type=%s",
                    type(exc).__name__,
                )


__all__ = ["ProfiledWindowsSoundPlaybackAdapter"]
