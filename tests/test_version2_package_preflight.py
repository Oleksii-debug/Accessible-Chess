from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import stat
import tempfile
import unittest
from unittest.mock import patch
import wave
import zipfile

from acs import version2_package_preflight as package_preflight
from acs.acsdb import ACSDB_SCHEMA_VERSION
from acs.settings import SCHEMA_VERSION as SETTINGS_SCHEMA_VERSION
from acs.sound_events import SoundEvent
from acs.version2_package_preflight import (
    CHECKSUMS_NAME,
    MANIFEST_NAME,
    PackageLimits,
    V2_PACKAGE_MANIFEST_SCHEMA_VERSION,
    V2_PACKAGE_PROFILE,
    Version2PackagePreflightError,
    validate_winforms_accessibility_app_config,
    validate_version2_package_tree,
    validate_version2_package_zip,
)
from acs.version2_upgrade import UPGRADE_JOURNAL_SCHEMA_VERSION


_SHA = "a" * 40

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


def _livekit_fixture_bundle() -> bytes:
    return (
        b"/* fixture */ LivekitClient Room "
        + b"".join(
            hashlib.sha256(f"livekit-fixture-{index}".encode("ascii")).digest()
            for index in range(4000)
        )
    )


_LIVEKIT_FIXTURE_BUNDLE_SHA256 = hashlib.sha256(
    _livekit_fixture_bundle()
).hexdigest()


def _livekit_fixture_notice() -> bytes:
    return (
        b"Copyright 2021 LiveKit, Inc.\n"
        b"Apache License, Version 2.0\n"
        b"fixture redistribution notice\n"
        b"Distributed on an AS IS basis without warranties or conditions.\n"
    )


_LIVEKIT_FIXTURE_NOTICE_SHA256 = hashlib.sha256(
    _livekit_fixture_notice()
).hexdigest()


def _validate_tree(root, **kwargs):
    with (
        patch.object(
            package_preflight,
            "_LIVEKIT_CLIENT_BUNDLE_SHA256",
            _LIVEKIT_FIXTURE_BUNDLE_SHA256,
        ),
        patch.object(
            package_preflight,
            "_LIVEKIT_CLIENT_NOTICE_SHA256",
            _LIVEKIT_FIXTURE_NOTICE_SHA256,
        ),
    ):
        return validate_version2_package_tree(
            root, expected_integration_sha=_SHA, **kwargs
        )


def _validate_zip(archive, **kwargs):
    with (
        patch.object(
            package_preflight,
            "_LIVEKIT_CLIENT_BUNDLE_SHA256",
            _LIVEKIT_FIXTURE_BUNDLE_SHA256,
        ),
        patch.object(
            package_preflight,
            "_LIVEKIT_CLIENT_NOTICE_SHA256",
            _LIVEKIT_FIXTURE_NOTICE_SHA256,
        ),
    ):
        return validate_version2_package_zip(
            archive, expected_integration_sha=_SHA, **kwargs
        )


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    digest.update(path.read_bytes())
    return digest.hexdigest()


def _write_checksums(root: Path) -> None:
    rows = []
    for path in sorted(
        (item for item in root.rglob("*") if item.is_file() and item.name != CHECKSUMS_NAME),
        key=lambda item: item.relative_to(root).as_posix().casefold(),
    ):
        relative = path.relative_to(root).as_posix()
        rows.append(f"{_sha256(path)}  {relative}")
    (root / CHECKSUMS_NAME).write_text("\n".join(rows) + "\n", encoding="utf-8")


def _minimal_windows_pe() -> bytes:
    """Return a structurally valid minimal PE32+ image for package fixtures."""
    data = bytearray(512)
    data[0:2] = b"MZ"
    pe_offset = 0x80
    data[0x3C:0x40] = pe_offset.to_bytes(4, "little")
    data[pe_offset:pe_offset + 4] = b"PE\x00\x00"
    coff = pe_offset + 4
    data[coff:coff + 2] = (0x8664).to_bytes(2, "little")
    data[coff + 2:coff + 4] = (1).to_bytes(2, "little")
    data[coff + 16:coff + 18] = (0xF0).to_bytes(2, "little")
    data[coff + 18:coff + 20] = (0x0022).to_bytes(2, "little")
    optional = coff + 20
    data[optional:optional + 2] = (0x20B).to_bytes(2, "little")
    return bytes(data)


def _make_tree(root: Path) -> None:
    product = root / "AccessibleChess"
    product.mkdir(parents=True)
    (product / "AccessibleChess.exe").write_bytes(_minimal_windows_pe())
    (product / "AccessibleChess.exe.config").write_text(
        _VALID_WINFORMS_CONFIG, encoding="utf-8"
    )

    web = product / "web"
    web.mkdir()
    web_files = (
        "index.html",
        "stage1_release_bootstrap.js",
        "stage1_board_actions.js",
        "full_product_pgn.js",
        "full_product_library.js",
        "full_product_books_training.js",
        "full_product_teacher.js",
        "full_product_education.js",
        "livekit_classroom_media.js",
        "version2_final_product_bootstrap.js",
        "version2_release_bootstrap.js",
    )
    for name in web_files:
        (web / name).write_text(f"// fixture {name}\n", encoding="utf-8")

    livekit = web / "vendor" / "livekit"
    livekit.mkdir(parents=True)
    livekit_bundle = _livekit_fixture_bundle()
    livekit_license = b"Apache License\nVersion 2.0\n" + (b"license fixture\n" * 400)
    livekit_notice = _livekit_fixture_notice()
    (livekit / "livekit-client.umd.js").write_bytes(livekit_bundle)
    (livekit / "LICENSE").write_bytes(livekit_license)
    (livekit / "NOTICE").write_bytes(livekit_notice)
    livekit_provenance = {
        "schema_version": 1,
        "component": "livekit-client",
        "version": "2.22.3",
        "license_id": "Apache-2.0",
        "source": "https://registry.npmjs.org/livekit-client/-/livekit-client-2.22.3.tgz",
        "upstream_tag": "v2.22.3",
        "npm_integrity": (
            "sha512-jw9zBKXY5Gtr5MZ7vEON3QhMNccuDvYHck1PFSyG1aaateQPqgKZFBMg"
            "ZkFZaXHIf9RV4MDW5xpTK2b/+qbwOg=="
        ),
        "bundle_sha256": hashlib.sha256(livekit_bundle).hexdigest(),
        "license_sha256": hashlib.sha256(livekit_license).hexdigest(),
        "notice_sha256": hashlib.sha256(livekit_notice).hexdigest(),
    }
    livekit_provenance_bytes = (
        json.dumps(livekit_provenance, sort_keys=True, indent=2) + "\n"
    ).encode("utf-8")
    (livekit / "provenance.json").write_bytes(livekit_provenance_bytes)

    assets = product / "assets"
    assets.mkdir()
    (assets / "content.dat").write_bytes(b"canonical-v2-content")
    sounds = assets / "sounds"
    sounds.mkdir()
    sound_files = {}
    for event in SoundEvent:
        name = f"{event.value}.wav"
        sound_files[event.value] = name
        with wave.open(str(sounds / name), "wb") as writer:
            writer.setnchannels(1)
            writer.setsampwidth(2)
            writer.setframerate(8000)
            writer.writeframes(b"\x00\x00" * 16)
    (sounds / "manifest.json").write_text(
        json.dumps({"schema_version": 1, "files": sound_files}, sort_keys=True)
        + "\n",
        encoding="utf-8",
    )

    engine = product / "engines" / "stockfish"
    engine.mkdir(parents=True)
    (engine / "stockfish.exe").write_bytes(_minimal_windows_pe())

    notices = root / "THIRD_PARTY_NOTICES"
    notices.mkdir()
    sound_provenance = {
        "schema_version": 1,
        "events": {
            event.value: {
                "file": sound_files[event.value],
                "sha256": _sha256(sounds / sound_files[event.value]),
                "license_id": "CC0-1.0",
                "source": f"urn:accessible-chess:test-fixture:sound:{event.value}",
                "creator": "Accessible Chess synthetic test fixture",
            }
            for event in SoundEvent
        },
    }
    (notices / "SOUND_PROVENANCE.json").write_text(
        json.dumps(sound_provenance, sort_keys=True, indent=2) + "\n",
        encoding="utf-8",
    )
    (notices / "LiveKit-client-LICENSE.txt").write_bytes(livekit_license)
    (notices / "LiveKit-client-NOTICE.txt").write_bytes(livekit_notice)
    (notices / "LIVEKIT_CLIENT_PROVENANCE.json").write_bytes(
        livekit_provenance_bytes
    )
    source_archive = notices / "Stockfish-18-source.zip"
    with zipfile.ZipFile(source_archive, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("Stockfish-sf_18/src/main.cpp", "// source fixture\n")
        archive.writestr("Stockfish-sf_18/Copying.txt", "GNU GPL v3\n")
    (notices / "Stockfish-NOTICE.txt").write_text(
        "Stockfish 18\nLicense: GNU GPL v3\nComplete corresponding source is included.\n",
        encoding="utf-8",
    )

    manifest = {
        "manifest_schema": V2_PACKAGE_MANIFEST_SCHEMA_VERSION,
        "product": "Accessible Chess",
        "package_profile": V2_PACKAGE_PROFILE,
        "integration_sha": _SHA,
        "human_tested": False,
        "nvda_verified": False,
        "upgrade_from_version1": True,
        "upgrade_journal_schema": UPGRADE_JOURNAL_SCHEMA_VERSION,
        "settings_schema": SETTINGS_SCHEMA_VERSION,
        "acsdb_schema": ACSDB_SCHEMA_VERSION,
        "user_data_bundled": False,
        "raw_source_bundled": False,
        "optional_external_backends_bundled": False,
    }
    (root / MANIFEST_NAME).write_text(
        json.dumps(manifest, sort_keys=True, indent=2) + "\n",
        encoding="utf-8",
    )
    _write_checksums(root)


def _zip_tree(root: Path, destination: Path) -> None:
    with zipfile.ZipFile(destination, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for path in sorted(root.rglob("*"), key=lambda item: item.relative_to(root).as_posix()):
            if path.is_file():
                archive.write(path, path.relative_to(root).as_posix())


class Version2PackagePreflightTests(unittest.TestCase):
    def test_sha256_rejects_pathname_replacement_between_lstat_and_open(self):
        with tempfile.TemporaryDirectory() as td:
            base = Path(td)
            target = base / "payload.bin"
            replacement = base / "replacement.bin"
            target.write_bytes(b"original package bytes")
            replacement.write_bytes(b"replacement package bytes")
            original_open = Path.open
            swapped = False

            def replacing_open(path_self, *args, **kwargs):
                nonlocal swapped
                if path_self == target and not swapped:
                    swapped = True
                    os.replace(replacement, target)
                return original_open(path_self, *args, **kwargs)

            with patch.object(Path, "open", new=replacing_open):
                with self.assertRaisesRegex(
                    Version2PackagePreflightError,
                    "package file changed while being opened",
                ):
                    package_preflight._sha256(target)
            self.assertTrue(swapped)

    def test_manifest_snapshot_rejects_pathname_replacement(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td) / "package"
            root.mkdir()
            _make_tree(root)
            manifest = root / MANIFEST_NAME
            replacement = root / "manifest-replacement.tmp"
            replacement.write_bytes(manifest.read_bytes())
            original_open = Path.open
            swapped = False

            def replacing_open(path_self, *args, **kwargs):
                nonlocal swapped
                if path_self == manifest and not swapped:
                    swapped = True
                    os.replace(replacement, manifest)
                return original_open(path_self, *args, **kwargs)

            with patch.object(Path, "open", new=replacing_open):
                with self.assertRaisesRegex(
                    Version2PackagePreflightError,
                    "release manifest changed while being opened",
                ):
                    package_preflight._manifest(root)
            self.assertTrue(swapped)

    def test_checksum_inventory_snapshot_rejects_pathname_replacement(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td) / "package"
            root.mkdir()
            payload = root / "payload.txt"
            payload.write_bytes(b"payload")
            checksum = root / CHECKSUMS_NAME
            digest = hashlib.sha256(payload.read_bytes()).hexdigest()
            checksum.write_text(f"{digest}  payload.txt\n", encoding="utf-8")
            replacement = root / "checksum-replacement.tmp"
            replacement.write_bytes(checksum.read_bytes())
            original_open = Path.open
            swapped = False

            def replacing_open(path_self, *args, **kwargs):
                nonlocal swapped
                if path_self == checksum and not swapped:
                    swapped = True
                    os.replace(replacement, checksum)
                return original_open(path_self, *args, **kwargs)

            with patch.object(Path, "open", new=replacing_open):
                with self.assertRaisesRegex(
                    Version2PackagePreflightError,
                    "checksum inventory changed while being opened",
                ):
                    package_preflight._checksums(
                        root,
                        (CHECKSUMS_NAME, "payload.txt"),
                    )
            self.assertTrue(swapped)

    def test_tree_rechecks_checksums_after_hygiene_phase(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td) / "package"
            root.mkdir()
            _make_tree(root)
            target = root / "AccessibleChess" / "assets" / "content.dat"

            def mutate_after_first_checksum(*_args, **_kwargs):
                target.write_bytes(b"late mutation after initial checksum validation")

            with patch.object(
                package_preflight,
                "_scan_text_hygiene",
                side_effect=mutate_after_first_checksum,
            ):
                with self.assertRaisesRegex(
                    Version2PackagePreflightError,
                    "package checksum mismatch: AccessibleChess/assets/content.dat",
                ):
                    _validate_tree(root)

    def test_winforms_accessibility_config_snapshot_rejects_pathname_replacement(self):
        with tempfile.TemporaryDirectory() as td:
            base = Path(td)
            config = base / "AccessibleChess.exe.config"
            config.write_text(_VALID_WINFORMS_CONFIG, encoding="utf-8")
            replacement = base / "replacement.config"
            replacement.write_text(_VALID_WINFORMS_CONFIG, encoding="utf-8")
            original_open = Path.open
            swapped = False

            def replacing_open(path_self, *args, **kwargs):
                nonlocal swapped
                if path_self == config and not swapped:
                    swapped = True
                    os.replace(replacement, config)
                return original_open(path_self, *args, **kwargs)

            with patch.object(Path, "open", new=replacing_open):
                with self.assertRaisesRegex(
                    Version2PackagePreflightError,
                    "WinForms accessibility app-config changed while being opened",
                ):
                    validate_winforms_accessibility_app_config(config)
            self.assertTrue(swapped)

    def test_semantic_text_authorities_reject_pathname_replacement(self):
        cases = (
            (
                Path("AccessibleChess/assets/sounds/manifest.json"),
                "packaged sound manifest changed while being opened",
            ),
            (
                Path("THIRD_PARTY_NOTICES/SOUND_PROVENANCE.json"),
                "sound provenance notice changed while being opened",
            ),
            (
                Path("THIRD_PARTY_NOTICES/Stockfish-NOTICE.txt"),
                "Stockfish GPL notice changed while being opened",
            ),
        )
        for relative, expected in cases:
            with self.subTest(relative=relative), tempfile.TemporaryDirectory() as td:
                base = Path(td)
                root = base / "package"
                root.mkdir()
                _make_tree(root)
                target = root / relative
                replacement = base / "replacement.tmp"
                replacement.write_bytes(target.read_bytes())
                original_open = Path.open
                swapped = False

                def replacing_open(path_self, *args, **kwargs):
                    nonlocal swapped
                    if path_self == target and not swapped:
                        swapped = True
                        os.replace(replacement, target)
                    return original_open(path_self, *args, **kwargs)

                with patch.object(Path, "open", new=replacing_open):
                    with self.assertRaisesRegex(
                        Version2PackagePreflightError,
                        expected,
                    ):
                        _validate_tree(root)
                self.assertTrue(swapped)

    def test_winforms_accessibility_config_rejects_runtime_mixed_text(self):
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "AccessibleChess.exe.config"
            path.write_text(
                _VALID_WINFORMS_CONFIG.replace(
                    "<AppContextSwitchOverrides",
                    "unexpected<AppContextSwitchOverrides",
                ),
                encoding="utf-8",
            )
            with self.assertRaisesRegex(
                Version2PackagePreflightError,
                "runtime must not contain mixed text",
            ):
                validate_winforms_accessibility_app_config(path)

    def test_winforms_accessibility_config_allows_other_valid_runtime_elements(self):
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "AccessibleChess.exe.config"
            path.write_text(
                _VALID_WINFORMS_CONFIG.replace(
                    "</runtime>",
                    "<gcServer enabled=\"true\" /></runtime>",
                ),
                encoding="utf-8",
            )
            validate_winforms_accessibility_app_config(path)

    def test_valid_tree_and_zip_post_build_readback(self):
        with tempfile.TemporaryDirectory() as td:
            base = Path(td)
            root = base / "package"
            root.mkdir()
            _make_tree(root)

            tree = _validate_tree(root)
            self.assertEqual(tree.integration_sha, _SHA)
            self.assertGreaterEqual(tree.checksums_verified, 3)
            self.assertIsNone(tree.archive_sha256)

            archive = base / "Accessible-Chess-V2.zip"
            _zip_tree(root, archive)
            readback = _validate_zip(archive)
            self.assertEqual(readback.integration_sha, _SHA)
            self.assertEqual(readback.inventory, tree.inventory)
            self.assertEqual(readback.checksums_verified, tree.checksums_verified)
            self.assertEqual(len(readback.archive_sha256 or ""), 64)

    def test_winforms_accessibility_app_config_is_required(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td) / "package"
            root.mkdir()
            _make_tree(root)
            (root / "AccessibleChess" / "AccessibleChess.exe.config").unlink()
            _write_checksums(root)
            with self.assertRaisesRegex(
                Version2PackagePreflightError,
                "WinForms accessibility app-config is missing",
            ):
                _validate_tree(root)

    def test_winforms_accessibility_app_config_semantics_fail_closed(self):
        cases = (
            (
                "<configuration><runtime /></configuration>\n",
                "exactly one AppContextSwitchOverrides element",
            ),
            (
                _VALID_WINFORMS_CONFIG.replace(
                    "Switch.UseLegacyAccessibilityFeatures.3=false",
                    "Switch.UseLegacyAccessibilityFeatures.3=true",
                ),
                "disable all legacy accessibility switches",
            ),
            (
                _VALID_WINFORMS_CONFIG.replace(
                    "Switch.UseLegacyAccessibilityFeatures.5=false",
                    "Switch.UseLegacyAccessibilityFeatures.4=false",
                ),
                "switch names must be unique",
            ),
            (
                _VALID_WINFORMS_CONFIG.replace(
                    "Switch.UseLegacyAccessibilityFeatures.5=false",
                    "Switch.UseLegacyAccessibilityFeatures.5=false;"
                    "Switch.Accessibility.Experimental=true",
                ),
                "unexpected accessibility switches",
            ),
            (
                "<!DOCTYPE configuration [<!ENTITY x 'false'>]>"
                "<configuration><runtime /></configuration>",
                "must not contain DTD or entities",
            ),
            (
                _VALID_WINFORMS_CONFIG.replace(
                    '" /></runtime>',
                    '">unexpected</AppContextSwitchOverrides></runtime>',
                ),
                "must not contain child content",
            ),
            (
                _VALID_WINFORMS_CONFIG.replace(
                    '" /></runtime>',
                    '"><unexpected /></AppContextSwitchOverrides></runtime>',
                ),
                "must not contain child content",
            ),
            (
                _VALID_WINFORMS_CONFIG.encode("utf-16"),
                "must be UTF-8",
            ),
            (
                _VALID_WINFORMS_CONFIG.replace(
                    'encoding="utf-8"',
                    'encoding="utf-16"',
                ),
                "XML declaration must declare UTF-8",
            ),
            (
                _VALID_WINFORMS_CONFIG.replace(
                    'encoding="utf-8"',
                    'encoding="windows-1252"',
                ),
                "XML declaration must declare UTF-8",
            ),
        )
        for config_text, expected in cases:
            with self.subTest(expected=expected), tempfile.TemporaryDirectory() as td:
                root = Path(td) / "package"
                root.mkdir()
                _make_tree(root)
                config = root / "AccessibleChess" / "AccessibleChess.exe.config"
                if isinstance(config_text, bytes):
                    config.write_bytes(config_text)
                else:
                    config.write_text(config_text, encoding="utf-8")
                _write_checksums(root)
                with self.assertRaisesRegex(Version2PackagePreflightError, expected):
                    _validate_tree(root)

    def test_zip_readback_rejects_semantically_invalid_winforms_app_config(self):
        with tempfile.TemporaryDirectory() as td:
            base = Path(td)
            root = base / "package"
            root.mkdir()
            _make_tree(root)
            config = root / "AccessibleChess" / "AccessibleChess.exe.config"
            config.write_text(
                '<?xml version="1.0" encoding="utf-8"?>\n'
                '<configuration><runtime><AppContextSwitchOverrides value="'
                'Switch.UseLegacyAccessibilityFeatures=false;'
                'Switch.UseLegacyAccessibilityFeatures.2=false;'
                'Switch.UseLegacyAccessibilityFeatures.3=false;'
                'Switch.UseLegacyAccessibilityFeatures.4=false'
                '" /></runtime></configuration>\n',
                encoding="utf-8",
            )
            _write_checksums(root)
            archive = base / "candidate.zip"
            _zip_tree(root, archive)
            with self.assertRaisesRegex(
                Version2PackagePreflightError,
                "missing required accessibility switches",
            ):
                _validate_zip(archive)

    def test_final_product_runtime_web_resources_are_required(self):
        required = (
            "full_product_teacher.js",
            "full_product_education.js",
            "livekit_classroom_media.js",
            "vendor/livekit/livekit-client.umd.js",
            "vendor/livekit/LICENSE",
            "vendor/livekit/NOTICE",
            "vendor/livekit/provenance.json",
            "version2_final_product_bootstrap.js",
        )
        for missing in required:
            with self.subTest(missing=missing), tempfile.TemporaryDirectory() as td:
                root = Path(td) / "package"
                root.mkdir()
                _make_tree(root)
                (root / "AccessibleChess" / "web" / missing).unlink()
                _write_checksums(root)
                with self.assertRaisesRegex(
                    Version2PackagePreflightError, "web resource is missing"
                ):
                    _validate_tree(root)

    def test_livekit_bundle_digest_tamper_fails_independent_preflight(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td) / "package"
            root.mkdir()
            _make_tree(root)
            bundle = root / "AccessibleChess/web/vendor/livekit/livekit-client.umd.js"
            bundle.write_bytes(bundle.read_bytes() + b"tampered")
            _write_checksums(root)
            with self.assertRaisesRegex(
                Version2PackagePreflightError,
                "LiveKit client provenance digest mismatch",
            ):
                _validate_tree(root)

    def test_oversized_livekit_bundle_is_rejected_before_memory_read(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td) / "package"
            root.mkdir()
            _make_tree(root)
            bundle = root / "AccessibleChess/web/vendor/livekit/livekit-client.umd.js"
            with bundle.open("r+b") as handle:
                handle.truncate(package_preflight._MAX_LIVEKIT_BUNDLE_BYTES + 1)
            _write_checksums(root)
            with self.assertRaisesRegex(
                Version2PackagePreflightError,
                "packaged LiveKit browser SDK exceeds archive byte limit",
            ):
                _validate_tree(root)

    def test_oversized_livekit_provenance_is_rejected_before_json_decode(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td) / "package"
            root.mkdir()
            _make_tree(root)
            provenance = root / "AccessibleChess/web/vendor/livekit/provenance.json"
            with provenance.open("r+b") as handle:
                handle.truncate(package_preflight._MAX_LIVEKIT_PROVENANCE_BYTES + 1)
            _write_checksums(root)
            with self.assertRaisesRegex(
                Version2PackagePreflightError,
                "packaged LiveKit provenance exceeds archive byte limit",
            ):
                _validate_tree(root)

    def test_livekit_bundle_and_provenance_coordinated_substitution_fails_pin(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td) / "package"
            root.mkdir()
            _make_tree(root)
            vendor = root / "AccessibleChess/web/vendor/livekit"
            bundle = vendor / "livekit-client.umd.js"
            bundle.write_bytes(bundle.read_bytes() + b"coordinated-substitution")
            provenance_path = vendor / "provenance.json"
            provenance = json.loads(provenance_path.read_text(encoding="utf-8"))
            provenance["bundle_sha256"] = hashlib.sha256(bundle.read_bytes()).hexdigest()
            provenance_bytes = (
                json.dumps(provenance, sort_keys=True, indent=2) + "\n"
            ).encode("utf-8")
            provenance_path.write_bytes(provenance_bytes)
            (
                root / "THIRD_PARTY_NOTICES/LIVEKIT_CLIENT_PROVENANCE.json"
            ).write_bytes(provenance_bytes)
            _write_checksums(root)
            with self.assertRaisesRegex(
                Version2PackagePreflightError,
                "bundle_sha256 does not match pinned release",
            ):
                _validate_tree(root)

    def test_livekit_central_notice_divergence_fails_independent_preflight(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td) / "package"
            root.mkdir()
            _make_tree(root)
            notice = root / "THIRD_PARTY_NOTICES/LiveKit-client-NOTICE.txt"
            notice.write_bytes(notice.read_bytes() + b"tampered")
            _write_checksums(root)
            with self.assertRaisesRegex(
                Version2PackagePreflightError,
                "central LiveKit NOTICE does not match",
            ):
                _validate_tree(root)

    def test_final_zip_and_nested_zip_use_snapshot_handles(self):
        with tempfile.TemporaryDirectory() as td:
            base = Path(td)
            root = base / "package"
            root.mkdir()
            _make_tree(root)
            archive = base / "Accessible-Chess-V2.zip"
            _zip_tree(root, archive)
            original_zipfile = zipfile.ZipFile
            with patch(
                "acs.version2_package_preflight.zipfile.ZipFile",
                wraps=original_zipfile,
            ) as wrapped:
                report = _validate_zip(archive)
            self.assertEqual(report.integration_sha, _SHA)
            self.assertGreaterEqual(len(wrapped.call_args_list), 2)
            for call in wrapped.call_args_list:
                self.assertFalse(isinstance(call.args[0], (str, Path)))

    def test_manifest_and_checksum_tamper_fail_closed(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td) / "package"
            root.mkdir()
            _make_tree(root)
            manifest_path = root / MANIFEST_NAME
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            manifest["nvda_verified"] = True
            manifest_path.write_text(json.dumps(manifest) + "\n", encoding="utf-8")
            _write_checksums(root)
            with self.assertRaisesRegex(
                Version2PackagePreflightError, "manifest contract mismatch"
            ):
                _validate_tree(root)

            manifest["nvda_verified"] = False
            manifest["human_tested"] = True
            manifest_path.write_text(json.dumps(manifest) + "\n", encoding="utf-8")
            _write_checksums(root)
            with self.assertRaisesRegex(
                Version2PackagePreflightError, "manifest contract mismatch"
            ):
                _validate_tree(root)

        with tempfile.TemporaryDirectory() as td:
            root = Path(td) / "package"
            root.mkdir()
            _make_tree(root)
            (root / "AccessibleChess" / "assets" / "content.dat").write_bytes(b"tampered")
            with self.assertRaisesRegex(
                Version2PackagePreflightError, "checksum mismatch"
            ):
                _validate_tree(root)

    def test_duplicate_manifest_key_and_checksum_path_rejected(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td) / "package"
            root.mkdir()
            _make_tree(root)
            manifest = json.loads((root / MANIFEST_NAME).read_text(encoding="utf-8"))
            body = json.dumps(manifest)
            body = body[:-1] + ', "product": "Accessible Chess"}'
            (root / MANIFEST_NAME).write_text(body, encoding="utf-8")
            _write_checksums(root)
            with self.assertRaisesRegex(
                Version2PackagePreflightError, "duplicate JSON keys"
            ):
                _validate_tree(root)

        with tempfile.TemporaryDirectory() as td:
            root = Path(td) / "package"
            root.mkdir()
            _make_tree(root)
            checksum_path = root / CHECKSUMS_NAME
            rows = checksum_path.read_text(encoding="utf-8").splitlines()
            checksum_path.write_text(
                "\n".join(rows + [rows[0]]) + "\n", encoding="utf-8"
            )
            with self.assertRaisesRegex(
                Version2PackagePreflightError, "duplicate paths"
            ):
                _validate_tree(root)

    def test_user_state_raw_source_secret_and_optional_backend_are_rejected(self):
        cases = (
            ("settings.json", b"{}", "user state"),
            ("debug.py", b"print('x')", "raw source"),
            ("token.json", b"{}", "secret-bearing"),
            ("uncbv.exe", b"MZ", "optional external backend"),
            ("libcbh.dll", b"MZ", "optional external backend"),
        )
        for name, payload, expected in cases:
            with self.subTest(name=name), tempfile.TemporaryDirectory() as td:
                root = Path(td) / "package"
                root.mkdir()
                _make_tree(root)
                (root / "AccessibleChess" / name).write_bytes(payload)
                _write_checksums(root)
                with self.assertRaisesRegex(Version2PackagePreflightError, expected):
                    _validate_tree(root)

    def test_private_paths_and_credentials_in_text_are_rejected_without_echo(self):
        samples = (
            b"diagnostic=C:\\Users\\Developer\\secret\\build",
            b"token=github_pat_ABCDEFGHIJKLMNOPQRSTUVWXYZ123456",
        )
        for payload in samples:
            with self.subTest(payload=payload[:10]), tempfile.TemporaryDirectory() as td:
                root = Path(td) / "package"
                root.mkdir()
                _make_tree(root)
                leak = root / "AccessibleChess" / "diagnostic.txt"
                leak.write_bytes(payload)
                _write_checksums(root)
                with self.assertRaises(Version2PackagePreflightError) as captured:
                    _validate_tree(root)
                self.assertNotIn("Developer", str(captured.exception))
                self.assertNotIn("github_pat_", str(captured.exception))

    def test_valid_pe_binary_private_build_path_is_not_misclassified_as_text(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td) / "package"
            root.mkdir()
            _make_tree(root)
            dll = (
                root
                / "AccessibleChess"
                / "clr_loader"
                / "ffi"
                / "dlls"
                / "amd64"
                / "ClrLoader.dll"
            )
            dll.parent.mkdir(parents=True)
            dll.write_bytes(
                _minimal_windows_pe()
                + b"\x00compiler=C:\\Users\\Builder\\source\\clr_loader\\ClrLoader.pdb\x00"
            )
            _write_checksums(root)
            report = _validate_tree(root)
            self.assertIn(
                "AccessibleChess/clr_loader/ffi/dlls/amd64/ClrLoader.dll",
                report.inventory,
            )

    def test_text_disguised_as_dll_does_not_bypass_private_path_gate(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td) / "package"
            root.mkdir()
            _make_tree(root)
            fake = root / "AccessibleChess" / "looks-binary.dll"
            fake.write_bytes(b"diagnostic=C:\\Users\\Developer\\secret\\build")
            _write_checksums(root)
            with self.assertRaisesRegex(
                Version2PackagePreflightError,
                "private local path leaked into package text",
            ):
                _validate_tree(root)

    def test_valid_pe_binary_does_not_bypass_secret_gate(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td) / "package"
            root.mkdir()
            _make_tree(root)
            dll = root / "AccessibleChess" / "helper.dll"
            dll.write_bytes(
                _minimal_windows_pe()
                + b"\x00token=github_pat_ABCDEFGHIJKLMNOPQRSTUVWXYZ123456\x00"
            )
            _write_checksums(root)
            with self.assertRaisesRegex(
                Version2PackagePreflightError,
                "secret-like credential leaked into package text",
            ):
                _validate_tree(root)

    def test_tree_bounds_fail_before_trusting_checksums(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td) / "package"
            root.mkdir()
            _make_tree(root)
            with self.assertRaisesRegex(Version2PackagePreflightError, "byte limit"):
                _validate_tree(
                    root,
                    limits=PackageLimits(
                        max_files=50,
                        max_bytes=8,
                        max_archive_bytes=1000,
                        max_member_bytes=1000,
                        max_compression_ratio=200,
                        max_text_scan_bytes=1000,
                    ),
                )

    def test_zip_rejects_traversal_case_collision_symlink_and_member_bounds(self):
        builders = []

        def traversal(archive):
            archive.writestr("../escape.txt", b"x")

        builders.append((traversal, "unsafe"))

        def collision(archive):
            archive.writestr("AccessibleChess/A.txt", b"a")
            archive.writestr("AccessibleChess/a.txt", b"b")

        builders.append((collision, "case-folding"))

        def symlink(archive):
            info = zipfile.ZipInfo("AccessibleChess/link")
            info.create_system = 3
            info.external_attr = (stat.S_IFLNK | 0o777) << 16
            archive.writestr(info, "target")

        builders.append((symlink, "symbolic links"))

        for builder, expected in builders:
            with self.subTest(expected=expected), tempfile.TemporaryDirectory() as td:
                archive_path = Path(td) / "bad.zip"
                with zipfile.ZipFile(archive_path, "w") as archive:
                    builder(archive)
                with self.assertRaisesRegex(Version2PackagePreflightError, expected):
                    _validate_zip(archive_path)

        with tempfile.TemporaryDirectory() as td:
            archive_path = Path(td) / "large.zip"
            with zipfile.ZipFile(archive_path, "w") as archive:
                archive.writestr("big.bin", b"x" * 16)
            with self.assertRaisesRegex(
                Version2PackagePreflightError, "member exceeds"
            ):
                _validate_zip(
                    archive_path,
                    limits=PackageLimits(
                        max_files=50,
                        max_bytes=100,
                        max_archive_bytes=1000,
                        max_member_bytes=8,
                        max_compression_ratio=200,
                        max_text_scan_bytes=100,
                    ),
                )

    def test_zip_rejects_superscript_windows_device_aliases_before_readback(self):
        reserved = (
            "COM¹.txt",
            "com².bin",
            "Com³.dat",
            "LPT¹.txt",
            "lpt².bin",
            "Lpt³.dat",
            "CONIN$.txt",
            "conout$.bin",
        )
        for name in reserved:
            with self.subTest(name=name), tempfile.TemporaryDirectory() as td:
                archive_path = Path(td) / "hostile.zip"
                with zipfile.ZipFile(archive_path, "w") as archive:
                    archive.writestr(f"AccessibleChess/{name}", b"hostile")

                with patch(
                    "acs.version2_package_preflight.tempfile.TemporaryDirectory",
                    side_effect=AssertionError("ZIP readback must not start"),
                ):
                    with self.assertRaisesRegex(
                        Version2PackagePreflightError,
                        "reserved Windows name",
                    ):
                        _validate_zip(archive_path)

    def test_zip_readback_rejects_accidental_user_data(self):
        with tempfile.TemporaryDirectory() as td:
            base = Path(td)
            root = base / "package"
            root.mkdir()
            _make_tree(root)
            (root / "AccessibleChess" / "library.acsdb").write_bytes(b"private-user-db")
            _write_checksums(root)
            archive_path = base / "bad-user-data.zip"
            _zip_tree(root, archive_path)
            with self.assertRaisesRegex(Version2PackagePreflightError, "user state"):
                _validate_zip(archive_path)


if __name__ == "__main__":
    unittest.main()
