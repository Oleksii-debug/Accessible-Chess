from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest import mock

from acs.chessbase_adapter import probe_chessbase_source


class Dev4ChessBaseProbeObservabilityTests(unittest.TestCase):
    """QA gates preventing false-green ChessBase companion evidence."""

    def test_companion_directory_io_failure_is_not_reported_as_no_companions(self) -> None:
        """Unreadable companion topology must remain distinguishable from absence.

        A permission/I/O failure while enumerating the primary CBH directory is
        not evidence that companion files do not exist.  The evidence boundary
        must fail closed or surface an explicit unavailable/I/O warning rather
        than converting the failure into the ordinary "no companions detected"
        state.
        """

        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "database.cbh"
            source.write_bytes(b"header")

            with mock.patch.object(Path, "iterdir", side_effect=PermissionError("access denied")):
                probe = probe_chessbase_source(source)

            warnings = " ".join(probe.warnings).lower()
            self.assertNotIn(
                "no classic cbh companion files were detected",
                warnings,
                "Directory-enumeration failure must not be collapsed into verified companion absence.",
            )
            self.assertTrue(
                any(token in warnings for token in ("permission", "access", "unavailable", "i/o", "io error", "could not")),
                "The probe must explicitly surface that companion topology could not be inspected.",
            )


if __name__ == "__main__":
    unittest.main()
