"""Read-only classic ChessBase CBG move-payload boundary evidence.

This module adapts only byte boundaries used by cbh2pgn, pinned at commit
42b3592738062db1f768239e85df1b98cb1cead9.  The pinned converter slices
normal-position move bytes from ``game_offset + 4`` and custom-position move
bytes from ``game_offset + 4 + 28`` through the declared game end.

Original cbh2pgn copyright (c) 2022 Dominik Klein, MIT License.
Accessible Chess deliberately does not decode move tokens here and does not
introduce cbh2pgn's GPL ``python-chess`` runtime dependency.
"""

from __future__ import annotations

from dataclasses import dataclass

from .chessbase_cbg import CbgDecodeError, parse_cbg_game_header


_HEADER_SIZE = 4
_CUSTOM_SETUP_PREFIX_AFTER_HEADER = 28
_CUSTOM_MOVE_PAYLOAD_OFFSET = _HEADER_SIZE + _CUSTOM_SETUP_PREFIX_AFTER_HEADER


@dataclass(frozen=True)
class ClassicCbgMovePayloadSpan:
    """Neutral byte span for a supported classic CBG move payload.

    The span identifies bytes only.  It carries no claim about move legality,
    token meaning, annotations, FEN, or decoded chess semantics.
    """

    game_offset: int
    game_end_offset: int
    payload_start_offset: int
    payload_length: int
    custom_setup_prefix_consumed: bool


def locate_cbg_move_payload(data: bytes, *, offset: int) -> ClassicCbgMovePayloadSpan:
    """Locate the pinned decoder's move-byte slice without decoding any move.

    Unsupported encoding states are rejected explicitly.  Custom-position games
    must contain the complete 32-byte fixed header/setup prefix before a move
    payload boundary can be reported.
    """

    header = parse_cbg_game_header(data, offset=offset)
    if header.unsupported_reasons:
        reasons = ", ".join(header.unsupported_reasons)
        raise CbgDecodeError(
            f"CBG move payload at offset {offset} is unsupported: {reasons}"
        )

    relative_payload_start = (
        _CUSTOM_MOVE_PAYLOAD_OFFSET
        if header.starts_from_custom_position
        else _HEADER_SIZE
    )
    if header.game_length < relative_payload_start:
        raise CbgDecodeError(
            f"CBG move payload at offset {offset} is truncated: "
            f"declared game length {header.game_length}, "
            f"need at least {relative_payload_start} bytes"
        )

    game_end = offset + header.game_length
    payload_start = offset + relative_payload_start
    return ClassicCbgMovePayloadSpan(
        game_offset=offset,
        game_end_offset=game_end,
        payload_start_offset=payload_start,
        payload_length=game_end - payload_start,
        custom_setup_prefix_consumed=header.starts_from_custom_position,
    )
