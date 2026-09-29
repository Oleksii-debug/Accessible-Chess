from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from acs.import_contract import SourceFingerprint
from acs.pgn_service import PgnFileError, open_pgn


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
    """QA gates for bounded resource use at the untrusted PGN file boundary."""

    def test_open_pgn_never_uses_unbounded_text_read(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "sample.pgn"
            path.write_text('[Event "seed"]\n\n*\n', encoding="utf-8")
            source = SourceFingerprint(
                path=str(path),
                size=18,
                sha256="0" * 64,
                suffix=".pgn",
            )
            handle = _BoundedTextHandle('[Event "QA"]\n\n*\n')

            with patch("acs.pgn_service.fingerprint", return_value=source), patch(
                "acs.pgn_service._open_direct_source", return_value=handle
            ):
                opened = open_pgn(path)

        self.assertEqual(opened.source, source)
        self.assertEqual(opened.total_games, 1)

    def test_absurdly_large_source_is_rejected_before_payload_open(self) -> None:
        """A finite source cap must reject before the bounded payload opener runs."""

        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "huge.pgn"
            with path.open("wb") as handle:
                handle.truncate(64 * 1024 * 1024 + 1)

            with patch(
                "acs.pgn_service._open_direct_source",
                side_effect=AssertionError("oversized PGN payload must not be opened"),
            ) as open_mock:
                with self.assertRaises(PgnFileError):
                    open_pgn(path)

            open_mock.assert_not_called()


if __name__ == "__main__":
    unittest.main()
