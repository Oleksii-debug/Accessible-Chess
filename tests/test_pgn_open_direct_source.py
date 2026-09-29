from __future__ import annotations

from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import acs.pgn_service as pgn_service
from acs.pgn_service import PgnFileError, PgnSourceChangedError, open_pgn


_SAMPLE_PGN = """[Event "Direct"]
[Result "*"]

1. e4 e5 *
"""


class PgnOpenDirectSourceTests(unittest.TestCase):
    def test_direct_source_read_does_not_use_following_path_open(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "source.pgn"
            source.write_text(_SAMPLE_PGN, encoding="utf-8", newline="")

            with patch.object(Path, "open", side_effect=AssertionError("Path.open must not be used")):
                opened = open_pgn(source)

            self.assertEqual(opened.total_games, 1)
            self.assertEqual(opened.games[0].tags["Event"], "Direct")

    def test_reparse_source_is_rejected_before_fingerprint_or_read(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "source.pgn"
            source.write_text(_SAMPLE_PGN, encoding="utf-8", newline="")

            with (
                patch.object(pgn_service, "_is_reparse_point", return_value=True),
                patch.object(pgn_service, "fingerprint") as fingerprint,
                patch.object(Path, "open") as path_open,
            ):
                with self.assertRaises(PgnFileError):
                    open_pgn(source)

            fingerprint.assert_not_called()
            path_open.assert_not_called()

    def test_fingerprint_validation_error_stays_in_pgn_file_error_domain(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "source.pgn"
            source.write_text(_SAMPLE_PGN, encoding="utf-8", newline="")

            with patch.object(
                pgn_service,
                "fingerprint",
                side_effect=ValueError("indirect source path"),
            ):
                with self.assertRaises(PgnFileError) as caught:
                    open_pgn(source)

            self.assertNotIsInstance(caught.exception, PgnSourceChangedError)
            self.assertIn("fingerprinted safely", str(caught.exception))

    def test_post_read_fingerprint_validation_error_is_source_changed(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "source.pgn"
            source.write_text(_SAMPLE_PGN, encoding="utf-8", newline="")
            real_fingerprint = pgn_service.fingerprint
            calls = 0

            def fail_revalidation(path, *args, **kwargs):
                nonlocal calls
                calls += 1
                if calls == 1:
                    return real_fingerprint(path, *args, **kwargs)
                raise ValueError("path became indirect")

            with patch.object(
                pgn_service,
                "fingerprint",
                side_effect=fail_revalidation,
            ):
                with self.assertRaises(PgnSourceChangedError):
                    open_pgn(source)

            self.assertEqual(calls, 2)


if __name__ == "__main__":
    unittest.main()
