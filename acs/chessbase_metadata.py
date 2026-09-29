from __future__ import annotations

"""Loss-aware classic ChessBase metadata capability contract.

The optional classic CBH/CBV path uses a pinned external libcbh backend. This
module records only metadata that the pinned backend actually exposes and keeps
source provenance separate from PGN tags. It is intentionally presentation
neutral so Library/UI code can report partial capabilities without inventing
proprietary fields.
"""

from dataclasses import dataclass
from enum import Enum
import unicodedata


PINNED_LIBCBH_COMMIT = "9641c5c3949d8fb210b17dd9aa54455645843696"
SCID_ECO_STRIDE = 131
SCID_ECO_MAIN_CODES = 500


class ChessBaseMetadataStatus(str, Enum):
    MAPPED = "mapped"
    PARTIAL = "partial"
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
    main-code sequence ``1 + 131*n`` for A00..E99. Zero means unknown. Values
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


def _normalized_backend_name(value: str) -> str:
    return " ".join(unicodedata.normalize("NFKC", value).split()).casefold()


def pinned_libcbh_declared_player_name_loss(expected: str, actual: str) -> bool:
    """Recognize only the exact real-corpus player-name loss boundary we can prove.

    The independent TWIC1134 PGN oracle exposed a bounded pinned-libcbh boundary:
    an ASCII given-name field of exactly 20 characters can arrive from the
    backend with only its final character missing, while the last name remains
    intact. Accessible Chess receives only the already-decoded backend string,
    so it must report that loss rather than fabricate the missing character.

    This deliberately does not accept arbitrary spelling, ordering, Unicode,
    internal-character or multi-character differences.
    """

    if type(expected) is not str or type(actual) is not str:
        raise TypeError("player names must be strings")
    text = " ".join(expected.split())
    if "," not in text:
        return False
    last, given = (part.strip() for part in text.split(",", 1))
    if not last or not given or not given.isascii() or len(given) != 20:
        return False
    complete = f"{given} {last}"
    bounded_loss = f"{given[:-1]} {last}"
    normalized_actual = _normalized_backend_name(actual)
    return (
        normalized_actual == _normalized_backend_name(bounded_loss)
        and normalized_actual != _normalized_backend_name(complete)
    )

def chessbase_metadata_capabilities() -> tuple[ChessBaseMetadataCapability, ...]:
    backend = f"libcbh@{PINNED_LIBCBH_COMMIT}"
    return (
        ChessBaseMetadataCapability("White", ChessBaseMetadataStatus.PARTIAL, "White", f"{backend}: player first/last name; real TWIC1134 oracle proves a bounded 20-to-19 character given-name loss boundary that must be reported, never reconstructed"),
        ChessBaseMetadataCapability("Black", ChessBaseMetadataStatus.PARTIAL, "Black", f"{backend}: player first/last name; real TWIC1134 oracle proves a bounded 20-to-19 character given-name loss boundary that must be reported, never reconstructed"),
        ChessBaseMetadataCapability("Event", ChessBaseMetadataStatus.MAPPED, "Event", f"{backend}: tournament title"),
        ChessBaseMetadataCapability("Site", ChessBaseMetadataStatus.MAPPED, "Site", f"{backend}: tournament place"),
        ChessBaseMetadataCapability("Date", ChessBaseMetadataStatus.MAPPED, "Date", f"{backend}: game date"),
        ChessBaseMetadataCapability("Round", ChessBaseMetadataStatus.MAPPED, "Round", f"{backend}: round/subround"),
        ChessBaseMetadataCapability("Result", ChessBaseMetadataStatus.MAPPED, "Result", f"{backend}: result enum"),
        ChessBaseMetadataCapability("WhiteElo", ChessBaseMetadataStatus.MAPPED, "WhiteElo", f"{backend}: white rating"),
        ChessBaseMetadataCapability("BlackElo", ChessBaseMetadataStatus.MAPPED, "BlackElo", f"{backend}: black rating"),
        ChessBaseMetadataCapability("ECO", ChessBaseMetadataStatus.MAPPED, "ECO", f"{backend}: Scid main ECO integer; subcodes intentionally unavailable"),
        ChessBaseMetadataCapability("BackendTags", ChessBaseMetadataStatus.PASSTHROUGH, "PGN tags", f"{backend}: decoded tag vector; no synthetic semantics"),
        ChessBaseMetadataCapability(
            "BackendTextEncoding",
            ChessBaseMetadataStatus.PASSTHROUGH,
            "Unicode text",
            f"{backend}: bridge preserves every backend byte deterministically as U+00XX; libcbh exposes no source charset contract, so no charset inference is claimed",
        ),
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
