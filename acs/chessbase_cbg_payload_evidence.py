"""Read-only evidence DTO for classic ChessBase CBG move payload bytes.

The byte boundaries come from cbh2pgn pinned at commit
42b3592738062db1f768239e85df1b98cb1cead9. Original cbh2pgn copyright
(c) 2022 Dominik Klein, MIT License.

Accessible Chess preserves the exact payload bytes and a SHA-256 fingerprint;
it deliberately assigns no move, annotation, legality, or FEN semantics and
does not introduce cbh2pgn's GPL ``python-chess`` runtime dependency.
"""

from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha256
from pathlib import Path

from .chessbase_cbg import CbgDecodeError, read_cbg_game_header_from_stream
from .chessbase_cbg_payload import (
    ClassicCbgMovePayloadSpan,
    locate_cbg_move_payload,
    locate_cbg_move_payload_from_header,
)


MAX_CLASSIC_CBG_PAYLOAD_BYTES = 0x00FFFFFF


@dataclass(frozen=True)
class ClassicCbgMovePayloadEvidence:
    """Exact opaque bytes for one supported classic CBG move payload."""

    game_offset: int
    payload_start_offset: int
    game_end_offset: int
    payload_bytes: bytes
    payload_sha256: str
    custom_setup_prefix_consumed: bool

    @property
    def payload_length(self) -> int:
        return len(self.payload_bytes)


def extract_cbg_move_payload_evidence(
    data: bytes, *, offset: int
) -> ClassicCbgMovePayloadEvidence:
    """Copy the declared move payload as opaque evidence without decoding it."""

    span = locate_cbg_move_payload(data, offset=offset)
    payload = bytes(data[span.payload_start_offset:span.game_end_offset])
    return _build_payload_evidence(span, payload)


def _build_payload_evidence(
    span: ClassicCbgMovePayloadSpan,
    payload: bytes,
) -> ClassicCbgMovePayloadEvidence:
    if len(payload) != span.payload_length:
        raise CbgDecodeError(
            f"CBG move payload at offset {span.game_offset} changed or is truncated: "
            f"expected {span.payload_length} bytes, got {len(payload)}"
        )
    return ClassicCbgMovePayloadEvidence(
        game_offset=span.game_offset,
        payload_start_offset=span.payload_start_offset,
        game_end_offset=span.game_end_offset,
        payload_bytes=payload,
        payload_sha256=sha256(payload).hexdigest(),
        custom_setup_prefix_consumed=span.custom_setup_prefix_consumed,
    )


def read_cbg_move_payload_evidence(
    path: str | Path,
    *,
    offset: int,
    max_payload_bytes: int = MAX_CLASSIC_CBG_PAYLOAD_BYTES,
) -> ClassicCbgMovePayloadEvidence:
    """Read exactly one bounded opaque payload from a proprietary source."""

    if (
        not isinstance(max_payload_bytes, int)
        or isinstance(max_payload_bytes, bool)
        or max_payload_bytes < 0
    ):
        raise CbgDecodeError("max_payload_bytes must be a non-negative integer")

    source = Path(path)
    with source.open("rb") as stream:
        header = read_cbg_game_header_from_stream(stream, offset=offset)
        span = locate_cbg_move_payload_from_header(header)
        if span.payload_length > max_payload_bytes:
            raise CbgDecodeError(
                f"CBG move payload at offset {offset} exceeds configured bound: "
                f"{span.payload_length} > {max_payload_bytes} bytes"
            )
        stream.seek(span.payload_start_offset)
        payload = stream.read(span.payload_length)
    return _build_payload_evidence(span, payload)
