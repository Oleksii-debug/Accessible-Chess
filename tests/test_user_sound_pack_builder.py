from __future__ import annotations

import json
from pathlib import Path
import tempfile
import unittest
import wave

from scripts.build_user_sound_pack import (
    DEFAULT_EVENT_FILES,
    EVENT_VARIANTS,
    build_sound_pack,
)


class UserSoundPackBuilderTests(unittest.TestCase):
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
            for relative in required:
                self._write_wave(source / relative)

            filler_count = 330 - len(required)
            for index in range(filler_count):
                self._write_wave(source / "ArchiveExtra" / f"extra-{index:03d}.wav")

            report = build_sound_pack(Path(td) / "input", destination)

            self.assertEqual(report["file_count"], 330)
            self.assertEqual(
                sum(1 for path in (destination / "library").rglob("*") if path.is_file()),
                330,
            )

            manifest = json.loads((destination / "manifest.json").read_text(encoding="utf-8"))
            variants = json.loads((destination / "variants.json").read_text(encoding="utf-8"))
            self.assertEqual(manifest["files"], DEFAULT_EVENT_FILES)
            for event, default_file in DEFAULT_EVENT_FILES.items():
                self.assertEqual(variants["events"][event][0]["id"], "1")
                self.assertEqual(variants["events"][event][0]["file"], default_file)

            self.assertEqual(
                [item["id"] for item in variants["events"]["move"]],
                ["1", "2", "3", "4", "5", "6"],
            )
            self.assertEqual(
                [item["id"] for item in variants["events"]["capture"]],
                ["1", "2", "3", "4", "5"],
            )


if __name__ == "__main__":
    unittest.main()
