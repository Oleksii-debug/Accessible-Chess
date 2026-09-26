from __future__ import annotations

import hashlib
import json
from pathlib import Path
import tempfile
import unittest
from unittest import mock

from acs.version2_release_sbom import (
    SBOM_NAME,
    Version2ReleaseSbomError,
    build_version2_release_sbom,
    validate_version2_release_sbom,
    write_version2_release_sbom,
)


_SHA = "a" * 40


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _package_verification_code(package: Path, inventory: tuple[str, ...]) -> str:
    hashes = sorted(
        hashlib.sha1(package.joinpath(*relative.split("/")).read_bytes()).hexdigest()
        for relative in inventory
    )
    return hashlib.sha1("".join(hashes).encode("ascii")).hexdigest()


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
        (notices / "Stockfish-COPYING.txt").write_text(
            "GNU GENERAL PUBLIC LICENSE\nVersion 3\n"
            "Redistribution is permitted under version 3 or any later version.\n",
            encoding="utf-8",
        )
        (sounds / "move.wav").write_bytes(b"RIFF-sound")
        (notices / "SOUND_PROVENANCE.json").write_text(
            json.dumps({
                "schema_version": 1,
                "events": {"move": {
                    "file": "move.wav",
                    "sha256": _sha256(sounds / "move.wav"),
                    "license_id": "CC0-1.0",
                    "source": "urn:accessible-chess:test:move",
                    "creator": "test",
                }},
            }, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        (package / "RELEASE_MANIFEST.json").write_text(
            json.dumps({"integration_sha": _SHA}) + "\n", encoding="utf-8"
        )
        (package / "SHA256SUMS.txt").write_text("fixture checksums\n", encoding="utf-8")
        return package

    @staticmethod
    def _inventory(package: Path) -> tuple[str, ...]:
        return tuple(sorted(
            (str(path.relative_to(package)).replace("\\", "/")
             for path in package.rglob("*") if path.is_file()),
            key=str.casefold,
        ))

    def test_sidecar_hashes_every_package_file_deterministically(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            package = self._package(root)
            inventory = self._inventory(package)
            first = root / SBOM_NAME
            second = root / "second.spdx.json"
            write_version2_release_sbom(
                package, first, integration_sha=_SHA, inventory=inventory
            )
            write_version2_release_sbom(
                package, second, integration_sha=_SHA, inventory=inventory
            )
            self.assertEqual(first.read_bytes(), second.read_bytes())
            actual = json.loads(first.read_text(encoding="utf-8"))
            names = [row["fileName"][2:] for row in actual["files"]]
            self.assertEqual(names, list(inventory))
            self.assertIn("RELEASE_MANIFEST.json", names)
            self.assertIn("SHA256SUMS.txt", names)
            self.assertIn("THIRD_PARTY_NOTICES/Stockfish-COPYING.txt", names)
            rows = {row["fileName"][2:]: row for row in actual["files"]}
            self.assertEqual(
                rows["AccessibleChess/assets/sounds/move.wav"]["licenseConcluded"],
                "CC0-1.0",
            )
            for relative in inventory:
                self.assertEqual(
                    rows[relative]["checksums"][0]["checksumValue"],
                    _sha256(package.joinpath(*relative.split("/"))),
                )
            product = next(p for p in actual["packages"] if p["name"] == "Accessible Chess")
            verification = product["packageVerificationCode"]
            self.assertEqual(
                verification,
                {"packageVerificationCodeValue": _package_verification_code(package, inventory)},
            )
            self.assertRegex(verification["packageVerificationCodeValue"], r"^[0-9a-f]{40}$")
            stockfish = next(p for p in actual["packages"] if p["name"] == "Stockfish")
            self.assertEqual(stockfish["licenseDeclared"], "GPL-3.0-or-later")
            self.assertEqual(stockfish["versionInfo"], "18")
            self.assertNotIn("packageVerificationCode", stockfish)
            self.assertIn("Stockfish-COPYING.txt", stockfish["comment"])

    def test_every_packaged_sound_requires_authoritative_provenance(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            package = self._package(root)
            sounds = package / "AccessibleChess" / "assets" / "sounds"
            (sounds / "unlisted.wav").write_bytes(b"RIFF-unproven")
            with self.assertRaisesRegex(
                Version2ReleaseSbomError, "missing authoritative provenance"
            ):
                build_version2_release_sbom(
                    package,
                    integration_sha=_SHA,
                    inventory=self._inventory(package),
                )

    def test_sidecar_must_be_outside_package_tree(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            package = self._package(root)
            with self.assertRaisesRegex(Version2ReleaseSbomError, "outside the package tree"):
                write_version2_release_sbom(
                    package,
                    package / SBOM_NAME,
                    integration_sha=_SHA,
                    inventory=self._inventory(package),
                )

    def test_supplied_inventory_must_equal_real_package_tree(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            package = self._package(root)
            inventory = tuple(
                name for name in self._inventory(package) if name != "SHA256SUMS.txt"
            )
            with self.assertRaisesRegex(
                Version2ReleaseSbomError, "does not exactly match package tree"
            ):
                build_version2_release_sbom(
                    package, integration_sha=_SHA, inventory=inventory
                )

    def test_validation_detects_payload_tamper_or_new_file(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            package = self._package(root)
            inventory = self._inventory(package)
            sbom = root / SBOM_NAME
            write_version2_release_sbom(
                package, sbom, integration_sha=_SHA, inventory=inventory
            )
            validate_version2_release_sbom(
                package, sbom, integration_sha=_SHA, inventory=inventory
            )
            (package / "AccessibleChess" / "AccessibleChess.exe").write_bytes(b"changed")
            with self.assertRaisesRegex(Version2ReleaseSbomError, "does not exactly describe"):
                validate_version2_release_sbom(
                    package, sbom, integration_sha=_SHA, inventory=inventory
                )

        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            package = self._package(root)
            old_inventory = self._inventory(package)
            sbom = root / SBOM_NAME
            write_version2_release_sbom(
                package, sbom, integration_sha=_SHA, inventory=old_inventory
            )
            (package / "AccessibleChess" / "new-runtime.dll").write_bytes(b"new")
            with self.assertRaisesRegex(Version2ReleaseSbomError, "does not exactly match package tree"):
                validate_version2_release_sbom(
                    package,
                    sbom,
                    integration_sha=_SHA,
                    inventory=old_inventory,
                )

    def test_invalid_license_evidence_and_existing_output_fail_closed(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            package = self._package(root)
            provenance_path = package / "THIRD_PARTY_NOTICES" / "SOUND_PROVENANCE.json"
            provenance = json.loads(provenance_path.read_text(encoding="utf-8"))
            provenance["events"]["move"]["license_id"] = "not a license/id"
            provenance_path.write_text(json.dumps(provenance) + "\n", encoding="utf-8")
            with self.assertRaisesRegex(Version2ReleaseSbomError, "license identity"):
                build_version2_release_sbom(package, integration_sha=_SHA)

        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            package = self._package(root)
            (package / "THIRD_PARTY_NOTICES" / "Stockfish-NOTICE.txt").write_text(
                "Stockfish 18\n", encoding="utf-8"
            )
            with self.assertRaisesRegex(Version2ReleaseSbomError, "GPL licensing"):
                build_version2_release_sbom(package, integration_sha=_SHA)

        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            package = self._package(root)
            (package / "THIRD_PARTY_NOTICES" / "Stockfish-COPYING.txt").write_text(
                "GNU GENERAL PUBLIC LICENSE\nVersion 3\n", encoding="utf-8"
            )
            with self.assertRaisesRegex(
                Version2ReleaseSbomError, "does not prove GPL-3.0-or-later"
            ):
                build_version2_release_sbom(package, integration_sha=_SHA)

        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            package = self._package(root)
            output = root / SBOM_NAME
            output.write_text("keep\n", encoding="utf-8")
            with self.assertRaisesRegex(Version2ReleaseSbomError, "must not already exist"):
                write_version2_release_sbom(
                    package,
                    output,
                    integration_sha=_SHA,
                    inventory=self._inventory(package),
                )
            self.assertEqual(output.read_text(encoding="utf-8"), "keep\n")

    def test_sidecar_create_is_atomic_against_exists_then_write_race(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            package = self._package(root)
            output = root / SBOM_NAME
            output.write_text("concurrent-writer\n", encoding="utf-8")

            # Simulate the old TOCTOU window: any preflight exists() check lies
            # that the target is absent even though another writer has created it.
            with mock.patch.object(Path, "exists", return_value=False):
                with self.assertRaisesRegex(
                    Version2ReleaseSbomError, "must not already exist"
                ):
                    write_version2_release_sbom(
                        package,
                        output,
                        integration_sha=_SHA,
                        inventory=self._inventory(package),
                    )

            self.assertEqual(
                output.read_text(encoding="utf-8"),
                "concurrent-writer\n",
            )


if __name__ == "__main__":
    unittest.main()