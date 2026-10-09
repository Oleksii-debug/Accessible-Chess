from __future__ import annotations

"""Deterministic private EPUB 3 preview using the validated BookDocument schema.

EPUBCheck, DAISY/assistive-technology manual evaluation, publication rights,
and independent semantic round trips remain separate required release gates.
No network, JavaScript, encryption, remote images or filesystem writes.
"""

from datetime import datetime, timezone
from hashlib import sha256
from html import escape
from io import BytesIO
import re
from xml.etree import ElementTree as ET
from zipfile import ZIP_DEFLATED, ZIP_STORED, ZipFile, ZipInfo

from .bookdocument import BookDocument
from .format_factory_export import FactoryExportError, FactoryExportResult, _block_lines, _source_digest


_MAX_PRIVATE_EPUB_BYTES = 128 * 1024 * 1024
_OPF = "http://www.idpf.org/2007/opf"
_DC = "http://purl.org/dc/elements/1.1/"
_XHTML = "http://www.w3.org/1999/xhtml"


def _modified_utc(value: str) -> tuple[str, tuple[int, int, int, int, int, int]]:
    if type(value) is not str or re.fullmatch(
        r"(?:19[89][0-9]|20[0-9]{2}|210[0-7])-(?:0[1-9]|1[0-2])-(?:0[1-9]|[12][0-9]|3[01])T"
        r"(?:[01][0-9]|2[0-3]):[0-5][0-9]:[0-5][0-9]Z", value
    ) is None:
        raise FactoryExportError("Explicit canonical UTC modification timestamp is required")
    try:
        parsed = datetime.strptime(value, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
    except ValueError as exc:
        raise FactoryExportError("Invalid UTC modification timestamp") from exc
    if not (1980 <= parsed.year <= 2107):
        raise FactoryExportError("EPUB archive timestamp is outside reproducible ZIP limits")
    return value, (parsed.year, parsed.month, parsed.day, parsed.hour, parsed.minute, parsed.second)


def _write_member(zf: ZipFile, name: str, body: bytes, archive_time: tuple[int, ...],
                  *, compression: int = ZIP_DEFLATED) -> None:
    info = ZipInfo(name, archive_time)
    info.compress_type = compression
    info.create_system = 3
    info.external_attr = 0o100644 << 16
    zf.writestr(info, body)


def export_factory_epub3_preview(
    document: BookDocument, *, source_sha256: str, modified_utc: str,
    allow_semantic_loss: bool = False,
) -> FactoryExportResult:
    """Return a private, deterministic EPUB ZIP or fail atomically.

    Caller supplies the actual qualified book/package modification timestamp.
    This function must not manufacture an edition or publication date.
    """
    digest = _source_digest(source_sha256)
    if type(document) is not BookDocument:
        raise FactoryExportError("Canonical BookDocument required")
    if type(allow_semantic_loss) is not bool:
        raise FactoryExportError("Loss approval must be an explicit boolean")
    modification, archive_time = _modified_utc(modified_utc)
    wire = document.as_dict()
    language = wire["language"]
    if type(language) is not str or not re.fullmatch(r"[a-z]{2,3}(?:-[A-Za-z]{2,8})?", language):
        raise FactoryExportError("EPUB3 language needs a qualified source code")
    title = escape(wire["title"])
    lang = escape(language, quote=True)
    pieces: list[str] = []
    toc: list[str] = []
    losses: list[str] = []
    for index, block in enumerate(wire["blocks"], 1):
        plain, markup, loss = _block_lines(block)
        if loss and loss != "TEXT_STRUCTURE_NOT_MACHINE_NAVIGABLE":
            losses.append(loss)
        if block["kind"] == "Heading":
            level = block["level"]
            anchor = "section-" + str(index)
            markup = markup.replace(f"<h{level}>", f'<h{level} id="{anchor}">', 1)
            toc.append(f'<li><a href="book.xhtml#{anchor}">{escape(block["text"])}</a></li>')
        pieces.append(markup)
    losses = list(dict.fromkeys(losses))
    if losses and not allow_semantic_loss:
        raise FactoryExportError("EPUB preview would lose original diagram fidelity")
    nav_list = "".join(toc) if toc else f'<li><a href="book.xhtml#start">{title}</a></li>'
    book = (
        '<?xml version="1.0" encoding="utf-8"?>'
        f'<html xmlns="{_XHTML}" xml:lang="{lang}" lang="{lang}">'
        '<head><meta charset="utf-8"/><title>' + title +
        '</title></head><body><main><h1 id="start">' + title + '</h1>' +
        "".join(pieces) + '</main></body></html>'
    )
    nav = (
        '<?xml version="1.0" encoding="utf-8"?>'
        f'<html xmlns="{_XHTML}" xmlns:epub="http://www.idpf.org/2007/ops" '
        f'xml:lang="{lang}" lang="{lang}"><head><title>Navigation</title></head><body>'
        '<nav epub:type="toc" id="toc"><h1>Contents</h1><ol>' +
        nav_list + '</ol></nav></body></html>'
    )
    package = (
        '<?xml version="1.0" encoding="utf-8"?>'
        f'<package xmlns="{_OPF}" version="3.0" unique-identifier="pub-id" '
        f'xml:lang="{lang}"><metadata xmlns:dc="{_DC}">'
        f'<dc:identifier id="pub-id">urn:sha256:{digest}</dc:identifier>'
        f'<dc:title>{title}</dc:title><dc:language>{lang}</dc:language>'
        f'<meta property="dcterms:modified">{modification}</meta>'
        '</metadata><manifest>'
        '<item id="nav" href="nav.xhtml" media-type="application/xhtml+xml" properties="nav"/>'
        '<item id="book" href="book.xhtml" media-type="application/xhtml+xml"/>'
        '</manifest><spine><itemref idref="book"/></spine></package>'
    )
    container = (
        '<?xml version="1.0" encoding="utf-8"?>'
        '<container version="1.0" xmlns="urn:oasis:names:tc:opendocument:xmlns:container">'
        '<rootfiles><rootfile full-path="OEBPS/package.opf" '
        'media-type="application/oebps-package+xml"/></rootfiles></container>'
    )
    items = (
        ("META-INF/container.xml", container),
        ("OEBPS/package.opf", package),
        ("OEBPS/nav.xhtml", nav),
        ("OEBPS/book.xhtml", book),
    )
    try:
        for _, value in items:
            ET.fromstring(value.encode("utf-8"))
    except ET.ParseError as exc:
        raise FactoryExportError("Preview XML validation failed") from exc
    output = BytesIO()
    with ZipFile(output, "w", allowZip64=False) as archive:
        _write_member(archive, "mimetype", b"application/epub+zip",
                      archive_time, compression=ZIP_STORED)
        for name, value in items:
            _write_member(archive, name, value.encode("utf-8"), archive_time)
    data = output.getvalue()
    if len(data) > _MAX_PRIVATE_EPUB_BYTES:
        raise FactoryExportError("EPUB preview exceeds the byte limit")
    return FactoryExportResult(
        "epub3", data, digest, sha256(data).hexdigest(), tuple(losses),
        tuple(wire["warnings"]), False,
    )
