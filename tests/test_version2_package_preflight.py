from __future__ import annotations

import hashlib
import json
from pathlib import Path
import stat
import tempfile
import unittest
from unittest.mock import patch
import wave
import zipfile

from acs import version2_package_preflight as preflight
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



def _validate_tree(root, **kwargs):
    return validate_version2_package_tree(
        root, expected_integration_sha=_SHA, **kwargs
    )


def _validate_zip(archive, **kwargs):
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


def _minimal_windows_pe(*, machine: int = 0x8664) -> bytes:
    """Return a structurally valid minimal PE32+ image for package fixtures."""
    data = bytearray(512)
    data[0:2] = b"MZ"
    pe_offset = 0x80
    data[0x3C:0x40] = pe_offset.to_bytes(4, "little")
    data[pe_offset:pe_offset + 4] = b"PE\x00\x00"
    coff = pe_offset + 4
    data[coff:coff + 2] = machine.to_bytes(2, "little")
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
    for relative in preflight._REQUIRED_DESKTOP_RUNTIME_FILES:
        runtime = root.joinpath(*relative.split("/"))
        runtime.parent.mkdir(parents=True, exist_ok=True)
        runtime.write_bytes(_minimal_windows_pe())

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
        "version2_final_product_bootstrap.js",
        "version2_local_profile.js",
        "p0_accessibility_runtime.js",
        "version2_release_bootstrap.js",
        "docs/ACCESSIBLE_CHESS_HOTKEYS_UK.txt",
        "docs/ACCESSIBLE_CHESS_CAPABILITIES_TESTING_UK.txt",
    )
    for name in web_files:
        path = web / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(f"// fixture {name}\n", encoding="utf-8")

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


def _write_inventory_wave(
    path: Path,
    *,
    sample: int,
    sample_width: int = 2,
) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with wave.open(str(path), "wb") as writer:
        writer.setnchannels(1)
        writer.setsampwidth(sample_width)
        writer.setframerate(8000)
        if sample_width == 1:
            if not 0 <= sample <= 255:
                raise ValueError("8-bit WAV sample must be in 0..255")
            writer.writeframes(bytes([sample]) * 16)
        elif sample_width == 2:
            writer.writeframes(int(sample).to_bytes(2, "little", signed=True) * 16)
        elif sample_width == 3:
            writer.writeframes(int(sample).to_bytes(3, "little", signed=True) * 16)
        else:
            raise ValueError("test WAV sample width must be 1, 2 or 3")


def _enable_full_sound_inventory(
    root: Path,
    *,
    alt_sample_width: int = 1,
) -> tuple[int, str, Path]:
    sounds = root / "AccessibleChess" / "assets" / "sounds"
    manifest_path = sounds / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    provenance_path = root / "THIRD_PARTY_NOTICES" / "SOUND_PROVENANCE.json"
    provenance = json.loads(provenance_path.read_text(encoding="utf-8"))

    library = sounds / "library"
    library.mkdir()
    moved: dict[str, str] = {}
    for file_name in sorted(set(manifest["files"].values()), key=str.casefold):
        source = sounds / file_name
        destination = library / file_name
        source.replace(destination)
        moved[file_name] = f"library/{file_name}"

    for event in SoundEvent:
        old_name = manifest["files"][event.value]
        new_name = moved[old_name]
        manifest["files"][event.value] = new_name
        provenance["events"][event.value]["file"] = new_name
        provenance["events"][event.value]["sha256"] = _sha256(sounds / new_name)

    alt = library / "move-alt.wav"
    _write_inventory_wave(alt, sample=177, sample_width=alt_sample_width)
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
    manifest_path.write_text(
        json.dumps(manifest, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    provenance_path.write_text(
        json.dumps(provenance, sort_keys=True, indent=2) + "\n",
        encoding="utf-8",
    )
    (sounds / "variants.json").write_text(
        json.dumps(variants, ensure_ascii=False, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    (sounds / "layers.json").write_text(
        json.dumps({"schema_version": 1, "events": {}}, sort_keys=True) + "\n",
        encoding="utf-8",
    )

    entries: list[dict[str, object]] = []
    fingerprint_rows: list[bytes] = []
    for path in sorted(
        (item for item in library.rglob("*") if item.is_file() and item.suffix.casefold() == ".wav"),
        key=lambda item: item.relative_to(library).as_posix().casefold(),
    ):
        relative = path.relative_to(library).as_posix()
        digest = _sha256(path)
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
        fingerprint_rows.append(f"{relative}\0{digest}\n".encode("utf-8"))

    inventory_sha = hashlib.sha256(b"".join(fingerprint_rows)).hexdigest()
    inventory = {
        "schema_version": 1,
        "source": preflight._USER_SOUND_SOURCE,
        "license_id": preflight._USER_SOUND_LICENSE_ID,
        "creator": preflight._USER_SOUND_CREATOR,
        "file_count": len(entries),
        "source_inventory_sha256": inventory_sha,
        "files": entries,
    }
    inventory_text = json.dumps(inventory, ensure_ascii=False, sort_keys=True, indent=2) + "\n"
    (sounds / "inventory.json").write_text(inventory_text, encoding="utf-8")
    (root / "THIRD_PARTY_NOTICES" / "SOUND_INVENTORY.json").write_text(
        inventory_text,
        encoding="utf-8",
    )
    return len(entries), inventory_sha, alt


def _zip_tree(root: Path, destination: Path) -> None:
    with zipfile.ZipFile(destination, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for path in sorted(root.rglob("*"), key=lambda item: item.relative_to(root).as_posix()):
            if path.is_file():
                archive.write(path, path.relative_to(root).as_posix())


class Version2PackagePreflightTests(unittest.TestCase):
    def test_relative_token_enforces_exact_win32_utf16_component_boundary(self):
        astral = "\U0001f642"
        accepted = astral * 125 + "a.txt"
        rejected = astral * 126 + "a.txt"
        self.assertEqual(len(accepted.encode("utf-16-le")) // 2, 255)
        self.assertGreater(len(rejected.encode("utf-16-le")) // 2, 255)
        accepted_path = f"AccessibleChess/{accepted}"
        self.assertEqual(
            preflight._relative_token(accepted_path, label="package path"),
            accepted_path,
        )
        with self.assertRaisesRegex(
            Version2PackagePreflightError,
            "255 UTF-16 code-unit component limit",
        ):
            preflight._relative_token(
                f"AccessibleChess/{rejected}",
                label="package path",
            )

    def test_relative_token_rejects_malformed_win32_unicode(self):
        with self.assertRaisesRegex(
            Version2PackagePreflightError,
            "not valid Win32 Unicode",
        ):
            preflight._relative_token(
                "AccessibleChess/broken\ud800.txt",
                label="package path",
            )

    def test_relative_token_rejects_extended_and_trimmed_win32_device_aliases(self):
        for name in ("CON .txt", "conin$.bin", "CONOUT$.dat"):
            with self.subTest(name=name):
                with self.assertRaisesRegex(
                    Version2PackagePreflightError,
                    "reserved Windows name",
                ):
                    preflight._relative_token(
                        f"AccessibleChess/{name}",
                        label="package path",
                    )

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

    def test_package_preflight_accepts_8bit_pcm_sound_asset(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td) / "package"
            root.mkdir()
            _make_tree(root)

            sound_root = root / "AccessibleChess" / "assets" / "sounds"
            manifest = json.loads(
                (sound_root / "manifest.json").read_text(encoding="utf-8")
            )
            file_name = manifest["files"][SoundEvent.LOW_TIME.value]
            sound_path = sound_root / file_name
            with wave.open(str(sound_path), "wb") as writer:
                writer.setnchannels(1)
                writer.setsampwidth(1)
                writer.setframerate(8000)
                writer.writeframes(bytes([0, 64, 128, 192, 255] * 4))

            provenance_path = root / "THIRD_PARTY_NOTICES" / "SOUND_PROVENANCE.json"
            provenance = json.loads(provenance_path.read_text(encoding="utf-8"))
            provenance["events"][SoundEvent.LOW_TIME.value]["sha256"] = _sha256(
                sound_path
            )
            provenance_path.write_text(
                json.dumps(provenance, sort_keys=True, indent=2) + "\n",
                encoding="utf-8",
            )
            _write_checksums(root)

            report = _validate_tree(root)
            self.assertEqual(report.integration_sha, _SHA)

    def test_sound_manifest_allows_provenance_verified_semantic_alias(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td) / "package"
            root.mkdir()
            _make_tree(root)

            sounds = root / "AccessibleChess" / "assets" / "sounds"
            manifest_path = sounds / "manifest.json"
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            events = list(SoundEvent)
            shared_event = events[0]
            alias_event = events[1]
            shared_file = manifest["files"][shared_event.value]
            manifest["files"][alias_event.value] = shared_file
            manifest_path.write_text(
                json.dumps(manifest, sort_keys=True) + "\n",
                encoding="utf-8",
            )

            provenance_path = root / "THIRD_PARTY_NOTICES" / "SOUND_PROVENANCE.json"
            provenance = json.loads(provenance_path.read_text(encoding="utf-8"))
            provenance["events"][alias_event.value]["file"] = shared_file
            provenance["events"][alias_event.value]["sha256"] = _sha256(
                sounds / shared_file
            )
            provenance_path.write_text(
                json.dumps(provenance, sort_keys=True, indent=2) + "\n",
                encoding="utf-8",
            )
            _write_checksums(root)

            report = _validate_tree(root)
            self.assertEqual(report.integration_sha, _SHA)

    def test_full_sound_inventory_tree_and_zip_readback_bind_nondefault_variant_bytes(self):
        with tempfile.TemporaryDirectory() as td:
            base = Path(td)
            root = base / "package"
            root.mkdir()
            _make_tree(root)
            count, inventory_sha, alt = _enable_full_sound_inventory(root)
            _write_checksums(root)

            with (
                patch.object(preflight, "_USER_SOUND_EXPECTED_WAV_COUNT", count),
                patch.object(
                    preflight,
                    "_USER_SOUND_EXPECTED_INVENTORY_SHA256",
                    inventory_sha,
                ),
            ):
                report = _validate_tree(root)
                self.assertEqual(report.integration_sha, _SHA)
                inventory_doc = json.loads(
                    (
                        root
                        / "AccessibleChess"
                        / "assets"
                        / "sounds"
                        / "inventory.json"
                    ).read_text(encoding="utf-8")
                )
                alt_entry = next(
                    item for item in inventory_doc["files"]
                    if item["file"] == "library/move-alt.wav"
                )
                self.assertEqual(alt_entry["sample_width_bytes"], 1)

                archive = base / "inventory-bound.zip"
                _zip_tree(root, archive)
                zip_report = _validate_zip(archive)
                self.assertEqual(zip_report.integration_sha, _SHA)

            original_size = alt.stat().st_size
            original_digest = _sha256(alt)
            _write_inventory_wave(alt, sample=77, sample_width=1)
            self.assertEqual(alt.stat().st_size, original_size)
            self.assertNotEqual(_sha256(alt), original_digest)
            # Demonstrate that regenerating the package's generic checksum list
            # cannot legitimize a substituted non-default runtime WAV.
            _write_checksums(root)
            with (
                patch.object(preflight, "_USER_SOUND_EXPECTED_WAV_COUNT", count),
                patch.object(
                    preflight,
                    "_USER_SOUND_EXPECTED_INVENTORY_SHA256",
                    inventory_sha,
                ),
                self.assertRaisesRegex(
                    Version2PackagePreflightError,
                    "sound inventory SHA-256 mismatch",
                ),
            ):
                _validate_tree(root)

    def test_inventory_bound_runtime_variant_rejects_24bit_pcm(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td) / "package"
            root.mkdir()
            _make_tree(root)
            count, inventory_sha, _alt = _enable_full_sound_inventory(
                root,
                alt_sample_width=3,
            )
            _write_checksums(root)
            with (
                patch.object(preflight, "_USER_SOUND_EXPECTED_WAV_COUNT", count),
                patch.object(
                    preflight,
                    "_USER_SOUND_EXPECTED_INVENTORY_SHA256",
                    inventory_sha,
                ),
                self.assertRaisesRegex(
                    Version2PackagePreflightError,
                    "runtime sound asset must be uncompressed 8-bit or 16-bit PCM",
                ),
            ):
                _validate_tree(root)

    def test_full_sound_inventory_rejects_nonfinite_duration_even_with_checksums(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td) / "package"
            root.mkdir()
            _make_tree(root)
            count, inventory_sha, _alt = _enable_full_sound_inventory(root)
            inventory_path = (
                root / "AccessibleChess" / "assets" / "sounds" / "inventory.json"
            )
            notice_path = root / "THIRD_PARTY_NOTICES" / "SOUND_INVENTORY.json"
            raw = json.loads(inventory_path.read_text(encoding="utf-8"))
            raw["files"][0]["duration_seconds"] = float("nan")
            malformed = json.dumps(raw, sort_keys=True) + "\n"
            inventory_path.write_text(malformed, encoding="utf-8")
            notice_path.write_text(malformed, encoding="utf-8")
            _write_checksums(root)
            with (
                patch.object(preflight, "_USER_SOUND_EXPECTED_WAV_COUNT", count),
                patch.object(
                    preflight,
                    "_USER_SOUND_EXPECTED_INVENTORY_SHA256",
                    inventory_sha,
                ),
                self.assertRaisesRegex(
                    Version2PackagePreflightError,
                    "non-finite JSON number: NaN",
                ),
            ):
                _validate_tree(root)

    def test_full_sound_inventory_notice_is_required_independently_of_checksums(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td) / "package"
            root.mkdir()
            _make_tree(root)
            count, inventory_sha, _alt = _enable_full_sound_inventory(root)
            notice = root / "THIRD_PARTY_NOTICES" / "SOUND_INVENTORY.json"
            notice.unlink()
            _write_checksums(root)
            with (
                patch.object(preflight, "_USER_SOUND_EXPECTED_WAV_COUNT", count),
                patch.object(
                    preflight,
                    "_USER_SOUND_EXPECTED_INVENTORY_SHA256",
                    inventory_sha,
                ),
                self.assertRaisesRegex(
                    Version2PackagePreflightError,
                    "inventory and audit notice must both be present",
                ),
            ):
                _validate_tree(root)

    def test_full_sound_inventory_notice_must_match_runtime_copy(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td) / "package"
            root.mkdir()
            _make_tree(root)
            count, inventory_sha, _alt = _enable_full_sound_inventory(root)
            notice_path = root / "THIRD_PARTY_NOTICES" / "SOUND_INVENTORY.json"
            notice = json.loads(notice_path.read_text(encoding="utf-8"))
            notice["creator"] = "tampered"
            notice_path.write_text(
                json.dumps(notice, sort_keys=True) + "\n",
                encoding="utf-8",
            )
            _write_checksums(root)
            with (
                patch.object(preflight, "_USER_SOUND_EXPECTED_WAV_COUNT", count),
                patch.object(
                    preflight,
                    "_USER_SOUND_EXPECTED_INVENTORY_SHA256",
                    inventory_sha,
                ),
                self.assertRaisesRegex(
                    Version2PackagePreflightError,
                    "does not match audit notice",
                ),
            ):
                _validate_tree(root)

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
            "version2_final_product_bootstrap.js",
            "version2_local_profile.js",
            "p0_accessibility_runtime.js",
            "docs/ACCESSIBLE_CHESS_HOTKEYS_UK.txt",
            "docs/ACCESSIBLE_CHESS_CAPABILITIES_TESTING_UK.txt",
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
                archive = Path(td) / "missing-resource.zip"
                _zip_tree(root, archive)
                with self.assertRaisesRegex(
                    Version2PackagePreflightError, "web resource is missing"
                ):
                    _validate_zip(archive)

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

    def test_zip_rejects_overlong_win32_component_before_readback(self):
        overlong = "\U0001f642" * 126 + "a.txt"
        self.assertGreater(len(overlong.encode("utf-16-le")) // 2, 255)
        with tempfile.TemporaryDirectory() as td:
            archive_path = Path(td) / "hostile.zip"
            with zipfile.ZipFile(archive_path, "w") as archive:
                archive.writestr(f"AccessibleChess/{overlong}", b"hostile")

            with patch(
                "acs.version2_package_preflight.tempfile.TemporaryDirectory",
                side_effect=AssertionError("ZIP readback must not start"),
            ):
                with self.assertRaisesRegex(
                    Version2PackagePreflightError,
                    "255 UTF-16 code-unit component limit",
                ):
                    _validate_zip(archive_path)

    def test_zip_rejects_superscript_windows_device_aliases_before_readback(self):
        reserved = (
            "COM¹.txt",
            "com².bin",
            "Com³.dat",
            "LPT¹.txt",
            "lpt².bin",
            "Lpt³.dat",
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
