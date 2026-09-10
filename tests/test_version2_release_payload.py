from __future__ import annotations

import hashlib
import json
from pathlib import Path
import stat
import struct
import tempfile
import unittest
from unittest.mock import patch
import wave
import zipfile

from acs import version2_release_payload as payload
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
    "version2_release_bootstrap.js",
)


class Version2ReleasePayloadTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.standalone = self.root / "standalone"
        (self.standalone / "web").mkdir(parents=True)
        (self.standalone / "AccessibleChess.exe").write_bytes(b"MZ\0v2-standalone")
        for name in _REQUIRED_WEB_FILES:
            (self.standalone / "web" / name).write_text(
                f"/* {name} */\n" if name.endswith(".js") else "<main>Accessible Chess</main>\n",
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

        self.stockfish = self.root / "stockfish.zip"
        self.stockfish_executable = self._windows_x64_pe(b"stockfish18")
        self._write_stockfish_archive(self.stockfish)

    @staticmethod
    def _write_wav(path: Path, *, sample: int) -> None:
        with wave.open(str(path), "wb") as writer:
            writer.setnchannels(1)
            writer.setsampwidth(2)
            writer.setframerate(8000)
            writer.writeframes(struct.pack("<h", sample) * 8)

    @staticmethod
    def _windows_x64_pe(payload_bytes: bytes = b"") -> bytes:
        data = bytearray(0x200)
        data[:2] = b"MZ"
        pe_offset = 0x80
        struct.pack_into("<I", data, 0x3C, pe_offset)
        data[pe_offset : pe_offset + 4] = b"PE\0\0"
        coff = pe_offset + 4
        struct.pack_into("<H", data, coff, 0x8664)
        struct.pack_into("<H", data, coff + 2, 3)
        struct.pack_into("<H", data, coff + 16, 0xF0)
        struct.pack_into("<H", data, coff + 18, 0x0022)
        struct.pack_into("<H", data, coff + 20, 0x20B)
        data.extend(payload_bytes)
        return bytes(data)

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

    def test_stages_canonical_stockfish_sounds_and_notices_atomically(self) -> None:
        result = self._prepare()

        self.assertEqual(result.root, self.root / "payload")
        self.assertTrue((result.product_dir / "AccessibleChess.exe").is_file())
        for name in _REQUIRED_WEB_FILES:
            self.assertTrue((result.product_dir / "web" / name).is_file())
        self.assertEqual(result.stockfish_executable.read_bytes(), self.stockfish_executable)
        self.assertEqual(
            resolve_stockfish_path(StockfishRuntimeConfig(application_dir=result.product_dir)),
            result.stockfish_executable.resolve(),
        )

        manifest = PackagedSoundAssetResolver(result.product_dir).load_manifest()
        self.assertEqual(set(manifest.files), set(SoundEvent))
        self.assertEqual(len(set(manifest.files.values())), 9)
        for wav in manifest.files.values():
            with wave.open(str(wav), "rb") as reader:
                self.assertEqual(reader.getcomptype(), "NONE")
                self.assertEqual(reader.getsampwidth(), 2)
                self.assertGreater(reader.getnframes(), 0)

        notices = result.notices_dir
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
        self.assertTrue((package / "RELEASE_MANIFEST.json").is_file())
        self.assertTrue((package / "SHA256SUMS.txt").is_file())

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

    def test_stockfish_requires_exactly_one_valid_windows_x64_pe(self) -> None:
        self._write_stockfish_archive(
            self.stockfish,
            extra_members=(("stockfish/helper.exe", self._windows_x64_pe(b"helper")),),
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
            output = self.root / f"payload-web-{name.replace('.', '-')}"
            with self.subTest(name=name):
                with self.assertRaisesRegex(
                    payload.Version2ReleasePayloadError,
                    "required web resource",
                ):
                    self._prepare(output)
                self._assert_no_publication(output)
            path.write_bytes(original)

    def test_sound_manifest_must_be_exact_nine_and_distinct(self) -> None:
        manifest_path = self.sounds / "manifest.json"
        original = json.loads(manifest_path.read_text(encoding="utf-8"))

        missing = json.loads(json.dumps(original))
        missing["files"].pop(next(iter(SoundEvent)).value)
        manifest_path.write_text(json.dumps(missing), encoding="utf-8")
        output = self.root / "payload-missing"
        with self.assertRaisesRegex(payload.Version2ReleasePayloadError, "exactly all nine"):
            self._prepare(output)
        self._assert_no_publication(output)

        extra = json.loads(json.dumps(original))
        extra["files"]["extra"] = "extra.wav"
        self._write_wav(self.sounds / "extra.wav", sample=1)
        manifest_path.write_text(json.dumps(extra), encoding="utf-8")
        output = self.root / "payload-extra"
        with self.assertRaisesRegex(payload.Version2ReleasePayloadError, "exactly all nine"):
            self._prepare(output)
        self._assert_no_publication(output)
        (self.sounds / "extra.wav").unlink()

        aliased = json.loads(json.dumps(original))
        events = list(SoundEvent)
        aliased["files"][events[1].value] = aliased["files"][events[0].value]
        manifest_path.write_text(json.dumps(aliased), encoding="utf-8")
        output = self.root / "payload-alias"
        with self.assertRaisesRegex(payload.Version2ReleasePayloadError, "distinct WAV"):
            self._prepare(output)
        self._assert_no_publication(output)

        manifest_path.write_text(json.dumps(original, sort_keys=True), encoding="utf-8")

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


if __name__ == "__main__":
    unittest.main()
