from __future__ import annotations

import hashlib
import json
from pathlib import Path
import tempfile
import unittest
import wave
from unittest.mock import patch

from scripts.build_user_sound_pack import (
    DEFAULT_EVENT_FILES,
    EVENT_VARIANTS,
    NEW_GAME_3D_IMPACT_MS,
    NEW_GAME_IMPACT_MS,
    SOUND_LAYERS,
    build_sound_pack,
)


class UserSoundPackBuilderTests(unittest.TestCase):
    def test_legacy_procedural_sound_generator_cannot_return(self):
        root = Path(__file__).resolve().parents[1]
        source = (root / "acs" / "sound.py").read_text(encoding="utf-8")
        self.assertNotIn("random.Random", source)
        self.assertNotIn("def _make(", source)
        self.assertNotIn("wave.open", source)
        self.assertIn("PackagedSoundAssetResolver", source)

    @staticmethod
    def _write_wave(path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        with wave.open(str(path), "wb") as writer:
            writer.setnchannels(1)
            writer.setsampwidth(2)
            writer.setframerate(22050)
            writer.writeframes(b"\x00\x00" * 16)

    def test_supplied_archive_build_retains_all_330_wavs_and_default_variant_one(self):
        with tempfile.TemporaryDirectory() as td:
            source = Path(td) / "input" / "звуки" / "Sounds"
            destination = Path(td) / "pack"

            required = {
                Path(file_name.removeprefix("library/"))
                for options in EVENT_VARIANTS.values()
                for _variant_id, file_name, _uk, _en in options
            }
            required.update(
                Path(file_name.removeprefix("library/"))
                for by_variant in SOUND_LAYERS.values()
                for sequence in by_variant.values()
                for file_name in sequence
            )
            for relative in required:
                self._write_wave(source / relative)

            filler_count = 330 - len(required)
            for index in range(filler_count):
                self._write_wave(source / "ArchiveExtra" / f"extra-{index:03d}.wav")

            fingerprint_rows = []
            for path in sorted(
                (item for item in source.rglob("*") if item.is_file() and item.suffix.lower() == ".wav"),
                key=lambda item: item.as_posix().casefold(),
            ):
                relative = path.relative_to(source).as_posix()
                digest = hashlib.sha256(path.read_bytes()).hexdigest()
                fingerprint_rows.append(f"{relative}\\0{digest}\\n".encode("utf-8"))
            expected = hashlib.sha256(b"".join(fingerprint_rows)).hexdigest()

            with patch(
                "scripts.build_user_sound_pack.EXPECTED_SOURCE_INVENTORY_SHA256",
                expected,
            ):
                report = build_sound_pack(Path(td) / "input", destination)

            self.assertEqual(report["file_count"], 330)
            self.assertEqual(
                sum(1 for path in (destination / "library").rglob("*") if path.is_file()),
                330,
            )

            manifest = json.loads((destination / "manifest.json").read_text(encoding="utf-8"))
            variants = json.loads((destination / "variants.json").read_text(encoding="utf-8"))
            layers = json.loads((destination / "layers.json").read_text(encoding="utf-8"))
            impacts = json.loads((destination / "newgame_impacts.json").read_text(encoding="utf-8"))
            self.assertEqual(manifest["files"], DEFAULT_EVENT_FILES)
            self.assertEqual(impacts["schema_version"], 2)
            self.assertEqual(impacts["default_variant"], "1")
            self.assertEqual(impacts["variants"]["1"]["impact_count"], 32)
            self.assertEqual(
                tuple(impacts["variants"]["1"]["impacts_ms"]),
                NEW_GAME_IMPACT_MS,
            )
            self.assertEqual(impacts["variants"]["3d"]["impact_count"], 32)
            self.assertEqual(
                tuple(impacts["variants"]["3d"]["impacts_ms"]),
                NEW_GAME_3D_IMPACT_MS,
            )
            for event, default_file in DEFAULT_EVENT_FILES.items():
                self.assertEqual(variants["events"][event][0]["id"], "1")
                self.assertEqual(variants["events"][event][0]["file"], default_file)

            self.assertEqual(
                [item["id"] for item in variants["events"]["move"]],
                ["1", "2", "3", "4", "5", "6", "3d-1", "3d-2", "3d-3"],
            )
            self.assertEqual(
                [item["id"] for item in variants["events"]["capture"]],
                ["1", "2", "3", "4", "5", "3d-1", "3d-2", "3d-3", "3d-4"],
            )
            self.assertEqual(manifest["files"]["promotion"], "library/Board/MOVEHIT1.WAV")
            self.assertEqual(
                [item["id"] for item in variants["events"]["promotion"]],
                ["1", "2", "3"],
            )
            self.assertEqual(
                layers["events"]["move"]["1"],
                ["library/Board/MOVE.WAV", "library/Board/MOVEHIT1.WAV"],
            )
            self.assertEqual(
                layers["events"]["capture"]["1"],
                ["library/Board/CAPTURE.WAV", "library/Board/CAPHIT1.WAV"],
            )
            self.assertEqual(
                layers["events"]["move"]["3d-1"],
                ["library/Board3d/MOVE.WAV", "library/Board3d/MOVEHIT1.WAV"],
            )

            rebuilt = Path(td) / "rebuilt"
            with patch(
                "scripts.build_user_sound_pack.EXPECTED_SOURCE_INVENTORY_SHA256",
                expected,
            ):
                rebuilt_report = build_sound_pack(destination, rebuilt)
            self.assertEqual(rebuilt_report["file_count"], 330)
            self.assertTrue((rebuilt / "library" / "Board" / "NEWGAME.WAV").is_file())


if __name__ == "__main__":
    unittest.main()
