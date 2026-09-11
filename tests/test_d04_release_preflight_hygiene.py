from __future__ import annotations

import hashlib
from pathlib import Path
import unittest

from acs.release_preflight import ReleasePreflightError, _validate_relative_token, inspect_release_package
from tests.test_release_preflight import ReleasePreflightTests


class D04ReleasePreflightHygieneTests(unittest.TestCase):
    def make_package(self) -> Path:
        harness = ReleasePreflightTests(
            methodName="test_unicode_space_tree_and_inventory_are_deterministic"
        )
        root = harness.make_package()
        self.addCleanup(harness.doCleanups)
        return root

    @staticmethod
    def rewrite_checksums(root: Path) -> None:
        files = sorted(
            (p for p in root.rglob("*") if p.is_file() and p.name != "SHA256SUMS.txt"),
            key=lambda p: p.relative_to(root).as_posix().casefold(),
        )
        rows = [
            f"{hashlib.sha256(path.read_bytes()).hexdigest()}  {path.relative_to(root).as_posix()}"
            for path in files
        ]
        (root / "SHA256SUMS.txt").write_text("\n".join(rows) + "\n", encoding="utf-8")

    def assert_rejected(self, root: Path, fragment: str) -> None:
        with self.assertRaises(ReleasePreflightError) as caught:
            inspect_release_package(root)
        self.assertIn(fragment, str(caught.exception))

    def test_nested_compiler_debug_and_runtime_logs_never_ship(self) -> None:
        for relative in (
            "AccessibleChess/diagnostics/nuitka-compilation-report.xml",
            "AccessibleChess/diagnostics/nuitka-crash-report.xml",
            "AccessibleChess/AccessibleChess.pdb",
            "AccessibleChess/crash/session.dmp",
            "AccessibleChess/logs/debug.log",
        ):
            with self.subTest(relative=relative):
                root = self.make_package()
                artifact = root / relative
                artifact.parent.mkdir(parents=True, exist_ok=True)
                artifact.write_text("C:/Users/private/Accessible-Chess/build/source.py", encoding="utf-8")
                self.rewrite_checksums(root)
                self.assert_rejected(root, "build/debug/privacy artifact")

    def test_windows_nonportable_path_tokens_fail_before_checksum_inventory(self) -> None:
        for token in (
            "AccessibleChess/con.txt",
            "AccessibleChess/AUX.bin",
            "AccessibleChess/cache:private",
            "AccessibleChess/trailing.",
            "AccessibleChess/trailing ",
        ):
            with self.subTest(token=token):
                with self.assertRaises(ReleasePreflightError) as caught:
                    _validate_relative_token(token, label="release path")
                self.assertIn("Windows-portable", str(caught.exception))

    def test_case_insensitive_file_collision_is_rejected_when_filesystem_can_represent_it(self) -> None:
        root = self.make_package()
        first = root / "AccessibleChess" / "plugins" / "Codec.dll"
        second = root / "AccessibleChess" / "plugins" / "codec.dll"
        first.parent.mkdir(parents=True, exist_ok=True)
        first.write_bytes(b"A")
        second.write_bytes(b"B")
        if first.read_bytes() == second.read_bytes():
            self.skipTest("filesystem is case-insensitive and cannot represent the collision")
        self.rewrite_checksums(root)
        self.assert_rejected(root, "case-insensitive path collision")


if __name__ == "__main__":
    unittest.main()
