from __future__ import annotations

"""Runtime adapter from authored starter self-checks to canonical chess Training.

The source corpus intentionally keeps short factual self-check questions beside the
book prose. Canonical Accessible Chess Training, however, accepts chess moves, not
arbitrary quiz strings. This module preserves each authored question and answer in
Books while deriving an explicit, legal one-move keyboard exercise for Training.
"""

from .bookdocument import BookDocument, Exercise, Paragraph
from .starter_books_training_content import build_starter_course


# Every token is a legal SAN move from the canonical starting FEN used by the
# starter corpus. Cycling several moves keeps keyboard practice from degenerating
# into one repeated answer while remaining deterministic and offline.
_STARTER_TRAINING_MOVES: tuple[str, ...] = (
    "e4",
    "d4",
    "Nf3",
    "Nc3",
    "c4",
    "e3",
    "d3",
    "c3",
    "g3",
    "b3",
)


def build_training_ready_starter_course() -> BookDocument:
    """Return the built-in course with all exercises accepted by canonical Training.

    The authoring corpus stores factual answers such as ``64`` or ``так``. Those
    remain visible in an adjacent Book paragraph. The Exercise itself is converted
    to an explicit keyboard move task whose expected answer is legal SAN, matching
    ``book_training``'s one-move contract exactly.
    """

    document = build_starter_course()
    output = []
    exercise_number = 0
    for block in document.blocks:
        if not isinstance(block, Exercise):
            output.append(block)
            continue

        authored_answer = block.answer_text or ""
        move = _STARTER_TRAINING_MOVES[exercise_number % len(_STARTER_TRAINING_MOVES)]
        exercise_number += 1
        block.prompt = (
            f"{block.prompt} Відповідай подумки. "
            f"Потім для клавіатурного закріплення виконай хід {move}."
        )
        block.answer_text = move
        block.solution_pgn = None
        output.append(block)
        output.append(
            Paragraph(
                text=f"Відповідь для самоперевірки: {authored_answer}",
                block_id=f"{block.block_id}-self-check-answer",
                source_anchor=f"{block.source_anchor}:self-check-answer",
            )
        )

    document.blocks = output
    # Force strict semantic rebuilding after authoring-time mutation. A corrupt
    # transformation must fail here instead of reaching Books/Training UI.
    document.as_dict()
    return document


__all__ = ["build_training_ready_starter_course"]
