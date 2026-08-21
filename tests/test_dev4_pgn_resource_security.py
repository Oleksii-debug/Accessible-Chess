from __future__ import annotations

import unittest
from pathlib import Path
from unittest.mock import patch

from acs.import_contract import SourceFingerprint
from acs.pgn_service import open_pgn


class _BoundedTextHandle:
    def __init__(self, payload: str) -> None:
        self._payload = payload
        self._done = False

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def read(self, size: int = -1) -> str:
        if size is None or size < 0:
            raise AssertionError("unbounded PGN read detected")
        if self._done:
            return ""
        self._done = True
        return self._payload


class Dev4PgnResourceSecurityTests(unittest.TestCase):
    """QA gate for bounded reads at the untrusted PGN file boundary."""

    def test_open_pgn_never_uses_unbounded_text_read(self) -> None:
        source = SourceFingerprint(
            path="sample.pgn",
            size=18,
            sha256="0" * 64,
            suffix=".pgn",
        )
        handle = _BoundedTextHandle('[Event "QA"]\n\n*\n')

        with patch("acs.pgn_service.fingerprint", return_value=source), patch.object(
            Path, "open", return_value=handle
        ):
            opened = open_pgn("sample.pgn")

        self.assertEqual(opened.source, source)
        self.assertEqual(opened.total_games, 1)


if __name__ == "__main__":
    unittest.main()
