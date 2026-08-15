"""Read-only classic ChessBase CBG game-header preflight.

This module adapts only evidence-backed CBG header bits used by cbh2pgn,
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


class CbgDecodeError(ValueError):
    """Raised when classic CBG header bytes are invalid or structurally unsafe."""


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


def read_cbg_game_header(path: str | Path, *, offset: int) -> ClassicCbgGameHeader:
    """Read one classic CBG header without modifying the proprietary source."""

    source = Path(path)
    with source.open("rb") as stream:
        data = stream.read()
    return parse_cbg_game_header(data, offset=offset)
