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


class Version2CbzTwoCbzEvidenceTests(unittest.TestCase):
    def test_encrypted_archives_are_recognized_without_support_claim(self) -> None:
        expected = {
            ".cbz": "encrypted_archive_container",
            ".2cbz": "encrypted_archive_container_unqualified_payload",
        }
        for suffix, source_kind in expected.items():
            with self.subTest(suffix=suffix):
                probe = probe_chessbase_source("archive" + suffix)
                self.assertTrue(probe.recognized)
                self.assertTrue(probe.is_primary_source)
                self.assertTrue(probe.read_only)
                self.assertEqual(probe.source_kind, source_kind)
                self.assertFalse(probe.decoder_available)
                self.assertFalse(probe.safe_to_import)
                rendered = " ".join(probe.warnings).casefold()
                self.assertIn("encrypted", rendered)
                self.assertIn("blocked", rendered)

    def test_encrypted_archive_integrity_is_opaque_source_only(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            for suffix in (".cbz", ".2cbz"):
                with self.subTest(suffix=suffix):
                    source = root / ("archive" + suffix)
                    source.write_bytes(b"opaque-encrypted-source")
                    snapshot = capture_integrity_snapshot(source)
                    self.assertEqual(len(snapshot.files), 1)
                    self.assertEqual(snapshot.files[0].extension, suffix)
                    self.assertEqual(verify_integrity_snapshot(snapshot), snapshot)
                    self.assertEqual(source.read_bytes(), b"opaque-encrypted-source")

    def test_encrypted_archive_mutation_invalidates_snapshot(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "archive.cbz"
            source.write_bytes(b"ciphertext-v1")
            snapshot = capture_integrity_snapshot(source)
            source.write_bytes(b"ciphertext-v2")
            with self.assertRaises(ChessBaseSourceChangedError):
                verify_integrity_snapshot(snapshot)

    def test_current_cbv_extractor_rejects_cbz_and_2cbz(self) -> None:
        config = ExternalCbvExtractorConfig(
            executable=Path("uncbv-not-invoked"),
            expected_backend_sha256="0" * 64,
        )
        for suffix in (".cbz", ".2cbz"):
            with self.subTest(suffix=suffix):
                with tempfile.TemporaryDirectory() as directory:
                    with self.assertRaises(CbvExtractError) as caught:
                        extract_cbv_external(
                            "archive" + suffix,
                            Path(directory),
                            config,
                        )
                self.assertEqual(caught.exception.code, CbvExtractCode.UNSUPPORTED_SOURCE)

    def test_windows_library_import_does_not_promote_encrypted_archives(self) -> None:
        suffixes = Version2WindowsFileActionDelegate._IMPORT_SUFFIXES
        self.assertNotIn(".cbz", suffixes)
        self.assertNotIn(".2cbz", suffixes)


if __name__ == "__main__":
    unittest.main()
