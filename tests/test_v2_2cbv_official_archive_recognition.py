from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from acs.chessbase_adapter import probe_chessbase_source
from acs.chessbase_integrity import (
    ChessBaseSourceChangedError,
    capture_integrity_snapshot,
    verify_integrity_snapshot,
)


class TwoCbvOfficialArchiveRecognitionTests(unittest.TestCase):
    def test_2cbv_is_recognized_as_blocked_modern_archive(self) -> None:
        probe = probe_chessbase_source("Training.2CBV")

        self.assertTrue(probe.recognized)
        self.assertTrue(probe.is_primary_source)
        self.assertEqual(probe.extension, ".2cbv")
        self.assertEqual(
            probe.source_kind,
            "modern_archive_container_unqualified_payload",
        )
        self.assertFalse(probe.decoder_available)
        self.assertFalse(probe.safe_to_import)
        self.assertEqual(probe.status, "adapter_only")
        self.assertTrue(
            any("officially documented" in warning for warning in probe.warnings)
        )
        self.assertTrue(
            any("classic CBV decoder" in warning for warning in probe.warnings)
        )

    def test_2cbv_opaque_source_hash_detects_later_mutation(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "Training.2cbv"
            source.write_bytes(b"opaque-modern-archive-v1")

            snapshot = capture_integrity_snapshot(source)

            self.assertEqual(len(snapshot.files), 1)
            self.assertEqual(snapshot.files[0].extension, ".2cbv")
            self.assertEqual(snapshot.files[0].role, "primary_source")
            self.assertEqual(snapshot.files[0].size_bytes, len(b"opaque-modern-archive-v1"))
            self.assertEqual(verify_integrity_snapshot(snapshot), snapshot)

            source.write_bytes(b"opaque-modern-archive-v2")
            with self.assertRaises(ChessBaseSourceChangedError):
                verify_integrity_snapshot(snapshot)

    def test_filename_recognition_does_not_claim_cbv_backend_compatibility(self) -> None:
        probe = probe_chessbase_source("Training.2cbv")
        report = probe.as_report_fields()

        self.assertFalse(report["decoder_available"])
        self.assertFalse(report["safe_to_import"])
        self.assertEqual(report["components"], [])
        self.assertNotEqual(report["source_kind"], "archive_container")


if __name__ == "__main__":
    unittest.main()
