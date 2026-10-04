from __future__ import annotations

"""Representative structured Diagram/VariationTree starter content for P0-F.

The examples are derived from the already-reviewed, position-specific W3
Training catalogue. They reuse the canonical BookDocument and Board contracts;
no second chess, Books, or Training implementation is introduced.
"""

from dataclasses import dataclass

from .bookdocument import BookDocument, Diagram, Heading, VariationTree
from .chesscore import Board, Move, parse_sq
from .starter_books_training_release import StarterTrainingTask, build_training_task_catalogue


STRUCTURED_EXAMPLE_COUNT = 16
STRUCTURED_EXAMPLE_PLY = 7


@dataclass(frozen=True, slots=True)
class StructuredStarterExample:
    example_id: str
    opening: str
    theme_uk: str
    root_fen: str
    main_san: str
    alternative_san: str
    variation_pgn: str


def _move_key(move: Move) -> tuple[int, int, str, bool, bool]:
    return (move.frm, move.to, move.promotion or "", move.en_passant, move.castle)


def _find_uci_move(board: Board, uci: str) -> Move:
    if len(uci) not in (4, 5):
        raise ValueError(f"invalid curated UCI move: {uci!r}")
    frm = parse_sq(uci[:2])
    to = parse_sq(uci[2:4])
    promotion = uci[4].upper() if len(uci) == 5 else None
    matches = [
        move
        for move in board.legal_moves()
        if move.frm == frm and move.to == to and move.promotion == promotion
    ]
    if len(matches) != 1:
        raise ValueError(f"curated move is not uniquely legal: {uci}")
    return matches[0]


def _san_from_fen(fen: str, move: Move) -> str:
    board = Board(fen)
    for current in board.legal_moves():
        if _move_key(current) == _move_key(move):
            return board.push(current)
    raise ValueError("move is not legal from structured-example root FEN")


def _variation_pgn(task: StarterTrainingTask, main: Move, alternative: Move) -> str:
    fields = task.fen.split()
    side_to_move = fields[1]
    fullmove = int(fields[5])
    if side_to_move == "w":
        prefix = f"{fullmove}."
    else:
        prefix = f"{fullmove}..."
    main_san = _san_from_fen(task.fen, main)
    alternative_san = _san_from_fen(task.fen, alternative)
    return (
        '[SetUp "1"]\n'
        f'[FEN "{task.fen}"]\n'
        '[Result "*"]\n\n'
        f"{prefix} {main_san} ({prefix} {alternative_san}) *"
    )


def build_structured_starter_examples() -> tuple[StructuredStarterExample, ...]:
    """Return one accessible diagram/variation example for each reviewed opening."""

    tasks = [task for task in build_training_task_catalogue() if task.ply == STRUCTURED_EXAMPLE_PLY]
    if len(tasks) != STRUCTURED_EXAMPLE_COUNT:
        raise RuntimeError(
            f"expected {STRUCTURED_EXAMPLE_COUNT} representative starter positions, got {len(tasks)}"
        )

    examples: list[StructuredStarterExample] = []
    for index, task in enumerate(tasks, start=1):
        board = Board(task.fen)
        main = _find_uci_move(board, task.answer_uci)
        alternatives = sorted(
            (move for move in board.legal_moves() if _move_key(move) != _move_key(main)),
            key=_move_key,
        )
        if not alternatives:
            raise RuntimeError(f"structured starter position {task.task_id} has no legal alternative")
        alternative = alternatives[0]
        variation_pgn = _variation_pgn(task, main, alternative)
        examples.append(
            StructuredStarterExample(
                example_id=f"structured-opening-{index:02d}",
                opening=task.opening,
                theme_uk=task.theme_uk,
                root_fen=task.fen,
                main_san=_san_from_fen(task.fen, main),
                alternative_san=_san_from_fen(task.fen, alternative),
                variation_pgn=variation_pgn,
            )
        )
    return tuple(examples)


def build_structured_starter_blocks() -> tuple[object, ...]:
    """Build accessible semantic blocks for the ready-to-open starter course."""

    blocks: list[object] = [
        Heading(
            text="Структуровані діаграми та дерева варіантів",
            level=2,
            block_id="starter-structured-heading",
            source_anchor="starter-structured:heading",
        )
    ]
    for example in build_structured_starter_examples():
        blocks.append(
            Diagram(
                fen=example.root_fen,
                caption=f"{example.opening}: {example.theme_uk}",
                alt_text=(
                    f"Шахова діаграма. {example.opening}. {example.theme_uk}. "
                    f"Позиція у FEN: {example.root_fen}."
                ),
                block_id=f"{example.example_id}-diagram",
                source_anchor=f"starter-structured:{example.example_id}:diagram",
            )
        )
        blocks.append(
            VariationTree(
                root_fen=example.root_fen,
                pgn=example.variation_pgn,
                title=(
                    f"{example.opening}: основний хід {example.main_san}; "
                    f"альтернатива {example.alternative_san}"
                ),
                block_id=f"{example.example_id}-variation",
                source_anchor=f"starter-structured:{example.example_id}:variation",
            )
        )
    return tuple(blocks)


def augment_starter_course(document: BookDocument) -> BookDocument:
    """Append representative structured content to the canonical starter course."""

    document.extend(build_structured_starter_blocks())
    return document


def structured_examples_manifest() -> dict[str, object]:
    examples = build_structured_starter_examples()
    return {
        "schema_version": 1,
        "diagram_count": len(examples),
        "variation_tree_count": len(examples),
        "unique_root_fen_count": len({example.root_fen for example in examples}),
        "accessible_alt_text_count": len(examples),
        "rav_example_count": sum("(" in example.variation_pgn and ")" in example.variation_pgn for example in examples),
        "source": "canonical W3 reviewed opening/training catalogue",
    }


__all__ = [
    "STRUCTURED_EXAMPLE_COUNT",
    "StructuredStarterExample",
    "augment_starter_course",
    "build_structured_starter_blocks",
    "build_structured_starter_examples",
    "structured_examples_manifest",
]
