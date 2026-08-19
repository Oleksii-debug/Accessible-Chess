from __future__ import annotations

"""Honest capability evidence for the replaceable ChessBase adapter boundary.

This report intentionally separates recognition, bounded metadata/evidence
parsing, and canonical game import. A format name or a successfully preserved
opaque payload never becomes a claim that moves or annotations were decoded.
"""

from dataclasses import dataclass
from typing import Literal


CAPABILITY_REPORT_SCHEMA_VERSION = 1

CapabilityStatus = Literal[
    "SUPPORTED",
    "PARTIAL",
    "UNSUPPORTED",
    "CORRUPT",
    "BLOCKED",
]


@dataclass(frozen=True, slots=True)
class ChessBaseCapability:
    surface: str
    status: CapabilityStatus
    evidence: str
    limitations: tuple[str, ...] = ()
    source_read_only: bool = True

    def as_dict(self) -> dict[str, object]:
        return {
            "surface": self.surface,
            "status": self.status,
            "evidence": self.evidence,
            "limitations": list(self.limitations),
            "source_read_only": self.source_read_only,
        }


_CAPABILITIES = (
    ChessBaseCapability(
        surface="family-probing",
        status="SUPPORTED",
        evidence="Primary/component recognition and classic companion discovery.",
        limitations=("Recognition is not content compatibility.",),
    ),
    ChessBaseCapability(
        surface="source-integrity",
        status="SUPPORTED",
        evidence="SHA-256 family snapshots detect membership, size, and byte drift.",
        limitations=("A later import must reject output if the snapshot changes.",),
    ),
    ChessBaseCapability(
        surface="classic-cbh-index",
        status="PARTIAL",
        evidence="Bounded fixed-record parsing for proven flags, offsets, date, result, round, and Elo fields.",
        limitations=("Unknown/reserved fields and unproven variants remain opaque.",),
    ),
    ChessBaseCapability(
        surface="classic-cbp-cbt-metadata",
        status="PARTIAL",
        evidence="Bounded one-record player and tournament projection for proven versions.",
        limitations=("Unproven versions and metadata fields are rejected or left opaque.",),
    ),
    ChessBaseCapability(
        surface="classic-cbg-header-setup",
        status="PARTIAL",
        evidence="Bounded header and fixed custom-position setup-prefix parsing.",
        limitations=("No canonical FEN or legality claim is produced.",),
    ),
    ChessBaseCapability(
        surface="classic-cbg-opaque-payload",
        status="PARTIAL",
        evidence="Declared payload boundaries, exact bytes, and SHA-256 can be preserved.",
        limitations=("Payload tokens have no move, variation, annotation, or legality semantics.",),
    ),
    ChessBaseCapability(
        surface="classic-cbg-moves-variations-annotations",
        status="UNSUPPORTED",
        evidence="No canonical move decoder is enabled.",
        limitations=("Do not create GameTree nodes or PGN by guessing opaque bytes.",),
    ),
    ChessBaseCapability(
        surface="cbv-cbf-2cbh-cbone-content",
        status="UNSUPPORTED",
        evidence="Only filename/family recognition exists.",
        limitations=("No evidence-backed content decoder or fixture corpus is present.",),
    ),
    ChessBaseCapability(
        surface="corrupt-truncated-or-changed-classic-input",
        status="CORRUPT",
        evidence="Bounds, unsupported flags, partial records, and source drift fail closed.",
        limitations=("Valid evidence from independent records may remain available.",),
    ),
    ChessBaseCapability(
        surface="full-or-lossless-chessbase-import",
        status="BLOCKED",
        evidence="Canonical move decoding and broad real-fixture evidence are absent.",
        limitations=(
            "decoder_available remains false",
            "safe_to_import remains false",
            "No full/lossless compatibility claim is permitted",
        ),
    ),
)


def chessbase_capabilities() -> tuple[ChessBaseCapability, ...]:
    return _CAPABILITIES


def chessbase_capability_report() -> dict[str, object]:
    return {
        "schema_version": CAPABILITY_REPORT_SCHEMA_VERSION,
        "adapter_replaceable": True,
        "source_read_only": True,
        "decoder_available": False,
        "safe_to_import": False,
        "capabilities": [item.as_dict() for item in _CAPABILITIES],
    }
