from __future__ import annotations

import os
from pathlib import Path
import tempfile
import unittest
from unittest import mock

from acs.chessbase_integrity import (
    ChessBaseIntegrityIOError,
    capture_integrity_snapshot,
)
from acs.import_contract import fingerprint as canonical_fingerprint


class D04ChessBaseIntegrityHandleIdentityTests(unittest.TestCase):
    def test_classic_chessbase_integrity_delegates_to_canonical_fingerprint(self) -> None:
        with tempfile.TemporaryDirectory(prefix="d04-cbh-canonical-fingerprint-") as directory:
            root = Path(directory)
            source = root / "sample.cbh"
            companion = root / "sample.cbg"
            source.write_bytes(b"header")
            companion.write_bytes(b"moves")

            with mock.patch(
                "acs.chessbase_integrity._canonical_fingerprint",
                wraps=canonical_fingerprint,
            ) as delegated:
                snapshot = capture_integrity_snapshot(source)

            self.assertEqual(delegated.call_count, 2)
            self.assertEqual([item.path for item in snapshot.files], [source, companion])
            self.assertEqual([item.size_bytes for item in snapshot.files], [6, 5])

    def test_path_replacement_between_validation_and_open_fails_closed(self) -> None:
        with tempfile.TemporaryDirectory(prefix="d04-cbh-handle-race-") as directory:
            root = Path(directory)
            source = root / "private-source.cbh"
            replacement = root / "replacement.bin"
            parked = root / "original.parked"
            original_bytes = b"authoritative chessbase source"
            replacement_bytes = b"different object that must never be fingerprinted as source"
            source.write_bytes(original_bytes)
            replacement.write_bytes(replacement_bytes)

            real_open = os.open
            swapped = False

            def swap_before_open(path, flags, *args, **kwargs):
                nonlocal swapped
                candidate = Path(os.fsdecode(path))
                if not swapped and candidate == source.absolute():
                    source.rename(parked)
                    replacement.rename(source)
                    swapped = True
                return real_open(path, flags, *args, **kwargs)

            try:
                with mock.patch("acs.import_contract.os.open", side_effect=swap_before_open):
                    with self.assertRaises(ChessBaseIntegrityIOError) as caught:
                        capture_integrity_snapshot(source)
            finally:
                if swapped:
                    if source.exists():
                        source.rename(replacement)
                    if parked.exists():
                        parked.rename(source)

            self.assertTrue(swapped, "adversarial replacement hook must execute")
            self.assertEqual(source.read_bytes(), original_bytes)
            self.assertEqual(replacement.read_bytes(), replacement_bytes)
            rendered = str(caught.exception)
            self.assertIn("private-source.cbh", rendered)
            self.assertNotIn(str(root), rendered)


if __name__ == "__main__":
    unittest.main()
