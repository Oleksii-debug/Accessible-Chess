"""Read-only classic ChessBase CBH-to-CBG payload evidence linking.

This module composes two already evidence-backed classic ChessBase facts from
cbh2pgn, pinned at commit 42b3592738062db1f768239e85df1b98cb1cead9:
CBH game records carry the CBG game offset, and supported CBG records expose an
opaque move-payload byte span.  No move token, annotation, FEN, or proprietary
field semantics are decoded here.

Original cbh2pgn copyright (c) 2022 Dominik Klein, MIT License.
Accessible Chess deliberately does not introduce cbh2pgn's GPL
``python-chess`` runtime dependency.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from .chessbase_cbg_payload_evidence import (
    ClassicCbgMovePayloadEvidence,
    extract_cbg_move_payload_evidence,
    read_cbg_move_payload_evidence,
)
from .chessbase_cbh import ClassicCbhRecord


class CbhCbgLinkError(ValueError):
    """Raised when a CBH record is not eligible for CBG payload linking."""


@dataclass(frozen=True)
class ClassicCbhCbgPayloadLink:
    """Neutral provenance link from one CBH record to opaque CBG bytes."""

    record_index: int
    game_offset: int
    payload: ClassicCbgMovePayloadEvidence


def link_cbh_record_to_cbg_payload(
    record: ClassicCbhRecord,
    cbg_data: bytes,
) -> ClassicCbhCbgPayloadLink:
    """Resolve an eligible CBH game record to CBG payload evidence.

    Deleted or non-game CBH records are rejected explicitly.  The record's
    evidence-backed ``game_offset`` is the only cross-file pointer used.  CBG
    structural and unsupported-state validation remains owned by the existing
    payload-evidence decoder and its exceptions are intentionally preserved.
    """

    if not record.is_game:
        raise CbhCbgLinkError(
            f"CBH record {record.record_index} is not a game record"
        )
    if record.marked_for_deletion:
        raise CbhCbgLinkError(
            f"CBH record {record.record_index} is marked for deletion"
        )

    payload = extract_cbg_move_payload_evidence(cbg_data, offset=record.game_offset)
    return ClassicCbhCbgPayloadLink(
        record_index=record.record_index,
        game_offset=record.game_offset,
        payload=payload,
    )


def read_cbh_record_cbg_payload_link(
    record: ClassicCbhRecord,
    cbg_path: str | Path,
) -> ClassicCbhCbgPayloadLink:
    """Read only the linked CBG payload without loading the complete source."""

    if not record.is_game:
        raise CbhCbgLinkError(
            f"CBH record {record.record_index} is not a game record"
        )
    if record.marked_for_deletion:
        raise CbhCbgLinkError(
            f"CBH record {record.record_index} is marked for deletion"
        )
    payload = read_cbg_move_payload_evidence(
        Path(cbg_path),
        offset=record.game_offset,
    )
    return ClassicCbhCbgPayloadLink(
        record_index=record.record_index,
        game_offset=record.game_offset,
        payload=payload,
    )
