from __future__ import annotations

"""Build the canonical Accessible Chess sound pack from the user-supplied archive tree.

The input may be either an extracted directory containing a Sounds directory
(directly or below one wrapper directory) or a ZIP produced from that exact
source. ZIP input is extracted through a bounded, path-safe reader before the
same canonical inventory validation is applied. Every WAV from the supplied
archive is copied into the pack so no legacy procedural audio is needed at runtime.
"""

import argparse
import hashlib
import json
import shutil
import tempfile
import wave
import zipfile
from pathlib import Path, PurePosixPath


DEFAULT_EVENT_FILES = {
    "move": "library/Board/MOVE.WAV",
    "capture": "library/Board/CAPTURE.WAV",
    "check": "library/Russian/Notation/Check.wav",
    "castle": "library/Board/castle.wav",
    "promotion": "library/Board/MOVEHIT1.WAV",
    "illegal": "library/Board/illegal.wav",
    "start": "library/Board/NEWGAME.WAV",
    "end": "library/Server/Gong.WAV",
    "mate": "library/Server/Gong.WAV",
    "draw": "library/Server/Gong.WAV",
    "tick": "library/Board/Tick.wav",
    "low_time": "library/Server/aooga.wav",
}

EVENT_VARIANTS = {
    "move": (
        ("1", "library/Board/MOVE.WAV", "Хід 1", "Move 1"),
        ("2", "library/Board/MOVE2.WAV", "Хід 2", "Move 2"),
        ("3", "library/Board/MOVE3.WAV", "Хід 3", "Move 3"),
        ("4", "library/Board/MOVE4.WAV", "Хід 4", "Move 4"),
        ("5", "library/Board/move5.wav", "Хід 5", "Move 5"),
        ("6", "library/Board/move6.wav", "Хід 6", "Move 6"),
        ("3d-1", "library/Board3d/MOVE.WAV", "Хід 3D 1", "3D move 1"),
        ("3d-2", "library/Board3d/MOVE2.WAV", "Хід 3D 2", "3D move 2"),
        ("3d-3", "library/Board3d/MOVE3.WAV", "Хід 3D 3", "3D move 3"),
    ),
    "capture": (
        ("1", "library/Board/CAPTURE.WAV", "Взяття 1", "Capture 1"),
        ("2", "library/Board/CAPTURE2.WAV", "Взяття 2", "Capture 2"),
        ("3", "library/Board/CAPTURE3.WAV", "Взяття 3", "Capture 3"),
        ("4", "library/Board/capture4.wav", "Взяття 4", "Capture 4"),
        ("5", "library/Board/capture5.wav", "Взяття 5", "Capture 5"),
        ("3d-1", "library/Board3d/CAPTURE.WAV", "Взяття 3D 1", "3D capture 1"),
        ("3d-2", "library/Board3d/CAPTURE2.WAV", "Взяття 3D 2", "3D capture 2"),
        ("3d-3", "library/Board3d/CAPTURE3.WAV", "Взяття 3D 3", "3D capture 3"),
        ("3d-4", "library/Board3d/capture4.wav", "Взяття 3D 4", "3D capture 4"),
    ),
    "check": (
        ("1", "library/Russian/Notation/Check.wav", "Шах — голос", "Check — voice"),
    ),
    "castle": (
        ("1", "library/Board/castle.wav", "Рокірування", "Castling"),
    ),
    "promotion": (
        ("1", "library/Board/MOVEHIT1.WAV", "Перетворення 1", "Promotion 1"),
        ("2", "library/Board/MOVEHIT2.WAV", "Перетворення 2", "Promotion 2"),
        ("3", "library/Board/MOVEHIT3.WAV", "Перетворення 3", "Promotion 3"),
    ),
    "illegal": (
        ("1", "library/Board/illegal.wav", "Нелегальний хід", "Illegal move"),
        ("3d", "library/Board3d/illegal.wav", "Нелегальний хід 3D", "3D illegal move"),
    ),
    "start": (
        ("1", "library/Board/NEWGAME.WAV", "Нова партія", "New game"),
        ("3d", "library/Board3d/NEWGAME.WAV", "Нова партія 3D", "3D new game"),
    ),
    "end": (
        ("1", "library/Server/Gong.WAV", "Кінець партії — гонг", "Game end — gong"),
    ),
    "mate": (
        ("1", "library/Server/Gong.WAV", "Мат — гонг", "Checkmate — gong"),
        ("ru", "library/Russian/Notation/Mate.wav", "Мат — голос (рос.)", "Checkmate — Russian voice"),
    ),
    "draw": (
        ("1", "library/Server/Gong.WAV", "Нічия — гонг", "Draw — gong"),
        ("en", "library/English/Draw.wav", "Нічия — голос (англ.)", "Draw — English voice"),
        ("ru", "library/Russian/Draw.wav", "Нічия — голос (рос.)", "Draw — Russian voice"),
    ),
    "tick": (
        ("1", "library/Board/Tick.wav", "Годинник", "Clock"),
        ("3d", "library/Board3d/Tick.wav", "Годинник 3D", "3D clock"),
    ),
    "low_time": (
        ("1", "library/Server/aooga.wav", "Мало часу — сигнал 1", "Low time — alert 1"),
        ("2", "library/Server/ping.wav", "Мало часу — сигнал 2", "Low time — alert 2"),
    ),
}

PROVENANCE_SOURCE = "urn:accessible-chess:user-upload:sound-archive:2026-10-03"
PROVENANCE_LICENSE = "USER_PROVIDED"
PROVENANCE_CREATOR = "User-provided legacy chess sound archive"
EXPECTED_SOURCE_WAV_COUNT = 330
EXPECTED_SOURCE_INVENTORY_SHA256 = "41f3223040e0720b2268e5c28f3ccec140a4f9d3386c12ffa7a82fc283a1f920"
NEW_GAME_IMPACT_MS = (
    160, 374, 748, 853, 1112, 1302, 1427, 1532,
    1766, 1906, 2504, 2599, 2869, 3143, 3751, 4106,
    4455, 4600, 4804, 4904, 5148, 5647, 5792, 5897,
    6276, 6455, 6610, 7074, 7588, 7797, 8062, 8231,
)
NEW_GAME_3D_IMPACT_MS = (
    145, 254, 424, 549, 698, 848, 943, 1048,
    1287, 1402, 1566, 1751, 1876, 2075, 2185, 2669,
    3098, 3522, 3766, 4021, 4200, 4505, 5158, 5907,
    6121, 6415, 6620, 6959, 7278, 7418, 7907, 8012,
)
NEW_GAME_IMPACTS_BY_VARIANT = {
    "1": NEW_GAME_IMPACT_MS,
    "3d": NEW_GAME_3D_IMPACT_MS,
}
NEW_GAME_DURATION_SECONDS_BY_VARIANT = {
    "1": 8.521723,
    "3d": 8.270045,
}

SOUND_LAYERS = {
    "move": {
        "1": ("library/Board/MOVE.WAV", "library/Board/MOVEHIT1.WAV"),
        "2": ("library/Board/MOVE2.WAV", "library/Board/MOVEHIT2.WAV"),
        "3": ("library/Board/MOVE3.WAV", "library/Board/MOVEHIT3.WAV"),
        "3d-1": ("library/Board3d/MOVE.WAV", "library/Board3d/MOVEHIT1.WAV"),
        "3d-2": ("library/Board3d/MOVE2.WAV", "library/Board3d/MOVEHIT2.WAV"),
        "3d-3": ("library/Board3d/MOVE3.WAV", "library/Board3d/MOVEHIT3.WAV"),
    },
    "capture": {
        "1": ("library/Board/CAPTURE.WAV", "library/Board/CAPHIT1.WAV"),
        "2": ("library/Board/CAPTURE2.WAV", "library/Board/CAPHIT2.WAV"),
        "3": ("library/Board/CAPTURE3.WAV", "library/Board/CAPHIT3.WAV"),
        "3d-1": ("library/Board3d/CAPTURE.WAV", "library/Board3d/CAPHIT1.WAV"),
        "3d-2": ("library/Board3d/CAPTURE2.WAV", "library/Board3d/CAPHIT2.WAV"),
        "3d-3": ("library/Board3d/CAPTURE3.WAV", "library/Board3d/CAPHIT3.WAV"),
    },
}


class SoundPackBuildError(RuntimeError):
    pass


def _validate_new_game_timeline_contract() -> None:
    """Fail closed if NEWGAME impact metadata can no longer drive 32-piece timing."""

    start_variants = {variant_id for variant_id, _file, _uk, _en in EVENT_VARIANTS["start"]}
    if set(NEW_GAME_IMPACTS_BY_VARIANT) != start_variants:
        raise SoundPackBuildError("NEWGAME impact variants do not match selectable start sounds")
    if set(NEW_GAME_DURATION_SECONDS_BY_VARIANT) != start_variants:
        raise SoundPackBuildError("NEWGAME duration variants do not match selectable start sounds")

    for variant_id in sorted(start_variants):
        impacts = NEW_GAME_IMPACTS_BY_VARIANT[variant_id]
        duration = NEW_GAME_DURATION_SECONDS_BY_VARIANT[variant_id]
        if (
            not isinstance(impacts, tuple)
            or len(impacts) != 32
            or any(type(value) is not int or value <= 0 for value in impacts)
            or tuple(sorted(set(impacts))) != impacts
        ):
            raise SoundPackBuildError(
                f"NEWGAME impact timeline must contain 32 strictly increasing millisecond offsets: {variant_id}"
            )
        if isinstance(duration, bool) or not isinstance(duration, (int, float)) or duration <= 0:
            raise SoundPackBuildError(f"NEWGAME duration is invalid: {variant_id}")
        duration_ms = float(duration) * 1000.0
        if impacts[-1] > duration_ms:
            raise SoundPackBuildError(f"NEWGAME final impact exceeds WAV duration: {variant_id}")
        tail_ms = duration_ms - impacts[-1]
        if not 100.0 <= tail_ms <= 350.0:
            raise SoundPackBuildError(
                f"NEWGAME impact timeline is not synchronized to the WAV tail: {variant_id}"
            )


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


MAX_ARCHIVE_MEMBER_COUNT = 2048
MAX_ARCHIVE_BYTES = 128 * 1024 * 1024
MAX_ARCHIVE_UNCOMPRESSED_BYTES = 128 * 1024 * 1024
_WINDOWS_FORBIDDEN_COMPONENT_CHARS = frozenset('<>:"/\\\\|?*')
_WINDOWS_RESERVED_NAMES = {
    "con",
    "prn",
    "aux",
    "nul",
    "conin$",
    "conout$",
    *(f"com{index}" for index in range(1, 10)),
    *(f"lpt{index}" for index in range(1, 10)),
    "com¹",
    "com²",
    "com³",
    "lpt¹",
    "lpt²",
    "lpt³",
}


def _windows_portable_component(part: str) -> str:
    """Validate one path component against the packaged Windows filesystem contract."""

    if type(part) is not str:
        raise SoundPackBuildError("sound-pack path component is not Windows-portable")
    try:
        utf16 = part.encode("utf-16-le", errors="strict")
    except UnicodeEncodeError as exc:
        raise SoundPackBuildError(
            "sound-pack path component is not Windows-portable"
        ) from exc
    device_stem = part.split(".", 1)[0].rstrip(" .").casefold()
    if (
        not part
        or part in {".", ".."}
        or part.rstrip(" .") != part
        or len(utf16) // 2 > 255
        or any(character in _WINDOWS_FORBIDDEN_COMPONENT_CHARS for character in part)
        or any(ord(character) < 32 or ord(character) == 0x7F for character in part)
        or device_stem in _WINDOWS_RESERVED_NAMES
    ):
        raise SoundPackBuildError("sound-pack path component is not Windows-portable")
    return part


def _snapshot_sound_zip(source: Path, destination: Path) -> int:
    total = 0
    try:
        with source.open("rb") as reader, destination.open("xb") as writer:
            while True:
                block = reader.read(1024 * 1024)
                if not block:
                    break
                total += len(block)
                if total > MAX_ARCHIVE_BYTES:
                    raise SoundPackBuildError(
                        "sound-pack ZIP exceeds the compressed size limit"
                    )
                writer.write(block)
    except SoundPackBuildError:
        raise
    except OSError as exc:
        raise SoundPackBuildError("sound-pack ZIP could not be snapshotted") from exc
    if total <= 0:
        raise SoundPackBuildError("sound-pack ZIP is empty")
    return total


def _safe_archive_member(name: str) -> PurePosixPath:
    if not isinstance(name, str) or not name or "\\" in name or "\x00" in name:
        raise SoundPackBuildError("unsafe ZIP member path")
    token = name[:-1] if name.endswith("/") else name
    if not token:
        raise SoundPackBuildError("unsafe ZIP member path")
    relative = PurePosixPath(token)
    if (
        relative.is_absolute()
        or relative.as_posix() != token
        or ".." in relative.parts
    ):
        raise SoundPackBuildError("unsafe ZIP member path")
    for part in relative.parts:
        _windows_portable_component(part)
    return relative


def _extract_sound_zip(source: Path, destination: Path) -> None:
    try:
        archive = zipfile.ZipFile(source, "r")
    except (OSError, zipfile.BadZipFile) as exc:
        raise SoundPackBuildError("invalid sound-pack ZIP") from exc
    with archive:
        members = archive.infolist()
        if len(members) > MAX_ARCHIVE_MEMBER_COUNT:
            raise SoundPackBuildError("sound-pack ZIP has too many entries")
        total = 0
        seen: set[str] = set()
        files: set[str] = set()
        directories: set[str] = set()
        for info in members:
            relative = _safe_archive_member(info.filename)
            folded = relative.as_posix().casefold()
            if folded in seen:
                raise SoundPackBuildError("sound-pack ZIP has duplicate paths")
            seen.add(folded)

            ancestors = tuple(
                PurePosixPath(*relative.parts[:index]).as_posix().casefold()
                for index in range(1, len(relative.parts))
            )
            if any(ancestor in files for ancestor in ancestors):
                raise SoundPackBuildError("sound-pack ZIP has file/directory topology collision")
            directories.update(ancestors)

            unix_mode = (info.external_attr >> 16) & 0o170000
            if unix_mode == 0o120000:
                raise SoundPackBuildError("sound-pack ZIP cannot contain symlinks")
            if info.is_dir():
                if folded in files:
                    raise SoundPackBuildError("sound-pack ZIP has file/directory topology collision")
                directories.add(folded)
                continue
            if folded in directories:
                raise SoundPackBuildError("sound-pack ZIP has file/directory topology collision")
            files.add(folded)
            total += int(info.file_size)
            if total > MAX_ARCHIVE_UNCOMPRESSED_BYTES:
                raise SoundPackBuildError("sound-pack ZIP expands beyond the size limit")
            target = destination.joinpath(*relative.parts)
            target.parent.mkdir(parents=True, exist_ok=True)
            with archive.open(info, "r") as reader, target.open("wb") as writer:
                shutil.copyfileobj(reader, writer, length=1024 * 1024)


def _locate_sounds(source: Path) -> Path:
    source = source.resolve()
    candidates = (
        source,
        source / "Sounds",
        source / "звуки" / "Sounds",
        source / "library",
    )
    for candidate in candidates:
        if (candidate / "Board").is_dir() and (candidate / "Server").is_dir():
            return candidate
    for candidate in source.glob("*/Sounds"):
        if (candidate / "Board").is_dir() and (candidate / "Server").is_dir():
            return candidate.resolve()
    raise SoundPackBuildError("could not locate the extracted Sounds directory")


def _safe_relative(path: Path, root: Path) -> PurePosixPath:
    relative = PurePosixPath(path.relative_to(root).as_posix())
    if relative.is_absolute() or ".." in relative.parts:
        raise SoundPackBuildError("unsafe source sound path")
    for part in relative.parts:
        _windows_portable_component(part)
    return relative


def _wave_info(path: Path) -> dict[str, object]:
    try:
        with wave.open(str(path), "rb") as reader:
            frames = reader.getnframes()
            rate = reader.getframerate()
            return {
                "channels": reader.getnchannels(),
                "sample_width_bytes": reader.getsampwidth(),
                "sample_rate": rate,
                "frames": frames,
                "duration_seconds": round(frames / rate, 6) if rate else 0,
                "compression": reader.getcomptype(),
            }
    except (EOFError, OSError, wave.Error) as exc:
        raise SoundPackBuildError(f"invalid WAV file: {path.name}") from exc


def _validate_event_paths(destination: Path) -> None:
    expected_events = set(DEFAULT_EVENT_FILES)
    if set(EVENT_VARIANTS) != expected_events:
        raise SoundPackBuildError("event variant map is incomplete")
    for event, default_file in DEFAULT_EVENT_FILES.items():
        default_path = destination / Path(default_file)
        if not default_path.is_file():
            raise SoundPackBuildError(f"missing default sound for {event}: {default_file}")
        options = EVENT_VARIANTS[event]
        ids = [item[0] for item in options]
        if not ids or ids[0] != "1" or len(ids) != len(set(ids)):
            raise SoundPackBuildError(f"invalid variant ids for {event}")
        if options[0][1] != default_file:
            raise SoundPackBuildError(f"variant 1 must be the default sound for {event}")
        for _variant_id, file_name, _uk, _en in options:
            path = destination / Path(file_name)
            if not path.is_file():
                raise SoundPackBuildError(f"missing sound variant: {file_name}")
            info = _wave_info(path)
            if info["compression"] != "NONE":
                raise SoundPackBuildError(f"compressed WAV is not supported: {file_name}")
            if info["sample_width_bytes"] not in {1, 2}:
                raise SoundPackBuildError(
                    f"selectable runtime variants must be 8-bit or 16-bit PCM: {file_name}"
                )


def _build_sound_pack_unchecked(
    source: Path,
    destination: Path,
    *,
    expected_source_archive_sha256: str | None = None,
    _source_archive_sha256: str | None = None,
    _source_archive_bytes: int | None = None,
) -> dict[str, object]:
    source = Path(source)
    if source.is_symlink():
        raise SoundPackBuildError("sound-pack source cannot be a symlink")
    if source.is_file():
        if source.suffix.casefold() != ".zip":
            raise SoundPackBuildError("sound-pack source file must be ZIP")
        with tempfile.TemporaryDirectory(prefix="accessible-chess-sounds-") as temp_dir:
            snapshot_root = Path(temp_dir)
            archive_snapshot = snapshot_root / "source.zip"
            archive_bytes = _snapshot_sound_zip(source, archive_snapshot)
            archive_sha256 = _sha256(archive_snapshot)
            if expected_source_archive_sha256 is not None:
                wanted = expected_source_archive_sha256.strip().casefold()
                if len(wanted) != 64 or any(
                    character not in "0123456789abcdef"
                    for character in wanted
                ):
                    raise SoundPackBuildError("expected source archive SHA-256 is invalid")
                if archive_sha256 != wanted:
                    raise SoundPackBuildError(
                        "sound-pack ZIP SHA-256 mismatch: "
                        f"actual={archive_sha256} expected={wanted}"
                    )

            extracted = snapshot_root / "extracted"
            extracted.mkdir()
            _extract_sound_zip(archive_snapshot, extracted)
            return _build_sound_pack_unchecked(
                extracted,
                destination,
                _source_archive_sha256=archive_sha256,
                _source_archive_bytes=archive_bytes,
            )

    sounds = _locate_sounds(source)
    destination = Path(destination)
    if destination.exists():
        raise SoundPackBuildError("destination already exists")
    destination.parent.mkdir(parents=True, exist_ok=True)
    staging = Path(
        tempfile.mkdtemp(
            prefix=f".{destination.name}.building-",
            dir=str(destination.parent),
        )
    )
    try:
        library = staging / "library"
        library.mkdir()

        inventory: list[dict[str, object]] = []
        source_fingerprint_rows: list[bytes] = []
        seen_casefold: set[str] = set()
        for source_path in sorted(sounds.rglob("*"), key=lambda item: item.as_posix().casefold()):
            if source_path.is_symlink():
                raise SoundPackBuildError("sound-pack source tree cannot contain symlinks")
            if not source_path.is_file():
                continue
            relative = _safe_relative(source_path, sounds)
            if source_path.suffix.casefold() != ".wav":
                continue
            folded = relative.as_posix().casefold()
            if folded in seen_casefold:
                raise SoundPackBuildError(f"case-insensitive duplicate sound path: {relative}")
            seen_casefold.add(folded)

            source_digest = _sha256(source_path)
            source_fingerprint_rows.append(
                f"{relative.as_posix()}\0{source_digest}\n".encode("utf-8")
            )

            target = library / Path(*relative.parts)
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(source_path, target)
            info = _wave_info(target)
            inventory.append(
                {
                    "file": f"library/{relative.as_posix()}",
                    "sha256": source_digest,
                    "bytes": target.stat().st_size,
                    **info,
                }
            )

        if len(inventory) != EXPECTED_SOURCE_WAV_COUNT:
            raise SoundPackBuildError(
                f"expected {EXPECTED_SOURCE_WAV_COUNT} WAV files from the supplied archive, "
                f"found {len(inventory)}"
            )
        source_inventory_sha256 = hashlib.sha256(
            b"".join(source_fingerprint_rows)
        ).hexdigest()
        if source_inventory_sha256 != EXPECTED_SOURCE_INVENTORY_SHA256:
            raise SoundPackBuildError(
                "source sound inventory does not match the exact user-supplied archive"
            )

        _validate_event_paths(staging)
        _validate_new_game_timeline_contract()
        for event, by_variant in SOUND_LAYERS.items():
            variants_for_event = {
                variant_id: file_name
                for variant_id, file_name, _uk, _en in EVENT_VARIANTS[event]
            }
            for variant_id, sequence in by_variant.items():
                if variant_id not in variants_for_event:
                    raise SoundPackBuildError(
                        f"sound layer references unknown variant: {event}/{variant_id}"
                    )
                if sequence[0] != variants_for_event[variant_id]:
                    raise SoundPackBuildError(
                        f"sound layer does not start with selected variant: {event}/{variant_id}"
                    )
                for file_name in sequence:
                    layer_path = staging / Path(file_name)
                    if not layer_path.is_file():
                        raise SoundPackBuildError(f"missing layered sound asset: {file_name}")
                    info = _wave_info(layer_path)
                    if info["compression"] != "NONE" or info["sample_width_bytes"] != 2:
                        raise SoundPackBuildError(
                            f"layered runtime sound must be 16-bit PCM: {file_name}"
                        )

        manifest = {
            "schema_version": 1,
            "files": DEFAULT_EVENT_FILES,
        }
        variants = {
            "schema_version": 1,
            "events": {
                event: [
                    {
                        "id": variant_id,
                        "file": file_name,
                        "label_uk": label_uk,
                        "label_en": label_en,
                    }
                    for variant_id, file_name, label_uk, label_en in options
                ]
                for event, options in EVENT_VARIANTS.items()
            },
        }
        layers = {
            "schema_version": 1,
            "events": {
                event: {
                    variant_id: list(sequence)
                    for variant_id, sequence in by_variant.items()
                }
                for event, by_variant in SOUND_LAYERS.items()
            },
        }
        provenance = {
            "schema_version": 1,
            "events": {
                event: {
                    "file": file_name,
                    "sha256": _sha256(staging / Path(file_name)),
                    "license_id": PROVENANCE_LICENSE,
                    "source": PROVENANCE_SOURCE,
                    "creator": PROVENANCE_CREATOR,
                }
                for event, file_name in DEFAULT_EVENT_FILES.items()
            },
        }
        inventory_doc = {
            "schema_version": 1,
            "source": PROVENANCE_SOURCE,
            "license_id": PROVENANCE_LICENSE,
            "creator": PROVENANCE_CREATOR,
            "file_count": len(inventory),
            "source_inventory_sha256": source_inventory_sha256,
            "files": inventory,
        }

        if _source_archive_sha256 is not None:
            if _source_archive_bytes is None or _source_archive_bytes < 1:
                raise SoundPackBuildError("source archive byte identity is invalid")
            inventory_doc["source_archive_sha256"] = _source_archive_sha256
            inventory_doc["source_archive_bytes"] = _source_archive_bytes
        elif _source_archive_bytes is not None:
            raise SoundPackBuildError("source archive identity is incomplete")

        (staging / "manifest.json").write_text(
            json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        (staging / "variants.json").write_text(
            json.dumps(variants, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        (staging / "layers.json").write_text(
            json.dumps(layers, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        (staging / "provenance.json").write_text(
            json.dumps(provenance, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        (staging / "inventory.json").write_text(
            json.dumps(inventory_doc, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        (staging / "newgame_impacts.json").write_text(
            json.dumps(
                {
                    "schema_version": 2,
                    "default_variant": "1",
                    "variants": {
                        variant_id: {
                            "source_file": next(
                                file_name
                                for current_id, file_name, _uk, _en
                                in EVENT_VARIANTS["start"]
                                if current_id == variant_id
                            ),
                            "duration_seconds": NEW_GAME_DURATION_SECONDS_BY_VARIANT[variant_id],
                            "impact_count": len(impacts),
                            "impacts_ms": list(impacts),
                        }
                        for variant_id, impacts in NEW_GAME_IMPACTS_BY_VARIANT.items()
                    },
                    "analysis": {
                        "window_ms": 20,
                        "hop_ms": 5,
                        "threshold_percentile": 60,
                        "minimum_peak_separation_ms": 90,
                        "three_d_selection": "32 strongest separated candidate peaks",
                    },
                },
                ensure_ascii=False,
                indent=2,
                sort_keys=True,
            ) + "\n",
            encoding="utf-8",
        )
        (staging / "README.txt").write_text(
            "Accessible Chess user-supplied sound pack\n"
            "All 330 WAV files from the supplied archive are retained under library/.\n"
            "Runtime defaults and selectable variants are declared in manifest.json and variants.json.\n"
            "Original MOVEHIT/CAPHIT landing layers are declared in layers.json.\n"
            "NEWGAME impact timing for the visual placement sequence is declared in newgame_impacts.json.\n"
            "Variant 1 is the default for every event.\n"
            "Redistribution rights are not inferred by this builder; provenance records the pack as user-provided.\n",
            encoding="utf-8",
        )
        try:
            staging.replace(destination)
        except Exception:
            shutil.rmtree(staging, ignore_errors=True)
            raise
        return inventory_doc

    except Exception:
        shutil.rmtree(staging, ignore_errors=True)
        raise


def build_sound_pack(
    source: Path,
    destination: Path,
    *,
    expected_source_archive_sha256: str | None = None,
) -> dict[str, object]:
    destination = Path(destination)
    if destination.exists():
        raise SoundPackBuildError("destination already exists")
    try:
        return _build_sound_pack_unchecked(
            source,
            destination,
            expected_source_archive_sha256=expected_source_archive_sha256,
        )
    except Exception:
        if destination.exists():
            shutil.rmtree(destination, ignore_errors=True)
        raise


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "source",
        type=Path,
        help="Extracted user sound archive directory or prepared ZIP",
    )
    parser.add_argument("destination", type=Path, help="New sound-pack output directory")
    parser.add_argument(
        "--expected-source-archive-sha256",
        default=None,
        help="Optional exact SHA-256 required when source is a ZIP",
    )
    args = parser.parse_args()
    report = build_sound_pack(
        args.source,
        args.destination,
        expected_source_archive_sha256=args.expected_source_archive_sha256,
    )
    print(
        json.dumps(
            {
                "ok": True,
                "file_count": report["file_count"],
                "destination": str(args.destination.resolve()),
            },
            ensure_ascii=False,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
