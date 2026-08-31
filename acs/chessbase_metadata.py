from __future__ import annotations

"""Loss-aware classic ChessBase metadata capability contract.

The optional classic CBH/CBV path uses a pinned external libcbh backend.  This
module records only metadata that the pinned backend actually exposes and keeps
source provenance separate from PGN tags.  It is intentionally presentation
neutral so Library/UI code can report partial capabilities without inventing
proprietary fields.
"""

from dataclasses import dataclass
from enum import Enum


PINNED_LIBCBH_COMMIT = "9641c5c3949d8fb210b17dd9aa54455645843696"
SCID_ECO_STRIDE = 131
SCID_ECO_MAIN_CODES = 500


class ChessBaseMetadataStatus(str, Enum):
    MAPPED = "mapped"
    PASSTHROUGH = "passthrough"
    PROVENANCE = "provenance"
    NOT_EXPOSED = "not_exposed"


@dataclass(frozen=True, slots=True)
class ChessBaseMetadataCapability:
    field: str
    status: ChessBaseMetadataStatus
    canonical_field: str | None
    evidence: str


def scid_eco_main_to_pgn(value: int) -> str | None:
    """Convert libcbh's main Scid ECO integer to a three-character PGN ECO.

    Pinned libcbh deliberately drops ChessBase ECO subcodes and emits the Scid
    main-code sequence ``1 + 131*n`` for A00..E99.  Zero means unknown.  Values
    outside that exact main-code sequence fail closed instead of guessing.
    """

    if type(value) is not int:
        raise TypeError("Scid ECO value must be an integer")
    if value == 0:
        return None
    if value < 1 or (value - 1) % SCID_ECO_STRIDE:
        return None
    index = (value - 1) // SCID_ECO_STRIDE
    if index < 0 or index >= SCID_ECO_MAIN_CODES:
        return None
    letter = chr(ord("A") + index // 100)
    return f"{letter}{index % 100:02d}"


def chessbase_metadata_capabilities() -> tuple[ChessBaseMetadataCapability, ...]:
    backend = f"libcbh@{PINNED_LIBCBH_COMMIT}"
    return (
        ChessBaseMetadataCapability("White", ChessBaseMetadataStatus.MAPPED, "White", f"{backend}: player first/last name"),
        ChessBaseMetadataCapability("Black", ChessBaseMetadataStatus.MAPPED, "Black", f"{backend}: player first/last name"),
        ChessBaseMetadataCapability("Event", ChessBaseMetadataStatus.MAPPED, "Event", f"{backend}: tournament title"),
        ChessBaseMetadataCapability("Site", ChessBaseMetadataStatus.MAPPED, "Site", f"{backend}: tournament place"),
        ChessBaseMetadataCapability("Date", ChessBaseMetadataStatus.MAPPED, "Date", f"{backend}: game date"),
        ChessBaseMetadataCapability("Round", ChessBaseMetadataStatus.MAPPED, "Round", f"{backend}: round/subround"),
        ChessBaseMetadataCapability("Result", ChessBaseMetadataStatus.MAPPED, "Result", f"{backend}: result enum"),
        ChessBaseMetadataCapability("WhiteElo", ChessBaseMetadataStatus.MAPPED, "WhiteElo", f"{backend}: white rating"),
        ChessBaseMetadataCapability("BlackElo", ChessBaseMetadataStatus.MAPPED, "BlackElo", f"{backend}: black rating"),
        ChessBaseMetadataCapability("ECO", ChessBaseMetadataStatus.MAPPED, "ECO", f"{backend}: Scid main ECO integer; subcodes intentionally unavailable"),
        ChessBaseMetadataCapability("BackendTags", ChessBaseMetadataStatus.PASSTHROUGH, "PGN tags", f"{backend}: decoded tag vector; no synthetic semantics"),
        ChessBaseMetadataCapability("SourceDatabase", ChessBaseMetadataStatus.PROVENANCE, "sources.name", "original user-selected CBH/CBV source, not extraction temp files"),
        ChessBaseMetadataCapability("SourceIndex", ChessBaseMetadataStatus.PROVENANCE, "games.source_index", "original decoded record index"),
        ChessBaseMetadataCapability("SourceSHA256", ChessBaseMetadataStatus.PROVENANCE, "sources.sha256", "fingerprint of the original selected CBH/CBV source"),
        ChessBaseMetadataCapability("Opening", ChessBaseMetadataStatus.NOT_EXPOSED, None, f"{backend}: no dedicated opening-name field; preserve only if an explicit backend tag exists"),
        ChessBaseMetadataCapability("WhiteTitle", ChessBaseMetadataStatus.NOT_EXPOSED, None, f"{backend}: player decoder exposes names only"),
        ChessBaseMetadataCapability("BlackTitle", ChessBaseMetadataStatus.NOT_EXPOSED, None, f"{backend}: player decoder exposes names only"),
    )


def chessbase_metadata_unavailable_fields() -> tuple[str, ...]:
    """Fields that must be reported as unavailable rather than fabricated."""

    return tuple(
        item.field
        for item in chessbase_metadata_capabilities()
        if item.status is ChessBaseMetadataStatus.NOT_EXPOSED
    )
