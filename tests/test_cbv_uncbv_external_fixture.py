from __future__ import annotations

import os
from pathlib import Path
import tempfile
import unittest

from acs.acsdb import AcsDatabase
from acs.cbv_extractor import ExternalCbvExtractorConfig, extract_cbv_external
from acs.chessbase_decoder import ExternalChessBaseDecoderConfig
from acs.chessbase_library_import import ChessBaseLibraryImportService


LIBCBH_COMMIT = "9641c5c3949d8fb210b17dd9aa54455645843696"


def _external_environment_ready() -> bool:
    return all(
        os.environ.get(name)
        for name in (
            "UNCBV_BINARY",
            "UNCBV_BINARY_SHA256",
            "UNCBV_FIXTURE",
            "LIBCBH_BRIDGE",
        )
    )


@unittest.skipUnless(
    _external_environment_ready(),
    "real pinned uncbv/libcbh environment is not configured",
)
class CbvUncbvExternalFixtureTests(unittest.TestCase):
    def setUp(self) -> None:
        self.fixture = Path(os.environ["UNCBV_FIXTURE"])
        self.extractor_config = ExternalCbvExtractorConfig(
            Path(os.environ["UNCBV_BINARY"]),
            expected_backend_sha256=os.environ["UNCBV_BINARY_SHA256"],
            timeout_seconds=120,
            max_source_bytes=64 * 1024 * 1024,
            max_extracted_bytes=256 * 1024 * 1024,
        )
        self.decoder_config = ExternalChessBaseDecoderConfig(
            Path(os.environ["LIBCBH_BRIDGE"]),
            expected_backend_commit=LIBCBH_COMMIT,
            timeout_seconds=120,
            library_directory=Path(os.environ["LIBCBH_BRIDGE"]).parent,
        )

    def test_real_cbv_archive_extracts_to_one_classic_cbh_family(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            result = extract_cbv_external(
                self.fixture,
                Path(temporary),
                self.extractor_config,
            )
            self.assertEqual(result.backend_name, "uncbv")
            self.assertGreater(result.entry_count, 1)
            self.assertGreater(result.extracted_bytes, 0)
            self.assertEqual(result.primary_path.suffix.lower(), ".cbh")
            self.assertTrue(result.primary_path.is_file())

    def test_real_cbv_to_libcbh_to_canonical_acsdatabase(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            database = AcsDatabase(Path(temporary) / "real-cbv.acsdb")
            try:
                service = ChessBaseLibraryImportService(
                    database,
                    self.decoder_config,
                    self.extractor_config,
                )
                report = service.import_database(self.fixture)

                self.assertEqual(report.source_format, "cbv")
                self.assertEqual(report.archive_backend_name, "uncbv")
                self.assertGreater(report.decoded_game_count, 0)
                self.assertEqual(report.decoded_game_count, report.imported_game_count)
                self.assertIsNotNone(report.library_result)
                row = database.get_source(report.library_result.source_id)
                self.assertEqual(row["source_format"], "cbv")
                self.assertEqual(row["sha256"], report.source_sha256)
            finally:
                database.close()


if __name__ == "__main__":
    unittest.main()
