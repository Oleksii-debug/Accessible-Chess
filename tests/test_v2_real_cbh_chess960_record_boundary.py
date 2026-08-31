from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest

from acs.acsdb import AcsDatabase
from acs.chessbase_decoder import ExternalChessBaseDecoderConfig, decode_chessbase_external
from acs.chessbase_library_import import (
    ChessBaseLibraryImportService,
    ChessBaseLibraryImportStatus,
    chessbase_family_sha256,
)
from acs.chesscore import Board
from acs.gametree import PgnGame, parse_games


LIBCBH_COMMIT = "9641c5c3949d8fb210b17dd9aa54455645843696"
STACK_BASE = "9d7833d2b4c05c93b37c7cf7139ea63701d7b73b"
UNSUPPORTED_CHESS960_RECORD = 960
EXPECTED_TOTAL = 188
EXPECTED_CHESS960 = 187
EXPECTED_STANDARD = 1
EXPECTED_SOURCE_SHA256 = "f9d4bd56b4d2ed777e226c7003c0569017ef7fc512fc8521ade424696be4f822"
EXPECTED_REFERENCE_SHA256 = "57e3f056f781923a4ce2ae55c034490560eb1c1e00a4bfbf095153543663d8e2"


def _environment_ready() -> bool:
    return all(
        os.environ.get(name)
        for name in (
            "LIBCBH_BRIDGE",
            "LIBCBH_CHESS960_BIEL_DIR",
        )
    )


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _family_hashes(directory: Path) -> dict[str, str]:
    files = sorted(
        path
        for path in directory.iterdir()
        if path.is_file() and path.name.startswith("Chess960Biel.")
    )
    if not files:
        raise AssertionError("pinned Chess960Biel family is missing")
    return {path.name: _sha256(path) for path in files}


def _decoder_config() -> ExternalChessBaseDecoderConfig:
    bridge = Path(os.environ["LIBCBH_BRIDGE"])
    return ExternalChessBaseDecoderConfig(
        bridge,
        expected_backend_commit=LIBCBH_COMMIT,
        timeout_seconds=120,
        library_directory=bridge.parent,
    )


def _normalized_person(value: str | None) -> str:
    if not value:
        return ""
    text = " ".join(value.split())
    if "," not in text:
        return text.casefold()
    last, first = text.split(",", 1)
    return " ".join((first.strip(), last.strip())).casefold()


def _identity(game: PgnGame) -> tuple[str, ...]:
    tags = game.tags
    return (
        tags.get("Event", "").casefold(),
        tags.get("Site", "").casefold(),
        tags.get("Date", ""),
        tags.get("Round", ""),
        tags.get("Board", ""),
        _normalized_person(tags.get("White")),
        _normalized_person(tags.get("Black")),
        tags.get("Result", ""),
    )


def _has_nonstandard_castling_rights(fen: str | None) -> bool:
    if not fen:
        return False
    parts = fen.split()
    if len(parts) < 3:
        return False
    rights = parts[2]
    return rights != "-" and any(ch not in "KQkq" for ch in rights)


def _stored_games(database: AcsDatabase) -> tuple[PgnGame, ...]:
    rows = database.conn.execute("SELECT pgn_text FROM games ORDER BY id").fetchall()
    return tuple(parse_games(str(row[0]))[0] for row in rows)


def _raw_bridge_records(source: Path) -> tuple[dict[str, object], ...]:
    bridge = Path(os.environ["LIBCBH_BRIDGE"])
    completed = subprocess.run(
        [os.fspath(bridge), "--json-v1", os.fspath(source)],
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        timeout=120,
        check=True,
    )
    root = json.loads(completed.stdout.decode("utf-8", errors="strict"))
    if root.get("protocol") != "accessible-chess-libcbh-v1":
        raise AssertionError("unexpected bridge protocol")
    if root.get("backend_commit") != LIBCBH_COMMIT:
        raise AssertionError("unexpected bridge backend commit")
    games = root.get("games")
    if type(games) is not list:
        raise AssertionError("bridge games payload is not a list")
    return tuple(games)


@unittest.skipUnless(_environment_ready(), "pinned real libcbh Chess960 corpus is not configured")
class RealCbhChess960RecordBoundaryTests(unittest.TestCase):
    def test_mixed_real_corpus_imports_standard_and_loses_chess960_explicitly(self) -> None:
        fixture = Path(os.environ["LIBCBH_CHESS960_BIEL_DIR"])
        source = fixture / "Chess960Biel.cbh"
        reference = fixture / "Chess960.pgn"
        self.assertTrue(source.is_file())
        self.assertTrue(reference.is_file())
        self.assertEqual(_sha256(source), EXPECTED_SOURCE_SHA256)
        self.assertEqual(_sha256(reference), EXPECTED_REFERENCE_SHA256)

        reference_games = tuple(parse_games(reference.read_text(encoding="utf-8-sig")))
        chess960_reference = tuple(
            game for game in reference_games if game.tags.get("Variant", "").casefold() == "chess960"
        )
        standard_reference = tuple(
            game for game in reference_games if game.tags.get("Variant", "").casefold() == "standard"
        )
        self.assertEqual(len(reference_games), EXPECTED_TOTAL)
        self.assertEqual(len(chess960_reference), EXPECTED_CHESS960)
        self.assertEqual(len(standard_reference), EXPECTED_STANDARD)
        standard_ids = {_identity(game) for game in standard_reference}
        chess960_ids = {_identity(game) for game in chess960_reference}
        self.assertFalse(standard_ids & chess960_ids)

        shredder_fens = tuple(
            game.tags.get("FEN", "")
            for game in chess960_reference
            if _has_nonstandard_castling_rights(game.tags.get("FEN"))
        )
        self.assertEqual(len(shredder_fens), EXPECTED_CHESS960)
        with self.assertRaises(ValueError):
            Board(shredder_fens[0])

        before_hashes = _family_hashes(fixture)

        # First prove the optional transport boundary itself, independently of
        # the Product decoder projection. Every explicit Chess960 record must
        # become a record-level unsupported loss, while the Standard record is
        # still decoded normally.
        raw_records = _raw_bridge_records(source)
        self.assertEqual(len(raw_records), EXPECTED_TOTAL)
        unsupported_records = tuple(
            record
            for record in raw_records
            if record.get("status") == "skipped"
            and record.get("error_code") == UNSUPPORTED_CHESS960_RECORD
        )
        decoded_records = tuple(record for record in raw_records if record.get("status") == "decoded")
        self.assertEqual(len(unsupported_records), EXPECTED_CHESS960)
        self.assertEqual(len(decoded_records), EXPECTED_STANDARD)
        self.assertTrue(
            all(record.get("reason") == "unsupported_chess960" for record in unsupported_records)
        )
        unsupported_indexes = {int(record["index"]) for record in unsupported_records}
        standard_index = int(decoded_records[0]["index"])
        self.assertEqual(len(unsupported_indexes), EXPECTED_CHESS960)
        self.assertNotIn(standard_index, unsupported_indexes)

        decoded = decode_chessbase_external(source, _decoder_config())
        self.assertEqual(decoded.backend_commit, LIBCBH_COMMIT)
        self.assertEqual(decoded.total_games, EXPECTED_STANDARD)
        self.assertEqual(len(decoded.warnings), EXPECTED_CHESS960)
        self.assertEqual({warning.game_index for warning in decoded.warnings}, unsupported_indexes)
        self.assertTrue(all(warning.code == "backend_record_skipped" for warning in decoded.warnings))
        self.assertTrue(all("code 960" in warning.message for warning in decoded.warnings))
        accepted = decoded.games[0]
        self.assertEqual(accepted.source_index, standard_index)
        self.assertIn(_identity(accepted), standard_ids)
        self.assertNotIn(_identity(accepted), chess960_ids)

        expected_family_digest = chessbase_family_sha256(decoded.source)

        with tempfile.TemporaryDirectory() as temporary:
            database_path = Path(temporary) / "chess960-record-boundary.acsdb"
            database = AcsDatabase(database_path)
            try:
                report = ChessBaseLibraryImportService(database, _decoder_config()).import_database(source)
                self.assertEqual(report.status, ChessBaseLibraryImportStatus.IMPORTED_WITH_WARNINGS)
                self.assertEqual(report.source_format, "cbh")
                self.assertEqual(report.source_name, source.name)
                self.assertEqual(report.source_sha256, expected_family_digest)
                self.assertEqual(report.decoded_game_count, EXPECTED_STANDARD)
                self.assertEqual(report.imported_game_count, EXPECTED_STANDARD)
                self.assertEqual(report.warning_count, EXPECTED_CHESS960)
                self.assertEqual({warning.game_index for warning in report.warnings}, unsupported_indexes)

                source_row = database.conn.execute(
                    "SELECT source_name, source_format, sha256 FROM sources"
                ).fetchone()
                self.assertIsNotNone(source_row)
                self.assertEqual(tuple(source_row), (source.name, "cbh", expected_family_digest))

                game_row = database.conn.execute(
                    "SELECT source_index, import_status FROM games"
                ).fetchone()
                self.assertIsNotNone(game_row)
                self.assertEqual(int(game_row[0]), standard_index)
                self.assertEqual(str(game_row[1]), "warning")

                attempt = database.conn.execute(
                    "SELECT status, game_count, warning_count FROM import_attempts"
                ).fetchone()
                self.assertIsNotNone(attempt)
                self.assertEqual(tuple(attempt), ("warning", EXPECTED_STANDARD, EXPECTED_CHESS960))

                stored_games = _stored_games(database)
                self.assertEqual(len(stored_games), EXPECTED_STANDARD)
                self.assertIn(_identity(stored_games[0]), standard_ids)
                self.assertNotIn(_identity(stored_games[0]), chess960_ids)
                self.assertEqual(database.conn.execute("PRAGMA quick_check").fetchone()[0], "ok")
                self.assertEqual(database.conn.execute("PRAGMA foreign_key_check").fetchall(), [])
            finally:
                database.close()

            reopened = AcsDatabase(database_path)
            try:
                self.assertEqual(reopened.conn.execute("PRAGMA quick_check").fetchone()[0], "ok")
                self.assertEqual(reopened.conn.execute("PRAGMA foreign_key_check").fetchall(), [])
                self.assertEqual(
                    int(reopened.conn.execute("SELECT COUNT(*) FROM sources").fetchone()[0]),
                    1,
                )
                self.assertEqual(
                    int(reopened.conn.execute("SELECT COUNT(*) FROM games").fetchone()[0]),
                    EXPECTED_STANDARD,
                )
                reopened_game = _stored_games(reopened)[0]
                self.assertIn(_identity(reopened_game), standard_ids)
                self.assertNotIn(_identity(reopened_game), chess960_ids)
            finally:
                reopened.close()

        self.assertEqual(_family_hashes(fixture), before_hashes, "real Chess960 source family mutated")

        matrix_path = (
            Path(__file__).resolve().parents[1]
            / "docs"
            / "automation"
            / "DEV4_CHESSBASE_CAPABILITY_MATRIX.md"
        )
        matrix = matrix_path.read_text(encoding="utf-8").casefold()
        self.assertIn("chess960", matrix)
        self.assertIn("unsupported", matrix)
        self.assertIn("cbv", matrix)

        evidence = {
            "stack_base": STACK_BASE,
            "libcbh_commit": LIBCBH_COMMIT,
            "source_sha256": _sha256(source),
            "reference_pgn_sha256": _sha256(reference),
            "reference_total_records": len(reference_games),
            "reference_standard_records": len(standard_reference),
            "reference_chess960_records": len(chess960_reference),
            "explicit_transport_losses": len(unsupported_records),
            "accepted_standard_records": decoded.total_games,
            "accepted_standard_source_index": accepted.source_index,
            "library_imported_records": EXPECTED_STANDARD,
            "library_warning_count": EXPECTED_CHESS960,
            "source_immutable": True,
            "acsdb_reopen": "PASS",
            "capability_matrix": "Chess960 UNSUPPORTED; CBV inherits CBH boundary",
        }
        print("CBH_CHESS960_RECORD_BOUNDARY_EVIDENCE=" + json.dumps(evidence, sort_keys=True))


if __name__ == "__main__":
    unittest.main()
