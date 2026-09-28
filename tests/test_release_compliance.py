from __future__ import annotations

import hashlib
import json
from pathlib import Path
import subprocess
import tempfile
import unittest

from tools.generate_release_compliance import (
    EvidenceError,
    FileRecord,
    generate,
    inventory_digest,
    verify,
)


CREATED = "2026-09-28T17:24:25Z"


def _git(root: Path, *args: str) -> str:
    return subprocess.run(
        ["git", *args],
        cwd=root,
        check=True,
        capture_output=True,
        text=True,
        encoding="utf-8",
    ).stdout.strip()


class ReleaseComplianceEvidenceTests(unittest.TestCase):
    def _fixture(self, root: Path) -> tuple[tuple[str, ...], str]:
        (root / "VERSION.txt").write_text("2.0-test\n", encoding="utf-8")
        (root / "acs").mkdir()
        (root / "acs" / "core.py").write_text("VALUE = 1\n", encoding="utf-8")
        (root / "web").mkdir()
        (root / "web" / "app.js").write_text("const value = 1;\n", encoding="utf-8")
        (root / "launcher.py").write_text("print('ok')\n", encoding="utf-8")
        includes = ("acs", "web", "launcher.py", "VERSION.txt")

        _git(root, "init", "--quiet")
        _git(root, "config", "core.autocrlf", "false")
        _git(root, "config", "user.name", "Accessible Chess Test")
        _git(root, "config", "user.email", "test@example.invalid")
        _git(root, "add", "--", *includes)
        _git(root, "commit", "--quiet", "-m", "fixture")
        commit = _git(root, "rev-parse", "HEAD")
        self.assertEqual(40, len(commit))
        return includes, commit

    def test_generation_is_byte_deterministic_and_verifiable(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            includes, commit = self._fixture(root)
            first = root / "evidence-a"
            second = root / "evidence-b"

            generate(
                root=root,
                output_dir=first,
                source_commit=commit,
                created=CREATED,
                includes=includes,
            )
            generate(
                root=root,
                output_dir=second,
                source_commit=commit,
                created=CREATED,
                includes=includes,
            )

            for name in (
                "accessible-chess.spdx.json",
                "accessible-chess.provenance.json",
                "accessible-chess.evidence.sha256",
            ):
                self.assertEqual(
                    (first / name).read_bytes(),
                    (second / name).read_bytes(),
                )

            for name in (
                "accessible-chess.spdx.json",
                "accessible-chess.provenance.json",
            ):
                payload = (first / name).read_bytes()
                self.assertTrue(payload.endswith(b"\n"))
                self.assertFalse(payload.endswith(b"\\n"))
                parsed = json.loads(payload.decode("utf-8"))
                self.assertIsInstance(parsed, dict)

            manifest_lines = (
                first / "accessible-chess.evidence.sha256"
            ).read_text(encoding="utf-8").splitlines()
            self.assertEqual(2, len(manifest_lines))
            for line, name in zip(
                manifest_lines,
                (
                    "accessible-chess.spdx.json",
                    "accessible-chess.provenance.json",
                ),
                strict=True,
            ):
                digest, recorded_name = line.split("  ", 1)
                self.assertEqual(name, recorded_name)
                self.assertEqual(
                    hashlib.sha256((first / name).read_bytes()).hexdigest(),
                    digest,
                )

            verify(
                root=root,
                evidence_dir=first,
                source_commit=commit,
                created=CREATED,
                includes=includes,
            )

    def test_provenance_binds_clean_git_head_and_uses_relative_paths(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            includes, commit = self._fixture(root)
            evidence = root / "evidence"
            generate(
                root=root,
                output_dir=evidence,
                source_commit=commit,
                created=CREATED,
                includes=includes,
            )
            provenance = json.loads(
                (evidence / "accessible-chess.provenance.json").read_text(
                    encoding="utf-8"
                )
            )

            self.assertEqual(commit, provenance["source"]["commit"])
            self.assertTrue(provenance["source"]["git_head_verified"])
            self.assertTrue(provenance["source"]["scoped_inputs_clean"])
            self.assertEqual("2026-09-28T17:24:25Z", provenance["created"])
            self.assertFalse(provenance["claims"]["human_tested"])
            self.assertFalse(provenance["claims"]["nvda_verified"])
            self.assertFalse(provenance["claims"]["final_windows_zip"])
            self.assertFalse(provenance["claims"]["license_inference_performed"])

            media_types = {item["path"]: item["media_type"] for item in provenance["files"]}
            self.assertEqual("text/x-python", media_types["acs/core.py"])
            self.assertEqual("text/javascript", media_types["web/app.js"])
            for item in provenance["files"]:
                path = item["path"]
                self.assertFalse(Path(path).is_absolute())
                self.assertNotIn("..", Path(path).parts)
                self.assertNotIn(str(root), path)

    def test_spdx_uses_noassertion_instead_of_inventing_license_claims(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            includes, commit = self._fixture(root)
            evidence = root / "evidence"
            generate(
                root=root,
                output_dir=evidence,
                source_commit=commit,
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
            self.assertFalse(package["filesAnalyzed"])
            self.assertTrue(
                spdx["documentNamespace"].startswith(
                    "https://github.com/Oleksii-debug/Accessible-Chess/spdx/"
                )
            )
            self.assertTrue(spdx["files"])
            for item in spdx["files"]:
                self.assertEqual("NOASSERTION", item["licenseConcluded"])
                self.assertEqual(["NOASSERTION"], item["licenseInfoInFiles"])
                self.assertEqual("NOASSERTION", item["copyrightText"])

    def test_verification_fails_closed_after_runtime_input_changes(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            includes, commit = self._fixture(root)
            evidence = root / "evidence"
            generate(
                root=root,
                output_dir=evidence,
                source_commit=commit,
                created=CREATED,
                includes=includes,
            )
            (root / "acs" / "core.py").write_text("VALUE = 2\n", encoding="utf-8")

            with self.assertRaises(EvidenceError):
                verify(
                    root=root,
                    evidence_dir=evidence,
                    source_commit=commit,
                    created=CREATED,
                    includes=includes,
                )

    def test_declared_commit_must_equal_actual_git_head(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            includes, commit = self._fixture(root)
            wrong = ("0" if commit[0] != "0" else "1") + commit[1:]
            with self.assertRaises(EvidenceError):
                generate(
                    root=root,
                    output_dir=root / "evidence",
                    source_commit=wrong,
                    created=CREATED,
                    includes=includes,
                )

    def test_canonical_inventory_line_uses_binary_separators_not_escape_text(self) -> None:
        record = FileRecord(
            path="acs/core.py",
            size=10,
            sha256="a" * 64,
            media_type="text/x-python",
        )
        encoded = record.canonical_line().encode("utf-8")
        self.assertEqual(3, encoded.count(b"\0"))
        self.assertTrue(encoded.endswith(b"\n"))
        self.assertNotIn(b"\\0", encoded)
        self.assertNotIn(b"\\n", encoded)

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
            _includes, commit = self._fixture(root)
            with self.assertRaises(EvidenceError):
                generate(
                    root=root,
                    output_dir=root / "evidence",
                    source_commit=commit,
                    created=CREATED,
                    includes=("../outside",),
                )

    def test_linked_ancestor_is_rejected_before_git_or_hashing(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            _includes, commit = self._fixture(root)
            link = root / "linked-acs"
            try:
                link.symlink_to(root / "acs", target_is_directory=True)
            except (OSError, NotImplementedError) as exc:
                self.skipTest(f"symlink creation unavailable on this runner: {exc}")

            with self.assertRaises(EvidenceError):
                generate(
                    root=root,
                    output_dir=root / "evidence",
                    source_commit=commit,
                    created=CREATED,
                    includes=("linked-acs/core.py", "VERSION.txt"),
                )

    def test_invalid_commit_or_naive_timestamp_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            includes, commit = self._fixture(root)

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
                    source_commit=commit,
                    created="2026-09-28T17:24:25",
                    includes=includes,
                )


if __name__ == "__main__":
    unittest.main()
