from __future__ import annotations

"""Bounded DOCX text/heading ingestion through the existing BookDocument importer.

Only user-visible WordprocessingML paragraphs are projected. This is neither
a chess rules parser nor support for macros, external links, embedded objects,
or arbitrary Office features. Unsupported features remain ordinary text at most.
"""
from dataclasses import dataclass
from hashlib import sha256
from io import BytesIO
from pathlib import PurePosixPath
import zipfile
from xml.etree import ElementTree

from .bookdocument import BookDocument, Heading, Paragraph

MAX_DOCX_SOURCE_BYTES = 8 * 1024 * 1024
_MAX_DOCX_UNCOMPRESSED_BYTES = 16 * 1024 * 1024
_W = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"
_MAX_DOCX_PARTS = 256


@dataclass(frozen=True, slots=True)
class DocxBookImportResult:
    book_key: str
    document: object
    warnings: tuple[str, ...]


def import_docx_book(source: bytes, *, source_name: str, control_checkpoint=None) -> DocxBookImportResult:
    if type(source) is not bytes or not 0 < len(source) <= MAX_DOCX_SOURCE_BYTES:
        raise ValueError("DOCX source exceeds supported bounds")
    if type(source_name) is not str or not source_name.strip():
        raise ValueError("DOCX source name is invalid")
    if control_checkpoint is not None:
        control_checkpoint()
    try:
        with zipfile.ZipFile(BytesIO(source)) as archive:
            infos = archive.infolist()
            names = [info.filename for info in infos]
            if len(infos) > _MAX_DOCX_PARTS or len(names) != len(set(names)):
                raise ValueError("DOCX contains duplicated or excessive archive members")
            if not {"[Content_Types].xml", "word/document.xml"}.issubset(names):
                raise ValueError("DOCX has no ordinary Word document part")
            budget = 0
            for info in infos:
                path = PurePosixPath(info.filename)
                if (
                    info.flag_bits & 1
                    or info.compress_type not in (zipfile.ZIP_STORED, zipfile.ZIP_DEFLATED)
                    or not info.filename or info.filename.startswith("/")
                    or "\\" in info.filename
                    or ".." in path.parts
                    or info.file_size < 0
                    or info.file_size > _MAX_DOCX_UNCOMPRESSED_BYTES
                    or info.filename.casefold().endswith(("vbaproject.bin", ".exe", ".dll"))
                ):
                    raise ValueError("DOCX unsafe archive member")
                budget += info.file_size
                if budget > _MAX_DOCX_UNCOMPRESSED_BYTES:
                    raise ValueError("DOCX expansion exceeds supported bounds")
            xml_bytes = archive.read("word/document.xml")
    except (OSError, zipfile.BadZipFile, RuntimeError, KeyError) as exc:
        raise ValueError("invalid DOCX book archive") from exc
    if b"<!DOCTYPE" in xml_bytes.upper() or b"<!ENTITY" in xml_bytes.upper():
        raise ValueError("DOCX external entity declarations are forbidden")
    if control_checkpoint is not None:
        control_checkpoint()
    try:
        document_root = ElementTree.fromstring(xml_bytes)
    except ElementTree.ParseError as exc:
        raise ValueError("invalid DOCX text XML") from exc
    body = document_root.find(_W + "body")
    if body is None:
        raise ValueError("DOCX has no reading body")
    blocks: list[Heading | Paragraph] = []
    for paragraph in body.iter(_W + "p"):
        if control_checkpoint is not None:
            control_checkpoint()
        parts: list[str] = []
        for node in paragraph.iter():
            if node.tag == _W + "t" and node.text is not None:
                parts.append(node.text)
            elif node.tag == _W + "tab":
                parts.append(" ")
            elif node.tag in (_W + "br", _W + "cr"):
                parts.append(" ")
        text = "".join(parts).strip()
        if not text:
            continue
        style = paragraph.find("./" + _W + "pPr/" + _W + "pStyle")
        heading = style.get(_W + "val", "") if style is not None else ""
        # A DOCX paragraph is an explicit Word semantic block, NOT Markdown.
        # Feeding literal Word prose into a Markdown importer could reinterpret
        # a plain \`\`\`fen / \`\`\`pgn paragraph as a chess Position/Game.
        if len(blocks) >= 10_000:
            raise ValueError("DOCX has too many readable paragraphs")
        if heading in ("Heading1", "heading 1"):
            blocks.append(Heading(text=text, level=1))
        elif heading in ("Heading2", "heading 2"):
            blocks.append(Heading(text=text, level=2))
        else:
            blocks.append(Paragraph(text=text))
    if not blocks:
        raise ValueError("DOCX has no accessible paragraph text")
    if control_checkpoint is not None:
        control_checkpoint()
    return DocxBookImportResult(
        book_key="docx-sha256:" + sha256(source).hexdigest(),
        document=BookDocument(title=source_name, source_name=source_name, blocks=blocks),
        warnings=("DOCX imported as passive Word text and headings only.",),
    )
