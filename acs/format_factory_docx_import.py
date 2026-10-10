from __future__ import annotations

"""Fail-closed, paragraph-only DOCX ingress using the canonical HTML Book importer.

This adapter intentionally does not parse chess notation or replace BookDocument.
Graphic, table, list, notes, revision, and hyperlink semantics are NOT guessed.
It uses no filesystem access, external relationship resolution, network or models.
"""

from html import escape
from io import BytesIO
from pathlib import PurePosixPath
from xml.etree import ElementTree as ET
from zipfile import BadZipFile, ZipFile

from .book_html_import import BookHtmlImportError, import_html_book

_W = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"
_CT = "{http://schemas.openxmlformats.org/package/2006/content-types}"
_DC = "{http://purl.org/dc/elements/1.1/}"
_MAIN_MIME = "application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"
_MAX_XML_BYTES = 8 * 1024 * 1024
_MAX_PARAGRAPHS = 50_000


class FactoryDocxImportError(ValueError):
    """Stable private error; never reveals source text or local paths."""


def _xml(data: bytes, purpose: str) -> ET.Element:
    if len(data) > _MAX_XML_BYTES or b"<!DOCTYPE" in data.upper() or b"<!ENTITY" in data.upper():
        raise FactoryDocxImportError(f"DOCX {purpose} is unsafe or too large")
    try:
        return ET.fromstring(data)
    except (ET.ParseError, ValueError, UnicodeError) as exc:
        raise FactoryDocxImportError(f"DOCX {purpose} XML is malformed") from exc


def _read(archive: ZipFile, name: str) -> bytes:
    try:
        info = archive.getinfo(name)
        if info.file_size > _MAX_XML_BYTES:
            raise FactoryDocxImportError("DOCX XML component exceeds the supported limit")
        return archive.read(info)
    except (KeyError, BadZipFile, RuntimeError, OSError, EOFError) as exc:
        raise FactoryDocxImportError("DOCX required component cannot be verified") from exc


def _reject_unsupported_package_parts(archive: ZipFile) -> None:
    names = [info.filename.lower() for info in archive.infolist()]
    unsupported = (
        "word/media/", "word/embeddings/", "word/charts/", "word/diagrams/",
        "word/activeX/", "word/footnotes.xml", "word/endnotes.xml",
        "word/comments.xml", "word/numbering.xml", "word/websettings.xml",
        "word/vbaproject.bin",
    )
    if any(name.startswith(unsupported) or
           (name.startswith("word/header") and name.endswith(".xml")) or
           (name.startswith("word/footer") and name.endswith(".xml"))
           for name in names):
        raise FactoryDocxImportError("DOCX contains unqualified rich-content parts")
    for name in archive.namelist():
        if not name.lower().endswith(".rels"):
            continue
        relationships = _xml(_read(archive, name), "relationships")
        for relation in relationships:
            if relation.attrib.get("TargetMode", "").lower() == "external":
                raise FactoryDocxImportError("DOCX contains an external relationship")


def _assert_content_type(archive: ZipFile) -> None:
    root = _xml(_read(archive, "[Content_Types].xml"), "content types")
    if root.tag != _CT + "Types" or not any(
        child.tag == _CT + "Override"
        and child.attrib.get("PartName") == "/word/document.xml"
        and child.attrib.get("ContentType") == _MAIN_MIME
        for child in root
    ):
        raise FactoryDocxImportError("DOCX is not a qualified main WordprocessingML document")


def _core_metadata(archive: ZipFile) -> tuple[str | None, str | None]:
    if "docProps/core.xml" not in archive.namelist():
        return None, None
    root = _xml(_read(archive, "docProps/core.xml"), "core metadata")
    title = root.findtext(_DC + "title")
    author = root.findtext(_DC + "creator")
    return (
        title.strip() if title and title.strip() else None,
        author.strip() if author and author.strip() else None,
    )


def _paragraph(node: ET.Element) -> tuple[str, str] | None:
    if node.tag != _W + "p":
        raise FactoryDocxImportError("DOCX reading order includes unsupported objects")
    tag = "p"
    text: list[str] = []
    for part in node:
        if part.tag == _W + "pPr":
            for prop in part:
                if prop.tag == _W + "numPr":
                    raise FactoryDocxImportError("DOCX list hierarchy is unqualified")
                if prop.tag == _W + "pStyle":
                    style = prop.attrib.get(_W + "val", "")
                    if style == "Title":
                        tag = "h1"
                    elif style.startswith("Heading") and style[7:] in "123456" and len(style) == 8:
                        tag = "h" + style[7:]
                    elif style not in ("", "Normal", "BodyText"):
                        raise FactoryDocxImportError("DOCX paragraph style needs semantic review")
        elif part.tag == _W + "r":
            for run in part:
                if run.tag == _W + "t":
                    text.append(run.text or "")
                elif run.tag == _W + "rPr":
                    if any(style.tag in {
                        _W + "b", _W + "i", _W + "u", _W + "strike",
                        _W + "vanish", _W + "vertAlign",
                    } for style in run):
                        raise FactoryDocxImportError("DOCX authored inline semantics need review")
                else:
                    raise FactoryDocxImportError("DOCX inline content is not qualified")
        else:
            raise FactoryDocxImportError("DOCX contains unsupported paragraph objects")
    value = "".join(text)
    return (tag, value) if value.strip() else None


def import_docx_paragraph_book(
    source: bytes, *, source_name: str,
    title: str | None = None, author: str | None = None,
    language: str | None = None,
):
    """Produce existing BookDocument only for provably text-only DOCX subsets.

    The source receipt, maintained by format_factory_intake, remains the
    authoritative SHA-256 of original DOCX bytes, not the transient XHTML.
    """
    try:
        with ZipFile(BytesIO(source), "r") as archive:
            _assert_content_type(archive)
            _reject_unsupported_package_parts(archive)
            core_title, core_author = _core_metadata(archive)
            root = _xml(_read(archive, "word/document.xml"), "document")
            if root.tag != _W + "document":
                raise FactoryDocxImportError("DOCX main document root is unsupported")
            body = root.find(_W + "body")
            if body is None:
                raise FactoryDocxImportError("DOCX body is missing")
            blocks: list[str] = []
            for part in body:
                if part.tag == _W + "sectPr":
                    if part.findall(".//" + _W + "headerReference") or part.findall(".//" + _W + "footerReference"):
                        raise FactoryDocxImportError("DOCX header/footer content is unqualified")
                    for columns in part.findall(".//" + _W + "cols"):
                        if int(columns.attrib.get(_W + "num", "1")) != 1:
                            raise FactoryDocxImportError("DOCX multi-column order is unqualified")
                    continue
                paragraph = _paragraph(part)
                if paragraph is None:
                    continue
                tag, text = paragraph
                blocks.append(f"<{tag}>" + escape(text) + f"</{tag}>")
                if len(blocks) > _MAX_PARAGRAPHS:
                    raise FactoryDocxImportError("DOCX contains too many semantic paragraphs")
            if not blocks:
                raise FactoryDocxImportError("DOCX contains no qualified readable text")
            projected_html = ("<html><body>" + "".join(blocks) + "</body></html>").encode("utf-8")
        canonical = import_html_book(
            projected_html, source_name=source_name,
            title=title or core_title, author=author or core_author,
            language=language,
        )
        warning = (
            "DOCX text-and-headings subset only: original typography, "
            "printed page mapping, rights and edition are not independently proven."
        )
        canonical.document.warnings.append(warning)
        canonical.document.as_dict()
        return canonical.document, tuple(canonical.document.warnings)
    except (BadZipFile, BookHtmlImportError, ET.ParseError, ValueError, OSError, TypeError) as exc:
        if isinstance(exc, FactoryDocxImportError):
            raise
        raise FactoryDocxImportError("DOCX cannot be safely represented as a semantic book") from exc
