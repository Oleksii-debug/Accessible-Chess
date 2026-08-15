"""Read-only classic ChessBase CBG preflight primitives.

This module adapts only evidence-backed CBG header/setup bytes used by cbh2pgn,
pinned at commit 42b3592738062db1f768239e85df1b98cb1cead9.

Original cbh2pgn copyright (c) 2022 Dominik Klein, MIT License.
Accessible Chess adaptation deliberately excludes cbh2pgn's GPL
``python-chess`` runtime dependency and exposes neutral immutable DTOs only.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


_MASK_CUSTOM_START = 0x40000000
_MASK_ENCODING_FLAG = 0x80000000
_MASK_SPECIAL_ENCODING = 0x04000000
_MASK_CHESS960 = 0x0A000000
_MASK_GAME_LENGTH = 0x00FFFFFF
_HEADER_SIZE = 4

_MASK_EP_FILE = 0x07
_MASK_TURN = 0x10
_MASK_WHITE_CASTLE_LONG = 0x01
_MASK_WHITE_CASTLE_SHORT = 0x02
_MASK_BLACK_CASTLE_LONG = 0x04
_MASK_BLACK_CASTLE_SHORT = 0x08
_SETUP_METADATA_OFFSET = 5
_SETUP_CASTLING_OFFSET = 6
_SETUP_MOVE_NUMBER_OFFSET = 7
_SETUP_BITSTREAM_OFFSET = 8
_SETUP_BITSTREAM_SIZE = 24
_SETUP_END = _SETUP_BITSTREAM_OFFSET + _SETUP_BITSTREAM_SIZE


class CbgDecodeError(ValueError):
    """Raised when classic CBG bytes are invalid or structurally unsafe."""


@dataclass(frozen=True)
class ClassicCbgGameHeader:
    """Neutral description of the four-byte classic CBG game header."""

    offset: int
    raw_size_info: int
    starts_from_custom_position: bool
    encoding_flag_set: bool
    is_chess960: bool
    has_special_encoding: bool
    game_length: int

    @property
    def unsupported_reasons(self) -> tuple[str, ...]:
        """Reasons the pinned cbh2pgn decoder would not decode this move stream."""

        reasons: list[str] = []
        if self.encoding_flag_set:
            reasons.append("encoding-flag")
        if self.is_chess960:
            reasons.append("chess960")
        if self.has_special_encoding:
            reasons.append("special-encoding")
        return tuple(reasons)

    @property
    def supported_by_pinned_decoder(self) -> bool:
        return not self.unsupported_reasons


@dataclass(frozen=True)
class ClassicCbgSetup:
    """Neutral evidence from the fixed classic custom-position setup prefix.

    Piece-placement semantics are intentionally not decoded here. ``setup_bytes``
    preserves the exact 24-byte setup bitstream consumed by the pinned decoder so
    later slices can specialize it without changing this read-only boundary.
    """

    offset: int
    en_passant_file_code: int
    black_to_move: bool
    white_castle_long: bool
    white_castle_short: bool
    black_castle_long: bool
    black_castle_short: bool
    next_move_number: int
    setup_bytes: bytes


def parse_cbg_game_header(data: bytes, *, offset: int) -> ClassicCbgGameHeader:
    """Inspect one CBG game header and validate its declared file boundary.

    The four-byte value is big-endian. The low 24 bits are the complete game
    length measured from ``offset``; the remaining evidence-backed bits are
    exposed without attempting move decoding. Unsupported encoding states are
    reported explicitly instead of guessed.
    """

    if not isinstance(offset, int) or isinstance(offset, bool) or offset < 0:
        raise CbgDecodeError("offset must be a non-negative integer")
    if offset + _HEADER_SIZE > len(data):
        raise CbgDecodeError(
            f"CBG game header at offset {offset} is truncated: "
            f"need {_HEADER_SIZE} bytes, file size is {len(data)}"
        )

    raw_size_info = int.from_bytes(data[offset:offset + _HEADER_SIZE], "big")
    game_length = raw_size_info & _MASK_GAME_LENGTH
    if game_length < _HEADER_SIZE:
        raise CbgDecodeError(
            f"CBG game at offset {offset} declares invalid length {game_length}"
        )
    game_end = offset + game_length
    if game_end > len(data):
        raise CbgDecodeError(
            f"CBG game at offset {offset} is truncated: declared end {game_end}, "
            f"file size is {len(data)}"
        )

    return ClassicCbgGameHeader(
        offset=offset,
        raw_size_info=raw_size_info,
        starts_from_custom_position=bool(raw_size_info & _MASK_CUSTOM_START),
        encoding_flag_set=bool(raw_size_info & _MASK_ENCODING_FLAG),
        is_chess960=bool(raw_size_info & _MASK_CHESS960),
        has_special_encoding=bool(raw_size_info & _MASK_SPECIAL_ENCODING),
        game_length=game_length,
    )


def parse_cbg_custom_setup(data: bytes, *, offset: int) -> ClassicCbgSetup:
    """Inspect the fixed setup prefix for one supported classic custom position.

    This mirrors only the byte/bit extraction performed by pinned cbh2pgn
    ``decode_start_position``. It deliberately does not infer piece placement,
    FEN, move semantics, annotations, Chess960 or special encodings.
    """

    header = parse_cbg_game_header(data, offset=offset)
    if not header.starts_from_custom_position:
        raise CbgDecodeError(
            f"CBG game at offset {offset} does not declare a custom start position"
        )
    if header.unsupported_reasons:
        reasons = ", ".join(header.unsupported_reasons)
        raise CbgDecodeError(
            f"CBG custom setup at offset {offset} is unsupported: {reasons}"
        )
    if header.game_length < _SETUP_END:
        raise CbgDecodeError(
            f"CBG custom setup at offset {offset} is truncated: "
            f"declared game length {header.game_length}, need at least {_SETUP_END} bytes"
        )

    metadata = data[offset + _SETUP_METADATA_OFFSET]
    castling = data[offset + _SETUP_CASTLING_OFFSET]
    next_move_number = data[offset + _SETUP_MOVE_NUMBER_OFFSET]
    setup_start = offset + _SETUP_BITSTREAM_OFFSET
    setup_end = setup_start + _SETUP_BITSTREAM_SIZE
    setup_bytes = bytes(data[setup_start:setup_end])

    return ClassicCbgSetup(
        offset=offset,
        en_passant_file_code=metadata & _MASK_EP_FILE,
        black_to_move=bool(metadata & _MASK_TURN),
        white_castle_long=bool(castling & _MASK_WHITE_CASTLE_LONG),
        white_castle_short=bool(castling & _MASK_WHITE_CASTLE_SHORT),
        black_castle_long=bool(castling & _MASK_BLACK_CASTLE_LONG),
        black_castle_short=bool(castling & _MASK_BLACK_CASTLE_SHORT),
        next_move_number=next_move_number,
        setup_bytes=setup_bytes,
    )


def read_cbg_game_header(path: str | Path, *, offset: int) -> ClassicCbgGameHeader:
    """Read one classic CBG header without modifying the proprietary source."""

    source = Path(path)
    with source.open("rb") as stream:
        data = stream.read()
    return parse_cbg_game_header(data, offset=offset)


def read_cbg_custom_setup(path: str | Path, *, offset: int) -> ClassicCbgSetup:
    """Read one classic CBG custom setup without modifying the source bytes."""

    source = Path(path)
    with source.open("rb") as stream:
        data = stream.read()
    return parse_cbg_custom_setup(data, offset=offset)
