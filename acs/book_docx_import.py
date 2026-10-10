from __future__ import annotations

"""Bounded, read-only DOCX -> canonical BookDocument semantic ingress.

This module reads WordprocessingML paragraphs/headings and image alternative
text. It implements no chess rules, OCR, remote fetching, macros or source-file
writeback. Images without explicit verified FEN remain notes, never positions.
"""

from dataclasses import dataclass
from hashlib import sha256
import io
from pathlib import PurePosixPath
import re
import stat
from typing import Callable
import xml.etree.ElementTree as ET
import zipfile

from .bookdocument import BookDocument, Heading, Note, Paragraph


MAX_DOCX_SOURCE_BYTES = 20 * 1024 * 1024
_MAX_DOCX_XML_BYTES = 20 * 1024 * 1024
_MAX_DOCX_EXPANDED_BYTES = 48 * 1024 * 1024
_MAX_DOCX_MEMBERS = 4096
_MAX_DOCX_BLOCKS = 20_000
_MAX_DOCX_TEXT = 8 * 1024 * 1024
_NS_WORD = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
_NS_DC = "http://purl.org/dc/elements/1.1/"
_NS_WP = "http://schemas.openxmlformats.org/drawingml/2006/wordprocessingDrawing"
_W = "{" + _NS_WORD + "}"
_DC = "{" + _NS_DC + "}"
_WP = "{" + _NS_WP + "}"
_HEADING = re.compile(r"^Heading\s*([1-6])$", re.IGNORECASE)


class DocxBookImportError(ValueError):
    """Stable, path-free refusal for unqualified or damaged DOCX packages."""


@dataclass(frozen=True, slots=True)
class DocxBookImportResult:
    document: BookDocument
    source_sha256: str
    book_key: str
    warnings: tuple[str, ...]


def _checkpoint(callback: Callable[[], None] | None) -> None:
    if callback is not None:
        callback()


def _parse_xml(payload: bytes, label: str) -> ET.Element:
    if b"<!DOCTYPE" in payload.upper() or b"<!ENTITY" in payload.upper():
        raise DocxBookImportError("DOCX XML entity declarations are not supported")
    try:
        return ET.fromstring(payload)
    except ET.ParseError as exc:
        raise DocxBookImportError("DOCX XML structure is invalid") from exc


def _safe_members(archive: zipfile.ZipFile) -> dict[str, zipfile.ZipInfo]:
    members = archive.infolist()
    if not members or len(members) > _MAX_DOCX_MEMBERS:
        raise DocxBookImportError("DOCX member count is invalid")
    result: dict[str, zipfile.ZipInfo] = {}
    expanded = 0
    for item in members:
        name = item.filename
        parts = name.split("/")
        mode = (item.external_attr >> 16) & 0xFFFF
        if (
            not name or len(name) > 512 or "\\" in name or name.startswith("/")
            or any(part in {".", ".."} for part in parts)
            or (item.flag_bits & 1)
            or stat.S_IFMT(mode) not in {0, stat.S_IFREG, stat.S_IFDIR}
            or name in result
            or name.rsplit("/", 1)[-1].casefold() in {"vbaproject.bin", "vbadata.xml"}
        ):
            raise DocxBookImportError("DOCX archive contains unsafe members")
        if not item.is_dir():
            expanded += item.file_size
            if item.file_size > _MAX_DOCX_XML_BYTES or expanded > _MAX_DOCX_EXPANDED_BYTES:
                raise DocxBookImportError("DOCX expanded content exceeds limits")
        result[name] = item
    if "word/document.xml" not in result or result["word/document.xml"].is_dir():
        raise DocxBookImportError("DOCX has no Word document body")
    if "[Content_Types].xml" not in result or result["[Content_Types].xml"].is_dir():
        raise DocxBookImportError("DOCX has no OPC content types")
    return result


def _read_part(archive: zipfile.ZipFile, members: dict[str, zipfile.ZipInfo],
               name: str, limit: int) -> bytes:
    info = members.get(name)
    if info is None or info.is_dir() or info.file_size > limit:
        raise DocxBookImportError("DOCX required part is missing or oversized")
    try:
        with archive.open(info, "r") as stream:
            payload = stream.read(limit + 1)
    except (OSError, RuntimeError, zipfile.BadZipFile) as exc:
        raise DocxBookImportError("DOCX part cannot be read") from exc
    if len(payload) != info.file_size:
        raise DocxBookImportError("DOCX part size changed while reading")
    return payload


def _paragraph_text(node: ET.Element) -> str:
    segments: list[str] = []
    for element in node.iter():
        if element.tag == _W + "t" and element.text:
            segments.append(element.text)
        elif element.tag in {_W + "tab", _W + "br", _W + "cr"}:
            segments.append(" ")
    return "".join(segments).strip()


def _image_alt_texts(node: ET.Element) -> tuple[str, ...]:
    output: list[str] = []
    for element in node.iter(_WP + "docPr"):
        text = element.attrib.get("descr") or element.attrib.get("title")
        output.append(text.strip() if text and text.strip() else "Image without alternative text")
    return tuple(output)


def import_docx_book(
    source: bytes, *, source_name: str,
    control_checkpoint: Callable[[], None] | None = None,
) -> DocxBookImportResult:
    if type(source) is not bytes or not 0 < len(source) <= MAX_DOCX_SOURCE_BYTES:
        raise DocxBookImportError("DOCX source must be bounded binary data")
    if type(source_name) is not str or not source_name.strip() or len(source_name) > 512:
        raise DocxBookImportError("DOCX display name is invalid")
    if control_checkpoint is not None and not callable(control_checkpoint):
        raise TypeError("DOCX checkpoint must be callable")
    _checkpoint(control_checkpoint)
    digest = sha256(source).hexdigest()
    try:
        with zipfile.ZipFile(io.BytesIO(source)) as archive:
            members = _safe_members(archive)
            types_xml = _read_part(archive, members, "[Content_Types].xml", 1024 * 1024)
            document_xml = _read_part(archive, members, "word/document.xml",
                                      _MAX_DOCX_XML_BYTES)
            core_xml = None
            if "docProps/core.xml" in members:
                core_xml = _read_part(archive, members, "docProps/core.xml", 1024 * 1024)
    except (zipfile.BadZipFile, zipfile.LargeZipFile, EOFError) as exc:
        raise DocxBookImportError("DOCX is not a valid bounded package") from exc

    _checkpoint(control_checkpoint)
    content_types = _parse_xml(types_xml, "content types")
    types_ns = "{http://schemas.openxmlformats.org/package/2006/content-types}"
    document_type = "application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"
    if content_types.tag != types_ns + "Types" or not any(
        member.tag == types_ns + "Override"
        and member.get("PartName") == "/word/document.xml"
        and member.get("ContentType") == document_type
        for member in content_types
    ):
        raise DocxBookImportError("DOCX package does not declare a genuine Word document")
    root = _parse_xml(document_xml, "body")
    if root.tag != _W + "document":
        raise DocxBookImportError("DOCX has an unexpected document root")
    body = root.find(_W + "body")
    if body is None:
        raise DocxBookImportError("DOCX body is absent")

    title = source_name.strip()
    author = None
    if core_xml is not None:
        core = _parse_xml(core_xml, "metadata")
        if core.findtext(_DC + "title"):
            title = core.findtext(_DC + "title").strip()[:512] or title
        if core.findtext(_DC + "creator"):
            author = core.findtext(_DC + "creator").strip()[:512] or None

    blocks: list[Heading | Paragraph | Note] = []
    warnings: set[str] = set()
    text_budget = 0
    if body.find(_W + "tbl") is not None:
        warnings.add("DOCX tables are read in paragraph order; cell structure is not retained.")
    for paragraph_number, paragraph in enumerate(body.iter(_W + "p")):
        _checkpoint(control_checkpoint)
        if len(blocks) >= _MAX_DOCX_BLOCKS:
            raise DocxBookImportError("DOCX contains too many semantic blocks")
        text = _paragraph_text(paragraph)
        text_budget += len(text)
        if text_budget > _MAX_DOCX_TEXT:
            raise DocxBookImportError("DOCX semantic text exceeds resource limits")
        style = paragraph.find(_W + "pPr/" + _W + "pStyle")
        style_name = style.attrib.get(_W + "val", "") if style is not None else ""
        is_numbered = paragraph.find(_W + "pPr/" + _W + "numPr") is not None
        if is_numbered:
            warnings.add("DOCX numbering is readable as text; full list semantics are not retained.")
        anchor = "word:p:" + str(paragraph_number)
        if text:
            match = _HEADING.fullmatch(style_name)
            if match:
                blocks.append(Heading(text=text, level=int(match.group(1)),
                                      source_anchor=anchor))
            elif style_name.casefold() == "title":
                blocks.append(Heading(text=text, level=1, source_anchor=anchor))
            else:
                blocks.append(Paragraph(text=text, source_anchor=anchor))
        if paragraph.find(".//" + _W + "drawing") is not None or paragraph.find(
            ".//" + _W + "pict"
        ) is not None:
            alt_texts = _image_alt_texts(paragraph)
            if not alt_texts:
                alt_texts = ("Image without alternative text",)
            for ordinal, alt_text in enumerate(alt_texts):
                if len(blocks) >= _MAX_DOCX_BLOCKS:
                    raise DocxBookImportError("DOCX contains too many semantic blocks")
                blocks.append(Note(text=alt_text[:4096], note_type="image",
                                   source_anchor=anchor + ":image:" + str(ordinal)))
            warnings.add("DOCX images are described as notes; no chess position or diagram is inferred.")
    _checkpoint(control_checkpoint)
    if not blocks:
        raise DocxBookImportError("DOCX contains no readable content")
    result_warnings = tuple(sorted(warnings))
    document = BookDocument(
        title=title, author=author, source_name=source_name.strip(),
        blocks=blocks, warnings=list(result_warnings),
    )
    return DocxBookImportResult(
        document=document,
        source_sha256=digest,
        book_key="docx-sha256:" + digest,
        warnings=result_warnings,
    )
