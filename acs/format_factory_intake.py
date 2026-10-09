from __future__ import annotations

"""Section 54 bounded, evidence-first source intake for existing Book importers."""

from dataclasses import dataclass
from hashlib import sha256
from io import BytesIO
from pathlib import PurePosixPath
import re
import stat
from typing import TYPE_CHECKING
from zipfile import BadZipFile, ZipFile

if TYPE_CHECKING:
    from .bookdocument import BookDocument

MAX_FACTORY_SOURCE_BYTES = 64 * 1024 * 1024
MAX_FACTORY_ARCHIVE_ENTRIES = 20_000
MAX_FACTORY_ENTRY_BYTES = 16 * 1024 * 1024
MAX_FACTORY_UNCOMPRESSED_BYTES = 128 * 1024 * 1024

_EXTENSIONS = {
    ".txt": "txt", ".md": "markdown", ".markdown": "markdown",
    ".htm": "html", ".html": "html", ".xhtml": "html",
    ".epub": "epub", ".docx": "docx", ".pdf": "pdf",
    ".pgn": "pgn", ".zip": "zip", ".png": "png",
    ".jpg": "jpeg", ".jpeg": "jpeg", ".cbv": "chessbase",
    ".cbh": "chessbase", ".cbf": "chessbase",
    ".2cbh": "chessbase", ".cbone": "chessbase",
}
_BOOK_FORMATS = frozenset(("txt", "markdown", "html", "epub"))
_PARTIAL_FORMATS = frozenset(("pgn", "docx", "pdf", "png", "jpeg"))


class FactoryIntakeError(ValueError):
    """Stable error that never embeds private source bytes or filesystem paths."""


@dataclass(frozen=True, slots=True)
class FactorySourceReceipt:
    schema_version: int
    sha256: str
    byte_count: int
    source_name: str
    detected_format: str
    declared_format: str | None
    extension_mismatch: bool
    import_status: str
    reason: str

    @property
    def can_import_as_book(self) -> bool:
        return self.import_status == "SUPPORTED_BOOK_INGRESS"


@dataclass(frozen=True, slots=True)
class FactoryImportedBook:
    source: FactorySourceReceipt
    document: "BookDocument"
    importer: str
    warnings: tuple[str, ...]


def _source_name(value: object) -> tuple[str, str | None]:
    if type(value) is not str or not value or len(value) > 1024:
        raise FactoryIntakeError("Source name must be bounded non-empty text")
    if any(ord(c) < 32 or ord(c) == 127 for c in value):
        raise FactoryIntakeError("Source name contains control characters")
    name = value.replace("\\", "/").split("/")[-1]
    if not name or name in (".", "..") or len(name) > 255:
        raise FactoryIntakeError("Source name is invalid")
    suffix = "." + name.rsplit(".", 1)[-1].lower() if "." in name else ""
    return name, _EXTENSIONS.get(suffix)


def _sniff_zip(source: bytes) -> str:
    try:
        with ZipFile(BytesIO(source), "r") as archive:
            infos = archive.infolist()
            if not infos or len(infos) > MAX_FACTORY_ARCHIVE_ENTRIES:
                raise FactoryIntakeError("Archive entry count is invalid")
            total = 0
            seen: set[str] = set()
            for member in infos:
                name = member.filename
                if (not name or "\x00" in name or "\\" in name or
                    name.startswith("/") or re.match(r"^[A-Za-z]:", name) or
                    any(p in ("", ".", "..") for p in name.rstrip("/").split("/"))):
                    raise FactoryIntakeError("Archive member path is unsafe")
                normalized = str(PurePosixPath(name)).casefold()
                if normalized in seen:
                    raise FactoryIntakeError("Archive contains duplicate names")
                seen.add(normalized)
                if member.flag_bits & ((1 << 0) | (1 << 6) | (1 << 13)):
                    raise FactoryIntakeError("Encrypted archive is unsupported")
                mode = (member.external_attr >> 16) & 0xffff
                if stat.S_IFMT(mode) not in (0, stat.S_IFREG, stat.S_IFDIR):
                    raise FactoryIntakeError("Archive contains a special file")
                if member.file_size > MAX_FACTORY_ENTRY_BYTES:
                    raise FactoryIntakeError("Archive entry is too large")
                total += member.file_size
                if total > MAX_FACTORY_UNCOMPRESSED_BYTES:
                    raise FactoryIntakeError("Archive uncompressed size is too large")
                if member.file_size and (
                    not member.compress_size or member.file_size > 2000 * member.compress_size
                ):
                    raise FactoryIntakeError("Archive compression is unsafe")
            if "mimetype" in seen:
                try:
                    mimetype = archive.read("mimetype")
                except (BadZipFile, RuntimeError, ValueError, OSError) as exc:
                    raise FactoryIntakeError("EPUB mimetype cannot be verified") from exc
                if mimetype == b"application/epub+zip":
                    if "meta-inf/container.xml" not in seen:
                        raise FactoryIntakeError("EPUB container descriptor missing")
                    return "epub"
            if "[content_types].xml" in seen and "word/document.xml" in seen:
                return "docx"
            return "zip"
    except (BadZipFile, OSError, OverflowError) as exc:
        raise FactoryIntakeError("Archive structure cannot be verified") from exc


def _sniff_text(source: bytes) -> str:
    try:
        if source.startswith((b"\xff\xfe", b"\xfe\xff")):
            value = source.decode("utf-16")
        else:
            value = source.decode("utf-8-sig")
    except UnicodeDecodeError:
        value = source.decode("cp1251")
    sample = value[:8192]
    if (not sample.strip() or "\x00" in sample or
        any(ord(c) < 32 and c not in "\t\r\n\f" for c in sample)):
        return "unknown"
    stripped = sample.lstrip().lower()
    if stripped.startswith(("<!doctype html", "<html", "<head", "<body")):
        return "html"
    if re.match(r'^\s*\[(Event|Site|Date|Round|White|Black|Result|FEN|SetUp)\s+"', sample):
        return "pgn"
    if re.search(r"(?m)(?:^\s*#{1,6}\s+\S|^\s*\x60{3}(?:pgn|fen|chess))", sample):
        return "markdown"
    return "txt"


def inspect_factory_source(source: bytes, *, source_name: str) -> FactorySourceReceipt:
    """Inspect byte identity and capability without guessing author or edition."""
    if type(source) is not bytes or not source:
        raise FactoryIntakeError("Source must be non-empty immutable bytes")
    if len(source) > MAX_FACTORY_SOURCE_BYTES:
        raise FactoryIntakeError("Source exceeds intake size limit")
    name, declared = _source_name(source_name)
    if source.startswith(b"%PDF-"):
        detected = "pdf"
    elif source.startswith(b"\x89PNG\r\n\x1a\n"):
        detected = "png"
    elif source.startswith(b"\xff\xd8\xff"):
        detected = "jpeg"
    elif source.startswith((b"PK\x03\x04", b"PK\x05\x06", b"PK\x07\x08")):
        detected = _sniff_zip(source)
    else:
        detected = _sniff_text(source)
    if detected in _BOOK_FORMATS:
        status, reason = "SUPPORTED_BOOK_INGRESS", "Canonical importer required"
    elif detected in _PARTIAL_FORMATS:
        status, reason = "PARTIAL", "Semantic conversion is unqualified"
    else:
        status, reason = "UNSUPPORTED", "No qualified importer"
    mismatch = declared is not None and declared != detected
    if mismatch:
        status, reason = "UNSUPPORTED", "Extension and source bytes disagree"
    return FactorySourceReceipt(
        1, sha256(source).hexdigest(), len(source), name, detected,
        declared, mismatch, status, reason,
    )


def import_factory_book(
    source: bytes, *, source_name: str,
    title: str | None = None, author: str | None = None,
    language: str | None = None,
) -> FactoryImportedBook:
    """Call accepted BookDocument ingress; leave PGN rules to canonical owners."""
    receipt = inspect_factory_source(source, source_name=source_name)
    if not receipt.can_import_as_book:
        raise FactoryIntakeError("Source is not qualified for semantic Book import")
    common = dict(
        source_name=receipt.source_name, title=title,
        author=author, language=language,
    )
    if receipt.detected_format in ("txt", "markdown"):
        from .book_text_import import import_text_book
        result = import_text_book(
            source, source_format=receipt.detected_format, **common,
        )
        importer = "acs.book_text_import"
    elif receipt.detected_format == "html":
        from .book_html_import import import_html_book
        result = import_html_book(source, **common)
        importer = "acs.book_html_import"
    else:
        from .book_epub_import import import_epub_book
        result = import_epub_book(source, **common)
        importer = "acs.book_epub_import"
    if result.source_sha256 != receipt.sha256:
        raise FactoryIntakeError("Source digest changed during semantic import")
    return FactoryImportedBook(
        receipt, result.document, importer, tuple(result.warnings),
    )
