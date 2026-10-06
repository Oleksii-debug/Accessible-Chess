from __future__ import annotations

import hashlib
import json
from pathlib import Path
import tempfile
import unittest
import wave
import zipfile
from unittest.mock import patch

from scripts import build_user_sound_pack as sound_builder
from scripts.build_user_sound_pack import (
    DEFAULT_EVENT_FILES,
    EVENT_VARIANTS,
    NEW_GAME_3D_IMPACT_MS,
    NEW_GAME_DURATION_SECONDS_BY_VARIANT,
    NEW_GAME_IMPACT_MS,
    NEW_GAME_IMPACTS_BY_VARIANT,
    SOUND_LAYERS,
    build_sound_pack,
)


class UserSoundPackBuilderTests(unittest.TestCase):
    def test_new_game_timeline_contract_is_exactly_32_and_wav_tail_bound(self):
        sound_builder._validate_new_game_timeline_contract()

        self.assertEqual(set(NEW_GAME_IMPACTS_BY_VARIANT), {"1", "3d"})
        for variant_id, impacts in NEW_GAME_IMPACTS_BY_VARIANT.items():
            with self.subTest(variant_id=variant_id):
                self.assertEqual(len(impacts), 32)
                self.assertEqual(tuple(sorted(set(impacts))), impacts)
                duration_ms = NEW_GAME_DURATION_SECONDS_BY_VARIANT[variant_id] * 1000
                self.assertLessEqual(impacts[-1], duration_ms)
                self.assertGreaterEqual(duration_ms - impacts[-1], 100)
                self.assertLessEqual(duration_ms - impacts[-1], 350)

    def test_new_game_timeline_contract_rejects_missing_piece_impact(self):
        malformed = dict(NEW_GAME_IMPACTS_BY_VARIANT)
        malformed["1"] = malformed["1"][:-1]
        with patch.object(sound_builder, "NEW_GAME_IMPACTS_BY_VARIANT", malformed):
            with self.assertRaisesRegex(
                sound_builder.SoundPackBuildError,
                "32 strictly increasing",
            ):
                sound_builder._validate_new_game_timeline_contract()

    def test_new_game_timeline_contract_rejects_desynchronized_audio_tail(self):
        malformed = dict(NEW_GAME_DURATION_SECONDS_BY_VARIANT)
        malformed["3d"] = 9.0
        with patch.object(sound_builder, "NEW_GAME_DURATION_SECONDS_BY_VARIANT", malformed):
            with self.assertRaisesRegex(
                sound_builder.SoundPackBuildError,
                "not synchronized",
            ):
                sound_builder._validate_new_game_timeline_contract()

    def test_zip_source_is_accepted_and_sha256_bound(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            source = root / "source"
            sounds = source / "library"
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
                self._write_wave(sounds / relative)
            self._write_wave_8bit(sounds / "Server" / "aooga.wav")
            self._write_wave_8bit(sounds / "Server" / "ping.wav")
            for index in range(330 - len(required)):
                self._write_wave(sounds / "ArchiveExtra" / f"extra-{index:03d}.wav")

            fingerprint_rows = []
            for path in sorted(
                (item for item in sounds.rglob("*") if item.is_file() and item.suffix.lower() == ".wav"),
                key=lambda item: item.as_posix().casefold(),
            ):
                relative = path.relative_to(sounds).as_posix()
                digest = hashlib.sha256(path.read_bytes()).hexdigest()
                fingerprint_rows.append(f"{relative}\0{digest}\n".encode("utf-8"))
            expected_inventory = hashlib.sha256(b"".join(fingerprint_rows)).hexdigest()

            archive = root / "sounds.zip"
            with zipfile.ZipFile(archive, "w", compression=zipfile.ZIP_STORED) as writer:
                for path in sorted(item for item in source.rglob("*") if item.is_file()):
                    writer.write(path, path.relative_to(source).as_posix())
            archive_sha = hashlib.sha256(archive.read_bytes()).hexdigest()

            destination = root / "pack"
            with patch(
                "scripts.build_user_sound_pack.EXPECTED_SOURCE_INVENTORY_SHA256",
                expected_inventory,
            ):
                report = build_sound_pack(
                    archive,
                    destination,
                    expected_source_archive_sha256=archive_sha,
                )
            self.assertEqual(report["file_count"], 330)
            self.assertEqual(report["source_archive_sha256"], archive_sha)
            self.assertEqual(report["source_archive_bytes"], archive.stat().st_size)
            recorded = json.loads(
                (destination / "inventory.json").read_text(encoding="utf-8")
            )
            self.assertEqual(recorded["source_archive_sha256"], archive_sha)
            self.assertEqual(recorded["source_archive_bytes"], archive.stat().st_size)
            self.assertTrue((destination / "library" / "Board" / "NEWGAME.WAV").is_file())

    def test_zip_source_hash_and_extraction_share_immutable_snapshot(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            source = root / "source" / "library"
            self._write_wave(source / "Board" / "MOVE.WAV")
            self._write_wave(source / "Server" / "Gong.WAV")
            archive = root / "sounds.zip"
            with zipfile.ZipFile(archive, "w", compression=zipfile.ZIP_STORED) as writer:
                for path in sorted(
                    item for item in (root / "source").rglob("*")
                    if item.is_file()
                ):
                    writer.write(path, path.relative_to(root / "source").as_posix())

            original_bytes = archive.read_bytes()
            original_digest = hashlib.sha256(original_bytes).hexdigest()
            original_size = len(original_bytes)
            original_extract = sound_builder._extract_sound_zip
            observed_sources: list[Path] = []

            def mutate_original_then_extract(snapshot: Path, destination: Path) -> None:
                observed_sources.append(snapshot)
                archive.write_bytes(b"mutated-after-snapshot")
                original_extract(snapshot, destination)

            destination = root / "pack"
            with (
                patch(
                    "scripts.build_user_sound_pack._extract_sound_zip",
                    side_effect=mutate_original_then_extract,
                ),
                self.assertRaisesRegex(Exception, "expected 330 WAV files"),
            ):
                build_sound_pack(
                    archive,
                    destination,
                    expected_source_archive_sha256=original_digest,
                )

            self.assertEqual(len(observed_sources), 1)
            self.assertNotEqual(observed_sources[0].resolve(), archive.resolve())
            self.assertEqual(hashlib.sha256(original_bytes).hexdigest(), original_digest)
            self.assertEqual(original_size, len(original_bytes))
            self.assertEqual(archive.read_bytes(), b"mutated-after-snapshot")
            self.assertFalse(destination.exists())
            self.assertEqual(list(root.glob(".pack.building-*")), [])

    def test_zip_source_rejects_oversized_compressed_snapshot(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            archive = root / "sounds.zip"
            with zipfile.ZipFile(archive, "w", compression=zipfile.ZIP_STORED) as writer:
                writer.writestr("library/Board/MOVE.WAV", b"x" * 64)
            destination = root / "pack"

            with (
                patch("scripts.build_user_sound_pack.MAX_ARCHIVE_BYTES", 16),
                self.assertRaisesRegex(Exception, "compressed size limit"),
            ):
                build_sound_pack(archive, destination)

            self.assertFalse(destination.exists())
            self.assertEqual(list(root.glob(".pack.building-*")), [])

    def test_zip_source_rejects_wrong_sha256_before_extraction(self):
        with tempfile.TemporaryDirectory() as td:
            archive = Path(td) / "sounds.zip"
            with zipfile.ZipFile(archive, "w") as writer:
                writer.writestr("library/Board/MOVE.WAV", b"not-used")
            destination = Path(td) / "pack"
            with self.assertRaisesRegex(Exception, "SHA-256 mismatch"):
                build_sound_pack(
                    archive,
                    destination,
                    expected_source_archive_sha256="0" * 64,
                )
            self.assertFalse(destination.exists())
            self.assertEqual(list(Path(td).glob(".pack.building-*")), [])

    def test_zip_source_rejects_path_traversal(self):
        with tempfile.TemporaryDirectory() as td:
            archive = Path(td) / "sounds.zip"
            with zipfile.ZipFile(archive, "w") as writer:
                writer.writestr("../escape.wav", b"x")
            destination = Path(td) / "pack"
            with self.assertRaisesRegex(Exception, "unsafe ZIP member path"):
                build_sound_pack(archive, destination)
            self.assertFalse((Path(td).parent / "escape.wav").exists())
            self.assertFalse(destination.exists())
            self.assertEqual(list(Path(td).glob(".pack.building-*")), [])

    def test_zip_source_rejects_windows_unsafe_member_names(self):
        cases = (
            ("reserved", "library/Board/CON.wav", "Windows-portable"),
            ("reserved-console", "library/Server/CONOUT$.wav", "Windows-portable"),
            ("forbidden-question", "library/Board/bad?.wav", "Windows-portable"),
            ("forbidden-pipe", "library/Board/bad|name.wav", "Windows-portable"),
            ("trailing-space", "library/Board/MOVE.WAV ", "Windows-portable"),
            ("too-long", "library/Board/" + "a" * 252 + ".wav", "Windows-portable"),
            ("normalized", "library//Board/MOVE.WAV", "unsafe ZIP member path"),
        )
        for label, member, expected in cases:
            with self.subTest(label=label), tempfile.TemporaryDirectory() as td:
                root = Path(td)
                archive = root / "sounds.zip"
                with zipfile.ZipFile(archive, "w") as writer:
                    writer.writestr(member, b"x")
                destination = root / "pack"
                with self.assertRaisesRegex(Exception, expected):
                    build_sound_pack(archive, destination)
                self.assertFalse(destination.exists())

    def test_zip_source_rejects_file_directory_topology_in_both_orders(self):
        cases = (
            (
                ("library/Board", b"file"),
                ("library/Board/MOVE.WAV", b"child"),
            ),
            (
                ("library/Board/MOVE.WAV", b"child"),
                ("library/Board", b"file"),
            ),
        )
        for members in cases:
            with self.subTest(order=members), tempfile.TemporaryDirectory() as td:
                root = Path(td)
                archive = root / "sounds.zip"
                with zipfile.ZipFile(archive, "w") as writer:
                    for name, data in members:
                        writer.writestr(name, data)
                destination = root / "pack"
                with self.assertRaisesRegex(Exception, "file/directory topology collision"):
                    build_sound_pack(archive, destination)
                self.assertFalse(destination.exists())

    def test_zip_source_rejects_symlink_members(self):
        with tempfile.TemporaryDirectory() as td:
            archive = Path(td) / "sounds.zip"
            info = zipfile.ZipInfo("library/Board/MOVE.WAV")
            info.create_system = 3
            info.external_attr = (0o120777 << 16)
            with zipfile.ZipFile(archive, "w") as writer:
                writer.writestr(info, b"target")
            destination = Path(td) / "pack"
            with self.assertRaisesRegex(Exception, "cannot contain symlinks"):
                build_sound_pack(archive, destination)
            self.assertFalse(destination.exists())

    def test_zip_source_rejects_case_insensitive_duplicate_paths(self):
        with tempfile.TemporaryDirectory() as td:
            archive = Path(td) / "sounds.zip"
            with zipfile.ZipFile(archive, "w") as writer:
                writer.writestr("library/Board/MOVE.WAV", b"a")
                writer.writestr("library/board/move.wav", b"b")
            destination = Path(td) / "pack"
            with self.assertRaisesRegex(Exception, "duplicate paths"):
                build_sound_pack(archive, destination)
            self.assertFalse(destination.exists())

    def test_win32_component_utf16_boundary_and_unicode_are_fail_closed(self):
        astral = chr(0x1F642)
        accepted = astral * 125 + "a.wav"
        rejected = astral * 126 + "a.wav"
        self.assertEqual(len(accepted.encode("utf-16-le")) // 2, 255)
        self.assertGreater(len(rejected.encode("utf-16-le")) // 2, 255)
        self.assertEqual(sound_builder._windows_portable_component(accepted), accepted)
        with self.assertRaisesRegex(
            sound_builder.SoundPackBuildError,
            "Windows-portable",
        ):
            sound_builder._windows_portable_component(rejected)
        with self.assertRaisesRegex(
            sound_builder.SoundPackBuildError,
            "Windows-portable",
        ):
            sound_builder._windows_portable_component("broken" + chr(0xD800) + ".wav")

    def test_direct_source_relative_paths_must_be_windows_portable(self):
        root = Path("root")
        cases = (
            root / "Board" / "CON.wav",
            root / "Server" / "CONIN$.wav",
            root / "Board" / "trailing.",
            root / "Board" / "bad?.wav",
            root / "Board" / "bad|name.wav",
            root / "Board" / ("a" * 252 + ".wav"),
            root / "Board" / "bad\x01.wav",
        )
        for candidate in cases:
            with self.subTest(candidate=str(candidate)), self.assertRaisesRegex(
                Exception,
                "Windows-portable",
            ):
                sound_builder._safe_relative(candidate, root)

    def test_failed_build_removes_partial_destination(self):
        with tempfile.TemporaryDirectory() as td:
            source = Path(td) / "source" / "library"
            self._write_wave(source / "Board" / "MOVE.WAV")
            destination = Path(td) / "pack"

            with self.assertRaises(Exception):
                build_sound_pack(Path(td) / "source", destination)

            self.assertFalse(destination.exists())
            self.assertEqual(list(Path(td).glob(".pack.building-*")), [])

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

    @staticmethod
    def _write_wave_8bit(path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        with wave.open(str(path), "wb") as writer:
            writer.setnchannels(1)
            writer.setsampwidth(1)
            writer.setframerate(22050)
            writer.writeframes(bytes([0, 64, 128, 192, 255] * 4))

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
            self._write_wave_8bit(source / "Server" / "aooga.wav")
            self._write_wave_8bit(source / "Server" / "ping.wav")

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
                fingerprint_rows.append(f"{relative}\0{digest}\n".encode("utf-8"))
            expected = hashlib.sha256(b"".join(fingerprint_rows)).hexdigest()

            with patch(
                "scripts.build_user_sound_pack.EXPECTED_SOURCE_INVENTORY_SHA256",
                expected,
            ):
                report = build_sound_pack(Path(td) / "input", destination)

            self.assertEqual(report["file_count"], 330)
            self.assertEqual(report["license_id"], "USER_PROVIDED")
            self.assertEqual(
                report["creator"],
                "User-provided legacy chess sound archive",
            )
            self.assertEqual(
                sum(1 for path in (destination / "library").rglob("*") if path.is_file()),
                330,
            )

            manifest = json.loads((destination / "manifest.json").read_text(encoding="utf-8"))
            variants = json.loads((destination / "variants.json").read_text(encoding="utf-8"))
            layers = json.loads((destination / "layers.json").read_text(encoding="utf-8"))
            impacts = json.loads((destination / "newgame_impacts.json").read_text(encoding="utf-8"))
            self.assertEqual(manifest["files"], DEFAULT_EVENT_FILES)
            self.assertEqual(
                variants,
                {
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
                },
            )
            self.assertEqual(
                layers,
                {
                    "schema_version": 1,
                    "events": {
                        event: {
                            variant_id: list(sequence)
                            for variant_id, sequence in by_variant.items()
                        }
                        for event, by_variant in SOUND_LAYERS.items()
                    },
                },
            )
            self.assertEqual(
                impacts,
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
                            "impact_count": len(impact_values),
                            "impacts_ms": list(impact_values),
                        }
                        for variant_id, impact_values in NEW_GAME_IMPACTS_BY_VARIANT.items()
                    },
                    "analysis": {
                        "window_ms": 20,
                        "hop_ms": 5,
                        "threshold_percentile": 60,
                        "minimum_peak_separation_ms": 90,
                        "three_d_selection": "32 strongest separated candidate peaks",
                    },
                },
            )
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
                [item["id"] for item in variants["events"]["mate"]],
                ["1", "ru"],
            )
            self.assertEqual(
                [item["id"] for item in variants["events"]["draw"]],
                ["1", "en", "ru"],
            )
            self.assertEqual(
                variants["events"]["mate"][1]["file"],
                "library/Russian/Notation/Mate.wav",
            )
            self.assertEqual(
                variants["events"]["draw"][1]["file"],
                "library/English/Draw.wav",
            )
            self.assertEqual(
                variants["events"]["draw"][2]["file"],
                "library/Russian/Draw.wav",
            )
            self.assertEqual(
                [item["id"] for item in variants["events"]["low_time"]],
                ["1", "2"],
            )
            self.assertEqual(
                variants["events"]["low_time"][0]["file"],
                "library/Server/aooga.wav",
            )
            self.assertEqual(
                variants["events"]["low_time"][1]["file"],
                "library/Server/ping.wav",
            )
            inventory_by_file = {
                item["file"]: item
                for item in report["files"]
            }
            self.assertEqual(
                inventory_by_file["library/Server/aooga.wav"]["sample_width_bytes"],
                1,
            )
            self.assertEqual(
                inventory_by_file["library/Server/ping.wav"]["sample_width_bytes"],
                1,
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
