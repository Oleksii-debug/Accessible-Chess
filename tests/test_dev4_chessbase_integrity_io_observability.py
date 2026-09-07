from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import acs.import_contract as import_contract
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

            # The production integrity owner now delegates to the canonical
            # no-follow descriptor-bound fingerprint(), which uses os.open.
            # Inject the same companion-unavailability failure at that real seam
            # rather than patching the removed Path.open implementation.
            real_open = os.open
            companion_absolute = os.path.abspath(os.fspath(companion))

            def guarded_open(path, flags, *args, **kwargs):
                if os.path.abspath(os.fspath(path)) == companion_absolute:
                    raise PermissionError("synthetic companion I/O failure")
                return real_open(path, flags, *args, **kwargs)

            try:
                with patch.object(import_contract.os, "open", side_effect=guarded_open):
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
