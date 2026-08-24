from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest import mock

from acs.chessbase_manifest import build_chessbase_manifest, verify_manifest_unchanged


class Dev4ChessBaseManifestIoObservabilityTests(unittest.TestCase):
    """QA gate for fail-closed ChessBase manifest verification observability."""

    def test_manifest_verification_reports_hash_io_failure_instead_of_crashing(self) -> None:
        """Unreadable evidence must be reported as failed verification.

        ``verify_manifest_unchanged`` is a public verification boundary that
        returns ``(ok, problems)`` for source-evidence changes.  A transient or
        permission-related read failure must therefore remain distinguishable
        from verified unchanged evidence and must not abort the caller before a
        negative verification result can be recorded.
        """

        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "sample.cbf"
            source.write_bytes(b"stable source evidence")
            manifest = build_chessbase_manifest(source)

            with mock.patch(
                "acs.chessbase_manifest._hash_file",
                side_effect=PermissionError("simulated unreadable source"),
            ):
                ok, problems = verify_manifest_unchanged(manifest)

            self.assertFalse(ok)
            self.assertTrue(problems)
            joined = "\n".join(problems).lower()
            self.assertTrue(
                "unread" in joined or "permission" in joined or "unavailable" in joined,
                "The verification result must preserve explicit I/O-unavailable evidence.",
            )


if __name__ == "__main__":
    unittest.main()
