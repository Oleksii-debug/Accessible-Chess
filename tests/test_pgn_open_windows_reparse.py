from __future__ import annotations

import os
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch

import acs.import_contract as import_contract
import acs.pgn_service as pgn_service
from acs.pgn_service import PgnFileError, open_pgn


_SAMPLE_PGN = """[Event "Direct Unicode"]
[Result "*"]

1. e4 e5 *
"""


def _remove_junction(path: Path) -> None:
    if os.name != "nt":
        return
    try:
        subprocess.run(
            ["cmd", "/c", "rmdir", str(path)],
            check=False,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
    except OSError:
        pass


@unittest.skipUnless(os.name == "nt", "Windows reparse-point contract")
class PgnOpenWindowsReparseTests(unittest.TestCase):
    def _replace_file_with_junction(self, source: Path, target: Path) -> None:
        source.unlink()
        completed = subprocess.run(
            ["cmd", "/c", "mklink", "/J", str(source), str(target)],
            check=False,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
        )
        if completed.returncode:
            self.fail(f"could not create Windows junction test fixture: {completed.stdout}")
        self.addCleanup(_remove_junction, source)

    def test_fingerprint_rejects_post_validation_junction_before_hashing(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "source.pgn"
            target = root / "foreign-target"
            target.mkdir()
            (target / "foreign.txt").write_text("foreign", encoding="utf-8")
            source.write_text(_SAMPLE_PGN, encoding="utf-8", newline="")

            real_validate = import_contract._validate_source_path
            validations = 0

            def validate_then_swap(path):
                nonlocal validations
                result = real_validate(path)
                validations += 1
                if validations == 1:
                    self._replace_file_with_junction(source, target)
                return result

            with patch.object(
                import_contract,
                "_validate_source_path",
                side_effect=validate_then_swap,
            ), patch.object(
                import_contract.hashlib,
                "sha256",
                side_effect=AssertionError("reparse target bytes must not be hashed"),
            ) as digest:
                with self.assertRaises((OSError, ValueError)):
                    import_contract.fingerprint(source)

            digest.assert_not_called()

    def test_open_rejects_junction_swap_after_fingerprint_before_reader_identity(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "source.pgn"
            target = root / "foreign-target"
            target.mkdir()
            (target / "foreign.txt").write_text("foreign", encoding="utf-8")
            source.write_text(_SAMPLE_PGN, encoding="utf-8", newline="")
            real_fingerprint = pgn_service.fingerprint
            fingerprint_calls = 0

            def fingerprint_then_swap(path, *args, **kwargs):
                nonlocal fingerprint_calls
                result = real_fingerprint(path, *args, **kwargs)
                fingerprint_calls += 1
                if fingerprint_calls == 1:
                    self._replace_file_with_junction(source, target)
                return result

            with patch.object(
                pgn_service,
                "fingerprint",
                side_effect=fingerprint_then_swap,
            ), patch.object(
                pgn_service,
                "_opened_source_identity",
            ) as opened_identity:
                with self.assertRaises(PgnFileError):
                    open_pgn(source)

            opened_identity.assert_not_called()


class PgnOpenDirectUnicodePathTests(unittest.TestCase):
    def test_direct_path_with_spaces_and_non_ascii_is_not_treated_as_indirect(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "дані з пробілами"
            root.mkdir()
            source = root / "партія ♞.pgn"
            source.write_text(_SAMPLE_PGN, encoding="utf-8", newline="")

            opened = open_pgn(source)

            self.assertEqual(opened.total_games, 1)
            self.assertEqual(opened.games[0].tags["Event"], "Direct Unicode")


if __name__ == "__main__":
    unittest.main()
