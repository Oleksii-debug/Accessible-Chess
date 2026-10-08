"""Production offline 2200+ Books/Training material through canonical chess rules.

The source is the byte-pinned original Lichess CC0 subset embedded in the
product Python package (not an external tests/ path or a sidecar provider).
"""
from __future__ import annotations

from .bookdocument import BookDocument, Exercise, Heading, Paragraph
from .chesscore import Board, parse_sq
from .section40_advanced_licensed_dataset import bundled_advanced_puzzles


ADVANCED_MATERIAL_ID = "advanced-lichess-16-original"
ADVANCED_BOOK_KEY = "section40:advanced-lichess-16-original"


def _apply_uci(board: Board, uci: str) -> None:
    if (type(uci) is not str or len(uci) not in (4, 5)
        or not uci[:4].isascii()):
        raise ValueError("invalid original Lichess puzzle move")
    start, end = parse_sq(uci[:2]), parse_sq(uci[2:4])
    promotion = uci[4].upper() if len(uci) == 5 else None
    candidates = tuple(m for m in board.legal_moves()
                       if m.frm == start and m.to == end
                       and m.promotion == promotion)
    if len(candidates) != 1:
        raise ValueError("original Lichess puzzle move fails canonical legal board")
    board.push(candidates[0])


def build_advanced_offline_material() -> tuple[BookDocument, tuple[dict, ...]]:
    """Publish ONLY 16 real qualified puzzle positions into existing BookDocument."""
    blocks = [
        Heading(
            text="Складна тактика Lichess 2200+",
            level=1, block_id="section40-advanced-heading",
            source_anchor="section40:advanced:heading",
        ),
        Paragraph(
            text=(
                "16 автентичних задач CC0 для шахістів від першого розряду. "
                "Показано позицію після попереднього ходу суперника. "
                "Позначення 2200+ — рейтинг СКЛАДНОСТІ задач на Lichess, "
                "це не FIDE Elo, розряд чи звання GM. "
                "Рішення відкривайте після самостійного розрахунку варіанта."
            ), block_id="section40-advanced-intro",
            source_anchor="section40:advanced:intro",
        ),
    ]
    tasks = []
    seen = set()
    puzzles = bundled_advanced_puzzles()
    for i, puzzle in enumerate(puzzles, 1):
        if type(puzzle) is not dict:
            raise ValueError("malformed real advanced material")
        pid, rating = puzzle.get("puzzle_id"), puzzle.get("rating")
        uci_moves = puzzle.get("uci_moves_with_opponent_first")
        themes = puzzle.get("themes")
        if (type(pid) is not str or not 5 <= len(pid) <= 8
            or not pid.isalnum() or pid in seen
            or type(rating) is not int or not 2200 <= rating <= 5000
            or type(uci_moves) is not str
            or type(themes) is not list or not themes
            or any(type(x) is not str or not x for x in themes)):
            raise ValueError("real advanced chess puzzle provenance invalid")
        seen.add(pid)
        moves = uci_moves.split()
        if not 2 <= len(moves) <= 128:
            raise ValueError("malformed real puzzle solution length")
        board = Board(puzzle["fen_before_opponent_move"])
        _apply_uci(board, moves[0])
        solver_fen = board.fen()
        answer = moves[1]
        for move in moves[1:]:
            _apply_uci(board, move)
        tasks.append({
            "puzzle_id": pid,
            "puzzle_rating_lichess_not_fide": rating,
            "themes": themes,
            "fen": solver_fen,
            "answer_uci": answer,
            "full_solution_uci": moves[1:],
            "source_opponent_move_uci": moves[0],
            "source_game_url": puzzle.get("game_url"),
            "source_id": "lichess_cc0_advanced_16_original_derived",
        })
        blocks.append(Heading(
            text=f"Задача {i:02d}. {', '.join(themes[:3])} — Lichess {rating}",
            level=2, block_id=f"section40-advanced-{pid}-heading",
            source_anchor=f"section40:advanced:{pid}:heading",
        ))
        blocks.append(Exercise(
            fen=solver_fen,
            prompt=f"Знайдіть найкращий хід і розрахуйте варіант. Теми: {', '.join(themes)}.",
            answer_text=answer,
            difficulty=f"Lichess puzzle {rating} (не FIDE)",
            block_id=f"section40-advanced-{pid}-exercise",
            source_anchor=f"section40:advanced:{pid}:exercise",
        ))
    document = BookDocument(
        title="16 справжніх складних тактичних задач Lichess (2200+, не FIDE)",
        language="uk",
        author="Lichess original CC0 contributors",
        source_name="https://github.com/mcognetta/lichess-combined-puzzle-game-db",
        source_rights="CC0-1.0; verified original Lichess source and rating qualification",
        blocks=blocks,
    )
    document.as_dict()
    return document, tuple(tasks)


__all__ = ["ADVANCED_MATERIAL_ID", "ADVANCED_BOOK_KEY", "build_advanced_offline_material"]
