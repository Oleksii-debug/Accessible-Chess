"""Fault-isolated read-only classic ChessBase CBH-to-CBG batch projection.

This module composes already evidence-backed classic ChessBase facts from
cbh2pgn, pinned at commit 42b3592738062db1f768239e85df1b98cb1cead9:
eligible CBH game records carry CBG offsets and supported CBG records expose
opaque payload byte evidence. No move token, annotation, FEN, legality, or
otherwise proprietary move semantics are decoded here.

Original cbh2pgn copyright (c) 2022 Dominik Klein, MIT License.
Accessible Chess deliberately does not introduce cbh2pgn's GPL
``python-chess`` runtime dependency.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Literal

from .chessbase_cbg import CbgDecodeError
from .chessbase_cbh import ClassicCbhRecord, iter_cbh_records
from .chessbase_cbh_cbg_link import (
    ClassicCbhCbgPayloadLink,
    link_cbh_record_to_cbg_payload,
)

BatchStatus = Literal["linked", "skipped", "failed"]


@dataclass(frozen=True)
class ClassicCbhCbgBatchItem:
    """One neutral batch result without inventing unsupported semantics."""

    record_index: int
    game_offset: int
    status: BatchStatus
    link: ClassicCbhCbgPayloadLink | None = None
    reason: str | None = None
    error_type: str | None = None


@dataclass(frozen=True)
class ClassicCbhCbgBatchProjection:
    """Ordered per-record projection with failures isolated to each record."""

    items: tuple[ClassicCbhCbgBatchItem, ...]

    @property
    def linked_count(self) -> int:
        return sum(item.status == "linked" for item in self.items)

    @property
    def skipped_count(self) -> int:
        return sum(item.status == "skipped" for item in self.items)

    @property
    def failed_count(self) -> int:
        return sum(item.status == "failed" for item in self.items)


def project_cbh_records_to_cbg_payload_evidence(
    records: Iterable[ClassicCbhRecord],
    cbg_data: bytes,
) -> ClassicCbhCbgBatchProjection:
    """Project CBH records to opaque CBG evidence without stopping on one defect.

    Non-game and deleted CBH records are explicit ``skipped`` outcomes. CBG
    structural or unsupported-state failures are explicit ``failed`` outcomes
    carrying the exact decoder exception type and message. Successful records
    preserve the existing evidence-backed link DTO.
    """

    items: list[ClassicCbhCbgBatchItem] = []
    for record in records:
        if not record.is_game:
            items.append(
                ClassicCbhCbgBatchItem(
                    record_index=record.record_index,
                    game_offset=record.game_offset,
                    status="skipped",
                    reason="not-game-record",
                )
            )
            continue
        if record.marked_for_deletion:
            items.append(
                ClassicCbhCbgBatchItem(
                    record_index=record.record_index,
                    game_offset=record.game_offset,
                    status="skipped",
                    reason="marked-for-deletion",
                )
            )
            continue

        try:
            link = link_cbh_record_to_cbg_payload(record, cbg_data)
        except CbgDecodeError as exc:
            items.append(
                ClassicCbhCbgBatchItem(
                    record_index=record.record_index,
                    game_offset=record.game_offset,
                    status="failed",
                    reason=str(exc),
                    error_type=type(exc).__name__,
                )
            )
            continue

        items.append(
            ClassicCbhCbgBatchItem(
                record_index=record.record_index,
                game_offset=record.game_offset,
                status="linked",
                link=link,
            )
        )

    return ClassicCbhCbgBatchProjection(items=tuple(items))


def read_cbh_cbg_batch_projection(
    cbh_path: str | Path,
    cbg_path: str | Path,
) -> ClassicCbhCbgBatchProjection:
    """Read both classic sources without modification and project all CBH records."""

    cbg_data = Path(cbg_path).read_bytes()
    return project_cbh_records_to_cbg_payload_evidence(
        iter_cbh_records(cbh_path),
        cbg_data,
    )
