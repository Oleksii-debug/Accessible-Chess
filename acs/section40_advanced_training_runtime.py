"""Production offline 2200+ Books/Training material through canonical chess rules.

The source is the byte-pinned original Lichess CC0 subset embedded in the
product Python package (not an external tests/ path or a sidecar provider).
"""
from __future__ import annotations

from .bookdocument import BookDocument, Exercise, Heading, Paragraph
from .chesscore import Board, parse_sq
from .section40_advanced_licensed_dataset import bundled_advanced_puzzles
from .section40_extreme_licensed_dataset import bundled_extreme_puzzles


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


def build_advanced_offline_material(*, language: str = "uk") -> tuple[BookDocument, tuple[dict, ...]]:
    """Publish ONLY 16 real qualified puzzle positions into existing BookDocument."""
    if type(language) is not str or language not in ("uk", "en"):
        raise ValueError("advanced material language must be uk or en")
    blocks = [
        Heading(
            text=("Advanced Lichess tactics 2200+" if language == "en"
                  else "Складна тактика Lichess 2200+"),
            level=1, block_id="section40-advanced-heading",
            source_anchor="section40:advanced:heading",
        ),
        Paragraph(
            text=(
                "16 authentic CC0 advanced chess puzzles. The previous opponent "
                "move has already been applied to the board. A 2200+ Lichess "
                "PUZZLE rating is not FIDE Elo or a chess title. Try the "
                "calculation before revealing the correct line."
                if language == "en" else
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
            text=f"{'Puzzle' if language == 'en' else 'Задача'} {i:02d}. {', '.join(themes[:3])} — Lichess {rating}",
            level=2, block_id=f"section40-advanced-{pid}-heading",
            source_anchor=f"section40:advanced:{pid}:heading",
        ))
        blocks.append(Exercise(
            fen=solver_fen,
            prompt=(f"Find the best move and calculate the continuation. Themes: {', '.join(themes)}."
                    if language == "en" else
                    f"Знайдіть найкращий хід і розрахуйте варіант. Теми: {', '.join(themes)}."),
            answer_text=answer,
            difficulty=f"Lichess puzzle {rating} ({'not FIDE' if language == 'en' else 'не FIDE'})",
            block_id=f"section40-advanced-{pid}-exercise",
            source_anchor=f"section40:advanced:{pid}:exercise",
        ))
    document = BookDocument(
        title=("16 authentic advanced Lichess chess puzzles (2200+, not FIDE)"
               if language == "en" else
               "16 справжніх складних тактичних задач Lichess (2200+, не FIDE)"),
        language=language,
        author="Lichess original CC0 contributors",
        source_name="https://github.com/mcognetta/lichess-combined-puzzle-game-db",
        source_rights="CC0-1.0; verified original Lichess source and rating qualification",
        blocks=blocks,
    )
    document.as_dict()
    return document, tuple(tasks)



EXTREME_MATERIAL_ID = "extreme-lichess-4-3000-plus"
EXTREME_BOOK_KEY = "section40:extreme-lichess-4-original"


def build_extreme_offline_material(*, language: str = "uk") -> tuple[BookDocument, tuple[dict, ...]]:
    """Separate advanced expert curriculum from beginner and FIDE categories.

    This is exactly 4 historical genuine original CC0 puzzle rows, not GM
    titles, not composer studies, and not substitute for publisher content.
    """
    if type(language) is not str or language not in ("uk", "en"):
        raise ValueError("extreme material language must be uk or en")
    blocks = [
        Heading(text=("Extreme Lichess puzzles 3000–3166" if language == "en"
                      else "Екстремальні задачі Lichess 3000–3166"),
                level=1, block_id="section40-extreme-heading",
                source_anchor="section40:extreme:heading"),
        Paragraph(text=(
            "Four authentic Lichess CC0 puzzles with ratings 3000–3166. "
            "These are puzzle difficulty ratings, not FIDE Elo, FIDE titles or "
            "composer studies. Calculate the line after the previous opponent move."
            if language == "en" else
            "Чотири дійсні шахові позиції з історичного CC0-корпусу Lichess. "
            "3000–3166 — рейтинг складності задач на Lichess, не FIDE Elo. "
            "Знайдіть продовження ПІСЛЯ вказаного в джерелі ходу суперника. "
            "Це не є етюди з установленим автором, не підтвердження рівня GM."
        ), block_id="section40-extreme-intro",
           source_anchor="section40:extreme:intro"),
    ]
    tasks = []
    seen = set()
    for index, puzzle in enumerate(bundled_extreme_puzzles(), 1):
        if type(puzzle) is not dict:
            raise ValueError("extreme real puzzle record invalid")
        ident = puzzle.get("puzzle_id")
        rating = puzzle.get("puzzle_rating")
        if (type(ident) is not str or not 5 <= len(ident) <= 8
            or not ident.isalnum() or ident in seen
            or type(rating) is not int or not 3000 <= rating <= 5000
            or puzzle.get("composed_study") is not False
            or puzzle.get("requires_opponent_first_move_before_presenting") is not True
            or type(puzzle.get("uci_moves_opponent_first")) is not str):
            raise ValueError("extreme real puzzle source provenance invalid")
        seen.add(ident)
        moves = puzzle["uci_moves_opponent_first"].split()
        if not 2 <= len(moves) <= 128:
            raise ValueError("extreme real puzzle has invalid solution length")
        board = Board(puzzle["fen_before_opponent_move"])
        _apply_uci(board, moves[0])
        fen = board.fen()
        answer = moves[1]
        for move in moves[1:]:
            _apply_uci(board, move)
        tasks.append({
            "puzzle_id": ident,
            "puzzle_rating_lichess_not_fide": rating,
            "themes": ["extreme", "calculation"],
            "fen": fen,
            "answer_uci": answer,
            "full_solution_uci": moves[1:],
            "source_opponent_move_uci": moves[0],
            "source_id": "lichess_cc0_extreme_4_original_derived_puzzles",
            "historical_original_line": puzzle["original_upstream_zero_based_line"],
        })
        blocks.append(Heading(
            text=f"{'Extreme puzzle' if language == 'en' else 'Екстремальна задача'} {index:02d}. Lichess {rating}",
            level=2,
            block_id=f"section40-extreme-{ident}-heading",
            source_anchor=f"section40:extreme:{ident}:heading",
        ))
        blocks.append(Exercise(
            fen=fen,
            prompt=("Find the best move, full line and opponent's defences."
                    if language == "en" else
                    "Знайдіть найкращий хід, повний варіант та захист суперника."),
            answer_text=answer,
            difficulty=f"Lichess puzzle {rating} ({'not FIDE' if language == 'en' else 'не FIDE'})",
            block_id=f"section40-extreme-{ident}-exercise",
            source_anchor=f"section40:extreme:{ident}:exercise",
        ))
    document = BookDocument(
        title=("Extreme Lichess chess puzzles: 3000–3166 (not FIDE)"
               if language == "en" else
               "Екстремальні шахові задачі: 3000–3166 Lichess (не FIDE)"),
        language=language,
        author="Lichess original CC0 puzzle contributors",
        source_name="https://github.com/FeXd/puzzle-chess",
        source_rights="CC0-1.0 original chess puzzle data; not FeXd GPL code",
        blocks=blocks,
    )
    document.as_dict()
    return document, tuple(tasks)


__all__ = ["ADVANCED_MATERIAL_ID", "ADVANCED_BOOK_KEY", "EXTREME_MATERIAL_ID", "EXTREME_BOOK_KEY", "build_advanced_offline_material", "build_extreme_offline_material"]
