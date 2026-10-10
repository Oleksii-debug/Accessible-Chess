from __future__ import annotations

"""Section 54.1: isolated, source-bound text-PDF probe, NOT a PDF book importer.

The canonical factory intake decides PDF identity/capability. This bounded worker
only returns untrusted page text and explicit REVIEW_REQUIRED evidence. It never
changes BookDocument, runs OCR, touches the network, or grants publication rights.
"""

from dataclasses import dataclass, field
from multiprocessing import get_context
from multiprocessing.connection import Connection

from .format_factory_intake import inspect_factory_source

MAX_PDF_SOURCE_BYTES = 8 * 1024 * 1024
MAX_PDF_PAGES = 128
MAX_PAGE_CHARACTERS = 20_000
MAX_TOTAL_CHARACTERS = 300_000


class FactoryPdfProbeError(ValueError):
    """Non-disclosing error; no source text or user path in messages."""


@dataclass(frozen=True, slots=True)
class FactoryPdfPage:
    file_page: int
    anchor: str
    text: str
    review_status: str = field(default="REVIEW_REQUIRED", init=False)


@dataclass(frozen=True, slots=True)
class FactoryPdfProbe:
    original_source_sha256: str
    original_byte_count: int
    page_count: int
    pages: tuple[FactoryPdfPage, ...]
    warnings: tuple[str, ...]
    review_status: str = "REVIEW_REQUIRED"
    public_release_approved: bool = field(default=False, init=False)


def _bounded_extract(source: bytes) -> tuple[int, list[tuple[int, str]], list[str]]:
    from io import BytesIO
    from pypdf import PdfReader

    reader = PdfReader(BytesIO(source), strict=True)
    try:
        if reader.is_encrypted:
            raise FactoryPdfProbeError("Encrypted PDF requires separate authorization")
        count = len(reader.pages)
        if count < 1 or count > MAX_PDF_PAGES:
            raise FactoryPdfProbeError("PDF page count exceeds qualified bounds")
        pages: list[tuple[int, str]] = []
        warnings: list[str] = []
        total = 0
        for index, page in enumerate(reader.pages, 1):
            text = page.extract_text() or ""
            if type(text) is not str:
                raise FactoryPdfProbeError("PDF text extraction is ambiguous")
            if not text.strip():
                warnings.append(f"FILE_PAGE_{index}_NO_EXTRACTABLE_TEXT")
            if any(ord(ch) == 0 for ch in text):
                raise FactoryPdfProbeError("PDF page contains ambiguous text")
            if len(text) > MAX_PAGE_CHARACTERS:
                raise FactoryPdfProbeError("PDF page text exceeds qualified bounds")
            total += len(text)
            if total > MAX_TOTAL_CHARACTERS:
                raise FactoryPdfProbeError("PDF total text exceeds qualified bounds")
            pages.append((index, text))
        warnings.extend((
            "PRINTED_PAGE_MAPPING_NOT_PROVEN",
            "READING_ORDER_NOT_PROVEN",
            "DIAGRAMS_AND_CHESS_NOTATION_NOT_VERIFIED",
            "COPYRIGHT_PERMISSION_NOT_VERIFIED",
        ))
        return count, pages, warnings
    finally:
        reader.close()


def _worker(conn: Connection, source: bytes) -> None:
    try:
        # POSIX-only memory ceiling; Windows still needs Job Object qualification.
        try:
            import resource
            limit = 512 * 1024 * 1024
            resource.setrlimit(resource.RLIMIT_AS, (limit, limit))
        except (ImportError, OSError, ValueError):
            pass
        try:
            result = _bounded_extract(source)
            conn.send(("ok", result))
        except Exception as exc:
            if isinstance(exc, FactoryPdfProbeError):
                conn.send(("error", str(exc)))
            elif isinstance(exc, (ImportError, ModuleNotFoundError)):
                conn.send(("error", "Optional pypdf PDF reader is not installed"))
            else:
                conn.send(("error", "PDF text could not be safely extracted"))
    finally:
        conn.close()


def probe_factory_text_pdf(
    source: bytes, *, source_name: str, timeout_seconds: float = 15.0,
) -> FactoryPdfProbe:
    """Local-only, bounded partial text evidence. Every page needs review."""
    receipt = inspect_factory_source(source, source_name=source_name)
    if receipt.detected_format != "pdf" or receipt.extension_mismatch:
        raise FactoryPdfProbeError("Source is not a matching PDF")
    if receipt.byte_count > MAX_PDF_SOURCE_BYTES:
        raise FactoryPdfProbeError("PDF exceeds bounded probe size")
    if type(timeout_seconds) not in (int, float) or not 0.1 <= timeout_seconds <= 60:
        raise FactoryPdfProbeError("Invalid probe time limit")
    ctx = get_context("spawn")
    parent, child = ctx.Pipe(duplex=False)
    process = ctx.Process(target=_worker, args=(child, source), daemon=True)
    try:
        try:
            process.start()
        except (OSError, RuntimeError, ValueError) as exc:
            raise FactoryPdfProbeError("Isolated PDF worker could not be started") from exc
        child.close()
        if not parent.poll(timeout_seconds):
            raise FactoryPdfProbeError("PDF probe time limit exceeded")
        try:
            status, payload = parent.recv()
        except (EOFError, OSError, ValueError) as exc:
            raise FactoryPdfProbeError("PDF probe worker ended without verified result") from exc
        if status != "ok":
            raise FactoryPdfProbeError(str(payload))
        count, raw_pages, warnings = payload
        if (type(count) is not int or not 1 <= count <= MAX_PDF_PAGES or
                type(raw_pages) is not list or len(raw_pages) != count):
            raise FactoryPdfProbeError("PDF probe returned invalid page mapping")
        pages = tuple(
            FactoryPdfPage(index, f"pdf:file-page:{index}", text)
            for index, text in raw_pages
        )
        if any(p.file_page != i for i, p in enumerate(pages, 1)):
            raise FactoryPdfProbeError("PDF probe returned invalid page order")
        return FactoryPdfProbe(
            receipt.sha256, receipt.byte_count, count,
            pages, tuple(warnings),
        )
    finally:
        parent.close()
        if process.pid is not None:
            if process.is_alive():
                process.terminate()
            process.join(timeout=2)
            if process.is_alive():
                process.kill()
                process.join(timeout=2)
        child.close()
