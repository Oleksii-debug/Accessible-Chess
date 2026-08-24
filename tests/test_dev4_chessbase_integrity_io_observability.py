from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from acs.chessbase_integrity import capture_integrity_snapshot, verify_integrity_snapshot


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

            original_open = Path.open

            def guarded_open(path: Path, *args, **kwargs):
                if path == companion:
                    raise PermissionError("synthetic companion I/O failure")
                return original_open(path, *args, **kwargs)

            try:
                with patch.object(Path, "open", new=guarded_open):
                    verify_integrity_snapshot(snapshot)
            except OSError as exc:
                self.fail(
                    "Integrity re-verification must convert component I/O unavailability "
                    f"into a domain verification failure instead of leaking raw {type(exc).__name__}: {exc}"
                )
            except RuntimeError:
                # A domain-level verification failure is acceptable; the Product may
                # use ChessBaseSourceChangedError or a more specific verification error.
                pass
            else:
                self.fail("Unverifiable companion evidence must fail closed.")


if __name__ == "__main__":
    unittest.main()
