"""Neutral read-only classic ChessBase per-record evidence composition.

This module only composes facts already exposed by the evidence-backed CBH,
CBP, CBT, and opaque CBG adapters. Layout evidence ultimately comes from
cbh2pgn pinned at 42b3592738062db1f768239e85df1b98cb1cead9.

Original cbh2pgn copyright (c) 2022 Dominik Klein, MIT License.
Accessible Chess exposes neutral DTOs only and does not introduce cbh2pgn's GPL
``python-chess`` runtime dependency. No move, FEN, legality, annotation, or
other proprietary move semantics are decoded here.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable, Literal

from .chessbase_cbh import ClassicCbhRecord
from .chessbase_cbh_cbg_batch import (
    ClassicCbhCbgBatchItem,
    project_cbh_records_to_cbg_payload_evidence,
)
from .chessbase_cbh_metadata import (
    ClassicCbhMetadataItem,
    project_cbh_records_to_metadata,
)

EvidenceStatus = Literal["complete", "partial", "skipped", "failed"]


@dataclass(frozen=True)
class ClassicCbhRecordEvidence:
    """One CBH record with independently fault-isolated evidence components."""

    record_index: int
    status: EvidenceStatus
    payload: ClassicCbhCbgBatchItem
    metadata: ClassicCbhMetadataItem


@dataclass(frozen=True)
class ClassicCbhEvidenceProjection:
    """Ordered evidence projection without inventing missing semantics."""

    items: tuple[ClassicCbhRecordEvidence, ...]

    @property
    def complete_count(self) -> int:
        return sum(item.status == "complete" for item in self.items)

    @property
    def partial_count(self) -> int:
        return sum(item.status == "partial" for item in self.items)

    @property
    def skipped_count(self) -> int:
        return sum(item.status == "skipped" for item in self.items)

    @property
    def failed_count(self) -> int:
        return sum(item.status == "failed" for item in self.items)


def _combined_status(
    payload: ClassicCbhCbgBatchItem,
    metadata: ClassicCbhMetadataItem,
) -> EvidenceStatus:
    if payload.status == "skipped" and metadata.status == "skipped":
        return "skipped"

    payload_ok = payload.status == "linked"
    metadata_ok = metadata.status == "projected"
    if payload_ok and metadata_ok:
        return "complete"
    if payload_ok or metadata_ok:
        return "partial"
    return "failed"


def project_cbh_record_evidence(
    records: Iterable[ClassicCbhRecord],
    cbg_data: bytes,
    cbp_data: bytes,
    cbt_data: bytes,
) -> ClassicCbhEvidenceProjection:
    """Compose existing per-record evidence while keeping failures independent.

    The record iterable is materialized exactly once so generators are safe.
    CBG payload evidence and CBP/CBT metadata are projected independently: a
    defect in one family does not discard evidence successfully established by
    the other family.
    """

    record_tuple = tuple(records)
    payload_projection = project_cbh_records_to_cbg_payload_evidence(
        record_tuple, cbg_data
    )
    metadata_projection = project_cbh_records_to_metadata(
        record_tuple, cbp_data, cbt_data
    )

    items: list[ClassicCbhRecordEvidence] = []
    for payload_item, metadata_item in zip(
        payload_projection.items, metadata_projection.items, strict=True
    ):
        if payload_item.record_index != metadata_item.record_index:
            raise ValueError("CBH evidence projections lost record alignment")
        items.append(
            ClassicCbhRecordEvidence(
                record_index=payload_item.record_index,
                status=_combined_status(payload_item, metadata_item),
                payload=payload_item,
                metadata=metadata_item,
            )
        )

    return ClassicCbhEvidenceProjection(items=tuple(items))
