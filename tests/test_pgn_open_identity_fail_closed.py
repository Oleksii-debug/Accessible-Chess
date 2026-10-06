from __future__ import annotations

from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from acs.pgn_service import PgnSourceChangedError, open_pgn


_SAMPLE_PGN = """[Event "Identity"]
[Result "*"]

1. e4 e5 *
"""


class PgnOpenIdentityFailureTests(unittest.TestCase):
    def test_open_fails_closed_when_opened_file_identity_cannot_be_inspected(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "identity.pgn"
            source.write_text(_SAMPLE_PGN, encoding="utf-8", newline="")

            with patch("acs.pgn_service.os.fstat", side_effect=OSError("identity unavailable")):
                with self.assertRaises(PgnSourceChangedError):
                    open_pgn(source)


if __name__ == "__main__":
    unittest.main()
