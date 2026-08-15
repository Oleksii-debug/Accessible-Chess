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

from .chessbase_cbg_payload import locate_cbg_move_payload


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
    return ClassicCbgMovePayloadEvidence(
        game_offset=span.game_offset,
        payload_start_offset=span.payload_start_offset,
        game_end_offset=span.game_end_offset,
        payload_bytes=payload,
        payload_sha256=sha256(payload).hexdigest(),
        custom_setup_prefix_consumed=span.custom_setup_prefix_consumed,
    )


def read_cbg_move_payload_evidence(
    path: str | Path, *, offset: int
) -> ClassicCbgMovePayloadEvidence:
    """Read opaque payload evidence without modifying the proprietary source."""

    source = Path(path)
    with source.open("rb") as stream:
        data = stream.read()
    return extract_cbg_move_payload_evidence(data, offset=offset)
