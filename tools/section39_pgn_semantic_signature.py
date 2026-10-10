"""Exact shared Section 39 PGN/Library nested-variation semantic oracle.

Preserved verbatim from protected PR #2494's section39_real_format_qualification.py.
No independent chess parser or game-rules implementation is created here.
"""
from __future__ import annotations

def _pgn_signature(games: tuple) -> tuple:
    """Compare full representable GameTree structure, not only top-level SAN.

    Annotations, language-visible comments, NAG and recursive sibling RAV
    must survive every PGN -> export -> PGN/ACSDB reimport pathway.  Move
    numbering is intentionally omitted as surface notation, not move meaning.
    """
    def comments(values):
        return tuple((c.text, c.style.value) for c in values)

    def line_semantics(line):
        return (
            comments(line.leading_comments),
            tuple(
                (
                    move.san,
                    tuple(move.nags),
                    comments(move.comments_before),
                    comments(move.comments_after),
                    tuple(line_semantics(child) for child in move.variations),
                )
                for move in line.moves
            ),
            comments(line.trailing_comments),
            line.result,
        )

    return tuple(
        (tuple(sorted(game.tags.items())), line_semantics(game.line))
        for game in games
    )
