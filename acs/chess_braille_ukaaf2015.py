from __future__ import annotations

"""UKAAF 2015 British Braille Chess Code, clause 5.1 Forsyth diagram CELLS.

Based narrowly on the publicly published technical rules and one reference
fixture: https://braillechess.org.uk/wp-content/uploads/2023/08/Braille-Chess-Notation.htm
Copyright of the source guidance remains with UKAAF (2015).

This small serializer covers only the POSITION symbol sequence of 5.1:
six-dot piece abbreviations, dot-6 distinguishing black pieces, lower
numbers for empty squares, and grouping consecutive fully empty ranks.
It does NOT implement chess move annotation, prose contractions, page
layout/cell-7 indentation, complete problems, or embosser qualification.
FEN parsing/validation comes entirely from the existing canonical Board.
"""

from dataclasses import dataclass
from .chesscore import Board
from .chess_braille_factory import BrailleFactoryError

STANDARD_ID = "UKAAF-CHESS-2015-5.1"
_STANDARD_SOURCE = (
    "https://braillechess.org.uk/wp-content/uploads/2023/08/"
    "Braille-Chess-Notation.htm"
)
# UKAAF 2015: abbreviations from 2.1, diagram-specific one-cell pieces in 5.1.
_WHITE = {
    "K": "\u2805",  # ⠅
    "Q": "\u281f",  # ⠟
    "R": "\u2817",  # ⠗
    "B": "\u2807",  # ⠇
    "N": "\u280e",  # ⠎
    "P": "\u280f",  # ⠏
}
# UKAAF 5.1 specifies black as dot 6 added to the same cell.
_PIECES = {**_WHITE, **{k.lower(): chr(ord(v) | 0x20)
                        for k, v in _WHITE.items()}}
_PIECES_REVERSE = {value: key for key, value in _PIECES.items()}
# Lower numbers from UKAAF algebraic/diagram convention (no number sign).
_LOWER_NUMBERS = {
    "0": "\u2834",  # ⠴
    "1": "\u2802",  # ⠂
    "2": "\u2806",  # ⠆
    "3": "\u2812",  # ⠒
    "4": "\u2832",  # ⠲
    "5": "\u2822",  # ⠢
    "6": "\u2816",  # ⠖
    "7": "\u2836",  # ⠶
    "8": "\u2826",  # ⠦
    "9": "\u2814",  # ⠔
}
_LOWER_REVERSE = {value: key for key, value in _LOWER_NUMBERS.items()}


@dataclass(frozen=True, slots=True)
class UnverifiedUKAAFDiagram:
    position_cells: str
    canonical_fen: str
    placement: str
    standard: str = STANDARD_ID
    source_url: str = _STANDARD_SOURCE
    status: str = "UNVERIFIED_REQUIRES_DECISION"
    layout_qualified: bool = False
    tactile_qualified: bool = False


def _lower_number(number: int) -> str:
    if type(number) is not int or not 1 <= number <= 64:
        raise BrailleFactoryError("Empty diagram group must span 1 to 64 squares")
    return "".join(_LOWER_NUMBERS[d] for d in str(number))


def decode_ukaaf2015_position_cells(cells: str) -> str:
    """Independent placement-only parser to prove exact 64-square roundtrip.

    This cannot assert a position is legal, identify the side to move, or
    certify full UKAAF 2015 layout. Board remains authoritative for legality.
    """
    if type(cells) is not str or not 0 < len(cells) <= 200:
        raise BrailleFactoryError("UKAAF diagram cell stream is missing/oversized")
    expanded: list[str] = []
    if cells.startswith(" ") or cells.endswith(" ") or "  " in cells:
        raise BrailleFactoryError("UKAAF diagram contains ambiguous rank separators")
    for group in cells.split(" "):
        digits = ""
        for cell in group:
            if cell in _LOWER_REVERSE:
                digits += _LOWER_REVERSE[cell]
                continue
            if digits:
                if digits[0] == "0":
                    raise BrailleFactoryError("Invalid leading zero in UKAAF empty group")
                count = int(digits)
                if count > 64 - len(expanded):
                    raise BrailleFactoryError("UKAAF diagram has more than 64 squares")
                expanded.extend("." for _ in range(count))
                digits = ""
            piece = _PIECES_REVERSE.get(cell)
            if piece is None:
                raise BrailleFactoryError("Unsupported chess diagram Braille cell")
            expanded.append(piece)
            if len(expanded) > 64:
                raise BrailleFactoryError("UKAAF diagram has more than 64 squares")
        if digits:
            if digits[0] == "0":
                raise BrailleFactoryError("Invalid leading zero in UKAAF empty group")
            count = int(digits)
            if count > 64 - len(expanded):
                raise BrailleFactoryError("UKAAF diagram has more than 64 squares")
            expanded.extend("." for _ in range(count))
    if len(expanded) != 64:
        raise BrailleFactoryError("UKAAF diagram is not a full 8x8 position")
    ranks: list[str] = []
    for offset in range(0, 64, 8):
        row = ""
        blanks = 0
        for char in expanded[offset:offset + 8]:
            if char == ".":
                blanks += 1
            else:
                if blanks:
                    row += str(blanks)
                    blanks = 0
                row += char
        if blanks:
            row += str(blanks)
        ranks.append(row)
    return "/".join(ranks)


def encode_ukaaf2015_position(fen: str) -> UnverifiedUKAAFDiagram:
    """Render six-dot UKAAF 2015 5.1 position and verify decoded placement."""
    if type(fen) is not str:
        raise BrailleFactoryError("Canonical chess FEN string is required")
    board = Board(fen)
    canonical = board.fen()
    placement = canonical.split(" ", 1)[0]
    ranks = placement.split("/")
    if len(ranks) != 8:
        raise BrailleFactoryError("Canonical Board did not provide exactly eight ranks")
    tokens: list[str] = []
    consecutive_empty_ranks = 0
    for rank in ranks:
        if rank == "8":
            consecutive_empty_ranks += 1
            continue
        if consecutive_empty_ranks:
            tokens.append(_lower_number(consecutive_empty_ranks * 8))
            consecutive_empty_ranks = 0
        rendered: list[str] = []
        for char in rank:
            if char.isdigit():
                rendered.append(_lower_number(int(char)))
            elif char in _PIECES:
                rendered.append(_PIECES[char])
            else:
                raise BrailleFactoryError("Unexpected canonical Board FEN piece")
        tokens.append("".join(rendered))
    if consecutive_empty_ranks:
        tokens.append(_lower_number(consecutive_empty_ranks * 8))
    encoded = " ".join(tokens)
    if decode_ukaaf2015_position_cells(encoded) != placement:
        raise BrailleFactoryError("UKAAF Forsyth position did not round-trip")
    return UnverifiedUKAAFDiagram(
        position_cells=encoded, canonical_fen=canonical, placement=placement,
    )
