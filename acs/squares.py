from __future__ import annotations

from collections.abc import Iterator


FILES = "abcdefgh"
RANKS = "12345678"
SQUARE_COUNT = 64


def square_name(index: int) -> str:
    """Return the canonical algebraic name for a zero-based square index."""

    if not isinstance(index, int) or isinstance(index, bool) or not 0 <= index < SQUARE_COUNT:
        raise ValueError("square index must be an integer in 0..63")
    return FILES[index % 8] + RANKS[index // 8]


def parse_square(value: str | int) -> int:
    """Parse one canonical square without attaching command semantics.

    The function deliberately knows nothing about moves, pointer commands,
    annotations, focus, or presentation. Those command families may share the
    same square identity without sharing behavior.
    """

    if isinstance(value, int) and not isinstance(value, bool):
        if 0 <= value < SQUARE_COUNT:
            return value
        raise ValueError("square index must be in 0..63")

    if not isinstance(value, str):
        raise ValueError("square must be canonical text or an integer in 0..63")
    text = value.strip().lower()
    if len(text) != 2 or text[0] not in FILES or text[1] not in RANKS:
        raise ValueError(f"invalid square: {value!r}")
    return (int(text[1]) - 1) * 8 + FILES.index(text[0])


def normalize_square(value: str | int) -> str:
    """Return the canonical lowercase algebraic form of a square value."""

    return square_name(parse_square(value))


def iter_square_names() -> Iterator[str]:
    """Yield all canonical square names in stable a1..h8 board order."""

    for index in range(SQUARE_COUNT):
        yield square_name(index)
