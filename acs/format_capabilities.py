from __future__ import annotations

"""Canonical product capability contract for chess/document interchange formats.

This module is deliberately presentation-neutral. It does not parse chess,
decode proprietary files, own legality, or publish Library state. It gives
application/UI/Agent callers one honest declaration of the operations that the
current product may claim for each format family.

Runtime semantics remain owned by the existing canonical authorities named in
`authority`. In particular, this table never promotes recognition of a
suffix into decoder support and never turns PARTIAL/BLOCKED into SUPPORTED.
"""

from dataclasses import dataclass
from enum import Enum
import json


class CapabilityStatus(str, Enum):
    SUPPORTED = "SUPPORTED"
    PARTIAL = "PARTIAL"
    UNSUPPORTED = "UNSUPPORTED"
    BLOCKED = "BLOCKED"


@dataclass(frozen=True, slots=True)
class FormatCapability:
    format_id: str
    label: str
    extensions: tuple[str, ...]
    read: CapabilityStatus
    edit: CapabilityStatus
    write: CapabilityStatus
    round_trip: CapabilityStatus
    availability: str
    authority: str
    evidence: str
    boundary: str

    def operation_status(self, operation: str) -> CapabilityStatus:
        if operation not in {"read", "edit", "write", "round_trip"}:
            raise KeyError(operation)
        return getattr(self, operation)

    def to_dict(self) -> dict[str, object]:
        return {
            "id": self.format_id,
            "label": self.label,
            "extensions": list(self.extensions),
            "operations": {
                "read": self.read.value,
                "edit": self.edit.value,
                "write": self.write.value,
                "round_trip": self.round_trip.value,
            },
            "availability": self.availability,
            "authority": self.authority,
            "evidence": self.evidence,
            "boundary": self.boundary,
        }


FORMAT_CAPABILITIES: tuple[FormatCapability, ...] = (
    FormatCapability(
        "fen",
        "FEN position",
        (".fen",),
        CapabilityStatus.SUPPORTED,
        CapabilityStatus.PARTIAL,
        CapabilityStatus.SUPPORTED,
        CapabilityStatus.PARTIAL,
        "built_in",
        "acs.position_editor.PositionState + acs.chesscore.Board",
        "Current FEN read/copy and Position Editor qualification lineages",
        "Read/write are built in and validated by the canonical chess core; current full-editor/corpus closure is still converging, so edit/round-trip remain PARTIAL.",
    ),
    FormatCapability(
        "epd",
        "EPD position interchange",
        (".epd",),
        CapabilityStatus.SUPPORTED,
        CapabilityStatus.PARTIAL,
        CapabilityStatus.SUPPORTED,
        CapabilityStatus.PARTIAL,
        "built_in",
        "acs.epd over acs.position_editor.PositionState",
        "Current EPD position-format and composed GameTree qualification",
        "Canonical position fields can be edited through PositionState; unknown operations remain opaque and operation editing/engine-command semantics are not claimed.",
    ),
    FormatCapability(
        "pgn",
        "PGN / GameTree",
        (".pgn",),
        CapabilityStatus.SUPPORTED,
        CapabilityStatus.SUPPORTED,
        CapabilityStatus.SUPPORTED,
        CapabilityStatus.PARTIAL,
        "built_in",
        "acs.pgn + acs.gametree + acs.pgn_workspace",
        "D06 semantic fidelity, editing, streaming, recovery and current composed-apex gates",
        "Representable valid GameTree semantics round-trip; malformed recovery may canonicalize syntax and must surface warnings instead of fabricating chess state.",
    ),
    FormatCapability(
        "acsdb",
        "ACSDB Library database",
        (".acsdb",),
        CapabilityStatus.PARTIAL,
        CapabilityStatus.PARTIAL,
        CapabilityStatus.PARTIAL,
        CapabilityStatus.PARTIAL,
        "built_in",
        "acs.acsdb + acs.library_import_service",
        "Library/ACSDB/search/import/export qualification lineages",
        "Internal durable Library format; current open convergence/qualification work prevents a whole-product SUPPORTED closure claim.",
    ),
    FormatCapability(
        "book-txt",
        "Plain-text chess book",
        (".txt",),
        CapabilityStatus.SUPPORTED,
        CapabilityStatus.UNSUPPORTED,
        CapabilityStatus.UNSUPPORTED,
        CapabilityStatus.UNSUPPORTED,
        "built_in",
        "acs.book_text_import -> BookDocument",
        "Book text import and semantic-reading regressions",
        "Semantic import is supported; source-format editing/writeback is not claimed.",
    ),
    FormatCapability(
        "book-markdown",
        "Markdown chess book",
        (".md", ".markdown"),
        CapabilityStatus.SUPPORTED,
        CapabilityStatus.UNSUPPORTED,
        CapabilityStatus.UNSUPPORTED,
        CapabilityStatus.UNSUPPORTED,
        "built_in",
        "Markdown semantic import -> BookDocument",
        "Current Markdown semantic and malformed-content qualification",
        "Semantic import is supported; source-format editing/writeback is not claimed.",
    ),
    FormatCapability(
        "book-html",
        "HTML chess book",
        (".html", ".htm"),
        CapabilityStatus.SUPPORTED,
        CapabilityStatus.UNSUPPORTED,
        CapabilityStatus.UNSUPPORTED,
        CapabilityStatus.UNSUPPORTED,
        "built_in",
        "acs.book_html_import -> BookDocument",
        "HTML semantic, resource-bound and malformed-content qualification",
        "Semantic import is supported; active content is not a chess authority and source-format writeback is not claimed.",
    ),
    FormatCapability(
        "book-epub",
        "EPUB chess book",
        (".epub",),
        CapabilityStatus.SUPPORTED,
        CapabilityStatus.UNSUPPORTED,
        CapabilityStatus.UNSUPPORTED,
        CapabilityStatus.UNSUPPORTED,
        "built_in",
        "acs.book_epub_import -> BookDocument",
        "EPUB semantic/resource/recovery qualification",
        "Semantic import is supported; source-format editing/writeback is not claimed.",
    ),
    FormatCapability(
        "chessbase-cbh",
        "ChessBase CBH family",
        (".cbh",),
        CapabilityStatus.PARTIAL,
        CapabilityStatus.UNSUPPORTED,
        CapabilityStatus.UNSUPPORTED,
        CapabilityStatus.UNSUPPORTED,
        "optional_external_backend",
        "existing CBH adapter + canonical GameTree/ACSDB publication",
        "docs/automation/DEV4_CHESSBASE_CAPABILITY_MATRIX.md",
        "Read is conditional on the pinned external backend and qualified Standard records. Chess960/Fischer Random remains UNSUPPORTED; no writeback.",
    ),
    FormatCapability(
        "chessbase-cbv",
        "ChessBase CBV archive",
        (".cbv",),
        CapabilityStatus.PARTIAL,
        CapabilityStatus.UNSUPPORTED,
        CapabilityStatus.UNSUPPORTED,
        CapabilityStatus.UNSUPPORTED,
        "optional_external_backend",
        "existing CBV extractor + CBH adapter + canonical GameTree/ACSDB publication",
        "docs/automation/DEV4_CHESSBASE_CAPABILITY_MATRIX.md",
        "Read is conditional on both qualified external backends and the inherited CBH semantic boundary; no writeback.",
    ),
    FormatCapability(
        "chessbase-cbf-cbi",
        "Legacy ChessBase CBF/CBI pair",
        (".cbf", ".cbi"),
        CapabilityStatus.BLOCKED,
        CapabilityStatus.UNSUPPORTED,
        CapabilityStatus.UNSUPPORTED,
        CapabilityStatus.UNSUPPORTED,
        "blocked_external_evidence",
        "recognition/integrity only; no semantic decoder registered",
        "docs/automation/V2_CHESSBASE_CAPABILITIES.json",
        "Blocked pending a lawful authentic same-stem fixture corpus, independent semantic oracle and qualified bounded decoder.",
    ),
    FormatCapability(
        "chessbase-2cbh",
        "ChessBase 2CBH",
        (".2cbh",),
        CapabilityStatus.BLOCKED,
        CapabilityStatus.UNSUPPORTED,
        CapabilityStatus.UNSUPPORTED,
        CapabilityStatus.UNSUPPORTED,
        "blocked_external_evidence",
        "recognition/fingerprinting only",
        "docs/automation/DEV4_CHESSBASE_CAPABILITY_MATRIX.md",
        "No fixture-backed semantic decoder is qualified.",
    ),
    FormatCapability(
        "chessbase-2cbv",
        "ChessBase 2CBV archive",
        (".2cbv",),
        CapabilityStatus.BLOCKED,
        CapabilityStatus.UNSUPPORTED,
        CapabilityStatus.UNSUPPORTED,
        CapabilityStatus.UNSUPPORTED,
        "blocked_external_evidence",
        "recognition/evidence lineages only; no current runtime decoder registration",
        "live evidence lineages #429/#431/#459",
        "Official archive-family identity and real paired-source evidence exist, but no qualified semantic decoder/publication path is integrated into the current product apex.",
    ),
    FormatCapability(
        "chessbase-2cbz",
        "ChessBase 2CBZ encrypted archive",
        (".2cbz",),
        CapabilityStatus.BLOCKED,
        CapabilityStatus.UNSUPPORTED,
        CapabilityStatus.UNSUPPORTED,
        CapabilityStatus.UNSUPPORTED,
        "blocked_external_evidence",
        "recognition/evidence only; no current runtime decoder registration",
        "live evidence lineage #316",
        "Encrypted/archive-family recognition evidence exists, but no qualified decryption/semantic decoder/publication path is integrated; no silent password handling.",
    ),
    FormatCapability(
        "chessbase-cbone",
        "ChessBase CBONE",
        (".cbone",),
        CapabilityStatus.BLOCKED,
        CapabilityStatus.UNSUPPORTED,
        CapabilityStatus.UNSUPPORTED,
        CapabilityStatus.UNSUPPORTED,
        "blocked_external_evidence",
        "recognition/fingerprinting only",
        "docs/automation/DEV4_CHESSBASE_CAPABILITY_MATRIX.md",
        "No fixture-backed semantic decoder is qualified.",
    ),
    FormatCapability(
        "chessbase-cbz",
        "ChessBase CBZ encrypted archive",
        (".cbz",),
        CapabilityStatus.BLOCKED,
        CapabilityStatus.UNSUPPORTED,
        CapabilityStatus.UNSUPPORTED,
        CapabilityStatus.UNSUPPORTED,
        "blocked_external_evidence",
        "recognition/research only",
        "docs/automation/DEV4_CHESSBASE_CAPABILITY_MATRIX.md",
        "Password/decryption lifecycle is not implemented; no silent password handling is allowed.",
    ),
)


def validate_format_capabilities(
    capabilities: tuple[FormatCapability, ...] = FORMAT_CAPABILITIES,
) -> None:
    if type(capabilities) is not tuple or not capabilities:
        raise ValueError("format capability registry must be a non-empty tuple")

    seen_ids: set[str] = set()
    seen_extensions: set[str] = set()
    for item in capabilities:
        if type(item) is not FormatCapability:
            raise TypeError("format capability entries must be exact FormatCapability values")
        if not item.format_id or item.format_id != item.format_id.strip():
            raise ValueError("format capability id must be non-empty canonical text")
        if item.format_id in seen_ids:
            raise ValueError(f"duplicate format capability id: {item.format_id}")
        seen_ids.add(item.format_id)

        if type(item.extensions) is not tuple or not item.extensions:
            raise ValueError(f"{item.format_id}: extensions must be a non-empty tuple")
        for extension in item.extensions:
            if (
                type(extension) is not str
                or not extension.startswith(".")
                or extension != extension.lower()
                or extension != extension.strip()
            ):
                raise ValueError(f"{item.format_id}: invalid extension {extension!r}")
            if extension in seen_extensions:
                raise ValueError(f"duplicate format extension: {extension}")
            seen_extensions.add(extension)

        for field_name in ("label", "availability", "authority", "evidence", "boundary"):
            value = getattr(item, field_name)
            if type(value) is not str or not value.strip():
                raise ValueError(f"{item.format_id}: {field_name} must be non-empty text")

        statuses = (item.read, item.edit, item.write, item.round_trip)
        if any(type(status) is not CapabilityStatus for status in statuses):
            raise TypeError(f"{item.format_id}: operation statuses must be CapabilityStatus")

        if item.round_trip in {CapabilityStatus.SUPPORTED, CapabilityStatus.PARTIAL}:
            if item.read in {CapabilityStatus.UNSUPPORTED, CapabilityStatus.BLOCKED}:
                raise ValueError(f"{item.format_id}: round-trip requires readable semantics")
            if item.write in {CapabilityStatus.UNSUPPORTED, CapabilityStatus.BLOCKED}:
                raise ValueError(f"{item.format_id}: round-trip requires writable semantics")

        if item.availability == "optional_external_backend":
            if item.read is not CapabilityStatus.PARTIAL:
                raise ValueError(
                    f"{item.format_id}: optional external backend must remain PARTIAL"
                )
            if any(
                status is not CapabilityStatus.UNSUPPORTED
                for status in (item.edit, item.write, item.round_trip)
            ):
                raise ValueError(
                    f"{item.format_id}: proprietary optional backend must not imply writeback"
                )

        if item.availability == "blocked_external_evidence":
            if item.read is not CapabilityStatus.BLOCKED:
                raise ValueError(
                    f"{item.format_id}: externally blocked read path must stay BLOCKED"
                )
            if any(
                status is not CapabilityStatus.UNSUPPORTED
                for status in (item.edit, item.write, item.round_trip)
            ):
                raise ValueError(
                    f"{item.format_id}: blocked decoder evidence must not imply writeback"
                )


def capability_by_id(format_id: str) -> FormatCapability:
    if type(format_id) is not str:
        raise TypeError("format_id must be exact text")
    for capability in FORMAT_CAPABILITIES:
        if capability.format_id == format_id:
            return capability
    raise KeyError(format_id)


def public_capability_payload() -> dict[str, object]:
    validate_format_capabilities()
    return {
        "schema_version": 1,
        "authority": "acs.format_capabilities.FORMAT_CAPABILITIES",
        "status_vocabulary": [status.value for status in CapabilityStatus],
        "operation_semantics": {
            "read": "Parse, import, or otherwise adopt source semantics into a canonical in-memory/product model under the declared boundary.",
            "edit": "Modify the canonical semantic state through a supported product editing workflow; this does not imply source-format writeback.",
            "write": "Serialize/export canonical semantic state to this interchange format; for textual position formats this may be canonical text rather than a dedicated file-save command.",
            "round_trip": "Read then write/reopen while preserving the semantics claimed by the boundary; PARTIAL explicitly permits only the documented bounded subset/loss policy.",
        },
        "semantics": {
            "SUPPORTED": "Built-in evidence supports the declared operation under its stated boundary.",
            "PARTIAL": "The operation is intentionally conditional or loss-bounded; the boundary field is part of the claim.",
            "UNSUPPORTED": "The product deliberately does not claim this operation.",
            "BLOCKED": "The operation is planned/recognized but cannot be promoted without the stated missing evidence or dependency.",
        },
        "formats": [item.to_dict() for item in FORMAT_CAPABILITIES],
        "invariants": [
            "Recognition of a filename or suffix is not decoder support.",
            "Format code never owns chess legality; accepted chess state is validated by canonical chess/application authorities.",
            "Malformed or unsupported input must fail closed or produce explicit bounded loss/warning evidence; it must not publish a fabricated position.",
            "Optional/proprietary read support does not imply bundled decoder availability or writeback support.",
        ],
    }


def render_json() -> str:
    return json.dumps(
        public_capability_payload(),
        ensure_ascii=False,
        indent=2,
        sort_keys=True,
    ) + "\n"


def _markdown_cell(value: str) -> str:
    return value.replace("\\", "\\\\").replace("|", "\\|").replace("\n", " ")


def render_markdown() -> str:
    validate_format_capabilities()
    lines = [
        "# Canonical format capability matrix",
        "",
        "Generated deterministically from `acs.format_capabilities.FORMAT_CAPABILITIES`.",
        "Do not edit this table independently; change the typed authority and regenerate.",
        "",
        "Status vocabulary: `SUPPORTED`, `PARTIAL`, `UNSUPPORTED`, `BLOCKED`.",
        "`PARTIAL` and `BLOCKED` are product truth, not temporary aliases for support.",
        "",
        "Operation meanings:",
        "- **Read**: parse/import/adopt source semantics into a canonical product model.",
        "- **Edit**: modify canonical semantic state through a supported product editing workflow; not source writeback.",
        "- **Write**: serialize/export canonical semantic state to this interchange format; textual position formats may produce canonical text rather than a dedicated file-save command.",
        "- **Round-trip**: read then write/reopen with the semantics stated by the boundary preserved.",
        "",
        "| Format | Extensions | Read | Edit | Write | Round-trip | Availability | Boundary |",
        "| --- | --- | --- | --- | --- | --- | --- | --- |",
    ]
    for item in FORMAT_CAPABILITIES:
        lines.append(
            "| "
            + " | ".join(
                (
                    _markdown_cell(item.label),
                    _markdown_cell(", ".join(item.extensions)),
                    item.read.value,
                    item.edit.value,
                    item.write.value,
                    item.round_trip.value,
                    _markdown_cell(item.availability),
                    _markdown_cell(item.boundary),
                )
            )
            + " |"
        )
    lines.extend(
        [
            "",
            "## Authority rule",
            "",
            "This matrix declares capabilities only. FEN/SAN/legality, GameTree, PGN,",
            "Library publication and BookDocument semantics remain owned by their existing",
            "canonical modules. Format adapters may validate syntax and bounded transport,",
            "but they must not invent a legal move or publish a chess position rejected by",
            "the canonical chess/application authority.",
            "",
            "## ChessBase evidence relationship",
            "",
            "`docs/automation/DEV4_CHESSBASE_CAPABILITY_MATRIX.md` remains the detailed",
            "CBH/CBV/variant evidence source. `docs/automation/V2_CHESSBASE_CAPABILITIES.json`",
            "remains the CBF/CBI evidence-only source. This whole-product matrix consumes",
            "those boundaries; it does not replace or silently promote them.",
            "",
        ]
    )
    return "\n".join(lines)


validate_format_capabilities()
