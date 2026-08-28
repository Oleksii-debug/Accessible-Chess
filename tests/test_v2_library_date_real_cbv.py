from __future__ import annotations

import os
from pathlib import Path
import tempfile
import unittest

from acs.acsdb import ACSDB_SCHEMA_VERSION, AcsDatabase
from acs.cbv_extractor import ExternalCbvExtractorConfig
from acs.chessbase_decoder import ExternalChessBaseDecoderConfig
from acs.chessbase_library_import import ChessBaseLibraryImportService
from acs.search_policy import search_date_key
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
    "real pinned TWIC CBV/libcbh environment is not configured",
)
class V2LibraryDateRealCbvTests(unittest.TestCase):
    def test_real_twic_cbv_import_search_reopen_and_integrity(self) -> None:
        fixture = Path(os.environ["UNCBV_FIXTURE"])
        self.assertEqual(fixture.name.lower(), "twic1134.cbv")
        extractor_config = ExternalCbvExtractorConfig(
            Path(os.environ["UNCBV_BINARY"]),
            expected_backend_sha256=os.environ["UNCBV_BINARY_SHA256"],
            timeout_seconds=300,
            max_source_bytes=64 * 1024 * 1024,
            max_extracted_bytes=256 * 1024 * 1024,
        )
        decoder_config = ExternalChessBaseDecoderConfig(
            Path(os.environ["LIBCBH_BRIDGE"]),
            expected_backend_commit=LIBCBH_COMMIT,
            timeout_seconds=120,
            library_directory=Path(os.environ["LIBCBH_BRIDGE"]).parent,
        )

        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "twic1134-date-search.acsdb"
            with AcsDatabase(path) as database:
                self.assertEqual(database.schema_version, ACSDB_SCHEMA_VERSION)
                report = ChessBaseLibraryImportService(
                    database,
                    decoder_config,
                    extractor_config,
                ).import_database(fixture)
                self.assertEqual(report.decoded_game_count, TWIC_1134_EXPECTED_GAMES)
                self.assertEqual(report.imported_game_count, TWIC_1134_EXPECTED_GAMES)

                dated_rows = database.conn.execute(
                    "SELECT id, game_date FROM games WHERE game_date IS NOT NULL ORDER BY id"
                ).fetchall()
                complete = [
                    (int(row["id"]), str(row["game_date"]), search_date_key(row["game_date"]))
                    for row in dated_rows
                    if search_date_key(row["game_date"]) is not None
                ]
                self.assertGreater(len(complete), 0)
                first_id, first_raw_date, first_key = complete[0]
                assert first_key is not None
                last_key = complete[-1][2]
                assert last_key is not None

                exact_ids = [
                    row["id"] for row in database.search_games(game_date=first_raw_date)
                ]
                self.assertIn(first_id, exact_ids)

                range_rows = database.search_games(
                    date_from=min(first_key, last_key),
                    date_to=max(first_key, last_key),
                    limit=1000,
                )
                self.assertGreater(len(range_rows), 0)
                self.assertTrue(
                    all(search_date_key(row["game_date"]) is not None for row in range_rows)
                )

                service = GameSearchService(database)
                service_page = service.search(
                    GameSearchQuery(
                        date_from=min(first_key, last_key),
                        date_to=max(first_key, last_key),
                        limit=50,
                    )
                )
                self.assertGreater(len(service_page.items), 0)
                self.assertEqual(database.verify_integrity(), ACSDB_SCHEMA_VERSION)
                source_id = report.library_result.source_id
                source_sha256 = database.get_source(source_id)["sha256"]

            with AcsDatabase(path) as reopened:
                self.assertEqual(reopened.schema_version, ACSDB_SCHEMA_VERSION)
                self.assertEqual(reopened.verify_integrity(), ACSDB_SCHEMA_VERSION)
                self.assertEqual(
                    reopened.get_source(source_id)["sha256"],
                    source_sha256,
                )
                self.assertGreater(
                    len(
                        reopened.search_games(
                            date_from=min(first_key, last_key),
                            date_to=max(first_key, last_key),
                            limit=100,
                        )
                    ),
                    0,
                )


if __name__ == "__main__":
    unittest.main()
