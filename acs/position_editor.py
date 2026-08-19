from __future__ import annotations

from dataclasses import dataclass, replace
from typing import Iterable

from .squares import FILES, parse_square

VALID_PIECES = frozenset("PNBRQKpnbrqk")
VALID_CASTLING = frozenset("KQkq")


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
        if len(self.pieces) != 64:
            raise PositionValidationError("position must contain exactly 64 squares")
        if any(piece is not None and piece not in VALID_PIECES for piece in self.pieces):
            raise PositionValidationError("position contains an invalid piece symbol")
        if self.turn not in {"w", "b"}:
            raise PositionValidationError("turn must be 'w' or 'b'")
        _validate_castling(self.castling)
        _validate_en_passant(self.en_passant, self.turn)
        if type(self.halfmove) is not int:
            raise PositionValidationError("halfmove clock must be an integer")
        if type(self.fullmove) is not int:
            raise PositionValidationError("fullmove number must be an integer")
        if self.halfmove < 0:
            raise PositionValidationError("halfmove clock must be non-negative")
        if self.fullmove < 1:
            raise PositionValidationError("fullmove number must be at least 1")

    def piece_at(self, square: str) -> str | None:
        return self.pieces[_square_index(square)]

    def with_piece(self, square: str, piece: str | None) -> "PositionState":
        if piece is not None and piece not in VALID_PIECES:
            raise PositionValidationError(f"invalid piece symbol: {piece!r}")
        values = list(self.pieces)
        values[_square_index(square)] = piece
        return replace(self, pieces=tuple(values))

    def cleared(self) -> "PositionState":
        return replace(self, pieces=(None,) * 64, castling="-", en_passant="-", halfmove=0)

    def with_turn(self, turn: str) -> "PositionState":
        return replace(self, turn=turn, en_passant="-")

    def with_castling(self, rights: Iterable[str] | str) -> "PositionState":
        if isinstance(rights, str):
            normalized = _normalize_castling(rights)
        else:
            normalized = _normalize_castling("".join(rights))
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
        return f"{'/'.join(ranks)} {self.turn} {self.castling} {self.en_passant} {self.halfmove} {self.fullmove}"

    @classmethod
    def from_fen(cls, fen: str) -> "PositionState":
        if not isinstance(fen, str):
            raise PositionValidationError("FEN must be text")
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
                if token.isdigit():
                    count = int(token)
                    if not 1 <= count <= 8:
                        raise PositionValidationError("FEN empty-square count must be 1..8")
                    file_index += count
                elif token in VALID_PIECES:
                    if file_index >= 8:
                        raise PositionValidationError("FEN rank contains more than 8 squares")
                    pieces[board_rank * 8 + file_index] = token
                    file_index += 1
                else:
                    raise PositionValidationError(f"invalid FEN board token: {token!r}")
            if file_index != 8:
                raise PositionValidationError("each FEN rank must expand to exactly 8 squares")

        try:
            halfmove = int(halfmove_text)
            fullmove = int(fullmove_text)
        except ValueError as exc:
            raise PositionValidationError("FEN move counters must be integers") from exc

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


def _square_index(square: str) -> int:
    try:
        return parse_square(square)
    except ValueError as exc:
        raise PositionValidationError(f"invalid square: {square!r}") from exc


def _normalize_castling(value: str) -> str:
    text = str(value).strip()
    if text in {"", "-"}:
        return "-"
    _validate_castling(text)
    return "".join(symbol for symbol in "KQkq" if symbol in text)


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
