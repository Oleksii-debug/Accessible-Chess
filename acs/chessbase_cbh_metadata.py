"""Fault-isolated read-only classic ChessBase CBH metadata projection.

This module composes only evidence-backed classic CBH references with CBP player
names and CBT tournament metadata. Layout facts come from cbh2pgn pinned at
42b3592738062db1f768239e85df1b98cb1cead9.

Original cbh2pgn copyright (c) 2022 Dominik Klein, MIT License.
Accessible Chess exposes neutral DTOs only and does not introduce cbh2pgn's GPL
``python-chess`` runtime dependency.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Iterable, Literal

from .chessbase_cbh import ClassicCbhRecord
from .chessbase_cbp import (
    CbpDecodeError,
    ClassicCbpPlayer,
    parse_cbp_player,
    read_cbp_player,
)
from .chessbase_cbt import (
    CbtDecodeError,
    ClassicCbtTournament,
    parse_cbt_tournament,
    read_cbt_tournament,
)

MetadataStatus = Literal["projected", "skipped", "failed"]


@dataclass(frozen=True)
class ClassicCbhMetadata:
    record_index: int
    white: ClassicCbpPlayer
    black: ClassicCbpPlayer
    tournament: ClassicCbtTournament


@dataclass(frozen=True)
class ClassicCbhMetadataItem:
    record_index: int
    status: MetadataStatus
    metadata: ClassicCbhMetadata | None = None
    reason: str | None = None
    error_type: str | None = None


@dataclass(frozen=True)
class ClassicCbhMetadataProjection:
    items: tuple[ClassicCbhMetadataItem, ...]

    @property
    def projected_count(self) -> int:
        return sum(item.status == "projected" for item in self.items)

    @property
    def skipped_count(self) -> int:
        return sum(item.status == "skipped" for item in self.items)

    @property
    def failed_count(self) -> int:
        return sum(item.status == "failed" for item in self.items)


def project_cbh_records_to_metadata(
    records: Iterable[ClassicCbhRecord],
    cbp_data: bytes,
    cbt_data: bytes,
) -> ClassicCbhMetadataProjection:
    """Resolve established CBH player/tournament references without guessing.

    Non-game and deleted records are explicit skips. A malformed, unsupported,
    or out-of-range CBP/CBT reference fails only that record, preserving order
    and allowing later records to be projected.
    """

    return _project_cbh_records_with_resolver(
        records,
        lambda record: (
            parse_cbp_player(cbp_data, player_no=record.white_player_offset),
            parse_cbp_player(cbp_data, player_no=record.black_player_offset),
            parse_cbt_tournament(
                cbt_data,
                tournament_no=record.tournament_offset,
            ),
        ),
    )


def _project_cbh_records_with_resolver(
    records: Iterable[ClassicCbhRecord],
    resolver: Callable[
        [ClassicCbhRecord],
        tuple[ClassicCbpPlayer, ClassicCbpPlayer, ClassicCbtTournament],
    ],
) -> ClassicCbhMetadataProjection:
    items: list[ClassicCbhMetadataItem] = []
    for record in records:
        if not record.is_game:
            items.append(ClassicCbhMetadataItem(
                record_index=record.record_index,
                status="skipped",
                reason="not-game-record",
            ))
            continue
        if record.marked_for_deletion:
            items.append(ClassicCbhMetadataItem(
                record_index=record.record_index,
                status="skipped",
                reason="marked-for-deletion",
            ))
            continue

        try:
            white, black, tournament = resolver(record)
        except (CbpDecodeError, CbtDecodeError) as exc:
            items.append(ClassicCbhMetadataItem(
                record_index=record.record_index,
                status="failed",
                reason=str(exc),
                error_type=type(exc).__name__,
            ))
            continue

        items.append(ClassicCbhMetadataItem(
            record_index=record.record_index,
            status="projected",
            metadata=ClassicCbhMetadata(
                record_index=record.record_index,
                white=white,
                black=black,
                tournament=tournament,
            ),
        ))

    return ClassicCbhMetadataProjection(items=tuple(items))


def read_cbh_records_metadata_projection(
    records: Iterable[ClassicCbhRecord],
    cbp_path: str | Path,
    cbt_path: str | Path,
) -> ClassicCbhMetadataProjection:
    """Project supplied CBH records with bounded CBP/CBT record reads.

    Decode failures remain isolated per CBH record. Filesystem-level failures
    such as a missing source are intentionally not relabeled as record damage.
    """

    player_source = Path(cbp_path)
    tournament_source = Path(cbt_path)
    return _project_cbh_records_with_resolver(
        records,
        lambda record: (
            read_cbp_player(
                player_source,
                player_no=record.white_player_offset,
            ),
            read_cbp_player(
                player_source,
                player_no=record.black_player_offset,
            ),
            read_cbt_tournament(
                tournament_source,
                tournament_no=record.tournament_offset,
            ),
        ),
    )
