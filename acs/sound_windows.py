from __future__ import annotations

"""Windows infrastructure adapter for packaged Accessible Chess sound assets.

This module is intentionally outside chess/domain contracts. It owns filesystem
layout, WAV scaling/cache and ``winsound`` usage. Worker 4 packages the assets and
runs the real Windows smoke; Core only defines the exact contract.
"""

import hashlib
import io
import json
import logging
import os
import struct
import sys
import tempfile
import wave
from dataclasses import dataclass
from pathlib import Path, PurePosixPath

from .sound_events import SoundEvent


SOUND_MANIFEST_SCHEMA_VERSION = 1
DEFAULT_SOUND_RELATIVE_DIR = Path("assets") / "sounds"
DEFAULT_SOUND_MANIFEST = "manifest.json"
DEFAULT_SOUND_VARIANTS_MANIFEST = "variants.json"
SOUND_VARIANTS_SCHEMA_VERSION = 1
DEFAULT_SOUND_LAYERS_MANIFEST = "layers.json"
SOUND_LAYERS_SCHEMA_VERSION = 1
REQUIRED_SOUND_EVENTS = tuple(SoundEvent)
SCALED_SOUND_CACHE_FORMAT_VERSION = 1
ASYNC_SOUND_EVENTS = frozenset({SoundEvent.START, SoundEvent.TICK, SoundEvent.LOW_TIME})


@dataclass(frozen=True)
class PackagedSoundManifest:
    root: Path
    files: dict[SoundEvent, Path]


@dataclass(frozen=True)
class SoundVariantOption:
    variant_id: str
    label_uk: str
    label_en: str
    path: Path


class PackagedSoundAssetResolver:
    """Resolve immutable packaged sound assets from an application directory.

    Packaging contract:
      <application_dir>/assets/sounds/manifest.json
      <application_dir>/assets/sounds/<declared wav files>

    The manifest is JSON schema 1:
      {"schema_version": 1, "files": {"move": "move.wav", ...}}
    Every ``SoundEvent`` including ``tick`` is mandatory. Missing or unsafe paths
    are explicit errors; there is no generated/system-sound fallback.
    """

    def __init__(self, application_dir: str | Path) -> None:
        self.application_dir = Path(application_dir)
        self.root = self.application_dir / DEFAULT_SOUND_RELATIVE_DIR

    def load_manifest(self) -> PackagedSoundManifest:
        manifest_path = self.root / DEFAULT_SOUND_MANIFEST
        if not manifest_path.is_file():
            raise FileNotFoundError(f"sound manifest missing: {manifest_path}")
        raw = json.loads(manifest_path.read_text(encoding="utf-8"))
        if raw.get("schema_version") != SOUND_MANIFEST_SCHEMA_VERSION:
            raise ValueError("unsupported sound manifest schema")
        mapping = raw.get("files")
        if not isinstance(mapping, dict):
            raise ValueError("sound manifest files must be an object")

        files: dict[SoundEvent, Path] = {}
        for event in REQUIRED_SOUND_EVENTS:
            value = mapping.get(event.value)
            if not isinstance(value, str) or not value.strip():
                raise ValueError(f"sound manifest missing event: {event.value}")
            if "\\" in value or "\x00" in value:
                raise ValueError(f"unsafe sound asset path for {event.value}")
            relative = PurePosixPath(value)
            if relative.is_absolute() or ".." in relative.parts or relative.as_posix() != value:
                raise ValueError(f"unsafe sound asset path for {event.value}")
            path = self.root.joinpath(*relative.parts).resolve()
            root = self.root.resolve()
            if root not in path.parents and path != root:
                raise ValueError(f"sound asset escapes packaged root: {event.value}")
            if path.suffix.casefold() != ".wav":
                raise ValueError(f"sound asset must be WAV: {event.value}")
            if not path.is_file():
                raise FileNotFoundError(f"sound asset missing for {event.value}: {path}")
            files[event] = path
        return PackagedSoundManifest(self.root, files)

    @staticmethod
    def _variant_id(value: object) -> str:
        if not isinstance(value, str):
            raise TypeError("sound variant id must be text")
        token = value.strip()
        if (
            not token
            or len(token) > 40
            or token != value
            or any(not (character.isalnum() or character in {"-", "_"}) for character in token)
        ):
            raise ValueError("sound variant id is invalid")
        return token

    def _variant_path(self, value: object, *, label: str) -> Path:
        if not isinstance(value, str) or not value.strip():
            raise ValueError(f"sound variant file is invalid: {label}")
        if "\\" in value or "\x00" in value:
            raise ValueError(f"unsafe sound variant path: {label}")
        relative = PurePosixPath(value)
        if relative.is_absolute() or ".." in relative.parts or relative.as_posix() != value:
            raise ValueError(f"unsafe sound variant path: {label}")
        path = self.root.joinpath(*relative.parts).resolve()
        root = self.root.resolve()
        if root not in path.parents and path != root:
            raise ValueError(f"sound variant escapes packaged root: {label}")
        if path.suffix.casefold() != ".wav":
            raise ValueError(f"sound variant must be WAV: {label}")
        if not path.is_file():
            raise FileNotFoundError(f"sound variant missing: {label}: {path}")
        return path

    def load_variant_catalog(self) -> dict[SoundEvent, tuple[SoundVariantOption, ...]]:
        manifest = self.load_manifest()
        path = self.root / DEFAULT_SOUND_VARIANTS_MANIFEST
        if not path.is_file():
            return {
                event: (
                    SoundVariantOption(
                        "1",
                        "Варіант 1",
                        "Variant 1",
                        manifest.files[event],
                    ),
                )
                for event in REQUIRED_SOUND_EVENTS
            }

        raw = json.loads(path.read_text(encoding="utf-8-sig"))
        if not isinstance(raw, dict) or raw.get("schema_version") != SOUND_VARIANTS_SCHEMA_VERSION:
            raise ValueError("unsupported sound variants schema")
        events = raw.get("events")
        if not isinstance(events, dict):
            raise ValueError("sound variants events must be an object")
        expected = {event.value for event in REQUIRED_SOUND_EVENTS}
        if set(events) != expected:
            raise ValueError("sound variants must declare exactly all semantic sound events")

        catalog: dict[SoundEvent, tuple[SoundVariantOption, ...]] = {}
        for event in REQUIRED_SOUND_EVENTS:
            raw_options = events[event.value]
            if not isinstance(raw_options, list) or not raw_options or len(raw_options) > 32:
                raise ValueError(f"sound variants are invalid for {event.value}")
            options: list[SoundVariantOption] = []
            seen: set[str] = set()
            for item in raw_options:
                if not isinstance(item, dict) or set(item) != {"id", "file", "label_uk", "label_en"}:
                    raise ValueError(f"sound variant entry is invalid for {event.value}")
                variant_id = self._variant_id(item["id"])
                if variant_id in seen:
                    raise ValueError(f"duplicate sound variant id for {event.value}")
                seen.add(variant_id)
                label_uk = item["label_uk"]
                label_en = item["label_en"]
                if (
                    not isinstance(label_uk, str)
                    or not label_uk.strip()
                    or len(label_uk) > 120
                    or not isinstance(label_en, str)
                    or not label_en.strip()
                    or len(label_en) > 120
                ):
                    raise ValueError(f"sound variant label is invalid for {event.value}")
                options.append(
                    SoundVariantOption(
                        variant_id,
                        label_uk.strip(),
                        label_en.strip(),
                        self._variant_path(item["file"], label=f"{event.value}/{variant_id}"),
                    )
                )
            by_id = {option.variant_id: option for option in options}
            if "1" not in by_id:
                raise ValueError(f"sound variants require default id 1 for {event.value}")
            if by_id["1"].path != manifest.files[event]:
                raise ValueError(f"sound variant 1 must match default manifest file for {event.value}")
            catalog[event] = tuple(options)
        return catalog

    def variants_for(self, event: SoundEvent) -> tuple[SoundVariantOption, ...]:
        if not isinstance(event, SoundEvent):
            raise TypeError("sound event must be SoundEvent")
        return self.load_variant_catalog()[event]

    def resolve(self, event: SoundEvent, *, variant_id: str | None = None) -> Path:
        if not isinstance(event, SoundEvent):
            raise TypeError("sound event must be SoundEvent")
        token = "1" if variant_id is None else self._variant_id(variant_id)
        for option in self.variants_for(event):
            if option.variant_id == token:
                return option.path
        raise KeyError(f"unknown sound variant for {event.value}: {token}")

    def load_layer_catalog(self) -> dict[SoundEvent, dict[str, tuple[Path, ...]]]:
        path = self.root / DEFAULT_SOUND_LAYERS_MANIFEST
        if not path.is_file():
            return {}
        raw = json.loads(path.read_text(encoding="utf-8-sig"))
        if not isinstance(raw, dict) or raw.get("schema_version") != SOUND_LAYERS_SCHEMA_VERSION:
            raise ValueError("unsupported sound layers schema")
        events = raw.get("events")
        if not isinstance(events, dict):
            raise ValueError("sound layers events must be an object")

        expected = {event.value for event in REQUIRED_SOUND_EVENTS}
        if not set(events).issubset(expected):
            raise ValueError("sound layers contain an unknown semantic event")

        variants = self.load_variant_catalog()
        catalog: dict[SoundEvent, dict[str, tuple[Path, ...]]] = {}
        for event_name, raw_variants in events.items():
            event = SoundEvent(event_name)
            if event in ASYNC_SOUND_EVENTS:
                raise ValueError(f"asynchronous sound event cannot be layered: {event.value}")
            if not isinstance(raw_variants, dict) or not raw_variants:
                raise ValueError(f"sound layers are invalid for {event.value}")
            available = {option.variant_id: option.path for option in variants[event]}
            event_layers: dict[str, tuple[Path, ...]] = {}
            for raw_variant_id, raw_sequence in raw_variants.items():
                variant_id = self._variant_id(raw_variant_id)
                if variant_id not in available:
                    raise ValueError(
                        f"sound layer references unknown variant: {event.value}/{variant_id}"
                    )
                if (
                    not isinstance(raw_sequence, list)
                    or not 2 <= len(raw_sequence) <= 4
                ):
                    raise ValueError(
                        f"sound layer sequence is invalid: {event.value}/{variant_id}"
                    )
                sequence = tuple(
                    self._variant_path(
                        value,
                        label=f"{event.value}/{variant_id}/layer-{index + 1}",
                    )
                    for index, value in enumerate(raw_sequence)
                )
                if sequence[0] != available[variant_id]:
                    raise ValueError(
                        f"sound layer must start with its selected variant: "
                        f"{event.value}/{variant_id}"
                    )
                if len(set(sequence)) != len(sequence):
                    raise ValueError(
                        f"sound layer sequence contains duplicate assets: "
                        f"{event.value}/{variant_id}"
                    )
                event_layers[variant_id] = sequence
            catalog[event] = event_layers
        return catalog

    def resolve_sequence(
        self,
        event: SoundEvent,
        *,
        variant_id: str | None = None,
    ) -> tuple[Path, ...]:
        if not isinstance(event, SoundEvent):
            raise TypeError("sound event must be SoundEvent")
        token = "1" if variant_id is None else self._variant_id(variant_id)
        primary = self.resolve(event, variant_id=token)
        return self.load_layer_catalog().get(event, {}).get(token, (primary,))


class WindowsSoundPlaybackAdapter:
    """Synchronous Windows WAV player implementing ``SoundPlaybackPort``.

    ``SND_NODEFAULT`` is mandatory: a missing/broken file must raise/log, never
    become a Windows system beep. Partial volume is implemented by scaling into a
    writable cache directory; packaged assets remain immutable.
    """

    def __init__(
        self,
        resolver: PackagedSoundAssetResolver,
        *,
        cache_dir: str | Path,
        variant_provider=None,
        logger: logging.Logger | None = None,
    ) -> None:
        if variant_provider is not None and not callable(variant_provider):
            raise TypeError("variant_provider must be callable or None")
        self._resolver = resolver
        self._cache_dir = Path(cache_dir)
        self._variant_provider = variant_provider
        self._logger = logger or logging.getLogger(__name__)

    def play(self, event: SoundEvent, *, volume: int) -> None:
        if sys.platform != "win32":
            raise RuntimeError("Windows sound playback adapter requires win32")
        if isinstance(volume, bool) or not isinstance(volume, int) or not 0 <= volume <= 100:
            raise ValueError("volume must be in 0..100")
        if volume == 0:
            return

        try:
            variant_id = None
            if self._variant_provider is not None:
                variant_id = self._variant_provider(event)
                if not isinstance(variant_id, str):
                    raise TypeError("sound variant provider must return text")
            resolve_sequence = getattr(self._resolver, "resolve_sequence", None)
            if callable(resolve_sequence):
                sources = (
                    resolve_sequence(event)
                    if variant_id is None
                    else resolve_sequence(event, variant_id=variant_id)
                )
            else:
                source = (
                    self._resolver.resolve(event)
                    if variant_id is None
                    else self._resolver.resolve(event, variant_id=variant_id)
                )
                sources = (source,)

            if not sources:
                raise ValueError("sound playback sequence cannot be empty")
            if event in ASYNC_SOUND_EVENTS and len(sources) != 1:
                raise ValueError("asynchronous sound events cannot use layered playback")

            import winsound

            # Mechanical move/capture cues may consist of a short movement cue
            # followed by the original landing/impact WAV.  Play those layers
            # synchronously and in declared order. NEWGAME and Tick remain
            # single multi-second asynchronous assets so the keyboard/UI stays
            # responsive while Windows owns playback.
            flags = winsound.SND_FILENAME | winsound.SND_NODEFAULT
            if event in ASYNC_SOUND_EVENTS:
                flags |= winsound.SND_ASYNC
            for source in sources:
                playable = (
                    source
                    if volume == 100
                    else self._scaled_copy(source, event, volume)
                )
                winsound.PlaySound(str(playable), flags)
        except Exception:
            self._logger.exception("chess sound playback failed for event=%s", event.value)
            raise

    def stop(self) -> None:
        """Stop the currently playing Windows WAV, if any."""

        if sys.platform != "win32":
            return
        try:
            import winsound

            winsound.PlaySound(None, 0)
        except Exception:
            self._logger.exception("could not stop current chess sound")
            raise

    def _scaled_copy(self, source: Path, event: SoundEvent, volume: int) -> Path:
        self._cache_dir.mkdir(parents=True, exist_ok=True)

        # Cache identity must follow the actual packaged bytes, not filesystem
        # timestamps. Release extraction, pack replacement and restore can
        # legitimately preserve or move mtimes backwards.
        source_bytes = source.read_bytes()
        source_digest = hashlib.sha256(source_bytes).hexdigest()
        try:
            resolver_root = Path(self._resolver.root).resolve()
            source_identity = source.resolve().relative_to(resolver_root).as_posix().casefold()
        except (AttributeError, TypeError, ValueError):
            source_identity = str(source.resolve()).casefold()
        source_key = hashlib.sha256(
            source_identity.encode("utf-8")
        ).hexdigest()[:16]
        destination = self._cache_dir / (
            f"{event.value}-v{volume}-a{source_key}-"
            f"s{SCALED_SOUND_CACHE_FORMAT_VERSION}-{source_digest}.wav"
        )
        with wave.open(io.BytesIO(source_bytes), "rb") as reader:
            params = reader.getparams()
            if params.comptype != "NONE" or params.sampwidth not in {1, 2}:
                raise ValueError("only 8-bit or 16-bit PCM WAV assets support volume scaling")
            frames = reader.readframes(reader.getnframes())
        expected_frame_bytes = params.nframes * params.nchannels * params.sampwidth
        if len(frames) != expected_frame_bytes:
            raise ValueError("truncated PCM WAV asset")

        factor = volume / 100.0
        if params.sampwidth == 1:
            # 8-bit PCM WAV samples are unsigned with silence centred at 128.
            scaled = bytes(
                max(0, min(255, int(round(128 + (sample - 128) * factor))))
                for sample in frames
            )
        else:
            samples = struct.unpack("<" + "h" * (len(frames) // 2), frames)
            scaled = b"".join(
                struct.pack("<h", max(-32768, min(32767, int(sample * factor))))
                for sample in samples
            )
        if destination.is_file() and self._cached_scaled_wave_is_valid(
            destination,
            params,
            scaled,
        ):
            self._prune_scaled_variants(destination, event, volume, source_key)
            return destination
        fd, temporary_name = tempfile.mkstemp(
            dir=self._cache_dir,
            prefix=f".{destination.name}.",
            suffix=".tmp",
        )
        os.close(fd)
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
            except OSError:
                # Temporary-cache cleanup is housekeeping. In particular, a
                # short Windows file lock must not replace the primary scaling
                # or publication exception with a less useful cleanup error.
                self._logger.warning(
                    "could not remove temporary chess sound cache file: %s",
                    temporary,
                    exc_info=True,
                )
        self._prune_scaled_variants(destination, event, volume, source_key)
        return destination

    @staticmethod
    def _cached_scaled_wave_is_valid(
        destination: Path,
        expected_params,
        expected_frames: bytes,
    ) -> bool:
        """Return whether an existing derived WAV exactly matches this transform."""

        try:
            with wave.open(str(destination), "rb") as reader:
                params = reader.getparams()
                if params != expected_params:
                    return False
                frames = reader.readframes(reader.getnframes())
        except (EOFError, OSError, ValueError, struct.error, wave.Error):
            return False
        return frames == expected_frames

    def _prune_scaled_variants(
        self,
        destination: Path,
        event: SoundEvent,
        volume: int,
        source_key: str,
    ) -> None:
        """Best-effort removal of superseded content-addressed cache variants."""

        # Remove the legacy single-file cache and obsolete transforms for
        # this exact packaged source path. Other layers of the same semantic
        # event must remain cached: MOVE+MOVEHIT and CAPTURE+CAPHIT are separate
        # source assets that intentionally share one event and volume.
        legacy = self._cache_dir / f"{event.value}-v{volume}.wav"
        old_content_addressed = tuple(
            self._cache_dir.glob(f"{event.value}-v{volume}-s*-*.wav")
        )
        same_source = tuple(
            self._cache_dir.glob(
                f"{event.value}-v{volume}-a{source_key}-*.wav"
            )
        )
        for candidate in (legacy, *old_content_addressed, *same_source):
            if candidate == destination:
                continue
            try:
                candidate.unlink()
            except FileNotFoundError:
                continue
            except OSError:
                # Cache housekeeping must never turn successful playback into a
                # product failure. The stale entry can be retried next time.
                self._logger.warning(
                    "could not prune stale chess sound cache file: %s",
                    candidate,
                    exc_info=True,
                )
