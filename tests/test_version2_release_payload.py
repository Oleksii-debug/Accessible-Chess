from __future__ import annotations

import hashlib
import json
from pathlib import Path
import shutil
import stat
import struct
import tempfile
import unittest
from unittest.mock import patch
import wave
import zipfile

from acs import version2_release_payload as payload
from acs import version2_package_preflight as package_preflight
from acs.sound_events import SoundEvent
from acs.sound_windows import PackagedSoundAssetResolver
from acs.stockfish_runtime import StockfishRuntimeConfig, resolve_stockfish_path
from acs.version2_package_assembler import assemble_version2_package_tree


_REQUIRED_WEB_FILES = (
    "index.html",
    "stage1_release_bootstrap.js",
    "stage1_board_actions.js",
    "full_product_pgn.js",
    "full_product_library.js",
    "full_product_books_training.js",
    "full_product_teacher.js",
    "full_product_education.js",
    "version2_final_product_bootstrap.js",
    "version2_local_profile.js",
    "p0_accessibility_runtime.js",
    "version2_release_bootstrap.js",
    "protection_locked.html",
    "protection_locked.js",
    "docs/ACCESSIBLE_CHESS_HOTKEYS_UK.txt",
    "docs/ACCESSIBLE_CHESS_CAPABILITIES_TESTING_UK.txt",
)

_VALID_WINFORMS_CONFIG = (
    '<?xml version="1.0" encoding="utf-8"?>\n'
    '<configuration><runtime><AppContextSwitchOverrides value="'
    'Switch.UseLegacyAccessibilityFeatures=false;'
    'Switch.UseLegacyAccessibilityFeatures.2=false;'
    'Switch.UseLegacyAccessibilityFeatures.3=false;'
    'Switch.UseLegacyAccessibilityFeatures.4=false;'
    'Switch.UseLegacyAccessibilityFeatures.5=false'
    '" /></runtime></configuration>\n'
)


class Version2ReleasePayloadTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.standalone = self.root / "standalone"
        (self.standalone / "web").mkdir(parents=True)
        (self.standalone / "AccessibleChess.exe").write_bytes(
            self._windows_pe(b"v2-standalone")
        )
        (self.standalone / "AccessibleChess.exe.config").write_text(
            _VALID_WINFORMS_CONFIG, encoding="utf-8"
        )
        for relative in package_preflight._REQUIRED_DESKTOP_RUNTIME_FILES:
            runtime = self.standalone.joinpath(*relative.split("/")[1:])
            runtime.parent.mkdir(parents=True, exist_ok=True)
            runtime.write_bytes(
                self._windows_pe(
                    b"runtime",
                    machine=(
                        0x014C
                        if relative
                        in package_preflight._REQUIRED_I386_MANAGED_DESKTOP_RUNTIME_FILES
                        else 0x8664
                    ),
                    managed=(
                        relative
                        in package_preflight._REQUIRED_MANAGED_DESKTOP_RUNTIME_FILES
                    ),
                )
            )
        for name in _REQUIRED_WEB_FILES:
            path = self.standalone / "web" / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(
                f"/* {name} */\n" if name.endswith(".js") else "Accessible Chess owner resource\n",
                encoding="utf-8",
            )

        self.sounds = self.root / "sounds"
        self.sounds.mkdir()
        files: dict[str, str] = {}
        for index, event in enumerate(SoundEvent, start=1):
            name = f"{event.value}.wav"
            files[event.value] = name
            self._write_wav(self.sounds / name, sample=index * 100)
        (self.sounds / "manifest.json").write_text(
            json.dumps({"schema_version": 1, "files": files}, sort_keys=True),
            encoding="utf-8",
        )
        self.sound_provenance = self.sounds / "provenance.json"
        self._write_sound_provenance()

        self.stockfish = self.root / "stockfish.zip"
        self.stockfish_executable = self._windows_pe(b"stockfish18")
        self._write_stockfish_archive(self.stockfish)

    @staticmethod
    def _write_wav(path: Path, *, sample: int, sample_width: int = 2) -> None:
        with wave.open(str(path), "wb") as writer:
            writer.setnchannels(1)
            writer.setsampwidth(sample_width)
            writer.setframerate(8000)
            if sample_width == 1:
                if not 0 <= sample <= 255:
                    raise ValueError("8-bit WAV sample must be in 0..255")
                writer.writeframes(bytes([sample]) * 8)
            elif sample_width == 2:
                writer.writeframes(struct.pack("<h", sample) * 8)
            else:
                raise ValueError("test WAV sample width must be 1 or 2")

    @staticmethod
    def _write_wav_8bit(path: Path) -> None:
        with wave.open(str(path), "wb") as writer:
            writer.setnchannels(1)
            writer.setsampwidth(1)
            writer.setframerate(8000)
            writer.writeframes(bytes([0, 64, 128, 192, 255] * 4))

    def _write_sound_provenance(self) -> None:
        manifest = json.loads((self.sounds / "manifest.json").read_text(encoding="utf-8"))
        events: dict[str, dict[str, str]] = {}
        for event in SoundEvent:
            file_name = manifest["files"][event.value]
            events[event.value] = {
                "file": file_name,
                "sha256": self._digest(self.sounds / file_name),
                "license_id": "CC0-1.0",
                "source": f"urn:accessible-chess:test-fixture:sound:{event.value}",
                "creator": "Accessible Chess synthetic test fixture",
            }
        self.sound_provenance.write_text(
            json.dumps({"schema_version": 1, "events": events}, sort_keys=True),
            encoding="utf-8",
        )

    @staticmethod
    def _windows_pe(
        payload_bytes: bytes = b"",
        *,
        machine: int = 0x8664,
        managed: bool = False,
    ) -> bytes:
        data = bytearray(0x400)
        data[:2] = b"MZ"
        pe_offset = 0x80
        struct.pack_into("<I", data, 0x3C, pe_offset)
        data[pe_offset : pe_offset + 4] = b"PE\0\0"
        coff = pe_offset + 4
        struct.pack_into("<H", data, coff, machine)
        struct.pack_into("<H", data, coff + 2, 1)
        optional_size = 0xF0 if machine == 0x8664 else 0xE0
        struct.pack_into("<H", data, coff + 16, optional_size)
        struct.pack_into("<H", data, coff + 18, 0x0022)
        optional = coff + 20
        pe32_plus = machine == 0x8664
        struct.pack_into("<H", data, optional, 0x20B if pe32_plus else 0x10B)
        struct.pack_into("<H", data, optional + 68, 0x0002)

        section = optional + optional_size
        data[section : section + 8] = b".text\0\0\0"
        struct.pack_into("<I", data, section + 8, 0x1000)
        struct.pack_into("<I", data, section + 12, 0x2000)
        struct.pack_into("<I", data, section + 16, 0x200)
        struct.pack_into("<I", data, section + 20, 0x200)

        if managed:
            directory_count_offset = 108 if pe32_plus else 92
            directory_table_offset = 112 if pe32_plus else 96
            struct.pack_into("<I", data, optional + directory_count_offset, 16)
            clr_directory = optional + directory_table_offset + (14 * 8)
            struct.pack_into("<I", data, clr_directory, 0x2000)
            struct.pack_into("<I", data, clr_directory + 4, 0x48)
            struct.pack_into("<I", data, 0x200, 0x48)
            struct.pack_into("<H", data, 0x204, 2)
            struct.pack_into("<H", data, 0x206, 5)
            struct.pack_into("<I", data, 0x208, 0x2080)
            struct.pack_into("<I", data, 0x20C, 0x40)
            data[0x280:0x284] = b"BSJB"
        data.extend(payload_bytes)
        return bytes(data)

    def _enable_inventory_sound_pack(self) -> tuple[int, str, Path]:
        manifest_path = self.sounds / "manifest.json"
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        provenance = json.loads(self.sound_provenance.read_text(encoding="utf-8"))

        library = self.sounds / "library"
        library.mkdir()
        moved: dict[str, str] = {}
        for file_name in sorted(set(manifest["files"].values()), key=str.casefold):
            source = self.sounds / file_name
            destination = library / file_name
            destination.parent.mkdir(parents=True, exist_ok=True)
            source.replace(destination)
            moved[file_name] = f"library/{file_name}"

        for event in SoundEvent:
            old_name = manifest["files"][event.value]
            new_name = moved[old_name]
            manifest["files"][event.value] = new_name
            provenance["events"][event.value]["file"] = new_name
            provenance["events"][event.value]["sha256"] = self._digest(
                self.sounds / new_name
            )

        alt = library / "move-alt.wav"
        self._write_wav(alt, sample=177, sample_width=1)
        variants = {
            "schema_version": 1,
            "events": {
                event.value: [
                    {
                        "id": "1",
                        "file": manifest["files"][event.value],
                        "label_uk": "Варіант 1",
                        "label_en": "Variant 1",
                    }
                ]
                for event in SoundEvent
            },
        }
        variants["events"][SoundEvent.MOVE.value].append(
            {
                "id": "2",
                "file": "library/move-alt.wav",
                "label_uk": "Хід 2",
                "label_en": "Move 2",
            }
        )
        (self.sounds / "variants.json").write_text(
            json.dumps(variants, ensure_ascii=False, sort_keys=True),
            encoding="utf-8",
        )
        (self.sounds / "layers.json").write_text(
            json.dumps({"schema_version": 1, "events": {}}, sort_keys=True),
            encoding="utf-8",
        )
        manifest_path.write_text(
            json.dumps(manifest, sort_keys=True),
            encoding="utf-8",
        )
        self.sound_provenance.write_text(
            json.dumps(provenance, sort_keys=True),
            encoding="utf-8",
        )

        entries: list[dict[str, object]] = []
        fingerprint_rows: list[bytes] = []
        for path in sorted(
            (item for item in library.rglob("*") if item.is_file() and item.suffix.casefold() == ".wav"),
            key=lambda item: item.relative_to(library).as_posix().casefold(),
        ):
            relative = path.relative_to(library).as_posix()
            digest = self._digest(path)
            with wave.open(str(path), "rb") as reader:
                frames = reader.getnframes()
                rate = reader.getframerate()
                entries.append(
                    {
                        "file": f"library/{relative}",
                        "sha256": digest,
                        "bytes": path.stat().st_size,
                        "channels": reader.getnchannels(),
                        "sample_width_bytes": reader.getsampwidth(),
                        "sample_rate": rate,
                        "frames": frames,
                        "duration_seconds": round(frames / rate, 6),
                        "compression": reader.getcomptype(),
                    }
                )
            fingerprint_rows.append(
                f"{relative}\0{digest}\n".encode("utf-8")
            )
        inventory_sha = hashlib.sha256(b"".join(fingerprint_rows)).hexdigest()
        inventory = {
            "schema_version": 1,
            "source": payload._USER_SOUND_SOURCE,
            "license_id": payload._USER_SOUND_LICENSE_ID,
            "creator": payload._USER_SOUND_CREATOR,
            "file_count": len(entries),
            "source_inventory_sha256": inventory_sha,
            "files": entries,
        }
        (self.sounds / "inventory.json").write_text(
            json.dumps(inventory, ensure_ascii=False, sort_keys=True),
            encoding="utf-8",
        )
        return len(entries), inventory_sha, alt

    def _write_stockfish_archive(
        self,
        path: Path,
        *,
        include_source: bool = True,
        include_license: bool = True,
        executable_bytes: bytes | None = None,
        extra_members: tuple[tuple[str, bytes], ...] = (),
    ) -> None:
        with zipfile.ZipFile(path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
            archive.writestr(
                "stockfish/stockfish-windows-x86-64.exe",
                self.stockfish_executable if executable_bytes is None else executable_bytes,
            )
            if include_license:
                archive.writestr("stockfish/Copying.txt", b"GNU GENERAL PUBLIC LICENSE\n")
            if include_source:
                archive.writestr("stockfish/src/uci.cpp", b"// corresponding source\n")
                archive.writestr("stockfish/src/uci.h", b"// header\n")
            for name, data in extra_members:
                archive.writestr(name, data)

    @staticmethod
    def _digest(path: Path) -> str:
        return hashlib.sha256(path.read_bytes()).hexdigest()

    def _prepare(self, output: Path | None = None):
        destination = output or (self.root / "payload")
        with patch.object(
            payload,
            "OFFICIAL_STOCKFISH_18_WINDOWS_X64_SHA256",
            self._digest(self.stockfish),
        ):
            return payload.prepare_version2_release_payload(
                self.standalone,
                self.stockfish,
                self.sounds,
                destination,
            )

    def _assert_no_publication(self, output: Path) -> None:
        self.assertFalse(output.exists(), f"unexpected published payload at {output}")

    def test_missing_winforms_accessibility_app_config_fails_without_output(self) -> None:
        (self.standalone / "AccessibleChess.exe.config").unlink()
        output = self.root / "payload"
        with patch.object(
            payload,
            "OFFICIAL_STOCKFISH_18_WINDOWS_X64_SHA256",
            self._digest(self.stockfish),
        ):
            with self.assertRaisesRegex(
                payload.Version2ReleasePayloadError,
                "WinForms accessibility app-config is missing or empty",
            ):
                payload.prepare_version2_release_payload(
                    self.standalone,
                    self.stockfish,
                    self.sounds,
                    output,
                )
        self._assert_no_publication(output)

    def test_invalid_winforms_accessibility_app_config_fails_without_output(self) -> None:
        (self.standalone / "AccessibleChess.exe.config").write_text(
            _VALID_WINFORMS_CONFIG.replace(
                "Switch.UseLegacyAccessibilityFeatures.4=false",
                "Switch.UseLegacyAccessibilityFeatures.4=true",
            ),
            encoding="utf-8",
        )
        output = self.root / "payload"
        with patch.object(
            payload,
            "OFFICIAL_STOCKFISH_18_WINDOWS_X64_SHA256",
            self._digest(self.stockfish),
        ):
            with self.assertRaisesRegex(
                payload.Version2ReleasePayloadError,
                "WinForms accessibility app-config is invalid",
            ):
                payload.prepare_version2_release_payload(
                    self.standalone,
                    self.stockfish,
                    self.sounds,
                    output,
                )
        self._assert_no_publication(output)

    def test_stages_canonical_stockfish_sounds_and_notices_atomically(self) -> None:
        result = self._prepare()

        self.assertEqual(result.root, self.root / "payload")
        self.assertTrue((result.product_dir / "AccessibleChess.exe").is_file())
        self.assertTrue((result.product_dir / "AccessibleChess.exe.config").is_file())
        self.assertEqual(
            (result.product_dir / "AccessibleChess.exe.config").read_bytes(),
            (self.standalone / "AccessibleChess.exe.config").read_bytes(),
        )
        for name in _REQUIRED_WEB_FILES:
            self.assertTrue((result.product_dir / "web" / name).is_file())
        self.assertEqual(result.stockfish_executable.read_bytes(), self.stockfish_executable)
        self.assertEqual(
            resolve_stockfish_path(StockfishRuntimeConfig(application_dir=result.product_dir)),
            result.stockfish_executable.resolve(),
        )

        manifest = PackagedSoundAssetResolver(result.product_dir).load_manifest()
        self.assertEqual(set(manifest.files), set(SoundEvent))
        self.assertEqual(len(set(manifest.files.values())), len(SoundEvent))
        for wav in manifest.files.values():
            with wave.open(str(wav), "rb") as reader:
                self.assertEqual(reader.getcomptype(), "NONE")
                self.assertEqual(reader.getsampwidth(), 2)
                self.assertGreater(reader.getnframes(), 0)
        self.assertFalse((manifest.root / "provenance.json").exists())

        notices = result.notices_dir
        sound_provenance = json.loads(
            (notices / "SOUND_PROVENANCE.json").read_text(encoding="utf-8")
        )
        self.assertEqual(sound_provenance["schema_version"], 1)
        self.assertEqual(set(sound_provenance["events"]), {event.value for event in SoundEvent})
        for event in SoundEvent:
            entry = sound_provenance["events"][event.value]
            self.assertEqual(entry["file"], manifest.files[event].name)
            self.assertEqual(entry["sha256"], self._digest(manifest.files[event]))
            self.assertEqual(entry["license_id"], "CC0-1.0")
            self.assertTrue(entry["source"].startswith("urn:accessible-chess:test-fixture:"))

        source_notice = notices / "Stockfish-18-source.zip"
        self.assertTrue(source_notice.is_file())
        with zipfile.ZipFile(source_notice) as archive:
            names = tuple(archive.namelist())
            self.assertTrue(any("/src/" in f"/{name}" for name in names))
            self.assertFalse(any(name.casefold().endswith(".exe") for name in names))
        self.assertIn(
            "GNU GENERAL PUBLIC LICENSE",
            (notices / "Stockfish-COPYING.txt").read_text(encoding="utf-8"),
        )
        text_notice = (notices / "Stockfish-NOTICE.txt").read_text(encoding="utf-8")
        self.assertIn("Stockfish 18", text_notice)
        self.assertIn("GPL", text_notice)
        self.assertIn("Corresponding source", text_notice)

        provenance = json.loads(
            (notices / "STOCKFISH_PROVENANCE.json").read_text(encoding="utf-8")
        )
        self.assertEqual(provenance["tag"], payload.OFFICIAL_STOCKFISH_18_TAG)
        self.assertEqual(provenance["upstream_commit"], payload.OFFICIAL_STOCKFISH_18_COMMIT)
        self.assertEqual(provenance["release_asset_sha256"], self._digest(self.stockfish))
        self.assertEqual(
            provenance["packaged_executable_sha256"],
            hashlib.sha256(self.stockfish_executable).hexdigest(),
        )
        self.assertEqual(provenance["corresponding_source"], "Stockfish-18-source.zip")
        self.assertEqual(
            provenance["corresponding_source_sha256"],
            self._digest(source_notice),
        )

    def test_prepared_payload_flows_into_existing_package_assembler(self) -> None:
        prepared = self._prepare()
        package = self.root / "candidate"

        assembled = assemble_version2_package_tree(
            prepared.product_dir,
            prepared.notices_dir,
            package,
            integration_sha="a" * 40,
        )

        self.assertEqual(assembled.package_root, package)
        self.assertEqual(assembled.tree_report.integration_sha, "a" * 40)
        self.assertTrue(
            (package / "AccessibleChess" / "engines" / "stockfish" / "stockfish.exe").is_file()
        )
        self.assertTrue(
            (package / "AccessibleChess" / "assets" / "sounds" / "manifest.json").is_file()
        )
        self.assertTrue(
            (package / "THIRD_PARTY_NOTICES" / "Stockfish-18-source.zip").is_file()
        )
        self.assertTrue(
            (package / "THIRD_PARTY_NOTICES" / "Stockfish-NOTICE.txt").is_file()
        )
        self.assertTrue(
            (package / "THIRD_PARTY_NOTICES" / "SOUND_PROVENANCE.json").is_file()
        )
        self.assertTrue((package / "RELEASE_MANIFEST.json").is_file())
        self.assertTrue((package / "SHA256SUMS.txt").is_file())

    def test_inventory_bound_payload_flows_through_package_assembler_preflight(self) -> None:
        count, inventory_sha, _alt = self._enable_inventory_sound_pack()
        with (
            patch.object(payload, "_USER_SOUND_EXPECTED_WAV_COUNT", count),
            patch.object(payload, "_USER_SOUND_EXPECTED_INVENTORY_SHA256", inventory_sha),
        ):
            prepared = self._prepare(self.root / "payload-inventory-assembled")

        package = self.root / "candidate-inventory-bound"
        with (
            patch.object(package_preflight, "_USER_SOUND_EXPECTED_WAV_COUNT", count),
            patch.object(
                package_preflight,
                "_USER_SOUND_EXPECTED_INVENTORY_SHA256",
                inventory_sha,
            ),
        ):
            assembled = assemble_version2_package_tree(
                prepared.product_dir,
                prepared.notices_dir,
                package,
                integration_sha="b" * 40,
            )

        self.assertEqual(assembled.tree_report.integration_sha, "b" * 40)
        self.assertTrue(
            (
                package
                / "AccessibleChess"
                / "assets"
                / "sounds"
                / "inventory.json"
            ).is_file()
        )
        self.assertTrue(
            (
                package
                / "THIRD_PARTY_NOTICES"
                / "SOUND_INVENTORY.json"
            ).is_file()
        )

    def test_wrong_stockfish_digest_fails_without_output(self) -> None:
        output = self.root / "payload"
        with self.assertRaisesRegex(payload.Version2ReleasePayloadError, "SHA-256 mismatch"):
            payload.prepare_version2_release_payload(
                self.standalone,
                self.stockfish,
                self.sounds,
                output,
            )
        self._assert_no_publication(output)

    def test_stockfish_archive_requires_corresponding_source_and_license(self) -> None:
        for label, kwargs, expected in (
            ("source", {"include_source": False}, "corresponding source"),
            ("license", {"include_license": False}, "license"),
        ):
            with self.subTest(label=label):
                self._write_stockfish_archive(self.stockfish, **kwargs)
                output = self.root / f"payload-{label}"
                with patch.object(
                    payload,
                    "OFFICIAL_STOCKFISH_18_WINDOWS_X64_SHA256",
                    self._digest(self.stockfish),
                ):
                    with self.assertRaisesRegex(payload.Version2ReleasePayloadError, expected):
                        payload.prepare_version2_release_payload(
                            self.standalone,
                            self.stockfish,
                            self.sounds,
                            output,
                        )
                self._assert_no_publication(output)
                self._write_stockfish_archive(self.stockfish)

    def test_stockfish_archive_unsafe_members_fail_before_publication(self) -> None:
        cases = (
            ("traversal", (("../escape.txt", b"no"),), "path traversal"),
            (
                "case-collision",
                (("stockfish/README.txt", b"a"), ("Stockfish/readme.txt", b"b")),
                "duplicate member names",
            ),
            ("device", (("stockfish/src/CON.txt", b"no"),), "Windows device path"),
        )
        for label, members, expected in cases:
            with self.subTest(label=label):
                self._write_stockfish_archive(self.stockfish, extra_members=members)
                output = self.root / f"payload-{label}"
                with patch.object(
                    payload,
                    "OFFICIAL_STOCKFISH_18_WINDOWS_X64_SHA256",
                    self._digest(self.stockfish),
                ):
                    with self.assertRaisesRegex(payload.Version2ReleasePayloadError, expected):
                        payload.prepare_version2_release_payload(
                            self.standalone,
                            self.stockfish,
                            self.sounds,
                            output,
                        )
                self._assert_no_publication(output)
                self._write_stockfish_archive(self.stockfish)
        self.assertFalse((self.root / "escape.txt").exists())

    def test_stockfish_archive_unsafe_directory_entry_fails_before_publication(self) -> None:
        with zipfile.ZipFile(self.stockfish, "w", compression=zipfile.ZIP_DEFLATED) as archive:
            archive.writestr(
                "stockfish/stockfish-windows-x86-64.exe",
                self.stockfish_executable,
            )
            archive.writestr("stockfish/Copying.txt", b"GNU GENERAL PUBLIC LICENSE\n")
            archive.writestr("stockfish/src/uci.cpp", b"// corresponding source\n")
            archive.writestr("../escape/", b"")
        output = self.root / "payload"
        with patch.object(
            payload,
            "OFFICIAL_STOCKFISH_18_WINDOWS_X64_SHA256",
            self._digest(self.stockfish),
        ):
            with self.assertRaisesRegex(payload.Version2ReleasePayloadError, "path traversal"):
                payload.prepare_version2_release_payload(
                    self.standalone,
                    self.stockfish,
                    self.sounds,
                    output,
                )
        self._assert_no_publication(output)

    def test_stockfish_archive_symlink_member_fails_before_publication(self) -> None:
        with zipfile.ZipFile(self.stockfish, "w", compression=zipfile.ZIP_DEFLATED) as archive:
            archive.writestr(
                "stockfish/stockfish-windows-x86-64.exe",
                self.stockfish_executable,
            )
            archive.writestr("stockfish/Copying.txt", b"GNU GENERAL PUBLIC LICENSE\n")
            archive.writestr("stockfish/src/uci.cpp", b"// corresponding source\n")
            link = zipfile.ZipInfo("stockfish/src/link.cpp")
            link.create_system = 3
            link.external_attr = (stat.S_IFLNK | 0o777) << 16
            archive.writestr(link, b"uci.cpp")
        output = self.root / "payload"
        with patch.object(
            payload,
            "OFFICIAL_STOCKFISH_18_WINDOWS_X64_SHA256",
            self._digest(self.stockfish),
        ):
            with self.assertRaisesRegex(payload.Version2ReleasePayloadError, "symlink"):
                payload.prepare_version2_release_payload(
                    self.standalone,
                    self.stockfish,
                    self.sounds,
                    output,
                )
        self._assert_no_publication(output)

    def test_stockfish_requires_exactly_one_valid_windows_pe(self) -> None:
        self._write_stockfish_archive(
            self.stockfish,
            extra_members=(("stockfish/helper.exe", self._windows_pe(b"helper")),),
        )
        output = self.root / "payload-extra-exe"
        with patch.object(
            payload,
            "OFFICIAL_STOCKFISH_18_WINDOWS_X64_SHA256",
            self._digest(self.stockfish),
        ):
            with self.assertRaisesRegex(payload.Version2ReleasePayloadError, "exactly one"):
                payload.prepare_version2_release_payload(
                    self.standalone,
                    self.stockfish,
                    self.sounds,
                    output,
                )
        self._assert_no_publication(output)

        self._write_stockfish_archive(self.stockfish, executable_bytes=b"MZ-not-a-pe")
        output = self.root / "payload-invalid-pe"
        with patch.object(
            payload,
            "OFFICIAL_STOCKFISH_18_WINDOWS_X64_SHA256",
            self._digest(self.stockfish),
        ):
            with self.assertRaisesRegex(payload.Version2ReleasePayloadError, "PE"):
                payload.prepare_version2_release_payload(
                    self.standalone,
                    self.stockfish,
                    self.sounds,
                    output,
                )
        self._assert_no_publication(output)

    def test_every_required_web_resource_is_fail_closed(self) -> None:
        for name in _REQUIRED_WEB_FILES:
            path = self.standalone / "web" / name
            original = path.read_bytes()
            path.unlink()
            output = self.root / f"payload-web-{name.replace('/', '-').replace('.', '-')}"
            with self.subTest(name=name):
                with self.assertRaisesRegex(
                    payload.Version2ReleasePayloadError,
                    "required web resource",
                ):
                    self._prepare(output)
                self._assert_no_publication(output)
            path.write_bytes(original)

    def test_sound_manifest_must_cover_complete_semantic_event_set(self) -> None:
        manifest_path = self.sounds / "manifest.json"
        original = json.loads(manifest_path.read_text(encoding="utf-8"))

        missing = json.loads(json.dumps(original))
        missing["files"].pop(next(iter(SoundEvent)).value)
        manifest_path.write_text(json.dumps(missing), encoding="utf-8")
        output = self.root / "payload-missing"
        with self.assertRaisesRegex(payload.Version2ReleasePayloadError, "exactly all semantic"):
            self._prepare(output)
        self._assert_no_publication(output)

        extra = json.loads(json.dumps(original))
        extra["files"]["extra"] = "extra.wav"
        self._write_wav(self.sounds / "extra.wav", sample=1)
        manifest_path.write_text(json.dumps(extra), encoding="utf-8")
        output = self.root / "payload-extra"
        with self.assertRaisesRegex(payload.Version2ReleasePayloadError, "exactly all semantic"):
            self._prepare(output)
        self._assert_no_publication(output)
        (self.sounds / "extra.wav").unlink()

    def test_release_payload_accepts_8bit_pcm_runtime_sound(self) -> None:
        target = self.sounds / f"{SoundEvent.LOW_TIME.value}.wav"
        self._write_wav_8bit(target)
        self._write_sound_provenance()

        result = self._prepare(self.root / "payload-8bit-sound")
        packaged = (
            result.product_dir
            / "assets"
            / "sounds"
            / f"{SoundEvent.LOW_TIME.value}.wav"
        )
        with wave.open(str(packaged), "rb") as reader:
            self.assertEqual(reader.getsampwidth(), 1)
            self.assertEqual(reader.getcomptype(), "NONE")

    def test_sound_manifest_allows_intentional_alias_when_provenance_matches(self) -> None:
        manifest_path = self.sounds / "manifest.json"
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        provenance = json.loads(self.sound_provenance.read_text(encoding="utf-8"))
        events = list(SoundEvent)
        source_event = events[0].value
        alias_event = events[1].value
        shared_file = manifest["files"][source_event]
        manifest["files"][alias_event] = shared_file
        provenance["events"][alias_event]["file"] = shared_file
        provenance["events"][alias_event]["sha256"] = self._digest(self.sounds / shared_file)
        manifest_path.write_text(json.dumps(manifest, sort_keys=True), encoding="utf-8")
        self.sound_provenance.write_text(
            json.dumps(provenance, sort_keys=True),
            encoding="utf-8",
        )

        result = self._prepare(self.root / "payload-alias")
        packaged_manifest = json.loads(
            (
                result.product_dir
                / "assets"
                / "sounds"
                / "manifest.json"
            ).read_text(encoding="utf-8")
        )
        self.assertEqual(
            packaged_manifest["files"][source_event],
            packaged_manifest["files"][alias_event],
        )

    def test_extended_sound_inventory_is_published_and_binds_runtime_variants(self) -> None:
        count, inventory_sha, alt = self._enable_inventory_sound_pack()
        with (
            patch.object(payload, "_USER_SOUND_EXPECTED_WAV_COUNT", count),
            patch.object(payload, "_USER_SOUND_EXPECTED_INVENTORY_SHA256", inventory_sha),
        ):
            result = self._prepare(self.root / "payload-inventory")

        packaged_root = result.product_dir / "assets" / "sounds"
        self.assertTrue((packaged_root / "inventory.json").is_file())
        self.assertTrue((packaged_root / "variants.json").is_file())
        self.assertTrue((packaged_root / "layers.json").is_file())
        self.assertEqual(
            self._digest(packaged_root / "library" / "move-alt.wav"),
            self._digest(alt),
        )

        notice_path = result.notices_dir / "SOUND_INVENTORY.json"
        self.assertTrue(notice_path.is_file())
        notice = json.loads(notice_path.read_text(encoding="utf-8"))
        self.assertEqual(notice["file_count"], count)
        self.assertEqual(notice["source_inventory_sha256"], inventory_sha)
        self.assertIn(
            "library/move-alt.wav",
            {entry["file"] for entry in notice["files"]},
        )
        alt_entry = next(
            entry for entry in notice["files"]
            if entry["file"] == "library/move-alt.wav"
        )
        self.assertEqual(alt_entry["sample_width_bytes"], 1)

    def test_non_default_variant_valid_pcm_substitution_fails_inventory_binding(self) -> None:
        count, inventory_sha, alt = self._enable_inventory_sound_pack()
        original_size = alt.stat().st_size
        original_digest = self._digest(alt)
        self._write_wav(alt, sample=77, sample_width=1)
        self.assertEqual(alt.stat().st_size, original_size)
        self.assertNotEqual(self._digest(alt), original_digest)
        output = self.root / "payload-inventory-tamper"
        with (
            patch.object(payload, "_USER_SOUND_EXPECTED_WAV_COUNT", count),
            patch.object(payload, "_USER_SOUND_EXPECTED_INVENTORY_SHA256", inventory_sha),
            self.assertRaisesRegex(
                payload.Version2ReleasePayloadError,
                "sound inventory SHA-256 mismatch",
            ),
        ):
            self._prepare(output)
        self._assert_no_publication(output)

    def test_sound_inventory_rejects_nonfinite_duration_atomically(self) -> None:
        count, inventory_sha, _alt = self._enable_inventory_sound_pack()
        inventory_path = self.sounds / "inventory.json"
        raw = json.loads(inventory_path.read_text(encoding="utf-8"))
        raw["files"][0]["duration_seconds"] = float("nan")
        inventory_path.write_text(
            json.dumps(raw, sort_keys=True),
            encoding="utf-8",
        )
        output = self.root / "payload-inventory-nan"
        with (
            patch.object(payload, "_USER_SOUND_EXPECTED_WAV_COUNT", count),
            patch.object(payload, "_USER_SOUND_EXPECTED_INVENTORY_SHA256", inventory_sha),
            self.assertRaisesRegex(
                payload.Version2ReleasePayloadError,
                "non-finite JSON number: NaN",
            ),
        ):
            self._prepare(output)
        self._assert_no_publication(output)

    def test_variant_catalog_without_inventory_fails_atomically(self) -> None:
        count, inventory_sha, _alt = self._enable_inventory_sound_pack()
        (self.sounds / "inventory.json").unlink()
        output = self.root / "payload-inventory-missing"
        with (
            patch.object(payload, "_USER_SOUND_EXPECTED_WAV_COUNT", count),
            patch.object(payload, "_USER_SOUND_EXPECTED_INVENTORY_SHA256", inventory_sha),
            self.assertRaisesRegex(
                payload.Version2ReleasePayloadError,
                "requires canonical sound inventory",
            ),
        ):
            self._prepare(output)
        self._assert_no_publication(output)

    def test_layered_sound_assets_are_packaged_and_malformed_layers_fail_atomically(self) -> None:
        impact = self.sounds / "move-hit.wav"
        self._write_wav(impact, sample=321)
        layers_path = self.sounds / "layers.json"
        layers_path.write_text(
            json.dumps(
                {
                    "schema_version": 1,
                    "events": {
                        "move": {
                            "1": ["move.wav", "move-hit.wav"],
                        }
                    },
                }
            ),
            encoding="utf-8",
        )

        output = self.root / "payload-layered-sounds"
        result = self._prepare(output)
        packaged_sound_root = result.product_dir / "assets" / "sounds"
        self.assertTrue((packaged_sound_root / "layers.json").is_file())
        self.assertTrue((packaged_sound_root / "move-hit.wav").is_file())

        shutil.rmtree(output)
        layers_path.write_text(
            json.dumps(
                {
                    "schema_version": 1,
                    "events": {
                        "move": {
                            "1": ["move-hit.wav", "move.wav"],
                        }
                    },
                }
            ),
            encoding="utf-8",
        )
        invalid_output = self.root / "payload-layered-sounds-invalid"
        with self.assertRaisesRegex(
            payload.Version2ReleasePayloadError,
            "production resolver contract",
        ):
            self._prepare(invalid_output)
        self._assert_no_publication(invalid_output)

    def test_sound_provenance_is_required_and_bound_to_every_asset(self) -> None:
        original = json.loads(self.sound_provenance.read_text(encoding="utf-8"))
        event = next(iter(SoundEvent)).value

        self.sound_provenance.unlink()
        output = self.root / "payload-provenance-missing"
        with self.assertRaisesRegex(payload.Version2ReleasePayloadError, "sound provenance"):
            self._prepare(output)
        self._assert_no_publication(output)
        self.sound_provenance.write_text(json.dumps(original), encoding="utf-8")

        cases = (
            ("digest", {"sha256": "0" * 64}, "SHA-256 mismatch"),
            ("license", {"license_id": "unknown"}, "license identity is unresolved"),
            ("source", {"source": r"C:\\private\\sound.wav"}, "HTTPS URL or URN"),
            ("creator", {"creator": "TBD"}, "creator identity is unresolved"),
            ("file", {"file": "other.wav"}, "does not match manifest"),
        )
        for label, mutation, expected in cases:
            with self.subTest(label=label):
                changed = json.loads(json.dumps(original))
                changed["events"][event].update(mutation)
                self.sound_provenance.write_text(json.dumps(changed), encoding="utf-8")
                output = self.root / f"payload-provenance-{label}"
                with self.assertRaisesRegex(payload.Version2ReleasePayloadError, expected):
                    self._prepare(output)
                self._assert_no_publication(output)
        self.sound_provenance.write_text(json.dumps(original, sort_keys=True), encoding="utf-8")

    def test_sound_provenance_event_set_is_closed_world(self) -> None:
        original = json.loads(self.sound_provenance.read_text(encoding="utf-8"))
        missing = json.loads(json.dumps(original))
        missing["events"].pop(next(iter(SoundEvent)).value)
        self.sound_provenance.write_text(json.dumps(missing), encoding="utf-8")
        output = self.root / "payload-provenance-event-missing"
        with self.assertRaisesRegex(payload.Version2ReleasePayloadError, "exactly all semantic"):
            self._prepare(output)
        self._assert_no_publication(output)
        self.sound_provenance.write_text(json.dumps(original, sort_keys=True), encoding="utf-8")

    def test_non_pcm_empty_or_truncated_wav_fails_without_output(self) -> None:
        target = self.sounds / f"{next(iter(SoundEvent)).value}.wav"
        for label, bytes_value in (
            ("invalid", b"not-a-wave"),
            ("empty", b"RIFF"),
        ):
            with self.subTest(label=label):
                target.write_bytes(bytes_value)
                output = self.root / f"payload-wav-{label}"
                with self.assertRaisesRegex(payload.Version2ReleasePayloadError, "WAV"):
                    self._prepare(output)
                self._assert_no_publication(output)
        self._write_wav(target, sample=100)

    def test_raw_python_source_suffixes_are_rejected_atomically(self) -> None:
        for suffix in (".py", ".pyc", ".pyo"):
            leak = self.standalone / f"leak{suffix}"
            leak.write_bytes(b"raw-python")
            output = self.root / f"payload-raw-{suffix[1:]}"
            with self.subTest(suffix=suffix):
                with self.assertRaisesRegex(payload.Version2ReleasePayloadError, "raw Python source"):
                    self._prepare(output)
                self._assert_no_publication(output)
            leak.unlink()

    def test_conflicting_stockfish_or_sound_payload_fails_without_output(self) -> None:
        stockfish_dir = self.standalone / "engines" / "stockfish"
        stockfish_dir.mkdir(parents=True)
        (stockfish_dir / "stockfish.exe").write_bytes(self.stockfish_executable)
        output = self.root / "payload-engine-conflict"
        with self.assertRaisesRegex(payload.Version2ReleasePayloadError, "Stockfish payload"):
            self._prepare(output)
        self._assert_no_publication(output)
        (stockfish_dir / "stockfish.exe").unlink()
        stockfish_dir.rmdir()
        stockfish_dir.parent.rmdir()

        sound_dir = self.standalone / "assets" / "sounds"
        sound_dir.mkdir(parents=True)
        (sound_dir / "manifest.json").write_text("{}", encoding="utf-8")
        output = self.root / "payload-sound-conflict"
        with self.assertRaisesRegex(payload.Version2ReleasePayloadError, "sound payload"):
            self._prepare(output)
        self._assert_no_publication(output)

    def test_output_inside_input_is_rejected_before_staging(self) -> None:
        output = self.standalone / "nested" / "payload"
        with self.assertRaisesRegex(payload.Version2ReleasePayloadError, "inside standalone"):
            self._prepare(output)
        self._assert_no_publication(output)
        self.assertFalse((self.standalone / "nested").exists())

    def test_existing_output_is_never_overwritten(self) -> None:
        output = self.root / "payload"
        output.mkdir()
        marker = output / "keep.txt"
        marker.write_text("keep", encoding="utf-8")

        with self.assertRaisesRegex(payload.Version2ReleasePayloadError, "already exists"):
            self._prepare(output)
        self.assertEqual(marker.read_text(encoding="utf-8"), "keep")

    def test_public_path_controls_reject_active_pathlike_before_hooks(self) -> None:
        touched: list[str] = []

        class ActivePath:
            def __fspath__(self):
                touched.append("fspath")
                raise AssertionError("active release-payload path hook executed")

        active = ActivePath()
        cases = (
            (active, self.stockfish, self.sounds, self.root / "out-a"),
            (self.standalone, active, self.sounds, self.root / "out-b"),
            (self.standalone, self.stockfish, active, self.root / "out-c"),
            (self.standalone, self.stockfish, self.sounds, active),
        )
        for standalone, stockfish, sounds, output in cases:
            with self.subTest(
                standalone=type(standalone).__name__,
                stockfish=type(stockfish).__name__,
                sounds=type(sounds).__name__,
                output=type(output).__name__,
            ):
                with patch.object(
                    payload,
                    "_require_clean_source_tree",
                    side_effect=AssertionError("release-payload filesystem work must not start"),
                ) as source_check:
                    with self.assertRaisesRegex(TypeError, "exact str or platform Path"):
                        payload.prepare_version2_release_payload(
                            standalone,
                            stockfish,
                            sounds,
                            output,
                        )
                source_check.assert_not_called()
                self.assertEqual(touched, [])




if __name__ == "__main__":
    unittest.main()
