from __future__ import annotations

"""Section 54 deterministic PRIVATE DOCX text/semantic preview.

This makes a bounded OOXML package without external resources or paid APIs.
It is NOT a print-ready book and does not claim NVDA/Word render certification.
Missing diagrams and collapsed variations/exercise disclosure are explicit losses.
"""

from hashlib import sha256
from html import escape
from io import BytesIO
import json
import re
from xml.etree import ElementTree as ET
from zipfile import ZIP_DEFLATED, ZipFile, ZipInfo

from .bookdocument import BookDocument
from .format_factory_epub import _modified_utc
from .format_factory_export import (
    FactoryExportError, FactoryExportResult, _block_lines, _source_digest,
)


_W = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
_PKG_REL = "http://schemas.openxmlformats.org/package/2006/relationships"
_O_REL = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
_CONTENT = "http://schemas.openxmlformats.org/package/2006/content-types"
_CP = "http://schemas.openxmlformats.org/package/2006/metadata/core-properties"
_DC = "http://purl.org/dc/elements/1.1/"
_DCTERMS = "http://purl.org/dc/terms/"
_MAX_DOCX_BYTES = 128 * 1024 * 1024


def _text_run(value: str) -> str:
    if type(value) is not str:
        raise FactoryExportError("Word text must be qualified Unicode")
    # Word preserves whitespace only when explicitly annotated.  Soft line
    # breaks use WordprocessingML <w:br/> rather than literal embedded LF.
    parts = value.split("\n")
    runs = []
    for index, part in enumerate(parts):
        if index:
            runs.append("<w:r><w:br/></w:r>")
        runs.append(f'<w:r><w:t xml:space="preserve">{escape(part)}</w:t></w:r>')
    return "".join(runs)


def _paragraph(value: str, *, style: str | None = None,
               num_id: int | None = None, level: int = 0) -> str:
    pr = []
    if style is not None:
        if not re.fullmatch(r"[A-Za-z][A-Za-z0-9]{0,50}", style):
            raise FactoryExportError("Unknown Word paragraph style")
        pr.append(f'<w:pStyle w:val="{style}"/>')
    if num_id is not None:
        if type(num_id) is not int or not 1 <= num_id <= 100_000 or type(level) is not int or level != 0:
            raise FactoryExportError("Invalid semantic list numbering")
        pr.append(f'<w:numPr><w:ilvl w:val="{level}"/><w:numId w:val="{num_id}"/></w:numPr>')
    properties = f'<w:pPr>{"".join(pr)}</w:pPr>' if pr else ""
    return f'<w:p>{properties}{_text_run(value)}</w:p>'


def _styles(language: str) -> str:
    styles = [
        ('Normal', 'Normal', 'paragraph', False),
        ('Title', 'Book Title', 'paragraph', False),
        ('Quote', 'Quote', 'paragraph', False),
    ]
    styles.extend((f'Heading{level}', f'Heading {level}', 'paragraph', True) for level in range(1, 7))
    result = []
    for style_id, title, style_type, outline in styles:
        ppr = ""
        if outline:
            level = int(style_id.removeprefix("Heading")) - 1
            ppr = f'<w:pPr><w:outlineLvl w:val="{level}"/></w:pPr>'
        result.append(
            f'<w:style w:type="{style_type}" w:styleId="{style_id}">'
            f'<w:name w:val="{escape(title, quote=True)}"/>{ppr}</w:style>'
        )
    return (f'<?xml version="1.0" encoding="utf-8"?><w:styles xmlns:w="{_W}">'
            f'<w:docDefaults><w:rPrDefault><w:rPr><w:lang w:val="{escape(language, quote=True)}"/>'
            f'</w:rPr></w:rPrDefault></w:docDefaults>{"".join(result)}</w:styles>')


def _numbering(list_instances: tuple[tuple[int, bool, int], ...]) -> str:
    abstract = []
    for id_value, marker in ((1, "bullet"), (2, "decimal")):
        glyph = "•" if marker == "bullet" else "%1."
        abstract.append(
            f'<w:abstractNum w:abstractNumId="{id_value}">'
            f'<w:multiLevelType w:val="singleLevel"/>'
            f'<w:lvl w:ilvl="0"><w:start w:val="1"/>'
            f'<w:numFmt w:val="{marker}"/><w:lvlText w:val="{glyph}"/>'
            f'<w:lvlJc w:val="left"/><w:pPr><w:tabs><w:tab w:val="num" w:pos="720"/>'
            f'</w:tabs><w:ind w:left="720" w:hanging="360"/></w:pPr></w:lvl>'
            f'</w:abstractNum>'
        )
    instances = "".join(
        f'<w:num w:numId="{num_id}">'
        f'<w:abstractNumId w:val="{2 if ordered else 1}"/>'
        f'<w:lvlOverride w:ilvl="0"><w:startOverride w:val="{start}"/></w:lvlOverride>'
        f'</w:num>'
        for num_id, ordered, start in list_instances
    )
    return (f'<?xml version="1.0" encoding="utf-8"?>'
            f'<w:numbering xmlns:w="{_W}">{"".join(abstract)}{instances}</w:numbering>')


def _parts(wire: dict[str, object], identity: str, timestamp: str) -> dict[str, str]:
    paragraphs = [_paragraph(wire["title"], style="Title")]
    losses: list[str] = []
    list_instances: list[tuple[int, bool, int]] = []
    for block in wire["blocks"]:
        kind = block["kind"]
        text, _, previous_loss = _block_lines(block)
        if kind == "Heading":
            paragraphs.append(_paragraph(block["text"], style=f'Heading{block["level"]}'))
        elif kind == "List":
            # Each semantic list has its own native Word numbering instance.
            # Reusing one instance across chapters silently carries counters.
            number_id = len(list_instances) + 1
            ordered = bool(block.get("ordered", False))
            start = block.get("start") or 1
            list_instances.append((number_id, ordered, start))
            for item in block["items"]:
                paragraphs.append(_paragraph(item, num_id=number_id))
        elif kind == "Paragraph":
            paragraphs.append(_paragraph(block["text"]))
        elif kind == "Note":
            paragraphs.append(_paragraph(text, style="Quote"))
        else:
            paragraphs.append(_paragraph(text))
            if previous_loss and previous_loss != "TEXT_STRUCTURE_NOT_MACHINE_NAVIGABLE":
                losses.append(previous_loss)
            if kind == "VariationTree":
                losses.append("VARIATION_TREE_NAVIGATION_FLATTENED")
            if kind == "Exercise":
                losses.append("EXERCISE_SOLUTION_DISCLOSURE_CHANGED")
    document = (
        f'<?xml version="1.0" encoding="utf-8"?>'
        f'<w:document xmlns:w="{_W}"><w:body>{"".join(paragraphs)}'
        '<w:sectPr><w:pgSz w:w="12240" w:h="15840"/><w:pgMar w:top="1440" '
        'w:right="1440" w:bottom="1440" w:left="1440"/></w:sectPr>'
        '</w:body></w:document>'
    )
    content_types = (
        '<?xml version="1.0" encoding="utf-8"?>'
        f'<Types xmlns="{_CONTENT}">'
        '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
        '<Default Extension="xml" ContentType="application/xml"/>'
        '<Override PartName="/word/document.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"/>'
        '<Override PartName="/word/styles.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.styles+xml"/>'
        '<Override PartName="/word/numbering.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.numbering+xml"/>'
        '<Override PartName="/docProps/core.xml" ContentType="application/vnd.openxmlformats-package.core-properties+xml"/>'
        '</Types>'
    )
    top_rels = (
        '<?xml version="1.0" encoding="utf-8"?>'
        f'<Relationships xmlns="{_PKG_REL}">'
        f'<Relationship Id="rId1" Type="{_O_REL}/officeDocument" Target="word/document.xml"/>'
        f'<Relationship Id="rId2" Type="http://schemas.openxmlformats.org/package/2006/relationships/metadata/core-properties" Target="docProps/core.xml"/>'
        '</Relationships>'
    )
    word_rels = (
        '<?xml version="1.0" encoding="utf-8"?>'
        f'<Relationships xmlns="{_PKG_REL}">'
        f'<Relationship Id="rId1" Type="{_O_REL}/styles" Target="styles.xml"/>'
        f'<Relationship Id="rId2" Type="{_O_REL}/numbering" Target="numbering.xml"/>'
        '</Relationships>'
    )
    core = (
        '<?xml version="1.0" encoding="utf-8"?>'
        f'<cp:coreProperties xmlns:cp="{_CP}" xmlns:dc="{_DC}" xmlns:dcterms="{_DCTERMS}" '
        'xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance">'
        f'<dc:title>{escape(wire["title"])}</dc:title>'
        f'<dc:language>{escape(wire["language"])}</dc:language>'
        f'<dc:identifier>urn:sha256:{identity}</dc:identifier>'
        f'<dcterms:modified xsi:type="dcterms:W3CDTF">{timestamp}</dcterms:modified>'
        '</cp:coreProperties>'
    )
    return ({
        "[Content_Types].xml": content_types,
        "_rels/.rels": top_rels,
        "docProps/core.xml": core,
        "word/document.xml": document,
        "word/_rels/document.xml.rels": word_rels,
        "word/styles.xml": _styles(wire["language"]),
        "word/numbering.xml": _numbering(tuple(list_instances)),
    }, tuple(dict.fromkeys(losses)))


def export_factory_docx_preview(
    document: BookDocument, *, source_sha256: str, modified_utc: str,
    allow_semantic_loss: bool = False,
) -> FactoryExportResult:
    """In-memory source-bound private DOCX; no automatic external publication."""
    source_id = _source_digest(source_sha256)
    if type(document) is not BookDocument:
        raise FactoryExportError("Canonical BookDocument required")
    if type(allow_semantic_loss) is not bool:
        raise FactoryExportError("Explicit loss permission required")
    timestamp, archive_time = _modified_utc(modified_utc)
    wire = document.as_dict()
    language = wire["language"]
    if type(language) is not str or re.fullmatch(r"[a-z]{2,3}(?:-[A-Za-z]{2,8})?", language) is None:
        raise FactoryExportError("Accessible DOCX needs an explicit qualified language")
    identity = sha256((source_id + ":" + sha256(json.dumps(
        wire, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")).hexdigest()).encode("ascii")).hexdigest()
    parts, losses = _parts(wire, identity, timestamp)
    if losses and not allow_semantic_loss:
        raise FactoryExportError("DOCX would lose declared book semantics")
    try:
        for item in parts.values():
            ET.fromstring(item.encode("utf-8"))
    except ET.ParseError as exc:
        raise FactoryExportError("Word XML content is not qualified") from exc
    data = BytesIO()
    with ZipFile(data, "w", compression=ZIP_DEFLATED, allowZip64=False) as zf:
        for name, xml in parts.items():
            info = ZipInfo(name, archive_time)
            info.compress_type = ZIP_DEFLATED
            info.create_system = 3
            info.external_attr = 0o100644 << 16
            zf.writestr(info, xml.encode("utf-8"))
    payload = data.getvalue()
    if len(payload) > _MAX_DOCX_BYTES:
        raise FactoryExportError("Private DOCX exceeds output byte limit")
    return FactoryExportResult(
        "docx", payload, source_id, sha256(payload).hexdigest(),
        losses, tuple(wire["warnings"]), False,
    )
