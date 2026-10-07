from __future__ import annotations

from dataclasses import dataclass, replace
from itertools import islice
import re
from typing import Iterable

from .input_limits import MAX_FEN_CHARS, MAX_SQUARE_TEXT_CHARS
from .squares import FILES, parse_square

VALID_PIECES = frozenset("PNBRQKpnbrqk")
VALID_CASTLING = frozenset("KQkq")
MAX_COORDINATE_POSITION_TOKENS = 64 * 2
MAX_COORDINATE_POSITION_CHARS = 4096
# Direct PositionState construction must never create a counter that cannot be
# represented inside the shared FEN ingress budget. This numeric fence runs
# before decimal rendering, so hostile/accidental huge ints cannot trigger
# Python integer-to-string conversion amplification.
_MAX_FEN_COUNTER_EXCLUSIVE = 10 ** MAX_FEN_CHARS
_MAX_SQUARE_DIAGNOSTIC_CHARS = 16
_MAX_PIECE_DIAGNOSTIC_CHARS = 16
_MAX_CASTLING_TEXT_CHARS = 256
_POSITION_SECTIONS_RE = re.compile(
    r"(?is)^\s*W\s*:\s*(?P<white>.*?)\s*\bB\s*:\s*(?P<black>.*?)\s*$"
)
_COORDINATE_TOKEN_RE = re.compile(r"[^,\s]+")


class PositionValidationError(ValueError):
    """Raised when a position/FEN cannot be represented safely."""


@dataclass(frozen=True)
class PositionState:
    """Presentation-neutral editable chess position.

    Squares use canonical algebraic names. The object deliberately does not own
    UI focus, speech, filesystem, or persistence concerns.
    """

    pieces: tuple[str | None, ...]
    turn: str = "w"
    castling: str = "-"
    en_passant: str = "-"
    halfmove: int = 0
    fullmove: int = 1

    def __post_init__(self) -> None:
        if type(self.pieces) is not tuple:
            raise PositionValidationError("pieces must be an immutable tuple")
        if len(self.pieces) != 64:
            raise PositionValidationError("position must contain exactly 64 squares")
        if any(
            piece is not None
            and (type(piece) is not str or piece not in VALID_PIECES)
            for piece in self.pieces
        ):
            raise PositionValidationError("position contains an invalid piece symbol")
        if type(self.turn) is not str or self.turn not in {"w", "b"}:
            raise PositionValidationError("turn must be 'w' or 'b'")
        if type(self.castling) is not str:
            raise PositionValidationError("castling rights must be text")
        if len(self.castling) > _MAX_CASTLING_TEXT_CHARS:
            raise PositionValidationError("castling rights text is too long")
        _validate_castling(self.castling)
        if (
            self.castling != "-"
            and self.castling != _canonical_castling_text(self.castling)
        ):
            raise PositionValidationError(
                "castling rights must use canonical KQkq order"
            )
        if type(self.en_passant) is not str:
            raise PositionValidationError("en-passant square must be text")
        if len(self.en_passant) > MAX_SQUARE_TEXT_CHARS:
            raise PositionValidationError("en-passant square text is too long")
        _validate_en_passant(self.en_passant, self.turn)
        if type(self.halfmove) is not int:
            raise PositionValidationError("halfmove clock must be an integer")
        if type(self.fullmove) is not int:
            raise PositionValidationError("fullmove number must be an integer")
        if self.halfmove < 0:
            raise PositionValidationError("halfmove clock must be non-negative")
        if self.fullmove < 1:
            raise PositionValidationError("fullmove number must be at least 1")
        _counter_text(self.halfmove, label="halfmove clock", minimum=0)
        _counter_text(self.fullmove, label="fullmove number", minimum=1)
        if len(self.to_fen()) > MAX_FEN_CHARS:
            raise PositionValidationError("FEN is too long")

    def piece_at(self, square: str) -> str | None:
        return self.pieces[_square_index(square)]

    def with_piece(self, square: str, piece: str | None) -> "PositionState":
        if piece is not None and (
            type(piece) is not str or piece not in VALID_PIECES
        ):
            # Do not format an untrusted value here: its __repr__ may execute.
            raise PositionValidationError("invalid piece symbol")
        values = list(self.pieces)
        values[_square_index(square)] = piece
        return replace(self, pieces=tuple(values))

    def cleared(self) -> "PositionState":
        return replace(self, pieces=(None,) * 64, castling="-", en_passant="-", halfmove=0)

    def with_turn(self, turn: str) -> "PositionState":
        return replace(self, turn=turn, en_passant="-")

    def with_en_passant(self, square: str) -> "PositionState":
        if type(square) is not str:
            raise PositionValidationError("en-passant square must be text")
        if len(square) > MAX_SQUARE_TEXT_CHARS:
            raise PositionValidationError("en-passant square text is too long")
        normalized = square.strip().lower()
        if normalized == "":
            normalized = "-"
        return replace(self, en_passant=normalized)

    def with_counters(self, halfmove: int, fullmove: int) -> "PositionState":
        if type(halfmove) is not int:
            raise PositionValidationError("halfmove clock must be an integer")
        if type(fullmove) is not int:
            raise PositionValidationError("fullmove number must be an integer")
        return replace(self, halfmove=halfmove, fullmove=fullmove)

    def with_castling(self, rights: Iterable[str] | str) -> "PositionState":
        if type(rights) is str:
            if len(rights) > _MAX_CASTLING_TEXT_CHARS:
                raise PositionValidationError("castling rights text is too long")
            normalized = _normalize_castling(rights)
        elif isinstance(rights, str):
            # A string subclass is scalar input, not a generic iterable. Reject it
            # before any overridable strip/iteration hooks can execute.
            raise PositionValidationError(
                "castling rights must be text or an iterable of text symbols"
            )
        else:
            try:
                iterator = iter(rights)
                values = tuple(islice(iterator, len(VALID_CASTLING) + 1))
            except TypeError as exc:
                raise PositionValidationError(
                    "castling rights must be text or an iterable of text symbols"
                ) from exc
            if len(values) > len(VALID_CASTLING):
                raise PositionValidationError(
                    "castling rights iterable contains too many symbols"
                )
            if any(type(value) is not str for value in values):
                raise PositionValidationError(
                    "castling rights iterable must contain text symbols"
                )
            normalized = _normalize_castling("".join(values))
        return replace(self, castling=normalized)

    def validate_playable(self) -> tuple[str, ...]:
        """Return exact structural problems without mutating the position."""
        problems: list[str] = []
        white_kings = sum(1 for p in self.pieces if p == "K")
        black_kings = sum(1 for p in self.pieces if p == "k")
        if white_kings != 1:
            problems.append(f"white king count must be 1, got {white_kings}")
        if black_kings != 1:
            problems.append(f"black king count must be 1, got {black_kings}")

        for file_index in range(8):
            if self.pieces[file_index] in {"P", "p"}:
                problems.append(f"pawn on invalid first rank at {FILES[file_index]}1")
            top_index = 56 + file_index
            if self.pieces[top_index] in {"P", "p"}:
                problems.append(f"pawn on invalid eighth rank at {FILES[file_index]}8")

        if "K" in self.castling and not (self.piece_at("e1") == "K" and self.piece_at("h1") == "R"):
            problems.append("white kingside castling right inconsistent with e1/h1")
        if "Q" in self.castling and not (self.piece_at("e1") == "K" and self.piece_at("a1") == "R"):
            problems.append("white queenside castling right inconsistent with e1/a1")
        if "k" in self.castling and not (self.piece_at("e8") == "k" and self.piece_at("h8") == "r"):
            problems.append("black kingside castling right inconsistent with e8/h8")
        if "q" in self.castling and not (self.piece_at("e8") == "k" and self.piece_at("a8") == "r"):
            problems.append("black queenside castling right inconsistent with e8/a8")
        return tuple(problems)

    def to_fen(self) -> str:
        ranks: list[str] = []
        for rank_index in range(7, -1, -1):
            empty = 0
            parts: list[str] = []
            for file_index in range(8):
                piece = self.pieces[rank_index * 8 + file_index]
                if piece is None:
                    empty += 1
                else:
                    if empty:
                        parts.append(str(empty))
                        empty = 0
                    parts.append(piece)
            if empty:
                parts.append(str(empty))
            ranks.append("".join(parts))
        halfmove_text = _counter_text(self.halfmove, label="halfmove clock", minimum=0)
        fullmove_text = _counter_text(self.fullmove, label="fullmove number", minimum=1)
        return f"{'/'.join(ranks)} {self.turn} {self.castling} {self.en_passant} {halfmove_text} {fullmove_text}"

    @classmethod
    def from_fen(cls, fen: str) -> "PositionState":
        if type(fen) is not str:
            # Keep FEN ingress passive: no user-defined text subclass may run
            # strip/split/equality hooks before this boundary rejects it.
            raise PositionValidationError("FEN must be text")
        if len(fen) > MAX_FEN_CHARS:
            raise PositionValidationError("FEN is too long")
        text = fen.strip()
        fields = text.split()
        if len(fields) != 6:
            raise PositionValidationError("FEN must contain exactly 6 fields")
        board, turn, castling, en_passant, halfmove_text, fullmove_text = fields
        rank_fields = board.split("/")
        if len(rank_fields) != 8:
            raise PositionValidationError("FEN board must contain exactly 8 ranks")

        pieces: list[str | None] = [None] * 64
        for fen_rank, rank_text in enumerate(rank_fields):
            board_rank = 7 - fen_rank
            file_index = 0
            for token in rank_text:
                # FEN piece-placement counts are ASCII grammar, not a generic
                # Unicode numeral channel. Keep this lexical boundary aligned
                # with canonical Board.set_fen without importing chess legality
                # into the editable PositionState representation.
                if token in "12345678":
                    file_index += ord(token) - ord("0")
                    if file_index > 8:
                        raise PositionValidationError("FEN rank contains more than 8 squares")
                elif token.isdigit():
                    raise PositionValidationError(
                        "FEN empty-square count must use ASCII digits 1..8"
                    )
                elif token in VALID_PIECES:
                    if file_index >= 8:
                        raise PositionValidationError("FEN rank contains more than 8 squares")
                    pieces[board_rank * 8 + file_index] = token
                    file_index += 1
                else:
                    raise PositionValidationError(f"invalid FEN board token: {token!r}")
            if file_index != 8:
                raise PositionValidationError("each FEN rank must expand to exactly 8 squares")

        # Python int() accepts signs and many Unicode decimal digits. FEN does
        # not: canonical Board.set_fen already requires unsigned ASCII decimal
        # counters. Enforce the same lexical contract here while leaving chess
        # legality (kings, checks, move provenance) outside the editor parser.
        for counter, label in (
            (halfmove_text, "halfmove"),
            (fullmove_text, "fullmove"),
        ):
            if not counter.isascii() or not counter.isdecimal():
                raise PositionValidationError(
                    f"FEN {label} counter must be an unsigned ASCII decimal integer"
                )
        try:
            halfmove = int(halfmove_text)
        except ValueError as exc:
            raise PositionValidationError(
                "FEN halfmove counter is too large"
            ) from exc
        try:
            fullmove = int(fullmove_text)
        except ValueError as exc:
            raise PositionValidationError(
                "FEN fullmove counter is too large"
            ) from exc

        _validate_fen_castling_token(castling)
        return cls(
            tuple(pieces),
            turn=turn,
            castling=_normalize_castling(castling),
            en_passant=en_passant,
            halfmove=halfmove,
            fullmove=fullmove,
        )


def standard_position() -> PositionState:
    return PositionState.from_fen("rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w KQkq - 0 1")


def empty_position(*, turn: str = "w") -> PositionState:
    return PositionState((None,) * 64, turn=turn)



def parse_piece_coordinate_position(text: str, *, turn: str = "w") -> PositionState:
    """Parse canonical W:/B: piece-coordinate text into PositionState.

    This presentation-neutral parser is the sole authority for the compact
    coordinate-position grammar used by move entry and legacy text-to-FEN
    adapters. It validates representation only; chess legality remains owned
    by the canonical chess-rules layer.
    """

    if type(text) is not str:
        raise ValueError("position text must be text")
    if len(text) > MAX_COORDINATE_POSITION_CHARS:
        raise ValueError("position text is too long")
    if type(turn) is not str or turn not in {"w", "b"}:
        raise ValueError("turn must be 'w' or 'b'")

    match = _POSITION_SECTIONS_RE.match(text)
    if match is None:
        raise ValueError("position text must contain W: and B: sections")

    position = empty_position(turn=turn)
    used: set[str] = set()
    token_budget = [0]
    position = _fill_coordinate_section(
        position,
        match.group("white"),
        white=True,
        used=used,
        token_budget=token_budget,
    )
    position = _fill_coordinate_section(
        position,
        match.group("black"),
        white=False,
        used=used,
        token_budget=token_budget,
    )

    white_kings = sum(piece == "K" for piece in position.pieces)
    black_kings = sum(piece == "k" for piece in position.pieces)
    if white_kings != 1 or black_kings != 1:
        raise ValueError("position text requires exactly one white and one black king")
    return position


def _fill_coordinate_section(
    position: PositionState,
    chunk: str,
    *,
    white: bool,
    used: set[str],
    token_budget: list[int],
) -> PositionState:
    # The compact grammar can describe at most 64 occupied squares: one piece
    # token and one square token per square. Scan incrementally and stop at the
    # first impossible token instead of allocating an unbounded split() result
    # from pasted/untrusted text.
    tokens: list[str] = []
    for match in _COORDINATE_TOKEN_RE.finditer(chunk):
        token_budget[0] += 1
        if token_budget[0] > MAX_COORDINATE_POSITION_TOKENS:
            raise ValueError("position text contains too many piece-square tokens")
        tokens.append(match.group(0))
    if len(tokens) % 2:
        raise ValueError("each piece must be followed by a square, for example N f3")

    result = position
    for index in range(0, len(tokens), 2):
        raw_piece = tokens[index]
        piece = raw_piece.upper()
        square = tokens[index + 1].lower()
        if piece not in "KQRBNP":
            if len(raw_piece) <= _MAX_PIECE_DIAGNOSTIC_CHARS:
                diagnostic = raw_piece
            else:
                diagnostic = raw_piece[:_MAX_PIECE_DIAGNOSTIC_CHARS] + "…"
            raise ValueError(f"unknown piece symbol: {diagnostic}")
        if square in used:
            raise ValueError(f"square {square} is specified more than once")
        try:
            result = result.with_piece(square, piece if white else piece.lower())
        except PositionValidationError as exc:
            # Public PositionState square ingress deliberately keeps malformed
            # values generic so hostile objects cannot trigger repr()/coercion.
            # Here square is already a bounded built-in token materialized by
            # this parser. Preserve useful detail only for short tokens; never
            # echo an arbitrarily long paste into an accessible error.
            if str(exc) == "invalid square" and len(square) <= _MAX_SQUARE_DIAGNOSTIC_CHARS:
                raise PositionValidationError(f"invalid square: {square!r}") from exc
            raise
        used.add(square)
    return result

def _counter_text(value: int, *, label: str, minimum: int) -> str:
    """Render a validated FEN counter without leaking runtime conversion errors."""

    if type(value) is not int:
        raise PositionValidationError(f"{label} must be an integer")
    if value < minimum:
        if minimum == 0:
            raise PositionValidationError(f"{label} must be non-negative")
        raise PositionValidationError(f"{label} must be at least {minimum}")
    if value >= _MAX_FEN_COUNTER_EXCLUSIVE:
        raise PositionValidationError(f"{label} is too large")
    try:
        return str(value)
    except ValueError as exc:
        # CPython may enforce a process-level integer-string conversion limit.
        # Keep that implementation detail inside the Position domain.
        raise PositionValidationError(f"{label} is too large") from exc


def _square_index(square: str) -> int:
    try:
        return parse_square(square)
    except ValueError as exc:
        # The rejected value may be an active object or an enormous integer.
        # Keep the domain error stable without invoking __repr__/integer text conversion.
        raise PositionValidationError("invalid square") from exc


def _canonical_castling_text(value: str) -> str:
    return "".join(symbol for symbol in "KQkq" if symbol in value)


def _validate_fen_castling_token(value: str) -> None:
    """Require the standard FEN KQkq relative order at text ingress."""

    _validate_castling(value)
    if value != "-" and value != _canonical_castling_text(value):
        raise PositionValidationError(
            "FEN castling rights must use canonical KQkq order"
        )


def _normalize_castling(value: str) -> str:
    if type(value) is not str:
        raise PositionValidationError("castling rights must be text")
    if len(value) > _MAX_CASTLING_TEXT_CHARS:
        raise PositionValidationError("castling rights text is too long")
    text = value.strip()
    if text in {"", "-"}:
        return "-"
    _validate_castling(text)
    return _canonical_castling_text(text)


def _validate_castling(value: str) -> None:
    if value == "-":
        return
    if not value or any(ch not in VALID_CASTLING for ch in value):
        raise PositionValidationError("invalid castling rights")
    if len(set(value)) != len(value):
        raise PositionValidationError("castling rights must not contain duplicates")


def _validate_en_passant(value: str, turn: str) -> None:
    if value == "-":
        return
    _square_index(value)
    rank = value[1]
    expected = "6" if turn == "w" else "3"
    if rank != expected:
        raise PositionValidationError(
            f"en-passant square rank must be {expected} when {turn} is to move"
        )
