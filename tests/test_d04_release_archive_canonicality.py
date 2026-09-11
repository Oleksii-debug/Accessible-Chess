from __future__ import annotations

import os
from pathlib import Path
import unittest
import warnings
import zipfile

from acs.release_preflight import (
    ReleasePreflightError,
    _validate_relative_token,
    inspect_release_package,
)
from tests.test_release_preflight import ReleasePreflightTests


class D04ReleaseArchiveCanonicalityTests(unittest.TestCase):
    def setUp(self) -> None:
        self._fixture = ReleasePreflightTests(methodName="test_unicode_space_tree_and_inventory_are_deterministic")
        self.addCleanup(self._fixture.doCleanups)

    def make_package(self) -> Path:
        return self._fixture.make_package()

    def assert_rejected(self, root: Path, fragment: str) -> None:
        with self.assertRaises(ReleasePreflightError) as caught:
            inspect_release_package(root)
        self.assertIn(fragment, str(caught.exception))

    def rewrite_checksums(self, root: Path) -> None:
        self._fixture.rewrite_checksums(root)

    def test_windows_forbidden_filename_characters_fail_at_token_boundary(self) -> None:
        for bad in ('bad<name>.dll', 'bad>name.dll', 'bad"name.dll', 'bad|name.dll', 'bad?name.dll', 'bad*name.dll'):
            with self.subTest(name=bad):
                with self.assertRaises(ReleasePreflightError) as caught:
                    _validate_relative_token(f"AccessibleChess/{bad}", label="release path")
                self.assertIn("Windows-portable", str(caught.exception))

    def test_windows_control_characters_fail_at_token_boundary(self) -> None:
        for codepoint in (1, 7, 31):
            with self.subTest(codepoint=codepoint):
                token = f"AccessibleChess/bad{chr(codepoint)}name.dll"
                with self.assertRaises(ReleasePreflightError) as caught:
                    _validate_relative_token(token, label="release path")
                self.assertIn("Windows-portable", str(caught.exception))

    @unittest.skipIf(os.name == "nt", "Win32 cannot materialize the forbidden filename used by this proof")
    def test_posix_builder_cannot_false_green_win32_invalid_payload_name(self) -> None:
        root = self.make_package()
        (root / "AccessibleChess" / "plugin?.dll").write_bytes(b"not-portable-to-windows")
        self.rewrite_checksums(root)
        self.assert_rejected(root, "Windows-portable")

    def test_stockfish_source_zip_rejects_exact_duplicate_members(self) -> None:
        root = self.make_package()
        source = root / "THIRD_PARTY_NOTICES" / "Stockfish-18-source.zip"
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", UserWarning)
            with zipfile.ZipFile(source, "w") as archive:
                archive.writestr("Stockfish-sf_18/Copying.txt", "GNU GENERAL PUBLIC LICENSE\nVersion 3")
                archive.writestr("Stockfish-sf_18/src/main.cpp", "int main(){}")
                archive.writestr("Stockfish-sf_18/src/main.cpp", "int other(){}")
        self.rewrite_checksums(root)
        self.assert_rejected(root, "duplicate Stockfish source ZIP entry")

    def test_stockfish_source_zip_rejects_case_insensitive_member_collisions(self) -> None:
        root = self.make_package()
        source = root / "THIRD_PARTY_NOTICES" / "Stockfish-18-source.zip"
        with zipfile.ZipFile(source, "w") as archive:
            archive.writestr("Stockfish-sf_18/Copying.txt", "GNU GENERAL PUBLIC LICENSE\nVersion 3")
            archive.writestr("Stockfish-sf_18/src/NNUE.cpp", "int a(){}")
            archive.writestr("Stockfish-sf_18/src/nnue.cpp", "int b(){}")
        self.rewrite_checksums(root)
        self.assert_rejected(root, "case-insensitive Stockfish source ZIP collision")


if __name__ == "__main__":
    unittest.main()
