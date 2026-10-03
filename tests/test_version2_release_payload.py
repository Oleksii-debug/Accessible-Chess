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
    "full_product_teacher.js",
    "full_product_education.js",
    "livekit_classroom_media.js",
    "vendor/livekit/livekit-client.umd.js",
    "vendor/livekit/LICENSE",
    "vendor/livekit/NOTICE",
    "vendor/livekit/provenance.json",
    "version2_final_product_bootstrap.js",
    "version2_release_bootstrap.js",
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
        (self.standalone / "AccessibleChess.exe").write_bytes(b"MZ\0v2-standalone")
        (self.standalone / "AccessibleChess.exe.config").write_text(
            _VALID_WINFORMS_CONFIG, encoding="utf-8"
        )
        for name in _REQUIRED_WEB_FILES:
            resource = self.standalone / "web" / name
            resource.parent.mkdir(parents=True, exist_ok=True)
            resource.write_text(
                f"/* {name} */ LivekitClient Room\n"
                if name.endswith(".js")
                else "<main>Accessible Chess</main>\n",
                encoding="utf-8",
            )

        livekit_root = self.standalone / "web" / "vendor" / "livekit"
        livekit_bundle = (
            b"/* packaged LiveKit fixture */ LivekitClient Room\n"
            + b"".join(
                hashlib.sha256(f"livekit-fixture-{index}".encode("ascii")).digest()
                for index in range(4000)
            )
        )
        livekit_license = b"Apache License\nVersion 2.0\n" + (b"license fixture\n" * 400)
        livekit_notice = (
            b"Copyright 2021 LiveKit, Inc.\n"
            b"Apache License, Version 2.0\n"
            b"fixture redistribution notice\n"
            b"Distributed on an AS IS basis without warranties or conditions.\n"
        )
        (livekit_root / "livekit-client.umd.js").write_bytes(livekit_bundle)
        (livekit_root / "LICENSE").write_bytes(livekit_license)
        (livekit_root / "NOTICE").write_bytes(livekit_notice)
        livekit_provenance = {
            "schema_version": 1,
            "component": "livekit-client",
            "version": payload._LIVEKIT_CLIENT_VERSION,
            "license_id": payload._LIVEKIT_CLIENT_LICENSE_ID,
            "source": payload._LIVEKIT_CLIENT_NPM_TARBALL_URL,
            "upstream_tag": f"v{payload._LIVEKIT_CLIENT_VERSION}",
            "npm_integrity": payload._LIVEKIT_CLIENT_NPM_INTEGRITY,
            "bundle_sha256": hashlib.sha256(livekit_bundle).hexdigest(),
            "license_sha256": hashlib.sha256(livekit_license).hexdigest(),
            "notice_sha256": hashlib.sha256(livekit_notice).hexdigest(),
        }
        (livekit_root / "provenance.json").write_text(
            json.dumps(livekit_provenance, sort_keys=True, indent=2) + "\n",
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
        self.stockfish_executable = self._windows_x64_pe(b"stockfish18")
        self._write_stockfish_archive(self.stockfish)

    @staticmethod
    def _write_wav(path: Path, *, sample: int) -> None:
        with wave.open(str(path), "wb") as writer:
            writer.setnchannels(1)
            writer.setsampwidth(2)
            writer.setframerate(8000)
            writer.writeframes(struct.pack("<h", sample) * 8)

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

    def test_tree_copy_never_dereferences_links_and_revalidates_destination(self) -> None:
        output = self.root / "payload-copy-boundary"
        with (
            patch.object(
                payload.shutil,
                "copytree",
                wraps=payload.shutil.copytree,
            ) as copytree,
            patch.object(
                payload,
                "_require_clean_source_tree",
                wraps=payload._require_clean_source_tree,
            ) as validate_tree,
        ):
            self._prepare(output)

        top_level_copies = [
            call
            for call in copytree.call_args_list
            if call.args
            and Path(call.args[0]) in {self.standalone, self.sounds}
        ]
        self.assertEqual(len(top_level_copies), 2)
        self.assertEqual(
            {Path(call.args[0]) for call in top_level_copies},
            {self.standalone, self.sounds},
        )
        self.assertTrue(
            all(call.kwargs.get("symlinks") is True for call in top_level_copies)
        )
        copied_labels = [
            call.kwargs.get("label")
            for call in validate_tree.call_args_list
            if call.kwargs.get("label") == "copied source"
        ]
        self.assertEqual(copied_labels, ["copied source", "copied source"])

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
        self.assertEqual(len(set(manifest.files.values())), 9)
        for wav in manifest.files.values():
            with wave.open(str(wav), "rb") as reader:
                self.assertEqual(reader.getcomptype(), "NONE")
                self.assertEqual(reader.getsampwidth(), 2)
                self.assertGreater(reader.getnframes(), 0)
        self.assertFalse((manifest.root / "provenance.json").exists())

        notices = result.notices_dir
        self.assertEqual(
            (notices / payload._LIVEKIT_LICENSE_NOTICE).read_bytes(),
            (result.product_dir / "web" / "vendor" / "livekit" / "LICENSE").read_bytes(),
        )
        self.assertEqual(
            (notices / payload._LIVEKIT_TEXT_NOTICE).read_bytes(),
            (result.product_dir / "web" / "vendor" / "livekit" / "NOTICE").read_bytes(),
        )
        self.assertTrue((notices / payload._LIVEKIT_PROVENANCE_NOTICE).is_file())
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

    def test_livekit_bundle_digest_tamper_fails_without_output(self) -> None:
        bundle = self.standalone / "web" / "vendor" / "livekit" / "livekit-client.umd.js"
        bundle.write_bytes(bundle.read_bytes() + b"tampered")
        output = self.root / "payload-livekit-tampered"
        with self.assertRaisesRegex(
            payload.Version2ReleasePayloadError,
            "LiveKit client packaged resource digest mismatch",
        ):
            self._prepare(output)
        self._assert_no_publication(output)

    def test_livekit_provenance_identity_tamper_fails_without_output(self) -> None:
        provenance_path = self.standalone / "web" / "vendor" / "livekit" / "provenance.json"
        provenance = json.loads(provenance_path.read_text(encoding="utf-8"))
        provenance["version"] = "0.0.0"
        provenance_path.write_text(
            json.dumps(provenance, sort_keys=True, indent=2) + "\n",
            encoding="utf-8",
        )
        output = self.root / "payload-livekit-provenance-tampered"
        with self.assertRaisesRegex(
            payload.Version2ReleasePayloadError,
            "does not match the pinned release",
        ):
            self._prepare(output)
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
        with self.assertRaisesRegex(payload.Version2ReleasePayloadError, "exactly all nine"):
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

    def test_link_like_source_root_is_rejected_before_copy(self) -> None:
        original = payload._is_link_like

        for source, label in (
            (self.standalone, "standalone"),
            (self.sounds, "sound pack"),
        ):
            output = self.root / f"payload-{label.replace(' ', '-')}-link"
            with self.subTest(label=label):
                def fake_is_link_like(path: Path, *, source: Path = source) -> bool:
                    if path == source:
                        return True
                    return original(path)

                with patch.object(
                    payload,
                    "_is_link_like",
                    side_effect=fake_is_link_like,
                ):
                    with self.assertRaisesRegex(
                        payload.Version2ReleasePayloadError,
                        rf"{label} contains a symlink or junction",
                    ):
                        self._prepare(output)
                self._assert_no_publication(output)

    def test_broken_output_entry_is_rejected_before_staging(self) -> None:
        output = self.root / "payload-broken-entry"
        original_lexists = payload.os.path.lexists

        def fake_lexists(path: object) -> bool:
            if Path(path) == output:
                return True
            return original_lexists(path)

        with patch.object(payload.os.path, "lexists", side_effect=fake_lexists):
            with self.assertRaisesRegex(
                payload.Version2ReleasePayloadError,
                "output payload root already exists",
            ):
                self._prepare(output)
        self._assert_no_publication(output)

    def test_link_like_output_parent_is_rejected(self) -> None:
        parent = self.root / "publication-parent"
        output = parent / "payload"
        original = payload._is_link_like

        def fake_is_link_like(path: Path) -> bool:
            if path == parent:
                return True
            return original(path)

        with patch.object(payload, "_is_link_like", side_effect=fake_is_link_like):
            with self.assertRaisesRegex(
                payload.Version2ReleasePayloadError,
                "output payload parent must be a real directory",
            ):
                self._prepare(output)
        self._assert_no_publication(output)

    def test_link_like_output_grandparent_is_rejected(self) -> None:
        grandparent = self.root / "publication-root"
        grandparent.mkdir()
        parent = grandparent / "nested"
        output = parent / "payload"
        original = payload._is_link_like

        def fake_is_link_like(path: Path) -> bool:
            if path == grandparent:
                return True
            return original(path)

        with patch.object(payload, "_is_link_like", side_effect=fake_is_link_like):
            with self.assertRaisesRegex(
                payload.Version2ReleasePayloadError,
                "output payload parent must be a real directory",
            ):
                self._prepare(output)
        self._assert_no_publication(output)
        self.assertFalse(parent.exists())

    def test_output_appearing_during_release_staging_is_not_overwritten(self) -> None:
        output = self.root / "payload-race"
        original_lexists = payload.os.path.lexists
        output_checks = 0

        def fake_lexists(path: object) -> bool:
            nonlocal output_checks
            if Path(path) == output:
                output_checks += 1
                return output_checks >= 2
            return original_lexists(path)

        with patch.object(payload.os.path, "lexists", side_effect=fake_lexists):
            with self.assertRaisesRegex(
                payload.Version2ReleasePayloadError,
                "output payload root appeared during staging",
            ):
                self._prepare(output)

        self._assert_no_publication(output)
        self.assertEqual(
            list(output.parent.glob(f".{output.name}.payload-*")),
            [],
        )

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