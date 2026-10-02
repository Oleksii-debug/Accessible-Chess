from __future__ import annotations

"""Trusted authoring adapter for canonical durable prepared positions.

This module does not parse PGN, books, databases, or chess rules. It snapshots
an already-canonical Board through Board.fen(), delegates FEN validation to
TeachingPositionSource/Chess Core, carries only opaque provenance anchors for
external content owners, and publishes through the existing D10
save_prepared_position CAS boundary.
"""

from .chesscore import Board
from .education_workspace import (
    EducationWorkspace,
    delete_prepared_position,
    save_prepared_position,
)
from .teaching_session import (
    PositionSourceKind,
    TeachingPositionSource,
    TeachingSessionError,
)


class PreparedPositionAuthoringError(ValueError):
    """Stable fail-closed authoring-boundary failure."""


def source_from_board(board: Board) -> TeachingPositionSource:
    """Snapshot a current/editor canonical Board as an exact FEN source."""

    if type(board) is not Board:
        raise PreparedPositionAuthoringError(
            "prepared-position board must be canonical Chess Core Board"
        )
    try:
        return TeachingPositionSource(
            PositionSourceKind.FEN,
            fen=board.fen(),
        )
    except (TeachingSessionError, TypeError, ValueError) as exc:
        raise PreparedPositionAuthoringError(
            "canonical board could not be captured as a prepared position"
        ) from exc


def source_from_fen(fen: str) -> TeachingPositionSource:
    """Validate editor/import FEN through the canonical teaching source."""

    try:
        return TeachingPositionSource(PositionSourceKind.FEN, fen=fen)
    except (TeachingSessionError, TypeError, ValueError) as exc:
        raise PreparedPositionAuthoringError(
            "prepared-position FEN is invalid"
        ) from exc


def source_from_pgn(
    *,
    fen: str,
    source_ref: str,
    source_index: int,
) -> TeachingPositionSource:
    """Reference one PGN/game anchor while retaining its canonical FEN snapshot."""

    return _external_source(
        PositionSourceKind.PGN,
        fen=fen,
        source_ref=source_ref,
        source_index=source_index,
    )


def source_from_book(
    *,
    fen: str,
    source_ref: str,
) -> TeachingPositionSource:
    """Reference a Book-owned position without parsing or copying Book state."""

    return _external_source(
        PositionSourceKind.BOOK,
        fen=fen,
        source_ref=source_ref,
        source_index=None,
    )


def source_from_database(
    *,
    fen: str,
    source_ref: str,
) -> TeachingPositionSource:
    """Reference an ACSDB/database position without becoming its data owner."""

    return _external_source(
        PositionSourceKind.DATABASE,
        fen=fen,
        source_ref=source_ref,
        source_index=None,
    )


def save_authored_prepared_position(
    workspace: EducationWorkspace,
    *,
    position_id: str,
    source: TeachingPositionSource,
    expected_position_revision: int,
    title: str | None = None,
    student_prompt: str | None = None,
    tags: tuple[str, ...] | None = None,
    order_index: int | None = None,
    teacher_notes: str | None = None,
) -> EducationWorkspace:
    """Publish one authored source through the canonical D10 CAS boundary."""

    if type(source) is not TeachingPositionSource:
        raise PreparedPositionAuthoringError(
            "prepared-position source must be canonical TeachingPositionSource"
        )
    return save_prepared_position(
        workspace,
        position_id=position_id,
        source=source,
        expected_position_revision=expected_position_revision,
        title=title,
        student_prompt=student_prompt,
        tags=tags,
        order_index=order_index,
        teacher_notes=teacher_notes,
    )


def delete_authored_prepared_position(
    workspace: EducationWorkspace,
    *,
    position_id: str,
    expected_position_revision: int,
) -> EducationWorkspace:
    """Delete one authored prepared position through the canonical D10 CAS."""

    return delete_prepared_position(
        workspace,
        position_id=position_id,
        expected_position_revision=expected_position_revision,
    )


def _external_source(
    kind: PositionSourceKind,
    *,
    fen: str,
    source_ref: str,
    source_index: int | None,
) -> TeachingPositionSource:
    try:
        return TeachingPositionSource(
            kind,
            fen=fen,
            source_ref=source_ref,
            source_index=source_index,
        )
    except (TeachingSessionError, TypeError, ValueError) as exc:
        raise PreparedPositionAuthoringError(
            "prepared-position provenance is invalid"
        ) from exc


__all__ = [
    "PreparedPositionAuthoringError",
    "delete_authored_prepared_position",
    "save_authored_prepared_position",
    "source_from_board",
    "source_from_book",
    "source_from_database",
    "source_from_fen",
    "source_from_pgn",
]
