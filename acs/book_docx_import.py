from __future__ import annotations

"""Bounded local DOCX ingestion into the semantic BookDocument path.

DOCX is an OPC/ZIP package. This adapter reads only local package XML, preserves
reading text/headings/list hints and image alternative text, and then delegates
semantic text projection to the existing Markdown importer. It never executes
macros, resolves external relationships, uses Word/Office automation, calls the
network, or infers a chess position from an embedded image.
"""

from dataclasses import dataclass
from hashlib import sha256
from io import BytesIO
from pathlib import PurePosixPath
import re
import stat
import xml.etree.ElementTree as ET
import zipfile

from .book_text_import import BookTextImportError, import_text_book
from .bookdocument import BookDocument


MAX_DOCX_SOURCE_BYTES = 64 * 1024 * 1024
MAX_DOCX_ENTRIES = 4096
MAX_DOCX_UNCOMPRESSED_BYTES = 256 * 1024 * 1024
MAX_DOCX_XML_BYTES = 32 * 1024 * 1024

_W = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
_WP = "http://schemas.openxmlformats.org/drawingml/2006/wordprocessingDrawing"
_XML = "http://www.w3.org/XML/1998/namespace"
_HEADING_NAME_RE = re.compile(r"^(?:heading|заголовок)\s*([1-6])$", re.I)


class BookDocxImportError(ValueError):
    pass


@dataclass(frozen=True, slots=True)
class BookDocxImportResult:
    document: BookDocument
    source_sha256: str
    book_key: str
    pgn_games: int
    positions: int
    warnings: tuple[str, ...]


def _safe_name(name: str) -> str:
    normalized = name.replace("\\", "/")
    path = PurePosixPath(normalized)
    if (
        not normalized
        or normalized.startswith("/")
        or ":" in path.parts[0]
        or any(part in {"", ".", ".."} for part in path.parts)
    ):
        raise BookDocxImportError("DOCX contains an unsafe package entry")
    return str(path)


def _archive_index(archive: zipfile.ZipFile) -> dict[str, zipfile.ZipInfo]:
    infos = archive.infolist()
    if not 1 <= len(infos) <= MAX_DOCX_ENTRIES:
        raise BookDocxImportError("DOCX package entry count is unsupported")
    total = 0
    index: dict[str, zipfile.ZipInfo] = {}
    folded: set[str] = set()
    for info in infos:
        name = _safe_name(info.filename)
        mode = (info.external_attr >> 16) & 0xFFFF
        if stat.S_ISLNK(mode):
            raise BookDocxImportError("DOCX package must not contain symlinks")
        if info.file_size < 0 or info.compress_size < 0:
            raise BookDocxImportError("DOCX package entry size is invalid")
        total += info.file_size
        if total > MAX_DOCX_UNCOMPRESSED_BYTES:
            raise BookDocxImportError("DOCX uncompressed package exceeds the safety limit")
        key = name.casefold()
        if key in folded:
            raise BookDocxImportError("DOCX package contains duplicate or colliding entries")
        folded.add(key)
        index[name] = info
    return index


def _read_entry(
    archive: zipfile.ZipFile,
    index: dict[str, zipfile.ZipInfo],
    name: str,
    *,
    limit: int = MAX_DOCX_XML_BYTES,
) -> bytes:
    info = index.get(name)
    if info is None:
        raise BookDocxImportError(f"DOCX required package part is missing: {name}")
    if info.file_size > limit:
        raise BookDocxImportError("DOCX XML part exceeds the safety limit")
    try:
        payload = archive.read(info)
    except (OSError, RuntimeError, zipfile.BadZipFile) as exc:
        raise BookDocxImportError("DOCX package part could not be read") from exc
    if len(payload) != info.file_size or len(payload) > limit:
        raise BookDocxImportError("DOCX package part changed size while reading")
    return payload


def _xml(payload: bytes, label: str) -> ET.Element:
    if b"<!DOCTYPE" in payload.upper() or b"<!ENTITY" in payload.upper():
        raise BookDocxImportError(f"DOCX {label} contains unsupported XML declarations")
    try:
        return ET.fromstring(payload)
    except ET.ParseError as exc:
        raise BookDocxImportError(f"DOCX {label} XML is malformed") from exc


def _styles(archive: zipfile.ZipFile, index: dict[str, zipfile.ZipInfo]) -> dict[str, int]:
    if "word/styles.xml" not in index:
        return {}
    root = _xml(_read_entry(archive, index, "word/styles.xml"), "styles")
    result: dict[str, int] = {}
    for style in root.findall(f".//{{{_W}}}style"):
        style_id = style.get(f"{{{_W}}}styleId")
        if not style_id:
            continue
        level = None
        outline = style.find(f".//{{{_W}}}outlineLvl")
        if outline is not None:
            raw = outline.get(f"{{{_W}}}val")
            if raw is not None and raw.isdigit() and 0 <= int(raw) <= 5:
                level = int(raw) + 1
        if level is None:
            name = style.find(f"{{{_W}}}name")
            label = name.get(f"{{{_W}}}val", "") if name is not None else ""
            match = _HEADING_NAME_RE.match(label.strip())
            if match:
                level = int(match.group(1))
        if level is not None:
            result[style_id] = level
    return result


def _paragraph_text(paragraph: ET.Element) -> str:
    parts: list[str] = []
    for node in paragraph.iter():
        if node.tag == f"{{{_W}}}t":
            parts.append(node.text or "")
        elif node.tag == f"{{{_W}}}tab":
            parts.append("\t")
        elif node.tag in {f"{{{_W}}}br", f"{{{_W}}}cr"}:
            parts.append("\n")
    return "".join(parts).strip()


def _paragraph_alt_texts(paragraph: ET.Element) -> list[str]:
    values: list[str] = []
    for node in paragraph.iter(f"{{{_WP}}}docPr"):
        value = (node.get("descr") or node.get("title") or "").strip()
        if value and value not in values:
            values.append(value)
    return values


def _paragraph_style(paragraph: ET.Element) -> str | None:
    style = paragraph.find(f"./{{{_W}}}pPr/{{{_W}}}pStyle")
    if style is None:
        return None
    value = style.get(f"{{{_W}}}val")
    return value.strip() if value else None


def _is_list_paragraph(paragraph: ET.Element) -> bool:
    return paragraph.find(f"./{{{_W}}}pPr/{{{_W}}}numPr") is not None


def _markdown_from_document(root: ET.Element, heading_styles: dict[str, int]) -> tuple[str, tuple[str, ...]]:
    lines: list[str] = []
    warnings: list[str] = []
    image_count = 0
    for paragraph in root.iter(f"{{{_W}}}p"):
        text = _paragraph_text(paragraph)
        alt_texts = _paragraph_alt_texts(paragraph)
        style = _paragraph_style(paragraph)
        level = heading_styles.get(style or "")
        if text:
            if level is not None:
                lines.extend(("#" * level + " " + text, ""))
            elif _is_list_paragraph(paragraph):
                lines.extend(("- " + text, ""))
            else:
                lines.extend((text, ""))
        for alt in alt_texts:
            image_count += 1
            safe = alt.replace("]", ")").replace("\n", " ").strip()
            if safe:
                lines.extend((f"![{safe}](docx-embedded-image-{image_count})", ""))
    markdown = "\n".join(lines).strip()
    if image_count:
        warnings.append(
            "DOCX embedded images were preserved only through available alternative text; no chess position was inferred from image pixels"
        )
    return markdown, tuple(warnings)


def import_docx_book(
    source: bytes,
    *,
    source_name: str,
) -> BookDocxImportResult:
    if type(source) is not bytes:
        raise TypeError("DOCX source must be bytes")
    if not source or len(source) > MAX_DOCX_SOURCE_BYTES:
        raise BookDocxImportError("DOCX source size is unsupported")
    if type(source_name) is not str or not source_name.strip():
        raise TypeError("source_name must be non-empty text")

    try:
        archive = zipfile.ZipFile(BytesIO(source), "r")
    except (zipfile.BadZipFile, OSError) as exc:
        raise BookDocxImportError("DOCX source is not a valid ZIP package") from exc

    with archive:
        index = _archive_index(archive)
        document = _xml(
            _read_entry(archive, index, "word/document.xml"),
            "document",
        )
        markdown, warnings = _markdown_from_document(
            document,
            _styles(archive, index),
        )

    if not markdown.strip():
        raise BookDocxImportError("DOCX contains no readable text or alternative text")
    try:
        imported = import_text_book(
            markdown,
            source_name=source_name.strip(),
            source_format="markdown",
        )
    except BookTextImportError as exc:
        raise BookDocxImportError("DOCX semantic text could not be imported") from exc

    digest = sha256(source).hexdigest()
    combined_warnings = tuple(dict.fromkeys((*warnings, *imported.warnings)))
    imported.document.source_name = source_name.strip()
    imported.document.warnings = list(combined_warnings)
    return BookDocxImportResult(
        document=imported.document,
        source_sha256=digest,
        book_key=f"docx-sha256:{digest}",
        pgn_games=imported.pgn_games,
        positions=imported.positions,
        warnings=combined_warnings,
    )


__all__ = [
    "BookDocxImportError",
    "BookDocxImportResult",
    "MAX_DOCX_SOURCE_BYTES",
    "import_docx_book",
]
