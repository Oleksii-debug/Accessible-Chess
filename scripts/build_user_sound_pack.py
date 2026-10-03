from __future__ import annotations

"""Build the canonical Accessible Chess sound pack from the user-supplied archive tree.

The input must be an extracted directory containing a Sounds directory, directly
or below one wrapper directory. Every WAV from the supplied archive is copied
into the pack so no legacy procedural audio is needed at runtime.
"""

import argparse
import hashlib
import json
import shutil
import wave
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
    "tick": "library/Board/Tick.wav",
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
    "tick": (
        ("1", "library/Board/Tick.wav", "Годинник", "Clock"),
        ("3d", "library/Board3d/Tick.wav", "Годинник 3D", "3D clock"),
    ),
}

PROVENANCE_SOURCE = "urn:accessible-chess:user-upload:sound-archive:2026-10-03"
PROVENANCE_LICENSE = "USER_PROVIDED"
PROVENANCE_CREATOR = "User-provided legacy chess sound archive"
EXPECTED_SOURCE_WAV_COUNT = 330
EXPECTED_SOURCE_INVENTORY_SHA256 = "41f3223040e0720b2268e5c28f3ccec140a4f9d3386c12ffa7a82fc283a1f920"


class SoundPackBuildError(RuntimeError):
    pass


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


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
            if info["sample_width_bytes"] != 2:
                raise SoundPackBuildError(
                    f"selectable runtime variants must be 16-bit PCM: {file_name}"
                )


def build_sound_pack(source: Path, destination: Path) -> dict[str, object]:
    sounds = _locate_sounds(source)
    if destination.exists():
        raise SoundPackBuildError("destination already exists")
    destination.mkdir(parents=True)
    library = destination / "library"
    library.mkdir()

    inventory: list[dict[str, object]] = []
    source_fingerprint_rows: list[bytes] = []
    seen_casefold: set[str] = set()
    for source_path in sorted(sounds.rglob("*"), key=lambda item: item.as_posix().casefold()):
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

    _validate_event_paths(destination)

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
    provenance = {
        "schema_version": 1,
        "events": {
            event: {
                "file": file_name,
                "sha256": _sha256(destination / Path(file_name)),
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
        "file_count": len(inventory),
        "source_inventory_sha256": source_inventory_sha256,
        "files": inventory,
    }

    (destination / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    (destination / "variants.json").write_text(
        json.dumps(variants, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    (destination / "provenance.json").write_text(
        json.dumps(provenance, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    (destination / "inventory.json").write_text(
        json.dumps(inventory_doc, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    (destination / "README.txt").write_text(
        "Accessible Chess user-supplied sound pack\n"
        "All 330 WAV files from the supplied archive are retained under library/.\n"
        "Runtime defaults and selectable variants are declared in manifest.json and variants.json.\n"
        "Variant 1 is the default for every event.\n"
        "Redistribution rights are not inferred by this builder; provenance records the pack as user-provided.\n",
        encoding="utf-8",
    )
    return inventory_doc


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("source", type=Path, help="Extracted user sound archive directory")
    parser.add_argument("destination", type=Path, help="New sound-pack output directory")
    args = parser.parse_args()
    report = build_sound_pack(args.source, args.destination)
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
