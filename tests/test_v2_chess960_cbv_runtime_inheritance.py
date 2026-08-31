from __future__ import annotations

from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from acs.acsdb import AcsDatabase
from acs.cbv_extractor import CbvExtraction, ExternalCbvExtractorConfig
from acs.chessbase_decoder import (
    ChessBaseDecodedDatabase,
    ChessBaseDecodeWarning,
    ExternalChessBaseDecoderConfig,
)
from acs.chessbase_integrity import ChessBaseIntegritySnapshot
from acs.chessbase_library_import import (
    ChessBaseLibraryImportService,
    ChessBaseLibraryImportStatus,
)
from acs.gametree import parse_games
from acs.import_contract import fingerprint


LIBCBH_COMMIT = "9641c5c3949d8fb210b17dd9aa54455645843696"


class Chess960CbvRuntimeInheritanceTests(unittest.TestCase):
    def test_cbv_reuses_cbh_record_boundary_but_publishes_original_archive_provenance(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / "mixed-standard-chess960.cbv"
            source.write_bytes(b"synthetic immutable archive bytes")
            source_fingerprint = fingerprint(source)

            standard = parse_games(
                '[Event "Standard"]\n'
                '[Site "Test"]\n'
                '[Date "2026.08.31"]\n'
                '[Round "1"]\n'
                '[White "White"]\n'
                '[Black "Black"]\n'
                '[Result "*"]\n\n'
                '1. e4 *\n'
            )[0]
            standard.source_index = 7
            losses = (
                ChessBaseDecodeWarning(1, "backend_record_skipped", "backend record skipped with code 960"),
                ChessBaseDecodeWarning(4, "backend_record_skipped", "backend record skipped with code 960"),
            )

            decode_inputs: list[Path] = []

            def fake_extract(path, destination, config):
                self.assertEqual(Path(path), source)
                self.assertIsInstance(config, ExternalCbvExtractorConfig)
                primary = Path(destination) / "mixed-standard-chess960.cbh"
                primary.write_bytes(b"extracted cbh family")
                return CbvExtraction(
                    source=source_fingerprint,
                    primary_path=primary,
                    entry_count=3,
                    extracted_bytes=primary.stat().st_size,
                    backend_name="uncbv",
                    backend_sha256="2" * 64,
                )

            def fake_decode(path, config):
                primary = Path(path)
                decode_inputs.append(primary)
                self.assertEqual(primary.suffix.lower(), ".cbh")
                self.assertNotEqual(primary, source)
                self.assertIsInstance(config, ExternalChessBaseDecoderConfig)
                return ChessBaseDecodedDatabase(
                    source=ChessBaseIntegritySnapshot(primary_path=primary, files=()),
                    backend_name="libcbh",
                    backend_commit=LIBCBH_COMMIT,
                    games=(standard,),
                    warnings=losses,
                )

            database = AcsDatabase(":memory:")
            try:
                decoder_config = ExternalChessBaseDecoderConfig(
                    root / "libcbh-json-bridge",
                    expected_backend_commit=LIBCBH_COMMIT,
                )
                extractor_config = ExternalCbvExtractorConfig(
                    root / "uncbv",
                    expected_backend_sha256="1" * 64,
                )
                service = ChessBaseLibraryImportService(
                    database,
                    decoder_config,
                    extractor_config,
                )

                with patch(
                    "acs.chessbase_library_import.extract_cbv_external",
                    side_effect=fake_extract,
                ), patch(
                    "acs.chessbase_library_import.decode_chessbase_external",
                    side_effect=fake_decode,
                ):
                    report = service.import_database(source)

                self.assertEqual(len(decode_inputs), 1)
                self.assertEqual(report.status, ChessBaseLibraryImportStatus.IMPORTED_WITH_WARNINGS)
                self.assertEqual(report.source_format, "cbv")
                self.assertEqual(report.source_name, source.name)
                self.assertEqual(report.source_sha256, source_fingerprint.sha256)
                self.assertEqual(report.archive_backend_name, "uncbv")
                self.assertEqual(report.archive_backend_sha256, "2" * 64)
                self.assertEqual(report.backend_name, "libcbh")
                self.assertEqual(report.backend_commit, LIBCBH_COMMIT)
                self.assertEqual(report.decoded_game_count, 1)
                self.assertEqual(report.imported_game_count, 1)
                self.assertEqual(report.warning_count, 2)
                self.assertEqual(tuple(warning.game_index for warning in report.warnings), (1, 4))

                source_row = database.conn.execute(
                    "SELECT source_name, source_format, sha256 FROM sources"
                ).fetchone()
                self.assertIsNotNone(source_row)
                self.assertEqual(
                    tuple(source_row),
                    (source.name, "cbv", source_fingerprint.sha256),
                )
                game_row = database.conn.execute(
                    "SELECT source_index, import_status FROM games"
                ).fetchone()
                self.assertIsNotNone(game_row)
                self.assertEqual(tuple(game_row), (7, "warning"))
                attempt = database.conn.execute(
                    "SELECT status, game_count, warning_count FROM import_attempts"
                ).fetchone()
                self.assertIsNotNone(attempt)
                self.assertEqual(tuple(attempt), ("warning", 1, 2))
                self.assertEqual(database.conn.execute("PRAGMA quick_check").fetchone()[0], "ok")
            finally:
                database.close()

            self.assertEqual(fingerprint(source), source_fingerprint, "original CBV source mutated")


if __name__ == "__main__":
    unittest.main()
