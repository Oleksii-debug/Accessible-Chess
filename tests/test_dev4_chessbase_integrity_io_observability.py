from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import acs.import_contract as import_contract
from acs.chessbase_integrity import (
    ChessBaseIntegrityIOError,
    capture_integrity_snapshot,
    verify_integrity_snapshot,
)


class Dev4ChessBaseIntegrityIoObservabilityTests(unittest.TestCase):
    """QA gate for structured fail-closed integrity re-verification."""

    def test_component_open_failure_does_not_escape_as_raw_oserror(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            primary = root / "sample.cbh"
            companion = root / "sample.cbg"
            primary.write_bytes(b"header")
            companion.write_bytes(b"moves")
            snapshot = capture_integrity_snapshot(primary)

            original_open = os.open
            companion_absolute = companion.absolute()

            def guarded_open(path, flags, *args, **kwargs):
                candidate = Path(os.fsdecode(path))
                if candidate == companion_absolute:
                    raise PermissionError("synthetic companion I/O failure")
                return original_open(path, flags, *args, **kwargs)

            # The canonical fingerprint owns the no-follow descriptor open.
            # Exercise that boundary directly while preserving the original
            # requirement: unverifiable companion evidence must fail closed as
            # a domain error and never escape as raw filesystem diagnostics.
            with patch.object(import_contract.os, "open", side_effect=guarded_open):
                with self.assertRaises(ChessBaseIntegrityIOError) as caught:
                    verify_integrity_snapshot(snapshot)

            rendered = str(caught.exception)
            self.assertNotIn("synthetic companion I/O failure", rendered)
            self.assertNotIn(str(root), rendered)


if __name__ == "__main__":
    unittest.main()
