from __future__ import annotations

from pathlib import Path
import tempfile
import unittest

from acs.cbv_extractor import (
    CbvExtractCode,
    CbvExtractError,
    ExternalCbvExtractorConfig,
    extract_cbv_external,
)
from acs.chessbase_adapter import probe_chessbase_source
from acs.chessbase_integrity import (
    ChessBaseSourceChangedError,
    capture_integrity_snapshot,
    verify_integrity_snapshot,
)
from acs.version2_windows_file_workflows import Version2WindowsFileActionDelegate


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
        rendered = " ".join(probe.warnings)
        self.assertIn("officially documented", rendered)
        self.assertIn("classic CBV decoder", rendered)
        self.assertIn("blocked", rendered.casefold())

    def test_2cbv_opaque_source_hash_detects_later_mutation(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "Training.2cbv"
            source.write_bytes(b"opaque-modern-archive-v1")
            snapshot = capture_integrity_snapshot(source)
            self.assertEqual(len(snapshot.files), 1)
            self.assertEqual(snapshot.files[0].extension, ".2cbv")
            self.assertEqual(snapshot.files[0].role, "primary_source")
            self.assertEqual(verify_integrity_snapshot(snapshot), snapshot)
            source.write_bytes(b"opaque-modern-archive-v2")
            with self.assertRaises(ChessBaseSourceChangedError):
                verify_integrity_snapshot(snapshot)

    def test_classic_cbv_extractor_does_not_inherit_2cbv(self) -> None:
        config = ExternalCbvExtractorConfig(
            executable=Path("uncbv-not-invoked"),
            expected_backend_sha256="0" * 64,
        )
        with tempfile.TemporaryDirectory() as directory:
            with self.assertRaises(CbvExtractError) as caught:
                extract_cbv_external(
                    "archive.2cbv",
                    Path(directory),
                    config,
                )
        self.assertEqual(caught.exception.code, CbvExtractCode.UNSUPPORTED_SOURCE)

    def test_windows_library_import_does_not_promote_2cbv(self) -> None:
        self.assertNotIn(
            ".2cbv",
            Version2WindowsFileActionDelegate._IMPORT_SUFFIXES,
        )


if __name__ == "__main__":
    unittest.main()
