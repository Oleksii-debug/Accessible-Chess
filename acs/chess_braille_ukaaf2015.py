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


@dataclass(frozen=True, slots=True)
class UnverifiedUKAAFMove:
    """One narrow algebraic chess-move coding result, not a legal move proof."""
    san: str
    cells: str
    standard: str = STANDARD_ID
    status: str = "UNVERIFIED_REQUIRES_DECISION"
    move_legality_proven: bool = False
    layout_qualified: bool = False


_SIMPLE_SAN_PATTERN = __import__("re").compile(
    r"^(?P<piece>[KQRBN]?)(?P<disamb>(?:[a-h][1-8]?|[1-8])?)"
    r"(?P<capture>x?)(?P<file>[a-h])(?P<rank>[1-8])"
    r"(?P<suffix>[+#]?)$"
)
_GRADE1_FILES = {
    "a": "\u2801", "b": "\u2803", "c": "\u2809", "d": "\u2819",
    "e": "\u2811", "f": "\u280b", "g": "\u281b", "h": "\u2813",
}


def encode_ukaaf2015_simple_san(san: str) -> UnverifiedUKAAFMove:
    """Lexical UKAAF 2015 3.2–3.6 subset; no chess legality is inferred.

    Only the caller's parser-validated SAN tokens may be fed here when used
    for production. Complex SAN (castling, promotion, NAG, game number,
    variations, e.p. markers) requires a separate qualified implementation.
    """
    if type(san) is not str or not 2 <= len(san) <= 12:
        raise BrailleFactoryError("Unsupported bounded chess SAN token")
    match = _SIMPLE_SAN_PATTERN.fullmatch(san)
    if not match:
        raise BrailleFactoryError("SAN notation falls outside proven UKAAF algebraic subset")
    piece = match["piece"]
    disambiguation = match["disamb"]
    capture = match["capture"] == "x"
    destination = match["file"] + match["rank"]
    suffix = match["suffix"]
    if not piece and disambiguation and not capture:
        raise BrailleFactoryError("An unmarked pawn origin would create chess-notation ambiguity")
    if not piece and capture and (
            len(disambiguation) != 1 or disambiguation not in _GRADE1_FILES):
        raise BrailleFactoryError("Pawn captures require one canonical source file")
    if piece and disambiguation:
        if len(disambiguation) > 2 or (
                len(disambiguation) == 2 and
                not (disambiguation[0] in _GRADE1_FILES and disambiguation[1] in "12345678")):
            raise BrailleFactoryError("Piece disambiguation is outside proven code subset")
    if not piece and capture and not disambiguation:
        raise BrailleFactoryError("Pawn capture is missing source-file evidence")
    cells = (_WHITE[piece] if piece else "")
    for char in disambiguation:
        cells += (_GRADE1_FILES[char] if char in _GRADE1_FILES
                  else _LOWER_NUMBERS[char])
    # UKAAF 2015 3.4: capture dots 56, check dots 45, both dots 456;
    # 3.6 permits the same check indicator for a pawn before its target.
    if capture and suffix == "+":
        cells += "\u2838"  # ⠸ dots 456
    elif capture:
        cells += "\u2830"  # ⠰ dots 56
    elif suffix == "+":
        cells += "\u2818"  # ⠘ dots 45
    cells += _GRADE1_FILES[destination[0]] + _LOWER_NUMBERS[destination[1]]
    if suffix == "#":
        cells += "\u281c\u280d"  # ⠜⠍, 2.2 "mate"
    if any(not "\u2800" <= char <= "\u283f" for char in cells):
        raise BrailleFactoryError("Chess algebraic code attempted non-six-dot output")
    return UnverifiedUKAAFMove(san=san, cells=cells)
