from __future__ import annotations

"""Private PDF-text -> canonical BookDocument projection; never a verified book.

Reuse Section 54's isolated PDF probe and the existing TXT importer. PDF page
provenance and extracted-text provenance are kept separate; no second semantic
schema, PGN parser, chess rules, OCR, or author-rights inference is introduced.
"""

from dataclasses import dataclass, field
from hashlib import sha256
from typing import TYPE_CHECKING

from .book_text_import import BookTextImportError, import_text_book
from .format_factory_pdf_probe import (
    FactoryPdfProbe,
    FactoryPdfProbeError,
    probe_factory_text_pdf,
)

if TYPE_CHECKING:
    from .bookdocument import BookDocument


@dataclass(frozen=True, slots=True)
class FactoryPdfTextProjection:
    probe: FactoryPdfProbe
    document: "BookDocument"
    projected_text_sha256: str
    page_start_lines: tuple[int, ...]
    warnings: tuple[str, ...]
    review_status: str = field(default="REVIEW_REQUIRED", init=False)
    public_release_approved: bool = field(default=False, init=False)


def project_factory_text_pdf_private(
    source: bytes, *, source_name: str,
    title: str | None = None, language: str | None = None,
    timeout_seconds: float = 15.0,
) -> FactoryPdfTextProjection:
    """Project ALL pages to canonical readable paragraphs, or fail atomically.

    Nothing in this partial projection confirms PDF reading order, exact layout,
    embedded diagrams, author's chess notation or copyrighted distribution.
    The original source bytes are never mutated. Unreadable pages cannot be
    silently skipped; proper OCR/reconciliation belongs to later factory work.
    """
    probe = probe_factory_text_pdf(
        source, source_name=source_name, timeout_seconds=timeout_seconds,
    )
    pages: list[str] = []
    lines: list[int] = []
    line = 1
    for page in probe.pages:
        text = page.text.replace("\r\n", "\n").replace("\r", "\n").strip("\n")
        if not text.strip():
            raise FactoryPdfProbeError(
                "PDF contains a page requiring OCR or independent review"
            )
        lines.append(line)
        pages.append(text)
        line += text.count("\n") + 2

    projected = "\n\n".join(pages)
    # Text that merely looks like SAN, FEN or an ASCII diagram remains ordinary
    # prose, as specified by the existing TXT importer contract.
    try:
        imported = import_text_book(
            projected, source_name=source_name, source_format="txt",
            title=title, language=language,
        )
    except (BookTextImportError, ValueError, TypeError) as exc:
        raise FactoryPdfProbeError(
            "PDF text cannot be represented by the canonical BookDocument"
        ) from exc
    digest = sha256(projected.encode("utf-8")).hexdigest()
    if imported.source_sha256 != digest or imported.pgn_games or imported.positions:
        raise FactoryPdfProbeError(
            "Canonical PDF text projection identity or chess safety failed"
        )
    warnings = tuple(probe.warnings) + (
        "PDF_TEXT_ONLY_PRIVATE_PREVIEW_REVIEW_REQUIRED",
    ) + tuple(imported.warnings)
    imported.document.warnings.extend(warnings)
    imported.document.as_dict()
    return FactoryPdfTextProjection(
        probe, imported.document, digest, tuple(lines), warnings,
    )
