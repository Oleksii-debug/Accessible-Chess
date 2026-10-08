"""Derive portable master-track PGN from 20 verified-source Lichess CC0 puzzles.

Import/export *only* through existing canonical chesscore + gametree. The PGN
is derivative practice data, not the original annotator's PGN, not a FIDE
master rating statement and not a copyrighted chess book download.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

from acs.chesscore import Board, parse_sq
from acs.gametree import MoveNode, PgnGame, VariationLine, serialize_game
from acs.pgn_roundtrip import parse_pgn_text
from acs.section40_advanced_licensed_dataset import SOURCE_SHA256 as ADVANCED_SHA
from acs.section40_extreme_licensed_dataset import SOURCE_SHA256 as EXTREME_SHA
from acs.section40_advanced_training_runtime import (
    build_advanced_offline_material, build_extreme_offline_material,
)

OUTPUT_NAME = "advanced-cc0-20-master-puzzles.pgn"
MANIFEST_NAME = "advanced-cc0-20-master-puzzles-manifest.json"


class AdvancedPuzzlePgnError(ValueError):
    """Bounded refusal for malformed or unqualified advanced puzzle game."""


def _move(board: Board, uci: str) -> MoveNode:
    if type(uci) is not str or len(uci) not in (4, 5):
        raise AdvancedPuzzlePgnError("original advanced puzzle move is invalid")
    if not uci[:4].isascii():
        raise AdvancedPuzzlePgnError("original advanced puzzle UCI is not ASCII")
    try:
        frm, to = parse_sq(uci[:2]), parse_sq(uci[2:4])
        promotion = uci[4].upper() if len(uci) == 5 else None
        legal = [m for m in board.legal_moves()
                 if m.frm == frm and m.to == to and m.promotion == promotion]
        if len(legal) != 1:
            raise AdvancedPuzzlePgnError("puzzle continuation is not a legal chess move")
        move = legal[0]
        san = board.san(move)
        board.push(move)
    except AdvancedPuzzlePgnError:
        raise
    except (ValueError, TypeError, IndexError, KeyError) as exc:
        raise AdvancedPuzzlePgnError("puzzle continuation failed canonical chess rules") from exc
    return MoveNode(san=san)


def build_advanced_pgn() -> tuple[bytes, dict[str, object]]:
    """One original 16-puzzle and one original 4-puzzle advanced source family."""
    _, advanced = build_advanced_offline_material()
    _, extreme = build_extreme_offline_material()
    combined = tuple(advanced) + tuple(extreme)
    if len(combined) != 20:
        raise AdvancedPuzzlePgnError("exact 20 authentic advanced puzzles required")
    seen: set[str] = set()
    games: list[PgnGame] = []
    for task in combined:
        ident = task["puzzle_id"]
        fen = task["fen"]
        rating = task["puzzle_rating_lichess_not_fide"]
        solution = task["full_solution_uci"]
        if (type(ident) is not str or not 5 <= len(ident) <= 8
            or not ident.isalnum() or ident in seen
            or type(rating) is not int or not 2200 <= rating <= 5000
            or type(solution) is not list or not 1 <= len(solution) <= 128):
            raise AdvancedPuzzlePgnError("advanced source exercise identity invalid")
        seen.add(ident)
        board = Board(fen)
        nodes = [_move(board, uci) for uci in solution]
        if task["answer_uci"] != solution[0]:
            raise AdvancedPuzzlePgnError("source answer and canonical solution diverged")
        tags = {
            "Event": "Accessible Chess CC0 advanced practice",
            "Site": task.get("source_game_url") or "https://lichess.org/",
            "Result": "*",
            "SetUp": "1",
            "FEN": fen,
            "PuzzleId": ident,
            "PuzzleRating": str(rating),
            "PuzzleRatingSystem": "Lichess-puzzle-NOT-FIDE",
            "SourceId": task["source_id"],
        }
        game = PgnGame(tags=tags, line=VariationLine(moves=nodes, result="*"),
                       source_index=len(games))
        games.append(game)
    pgn = ("\n\n".join(serialize_game(game).rstrip() for game in games) + "\n").encode("utf-8")
    if len(pgn) > 2 * 1024 * 1024:
        raise AdvancedPuzzlePgnError("advanced PGN derivative exceeded source budget")
    reopened = parse_pgn_text(pgn.decode("utf-8"), strict=True)
    if len(reopened) != len(games):
        raise AdvancedPuzzlePgnError("canonical PGN serializer lost source puzzle games")
    for index, (expected, actual) in enumerate(zip(games, reopened, strict=True)):
        if (
            actual.tags.get("FEN") != expected.tags["FEN"]
            or actual.tags.get("PuzzleId") != expected.tags["PuzzleId"]
            or actual.tags.get("PuzzleRating") != expected.tags["PuzzleRating"]
            or [x.san for x in actual.line.moves] != [x.san for x in expected.line.moves]
        ):
            raise AdvancedPuzzlePgnError("canonical PGN roundtrip changed puzzle " + str(index))
    manifest = {
        "schema": "accessible-chess-section38-39-master-puzzle-derivative-v1",
        "kind": "CANONICAL_DERIVED_PGN_NOT_ORIGINAL_CHESS_BOOK",
        "rights": "Lichess CC0 original puzzle data; user training derivative only",
        "source_count": 2,
        "source_ids": [
            "lichess_cc0_advanced_16_original_derived",
            "lichess_cc0_extreme_4_original_derived_puzzles",
        ],
        "source_sha256": [ADVANCED_SHA, EXTREME_SHA],
        "source_original_game_pgn": False,
        "contains_copyrighted_external_books": False,
        "language_independent_move_notation": "PGN-SAN",
        "ukrainian_title": "20 складних шахових задач від рівня КМС: оригінальні дані Lichess",
        "english_title": "20 advanced candidate-master training puzzles from Lichess CC0 data",
        "puzzles": len(games),
        "min_puzzle_rating_lichess_not_fide": min(x["puzzle_rating_lichess_not_fide"] for x in combined),
        "max_puzzle_rating_lichess_not_fide": max(x["puzzle_rating_lichess_not_fide"] for x in combined),
        "original_source_verification": "See immutable licensed Section37 corpus + source-only CI; this receipt is derived source evidence",
        "pgn_file": OUTPUT_NAME,
        "pgn_bytes": len(pgn),
        "pgn_sha256": hashlib.sha256(pgn).hexdigest(),
        "formats": ["PGN", "FEN", "SAN"],
        "application_entry": "existing PGN Open or Library PGN import; Books/Training keep canonical CC0 dataset",
        "section38_terminal_done": False,
        "section39_terminal_done": False,
    }
    return pgn, manifest


def main() -> None:
    """Materialize reproducible, offline, cross-language Windows-importable PGN."""
    destination = Path("_section38_39_advanced_pgn_qa")
    if destination.exists() or destination.is_symlink():
        raise FileExistsError("cannot overwrite an existing owner/source QA output")
    pgn, manifest = build_advanced_pgn()
    destination.mkdir(mode=0o700)
    (destination / OUTPUT_NAME).write_bytes(pgn)
    (destination / MANIFEST_NAME).write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(json.dumps({"source_ids": manifest["source_ids"], "games": manifest["puzzles"],
                      "pgn_sha256": manifest["pgn_sha256"],
                      "terminal_done": False}, sort_keys=True))


if __name__ == "__main__":
    main()
