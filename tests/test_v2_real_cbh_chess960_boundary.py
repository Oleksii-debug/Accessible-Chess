from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import re
import tempfile
import unittest

from acs.acsdb import AcsDatabase
from acs.chessbase_decoder import (
    ChessBaseDecodeCode,
    ChessBaseDecodeError,
    ExternalChessBaseDecoderConfig,
    decode_chessbase_external,
)
from acs.chessbase_library_import import ChessBaseLibraryImportService
from acs.chesscore import Board


LIBCBH_COMMIT = "9641c5c3949d8fb210b17dd9aa54455645843696"
PRODUCT_AUTHORITY = "4b23c5c5a47835e66f886df8b6705cdb535f6531"
_ALLOWED_FAIL_CLOSED_CODES = {
    ChessBaseDecodeCode.INVALID_GAME,
    ChessBaseDecodeCode.INVALID_MOVE,
}


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


@unittest.skipUnless(_environment_ready(), "pinned real libcbh Chess960 corpus is not configured")
class RealCbhChess960BoundaryTests(unittest.TestCase):
    def test_real_biel_chess960_fails_closed_without_silent_standard_publication(self) -> None:
        fixture = Path(os.environ["LIBCBH_CHESS960_BIEL_DIR"])
        source = fixture / "Chess960Biel.cbh"
        reference = fixture / "Chess960.pgn"
        self.assertTrue(source.is_file())
        self.assertTrue(reference.is_file())

        reference_text = reference.read_text(encoding="utf-8-sig")
        variants = re.findall(r'^\[Variant "([^"]+)"\]\s*$', reference_text, flags=re.MULTILINE)
        fens = re.findall(r'^\[FEN "([^"]+)"\]\s*$', reference_text, flags=re.MULTILINE)
        self.assertGreater(len(variants), 0)
        self.assertEqual(set(variants), {"Chess960"})
        self.assertEqual(len(variants), len(fens))
        self.assertRegex(reference_text, r"\bO-O(?:-O)?\b")

        nonstandard_castling_fens = []
        for fen in fens:
            parts = fen.split()
            self.assertGreaterEqual(len(parts), 4)
            rights = parts[2]
            if rights != "-" and any(ch not in "KQkq" for ch in rights):
                nonstandard_castling_fens.append(fen)
        self.assertGreater(len(nonstandard_castling_fens), 0)

        # The one canonical chess core is intentionally standard-chess-only on
        # this authority.  The real Shredder-FEN variant rights must therefore
        # never be coerced into a standard position.
        with self.assertRaises(ValueError):
            Board(nonstandard_castling_fens[0])

        before_hashes = _family_hashes(fixture)
        decode_outcome: dict[str, object]
        try:
            decoded = decode_chessbase_external(source, _decoder_config())
        except ChessBaseDecodeError as exc:
            self.assertIn(
                exc.code,
                _ALLOWED_FAIL_CLOSED_CODES,
                f"real Chess960 must fail at canonical variant/legality validation, not mechanically: {exc.code}",
            )
            decode_outcome = {
                "kind": "exception",
                "code": exc.code.value,
                "canonical_games": 0,
            }
        else:
            # Warning-only total rejection is also fail-closed.  Any canonical
            # game would be a silent variant-to-standard interpretation because
            # this authority has no Chess960 rules contract.
            self.assertEqual(len(decoded.games), 0, "Chess960 produced canonical standard-chess games")
            self.assertGreater(len(decoded.warnings), 0, "Chess960 rejection lacked loss accounting")
            decode_outcome = {
                "kind": "warnings_no_games",
                "warnings": len(decoded.warnings),
                "canonical_games": 0,
            }

        with tempfile.TemporaryDirectory() as temporary:
            database_path = Path(temporary) / "chess960-boundary.acsdb"
            database = AcsDatabase(database_path)
            try:
                self.assertEqual(_database_counts(database), {
                    "sources": 0,
                    "games": 0,
                    "positions": 0,
                    "import_attempts": 0,
                })
                try:
                    report = ChessBaseLibraryImportService(database, _decoder_config()).import_database(source)
                except ChessBaseDecodeError as exc:
                    self.assertIn(exc.code, _ALLOWED_FAIL_CLOSED_CODES)
                    import_outcome = {"kind": "exception", "code": exc.code.value}
                else:
                    self.assertEqual(report.decoded_game_count, 0)
                    self.assertEqual(report.imported_game_count, 0)
                    self.assertGreater(report.warning_count, 0)
                    import_outcome = {
                        "kind": "no_games_warning",
                        "warnings": report.warning_count,
                    }
                self.assertEqual(_database_counts(database), {
                    "sources": 0,
                    "games": 0,
                    "positions": 0,
                    "import_attempts": 0,
                })
                self.assertEqual(database.conn.execute("PRAGMA quick_check").fetchone()[0], "ok")
            finally:
                database.close()

            reopened = AcsDatabase(database_path)
            try:
                self.assertEqual(_database_counts(reopened), {
                    "sources": 0,
                    "games": 0,
                    "positions": 0,
                    "import_attempts": 0,
                })
                self.assertEqual(reopened.conn.execute("PRAGMA quick_check").fetchone()[0], "ok")
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
            "reference_variant_records": len(variants),
            "reference_fen_records": len(fens),
            "nonstandard_castling_fens": len(nonstandard_castling_fens),
            "reference_contains_castling": True,
            "canonical_board_accepts_first_shredder_fen": False,
            "decode_outcome": decode_outcome,
            "library_import_outcome": import_outcome,
            "library_publication": "NONE",
            "acsdb_reopen": "EMPTY_OK",
            "source_immutable": True,
            "capability_matrix_explicit_chess960_boundary": explicit_boundary,
        }
        print("CBH_CHESS960_BOUNDARY_EVIDENCE=" + json.dumps(evidence, sort_keys=True))

        # Functional behavior may correctly fail closed, but the public format
        # claim must disclose that a real CBH variant is outside the supported
        # canonical rules surface.  Otherwise `.cbh SUPPORTED` overclaims the
        # actual end-product capability.
        self.assertTrue(
            explicit_boundary,
            "CBH capability matrix does not explicitly classify Chess960/Fischer Random as PARTIAL, UNSUPPORTED, or BLOCKED",
        )


if __name__ == "__main__":
    unittest.main()
