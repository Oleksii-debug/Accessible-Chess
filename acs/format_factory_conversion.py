from __future__ import annotations

"""Private, source-verified Section 54 import-select-export conversion slice.

No file writes, external calls, model inference, guessing chess moves or public
publishing. This is a qualified in-memory preview, not a complete book factory.
The trusted host must separately manage output persistence and release rights.
"""

from dataclasses import dataclass
from hashlib import sha256
import re

from .bookdocument import BookDocument
from .format_factory_export import FactoryExportResult, export_factory_preview
from .format_factory_intake import FactoryImportedBook, FactoryIntakeError, import_factory_book
from .format_factory_policy import FactoryJobPolicy, FactorySelection


class FactoryConversionError(ValueError):
    """Stable conversion/review failure without private source content."""


@dataclass(frozen=True, slots=True)
class FactoryConversionResult:
    source_sha256: str
    policy_sha256: str
    import_format: str
    importer: str
    selected_block_count: int
    outputs: tuple[FactoryExportResult, ...]
    source_warnings: tuple[str, ...]
    public_release_approved: bool = False


def _included(n: int, intervals: tuple[tuple[int, int], ...]) -> bool:
    return any(start <= n <= end for start, end in intervals)


def _resolve_selection(document: BookDocument, selection: FactorySelection) -> BookDocument:
    """Enforce complete semantic chapter spans; never invent page/edition anchors."""
    if selection.kind == "all":
        return document
    if selection.kind != "chapters":
        raise FactoryConversionError(
            "Requested scope lacks a qualified canonical anchor resolver"
        )
    wire = document.as_dict()
    blocks = wire["blocks"]
    headings = [
        (index, block["level"]) for index, block in enumerate(blocks)
        if block["kind"] == "Heading"
    ]
    if not headings:
        raise FactoryConversionError("Source contains no semantic chapter headings")
    chapter_level = min(level for _, level in headings)
    starts = [index for index, level in headings if level == chapter_level]
    if not starts:
        raise FactoryConversionError("Source has no resolvable chapter anchors")
    selected: list[dict[str, object]] = []
    found = 0
    for number, start in enumerate(starts, 1):
        end = starts[number] if number < len(starts) else len(blocks)
        if not _included(number, selection.ranges):
            continue
        selected.extend(blocks[start:end])
        found += 1
    expected = sum(end - start + 1 for start, end in selection.ranges)
    if found != expected or not selected:
        raise FactoryConversionError("Some requested chapters are absent from verified source")
    # Use the accepted BookDocument schema/validators, never mutate the input
    # BookDocument or construct shadow semantic block objects.
    return BookDocument.from_dict({**wire, "blocks": selected})


def convert_factory_book_private(
    source: bytes,
    *,
    source_name: str,
    policy: FactoryJobPolicy,
    source_language: str,
    allow_semantic_loss: bool = False,
) -> FactoryConversionResult:
    """Single-call safe conversion of a validated local source to private previews.

    All checks and requested formats finish before any output is returned.
    The source language is an explicit caller assertion; this routine performs
    no translation and must never claim a different output language.
    """
    if type(policy) is not FactoryJobPolicy:
        raise FactoryConversionError("Validated immutable factory policy required")
    if type(source) is not bytes or not source:
        raise FactoryConversionError("Immutable source bytes required")
    source_digest = sha256(source).hexdigest()
    if source_digest != policy.source_sha256:
        raise FactoryConversionError("Source changed since policy approval")
    if (type(source_language) is not str or
            re.fullmatch(r"[a-z]{2,3}(?:-[A-Za-z]{2,8})?", source_language) is None or
            source_language != policy.output_language):
        raise FactoryConversionError("A matching original-language assertion is required; translation is unqualified")
    if policy.allowed_external_search or policy.allowed_external_ai:
        raise FactoryConversionError("External research/AI is not qualified in private preview workflow")
    if type(allow_semantic_loss) is not bool:
        raise FactoryConversionError("Loss permission must be an explicit boolean")
    if any(fmt not in ("html", "txt") for fmt in policy.output_formats):
        raise FactoryConversionError("One or more requested exporters are unqualified")
    try:
        imported: FactoryImportedBook = import_factory_book(
            source, source_name=source_name, language=source_language,
        )
    except (FactoryIntakeError, ValueError) as exc:
        raise FactoryConversionError("Canonical source import failed or is unsupported") from exc
    if imported.source.sha256 != source_digest:
        raise FactoryConversionError("Source identity mismatch after import")
    try:
        selected = _resolve_selection(imported.document, policy.selection)
        rendered = tuple(
            export_factory_preview(
                selected, source_sha256=source_digest, output_format=fmt,
                allow_semantic_loss=allow_semantic_loss,
            )
            for fmt in policy.output_formats
        )
    except (ValueError, TypeError) as exc:
        raise FactoryConversionError("Selected conversion failed or requires semantic review") from exc
    if not rendered:
        raise FactoryConversionError("Empty output set is forbidden")
    return FactoryConversionResult(
        source_sha256=source_digest,
        policy_sha256=policy.digest(),
        import_format=imported.source.detected_format,
        importer=imported.importer,
        selected_block_count=len(selected.blocks),
        outputs=rendered,
        source_warnings=imported.warnings,
    )
