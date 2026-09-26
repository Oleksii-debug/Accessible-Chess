from __future__ import annotations

import hashlib
import json
from pathlib import Path
import tempfile
import unittest

from acs.version2_release_sbom import (
    CHECKSUMS_NAME,
    SBOM_NAME,
    Version2ReleaseSbomError,
    build_version2_release_sbom,
    validate_version2_release_sbom,
    write_version2_release_sbom,
)


_SHA = "a" * 40


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


class Version2ReleaseSbomTests(unittest.TestCase):
    def _package(self, root: Path) -> Path:
        package = root / "package"
        engine = package / "AccessibleChess" / "engines" / "stockfish"
        sounds = package / "AccessibleChess" / "assets" / "sounds"
        notices = package / "THIRD_PARTY_NOTICES"
        engine.mkdir(parents=True)
        sounds.mkdir(parents=True)
        notices.mkdir(parents=True)

        (package / "AccessibleChess" / "AccessibleChess.exe").write_bytes(b"MZ-product")
        (engine / "stockfish.exe").write_bytes(b"MZ-stockfish")
        (notices / "Stockfish-18-source.zip").write_bytes(b"source")
        (notices / "Stockfish-NOTICE.txt").write_text(
            "Stockfish 18\nLicense: GNU GPL v3 or later\n", encoding="utf-8"
        )
        (sounds / "move.wav").write_bytes(b"RIFF-sound")
        (notices / "SOUND_PROVENANCE.json").write_text(
            json.dumps(
                {
                    "schema_version": 1,
                    "events": {
                        "move": {
                            "file": "move.wav",
                            "sha256": _sha256(sounds / "move.wav"),
                            "license_id": "CC0-1.0",
                            "source": "urn:accessible-chess:test:move",
                            "creator": "test",
                        }
                    },
                },
                sort_keys=True,
            )
            + "\n",
            encoding="utf-8",
        )
        (package / "RELEASE_MANIFEST.json").write_text(
            json.dumps({"integration_sha": _SHA}) + "\n", encoding="utf-8"
        )
        return package

    def test_writes_deterministic_exact_file_inventory(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            package = self._package(Path(td))
            before = build_version2_release_sbom(package, integration_sha=_SHA)
            target = write_version2_release_sbom(package, integration_sha=_SHA)
            self.assertEqual(target.name, SBOM_NAME)
            actual = json.loads(target.read_text(encoding="utf-8"))
            self.assertEqual(actual, before)
            self.assertEqual(actual["spdxVersion"], "SPDX-2.3")
            self.assertEqual(actual["dataLicense"], "CC0-1.0")
            self.assertEqual(
                actual["documentNamespace"],
                f"https://github.com/Oleksii-debug/Accessible-Chess/spdx/{_SHA}",
            )

            names = [row["fileName"][2:] for row in actual["files"]]
            self.assertEqual(names, sorted(names, key=str.casefold))
            self.assertNotIn(SBOM_NAME, names)
            self.assertNotIn(CHECKSUMS_NAME, names)
            self.assertIn("RELEASE_MANIFEST.json", names)
            self.assertIn("AccessibleChess/engines/stockfish/stockfish.exe", names)
            self.assertIn("THIRD_PARTY_NOTICES/Stockfish-18-source.zip", names)

            rows = {row["fileName"][2:]: row for row in actual["files"]}
            self.assertEqual(
                rows["AccessibleChess/assets/sounds/move.wav"]["licenseConcluded"],
                "CC0-1.0",
            )
            for relative, row in rows.items():
                checksum = row["checksums"][0]
                self.assertEqual(checksum["algorithm"], "SHA256")
                self.assertEqual(
                    checksum["checksumValue"],
                    _sha256(package.joinpath(*relative.split("/"))),
                )

            stockfish = next(item for item in actual["packages"] if item["name"] == "Stockfish")
            self.assertEqual(stockfish["versionInfo"], "18")
            self.assertEqual(stockfish["licenseDeclared"], "GPL-3.0-or-later")
            self.assertIn("corresponding source", stockfish["comment"])

    def test_validation_detects_payload_tamper(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            package = self._package(Path(td))
            write_version2_release_sbom(package, integration_sha=_SHA)
            inventory = tuple(
                sorted(
                    (
                        str(path.relative_to(package)).replace("\\", "/")
                        for path in package.rglob("*")
                        if path.is_file()
                    ),
                    key=str.casefold,
                )
            )
            validate_version2_release_sbom(
                package,
                integration_sha=_SHA,
                inventory=inventory,
            )
            (package / "AccessibleChess" / "AccessibleChess.exe").write_bytes(b"MZ-tampered")
            with self.assertRaisesRegex(
                Version2ReleaseSbomError,
                "does not exactly describe",
            ):
                validate_version2_release_sbom(
                    package,
                    integration_sha=_SHA,
                    inventory=inventory,
                )

    def test_validation_detects_unlisted_new_payload_file(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            package = self._package(Path(td))
            write_version2_release_sbom(package, integration_sha=_SHA)
            (package / "AccessibleChess" / "new-runtime.dll").write_bytes(b"new")
            inventory = tuple(
                sorted(
                    (
                        str(path.relative_to(package)).replace("\\", "/")
                        for path in package.rglob("*")
                        if path.is_file()
                    ),
                    key=str.casefold,
                )
            )
            with self.assertRaisesRegex(
                Version2ReleaseSbomError,
                "does not exactly describe",
            ):
                validate_version2_release_sbom(
                    package,
                    integration_sha=_SHA,
                    inventory=inventory,
                )

    def test_invalid_sound_license_and_stockfish_notice_fail_closed(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            package = self._package(Path(td))
            provenance = json.loads(
                (package / "THIRD_PARTY_NOTICES" / "SOUND_PROVENANCE.json").read_text(
                    encoding="utf-8"
                )
            )
            provenance["events"]["move"]["license_id"] = "not a license/id"
            (package / "THIRD_PARTY_NOTICES" / "SOUND_PROVENANCE.json").write_text(
                json.dumps(provenance) + "\n", encoding="utf-8"
            )
            with self.assertRaisesRegex(Version2ReleaseSbomError, "license identity"):
                build_version2_release_sbom(package, integration_sha=_SHA)

        with tempfile.TemporaryDirectory() as td:
            package = self._package(Path(td))
            (package / "THIRD_PARTY_NOTICES" / "Stockfish-NOTICE.txt").write_text(
                "Stockfish 18\n", encoding="utf-8"
            )
            with self.assertRaisesRegex(Version2ReleaseSbomError, "GPL licensing"):
                build_version2_release_sbom(package, integration_sha=_SHA)

    def test_existing_sbom_is_never_overwritten(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            package = self._package(Path(td))
            target = package / SBOM_NAME
            target.write_text("keep\n", encoding="utf-8")
            with self.assertRaisesRegex(Version2ReleaseSbomError, "must not already exist"):
                write_version2_release_sbom(package, integration_sha=_SHA)
            self.assertEqual(target.read_text(encoding="utf-8"), "keep\n")


if __name__ == "__main__":
    unittest.main()
