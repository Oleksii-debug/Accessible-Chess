from __future__ import annotations

import json
from pathlib import Path
import tempfile
import unittest

from tools.generate_release_compliance import (
    EvidenceError,
    FileRecord,
    generate,
    inventory_digest,
    verify,
)


COMMIT = "0123456789abcdef0123456789abcdef01234567"
CREATED = "2026-09-28T17:24:25Z"


class ReleaseComplianceEvidenceTests(unittest.TestCase):
    def _fixture(self, root: Path) -> tuple[str, ...]:
        (root / "VERSION.txt").write_text("2.0-test\n", encoding="utf-8")
        (root / "acs").mkdir()
        (root / "acs" / "core.py").write_text("VALUE = 1\n", encoding="utf-8")
        (root / "web").mkdir()
        (root / "web" / "app.js").write_text("const value = 1;\n", encoding="utf-8")
        (root / "launcher.py").write_text("print('ok')\n", encoding="utf-8")
        return ("acs", "web", "launcher.py", "VERSION.txt")

    def test_generation_is_byte_deterministic_and_verifiable(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            includes = self._fixture(root)
            first = root / "evidence-a"
            second = root / "evidence-b"

            generate(
                root=root,
                output_dir=first,
                source_commit=COMMIT,
                created=CREATED,
                includes=includes,
            )
            generate(
                root=root,
                output_dir=second,
                source_commit=COMMIT,
                created=CREATED,
                includes=includes,
            )

            for name in (
                "accessible-chess.spdx.json",
                "accessible-chess.provenance.json",
            ):
                self.assertEqual(
                    (first / name).read_bytes(),
                    (second / name).read_bytes(),
                )

            verify(
                root=root,
                evidence_dir=first,
                source_commit=COMMIT,
                created=CREATED,
                includes=includes,
            )

    def test_provenance_uses_relative_paths_and_never_overclaims_release_acceptance(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            includes = self._fixture(root)
            evidence = root / "evidence"
            generate(
                root=root,
                output_dir=evidence,
                source_commit=COMMIT,
                created=CREATED,
                includes=includes,
            )
            provenance = json.loads(
                (evidence / "accessible-chess.provenance.json").read_text(
                    encoding="utf-8"
                )
            )

            self.assertEqual(COMMIT, provenance["source"]["commit"])
            self.assertEqual("2026-09-28T17:24:25Z", provenance["created"])
            self.assertFalse(provenance["claims"]["human_tested"])
            self.assertFalse(provenance["claims"]["nvda_verified"])
            self.assertFalse(provenance["claims"]["final_windows_zip"])
            self.assertFalse(provenance["claims"]["license_inference_performed"])
            for item in provenance["files"]:
                path = item["path"]
                self.assertFalse(Path(path).is_absolute())
                self.assertNotIn("..", Path(path).parts)
                self.assertNotIn(str(root), path)

    def test_spdx_uses_noassertion_instead_of_inventing_license_claims(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            includes = self._fixture(root)
            evidence = root / "evidence"
            generate(
                root=root,
                output_dir=evidence,
                source_commit=COMMIT,
                created=CREATED,
                includes=includes,
            )
            spdx = json.loads(
                (evidence / "accessible-chess.spdx.json").read_text(
                    encoding="utf-8"
                )
            )

            self.assertEqual("SPDX-2.3", spdx["spdxVersion"])
            package = spdx["packages"][0]
            self.assertEqual("NOASSERTION", package["licenseConcluded"])
            self.assertEqual("NOASSERTION", package["licenseDeclared"])
            self.assertEqual("NOASSERTION", package["copyrightText"])
            self.assertTrue(spdx["files"])
            for item in spdx["files"]:
                self.assertEqual("NOASSERTION", item["licenseConcluded"])
                self.assertEqual("NOASSERTION", item["copyrightText"])

    def test_verification_fails_closed_after_runtime_input_changes(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            includes = self._fixture(root)
            evidence = root / "evidence"
            generate(
                root=root,
                output_dir=evidence,
                source_commit=COMMIT,
                created=CREATED,
                includes=includes,
            )
            (root / "acs" / "core.py").write_text("VALUE = 2\n", encoding="utf-8")

            with self.assertRaises(EvidenceError):
                verify(
                    root=root,
                    evidence_dir=evidence,
                    source_commit=COMMIT,
                    created=CREATED,
                    includes=includes,
                )

    def test_inventory_digest_changes_when_file_identity_changes(self) -> None:
        base = [
            FileRecord(
                path="acs/core.py",
                size=10,
                sha256="a" * 64,
                media_type="text/x-python",
            )
        ]
        changed = [
            FileRecord(
                path="acs/core.py",
                size=10,
                sha256="b" * 64,
                media_type="text/x-python",
            )
        ]
        self.assertNotEqual(inventory_digest(base), inventory_digest(changed))

    def test_include_path_traversal_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            self._fixture(root)
            with self.assertRaises(EvidenceError):
                generate(
                    root=root,
                    output_dir=root / "evidence",
                    source_commit=COMMIT,
                    created=CREATED,
                    includes=("../outside",),
                )

    def test_invalid_commit_or_naive_timestamp_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            includes = self._fixture(root)

            with self.assertRaises(EvidenceError):
                generate(
                    root=root,
                    output_dir=root / "bad-commit",
                    source_commit="abc123",
                    created=CREATED,
                    includes=includes,
                )

            with self.assertRaises(EvidenceError):
                generate(
                    root=root,
                    output_dir=root / "bad-time",
                    source_commit=COMMIT,
                    created="2026-09-28T17:24:25",
                    includes=includes,
                )


if __name__ == "__main__":
    unittest.main()
