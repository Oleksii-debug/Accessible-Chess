from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import tempfile
import unittest

from acs.acsdb import AcsDatabase
from acs.chessbase_decoder import (
    ChessBaseDecodeError,
    ExternalChessBaseDecoderConfig,
    decode_chessbase_external,
)
from acs.chessbase_library_import import ChessBaseLibraryImportService
from acs.chesscore import Board
from acs.gametree import PgnGame, parse_games


LIBCBH_COMMIT = "9641c5c3949d8fb210b17dd9aa54455645843696"
PRODUCT_AUTHORITY = "575ec0088982d2f90adb47c040a5714d68186b0e"


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


def _database_counts(database: AcsDatabase) -> dict[str, int]:
    return {
        table: int(database.conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0])
        for table in ("sources", "games", "positions", "import_attempts")
    }


def _decoder_config() -> ExternalChessBaseDecoderConfig:
    bridge = Path(os.environ["LIBCBH_BRIDGE"])
    return ExternalChessBaseDecoderConfig(
        bridge,
        expected_backend_commit=LIBCBH_COMMIT,
        timeout_seconds=120,
        library_directory=bridge.parent,
    )


def _matrix_has_explicit_chess960_boundary(matrix: str) -> bool:
    lines = matrix.splitlines()
    for index, line in enumerate(lines):
        lowered = line.casefold()
        if "chess960" not in lowered and "fischer random" not in lowered:
            continue
        window = "\n".join(lines[max(0, index - 2) : index + 3])
        if any(status in window for status in ("PARTIAL", "UNSUPPORTED", "BLOCKED")):
            return True
    return False


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


def _variant_of(game: PgnGame, chess960_ids: set[tuple[str, ...]], standard_ids: set[tuple[str, ...]]) -> str:
    tag = game.tags.get("Variant", "").strip().casefold()
    if tag == "chess960":
        return "chess960"
    if tag == "standard":
        return "standard"
    if _has_nonstandard_castling_rights(game.tags.get("FEN")):
        return "chess960"
    identity = _identity(game)
    in_960 = identity in chess960_ids
    in_standard = identity in standard_ids
    if in_960 and not in_standard:
        return "chess960"
    if in_standard and not in_960:
        return "standard"
    return "unknown"


def _stored_games(database: AcsDatabase) -> tuple[PgnGame, ...]:
    rows = database.conn.execute("SELECT pgn_text FROM games ORDER BY id").fetchall()
    return tuple(parse_games(str(row[0]))[0] for row in rows)


@unittest.skipUnless(_environment_ready(), "pinned real libcbh Chess960 corpus is not configured")
class RealCbhChess960BoundaryTests(unittest.TestCase):
    def test_real_biel_mixed_corpus_never_silently_publishes_chess960_as_standard(self) -> None:
        fixture = Path(os.environ["LIBCBH_CHESS960_BIEL_DIR"])
        source = fixture / "Chess960Biel.cbh"
        reference = fixture / "Chess960.pgn"
        self.assertTrue(source.is_file())
        self.assertTrue(reference.is_file())

        reference_games = tuple(parse_games(reference.read_text(encoding="utf-8-sig")))
        self.assertGreater(len(reference_games), 0)
        chess960_reference = tuple(
            game for game in reference_games if game.tags.get("Variant", "").casefold() == "chess960"
        )
        standard_reference = tuple(
            game for game in reference_games if game.tags.get("Variant", "").casefold() == "standard"
        )
        self.assertGreater(len(chess960_reference), 0)
        self.assertGreater(len(standard_reference), 0)
        self.assertEqual(len(chess960_reference) + len(standard_reference), len(reference_games))

        chess960_ids = {_identity(game) for game in chess960_reference}
        standard_ids = {_identity(game) for game in standard_reference}
        self.assertFalse(chess960_ids & standard_ids, "reference identity key is not variant-discriminating")

        shredder_fens = tuple(
            game.tags.get("FEN", "")
            for game in chess960_reference
            if _has_nonstandard_castling_rights(game.tags.get("FEN"))
        )
        self.assertGreater(len(shredder_fens), 0)
        self.assertTrue(
            any(
                move.san in {"O-O", "O-O-O"}
                for game in chess960_reference
                for move in game.line.moves
            ),
            "real Chess960 reference lacks a mainline castling move",
        )

        # The single canonical chess core on this authority is standard-only.
        # Shredder-FEN rights therefore must not be coerced into a standard game.
        with self.assertRaises(ValueError):
            Board(shredder_fens[0])

        before_hashes = _family_hashes(fixture)
        decoded_games: tuple[PgnGame, ...] = ()
        decoded_warning_count = 0
        decode_outcome: dict[str, object]
        try:
            decoded = decode_chessbase_external(source, _decoder_config())
        except ChessBaseDecodeError as exc:
            decode_outcome = {
                "kind": "exception",
                "code": exc.code.value,
                "canonical_games": 0,
            }
        else:
            decoded_games = tuple(decoded.games)
            decoded_warning_count = len(decoded.warnings)
            decoded_variants = [
                _variant_of(game, chess960_ids, standard_ids) for game in decoded_games
            ]
            decoded_chess960 = decoded_variants.count("chess960")
            decoded_unknown = decoded_variants.count("unknown")
            self.assertEqual(decoded_unknown, 0, "decoder produced games not traceable to the real reference")
            self.assertEqual(
                decoded_chess960,
                0,
                "unsupported Chess960 records were accepted into the standard canonical rules surface",
            )
            self.assertLessEqual(len(decoded_games), len(standard_reference))
            if len(decoded_games) < len(reference_games):
                self.assertGreater(
                    decoded_warning_count,
                    0,
                    "variant loss was not represented by decoder warnings",
                )
            decode_outcome = {
                "kind": "partial_or_standard_subset",
                "canonical_games": len(decoded_games),
                "warnings": decoded_warning_count,
                "decoded_standard_records": decoded_variants.count("standard"),
                "decoded_chess960_records": decoded_chess960,
            }

        with tempfile.TemporaryDirectory() as temporary:
            database_path = Path(temporary) / "chess960-boundary.acsdb"
            database = AcsDatabase(database_path)
            try:
                initial_counts = _database_counts(database)
                self.assertEqual(initial_counts, {
                    "sources": 0,
                    "games": 0,
                    "positions": 0,
                    "import_attempts": 0,
                })
                try:
                    report = ChessBaseLibraryImportService(database, _decoder_config()).import_database(source)
                except ChessBaseDecodeError as exc:
                    import_outcome = {"kind": "exception", "code": exc.code.value}
                    self.assertEqual(_database_counts(database), initial_counts)
                    stored_games: tuple[PgnGame, ...] = ()
                else:
                    self.assertEqual(report.decoded_game_count, len(decoded_games))
                    self.assertEqual(report.imported_game_count, len(decoded_games))
                    if len(decoded_games) < len(reference_games):
                        self.assertGreater(report.warning_count, 0)
                    stored_games = _stored_games(database)
                    self.assertEqual(len(stored_games), len(decoded_games))
                    stored_variants = [
                        _variant_of(game, chess960_ids, standard_ids) for game in stored_games
                    ]
                    self.assertEqual(stored_variants.count("unknown"), 0)
                    self.assertEqual(
                        stored_variants.count("chess960"),
                        0,
                        "Library contains an unsupported Chess960 record as canonical standard chess",
                    )
                    import_outcome = {
                        "kind": "partial_or_standard_subset",
                        "decoded": report.decoded_game_count,
                        "imported": report.imported_game_count,
                        "warnings": report.warning_count,
                        "stored_chess960_records": stored_variants.count("chess960"),
                    }
                self.assertEqual(database.conn.execute("PRAGMA quick_check").fetchone()[0], "ok")
                self.assertEqual(database.conn.execute("PRAGMA foreign_key_check").fetchall(), [])
                published_counts = _database_counts(database)
            finally:
                database.close()

            reopened = AcsDatabase(database_path)
            try:
                self.assertEqual(reopened.conn.execute("PRAGMA quick_check").fetchone()[0], "ok")
                self.assertEqual(reopened.conn.execute("PRAGMA foreign_key_check").fetchall(), [])
                self.assertEqual(_database_counts(reopened), published_counts)
                reopened_games = _stored_games(reopened)
                reopened_variants = [
                    _variant_of(game, chess960_ids, standard_ids) for game in reopened_games
                ]
                self.assertEqual(reopened_variants.count("unknown"), 0)
                self.assertEqual(reopened_variants.count("chess960"), 0)
            finally:
                reopened.close()

        after_hashes = _family_hashes(fixture)
        self.assertEqual(after_hashes, before_hashes, "real Chess960 source family mutated")

        matrix_path = Path(__file__).resolve().parents[1] / "docs" / "automation" / "DEV4_CHESSBASE_CAPABILITY_MATRIX.md"
        matrix = matrix_path.read_text(encoding="utf-8")
        explicit_boundary = _matrix_has_explicit_chess960_boundary(matrix)

        evidence = {
            "product_authority": PRODUCT_AUTHORITY,
            "libcbh_commit": LIBCBH_COMMIT,
            "source_sha256": _sha256(source),
            "reference_pgn_sha256": _sha256(reference),
            "reference_total_records": len(reference_games),
            "reference_standard_records": len(standard_reference),
            "reference_chess960_records": len(chess960_reference),
            "nonstandard_castling_fens": len(shredder_fens),
            "canonical_board_accepts_first_shredder_fen": False,
            "decode_outcome": decode_outcome,
            "library_import_outcome": import_outcome,
            "acsdb_counts": published_counts,
            "acsdb_reopen": "PASS",
            "source_immutable": True,
            "capability_matrix_explicit_chess960_boundary": explicit_boundary,
        }
        print("CBH_CHESS960_BOUNDARY_EVIDENCE=" + json.dumps(evidence, sort_keys=True))

        # Functional fail-closed behavior is not enough for a broad `.cbh`
        # support claim: unsupported real variants must be disclosed explicitly.
        self.assertTrue(
            explicit_boundary,
            "CBH capability matrix does not explicitly classify Chess960/Fischer Random as PARTIAL, UNSUPPORTED, or BLOCKED",
        )


if __name__ == "__main__":
    unittest.main()
