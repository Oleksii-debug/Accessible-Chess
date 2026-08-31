from __future__ import annotations

import os
from pathlib import Path
import tempfile
import unittest

from acs.acsdb import AcsDatabase
from acs.cbv_extractor import ExternalCbvExtractorConfig, extract_cbv_external
from acs.chessbase_decoder import ExternalChessBaseDecoderConfig
from acs.chessbase_library_import import ChessBaseLibraryImportService
from acs.game_identity import same_game_tree
from acs.gametree import parse_games
from acs.pgn_service import open_pgn, save_pgn_atomic
from acs.search_service import GameSearchQuery, GameSearchService


LIBCBH_COMMIT = "9641c5c3949d8fb210b17dd9aa54455645843696"
TWIC_1134_EXPECTED_GAMES = 6117


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
        self.small_fixture = Path(
            os.environ.get("UNCBV_SMALL_FIXTURE", os.environ["UNCBV_FIXTURE"])
        )
        self.extractor_config = ExternalCbvExtractorConfig(
            Path(os.environ["UNCBV_BINARY"]),
            expected_backend_sha256=os.environ["UNCBV_BINARY_SHA256"],
            timeout_seconds=300,
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
                self.small_fixture,
                Path(temporary),
                self.extractor_config,
            )
            self.assertEqual(result.backend_name, "uncbv")
            self.assertGreater(result.entry_count, 1)
            self.assertGreater(result.extracted_bytes, 0)
            self.assertEqual(result.primary_path.suffix.lower(), ".cbh")
            self.assertTrue(result.primary_path.is_file())

    def test_real_cbv_to_library_search_export_reopen_and_acsdb_reopen(self) -> None:
        self.assertEqual(self.fixture.name.lower(), "twic1134.cbv")
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            database_path = root / "real-cbv.acsdb"
            database = AcsDatabase(database_path)
            try:
                service = ChessBaseLibraryImportService(
                    database,
                    self.decoder_config,
                    self.extractor_config,
                )
                report = service.import_database(self.fixture)

                self.assertEqual(report.source_format, "cbv")
                self.assertEqual(report.archive_backend_name, "uncbv")
                self.assertEqual(report.decoded_game_count, TWIC_1134_EXPECTED_GAMES)
                self.assertEqual(report.imported_game_count, TWIC_1134_EXPECTED_GAMES)
                self.assertIsNotNone(report.library_result)
                source_id = report.library_result.source_id
                row = database.get_source(source_id)
                self.assertEqual(row["source_format"], "cbv")
                self.assertEqual(row["sha256"], report.source_sha256)

                page = GameSearchService(database).search(GameSearchQuery())
                self.assertGreater(len(page.items), 0)
                stored = database.get_game(page.items[0].game_id)
                canonical = parse_games(stored["pgn_text"])[0]
                export_path = root / "sample-from-real-cbv.pgn"
                save_pgn_atomic(export_path, (canonical,))
                reopened = open_pgn(export_path).games[0]
                self.assertTrue(same_game_tree(canonical, reopened))
            finally:
                database.close()

            reopened_database = AcsDatabase(database_path)
            try:
                row = reopened_database.get_source(source_id)
                self.assertEqual(row["source_format"], "cbv")
                self.assertEqual(row["sha256"], report.source_sha256)
                count = reopened_database.conn.execute(
                    "SELECT COUNT(*) FROM games"
                ).fetchone()[0]
                self.assertEqual(count, TWIC_1134_EXPECTED_GAMES)
            finally:
                reopened_database.close()


if __name__ == "__main__":
    unittest.main()
