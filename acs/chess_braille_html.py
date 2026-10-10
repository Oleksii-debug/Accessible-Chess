from __future__ import annotations

"""Source-readable offline HTML preview of an UNVERIFIED chess Braille edition.

The original chess BookDocument supplies the accessible reading layer. Its
Braille cell pages are displayed separately for visual checking and are NOT
passed off as reliable screen-reader transcriptions. This does not implement
the certified eBraille publication standard, nor print-ready production.
"""

from dataclasses import dataclass
from hashlib import sha256
from html import escape
import json
from xml.etree import ElementTree as ET

from .bookdocument import BookDocument
from .chess_braille_factory import (
    BrailleFactoryError, BraillePreparation, PEF_NS, _canonical_lines,
)
from .chess_braille_brf import NABCC_DISPLAY_TABLE, pef_to_provisional_brf

MAX_HTML_BYTES = 32 * 1024 * 1024
MAX_PREVIEW_PAGES = 2000
MAX_PREVIEW_BLOCKS = 50000


@dataclass(frozen=True, slots=True)
class ProvisionalHTML:
    data: bytes
    sha256: str
    pages: int
    status: str = "UNVERIFIED_REQUIRES_DECISION"
    print_ready: bool = False


def _tagged_text(tag: str, text: str) -> str:
    return "<" + tag + ">" + escape(text, quote=True) + "</" + tag + ">"


def render_local_braille_html(document: BookDocument,
                              preparation: BraillePreparation) -> ProvisionalHTML:
    """Generate text-first offline navigation with explicit provisional PEF pages.

    The canonical BookDocument is validated and SHA-compared against the PEF
    manifest. HTML always uses escaped text from that validated source.
    """
    if not isinstance(document, BookDocument):
        raise BrailleFactoryError("An original canonical book is required for HTML preview")
    segments, source_sha = _canonical_lines(document)
    if not segments or source_sha != preparation.manifest.get("source_book_sha256"):
        raise BrailleFactoryError("HTML source does not match pinned PEF edition")
    # Reuse the separate fail-closed PEF/BRF structural checker rather than
    # assuming a potentially tampered in-memory manifest is trustworthy.
    checked = pef_to_provisional_brf(preparation, display_table=NABCC_DISPLAY_TABLE)
    if checked.pages > MAX_PREVIEW_PAGES:
        raise BrailleFactoryError("HTML page preview exceeds bounded output capacity")
    canonical = BookDocument.from_dict(document.as_dict())
    if len(canonical.blocks) > MAX_PREVIEW_BLOCKS:
        raise BrailleFactoryError("HTML semantic source exceeds block limits")
    raw_title = canonical.title
    page_count = checked.pages
    p = ['<!DOCTYPE html><html lang="' + escape(
        preparation.manifest["language"], quote=True) + '"><head><meta charset="utf-8">',
        '<meta name="viewport" content="width=device-width,initial-scale=1">',
        '<meta http-equiv="Content-Security-Policy" content="default-src &#39;none&#39;; style-src &#39;unsafe-inline&#39;; base-uri &#39;none&#39;; form-action &#39;none&#39;">',
        _tagged_text("title", raw_title + " — UNVERIFIED Braille preview"),
        '<style>body{font-family:system-ui,sans-serif;line-height:1.6;max-width:72rem;margin:1rem auto;padding:0 1rem}'
        ':focus-visible{outline:3px solid currentColor;outline-offset:3px}'
        '.braille{font-size:1.3rem;white-space:pre;overflow-x:auto;line-height:1.8}'
        'nav a{display:inline-block;padding:.2rem}main{max-width:70ch}'
        '.skip{position:absolute;left:-10000px}.skip:focus{position:static}'
        '@media print{.warning{font-weight:bold}}'
        '</style></head><body>',
        '<a class="skip" href="#source-book">Skip to original accessible book text</a>',
        _tagged_text("h1", raw_title),
        '<p class="warning"><strong>UNVERIFIED PREVIEW — NOT APPROVED FOR EMBOSSING, '
        'DISTRIBUTION OR PRINT-READY USE.</strong></p>',
        '<p>Original semantic chess text is provided for screen-reader navigation; '
        'the Braille cell pages below are displayed for manual visual review, '
        'not independently certified Braille transcriptions.</p>',
        '<nav aria-label="Preview navigation"><a href="#source-book">Original accessible source</a> '
        '<a href="#braille-pages">Provisional Braille pages</a></nav>',
        '<main id="source-book" aria-label="Original source text">',
        '<h2>Original accessible book text</h2>',
    ]
    if canonical.author:
        p.append(_tagged_text("p", "Author: " + canonical.author))
    for index, block in enumerate(canonical.blocks, start=1):
        data = block.as_dict()
        kind = data["kind"]
        anchor = "source-block-" + str(index)
        p.append('<section id="' + anchor + '">')
        if kind == "Heading":
            level = min(6, data["level"] + 2)
            p.append(_tagged_text("h" + str(level), data["text"]))
        elif kind in ("Paragraph", "Note"):
            p.append(_tagged_text("p", data["text"]))
        elif kind == "List":
            tag = "ol" if data["ordered"] else "ul"
            start = ' start="' + str(data["start"]) + '"' if tag == "ol" and data.get("start") is not None else ""
            p.append("<" + tag + start + ">")
            for item in data["items"]:
                p.append(_tagged_text("li", item))
            p.append("</" + tag + ">")
        elif kind in ("Position", "Diagram", "Exercise"):
            p.append(_tagged_text("h3", kind + " " + str(index)))
            p.append(_tagged_text("p", "Canonical FEN: " + data["fen"]))
            for field in ("caption", "alt_text", "prompt", "answer_text",
                          "side_to_move_note", "difficulty", "solution_pgn"):
                value = data.get(field)
                if value:
                    p.append(_tagged_text("p", field.replace("_", " ") + ": " + value))
        elif kind in ("Game", "VariationTree"):
            p.append(_tagged_text("h3", data.get("title") or (kind + " " + str(index))))
            if data.get("root_fen"):
                p.append(_tagged_text("p", "Root FEN: " + data["root_fen"]))
            p.append(_tagged_text("pre", data["pgn"]))
        else:
            raise BrailleFactoryError("Unsupported canonical semantic book block")
        p.append("</section>")
    p.append('</main><section id="braille-pages" aria-label="Unverified Braille page preview">'
             '<h2>Provisional Braille cell pages</h2>')
    root = ET.fromstring(preparation.pef)
    pages = root.findall(".//{" + PEF_NS + "}page")
    if len(pages) != page_count:
        raise BrailleFactoryError("PEF HTML page source differs from structural result")
    p.append('<nav aria-label="Go to Braille preview page"><ol>')
    for idx in range(page_count):
        p.append('<li><a href="#braille-page-' + str(idx + 1) +
                 '">Page ' + str(idx + 1) + '</a></li>')
    p.append('</ol></nav>')
    for idx, page in enumerate(pages, start=1):
        p.append('<section id="braille-page-' + str(idx) + '" aria-label="Provisional Braille page ' +
                 str(idx) + '">')
        p.append(_tagged_text("h3", "Unverified Braille page " + str(idx)))
        page_rows = [row.text or "" for row in page]
        p.append('<pre class="braille" aria-hidden="true">' +
                 escape("\n".join(page_rows), quote=True) + '</pre>')
        p.append('<p>These Unicode Braille cells require independent translation '
                 'and tactile qualification. Read the accessible original text above.</p>')
        p.append('</section>')
    p.append('</section></body></html>')
    data = "\n".join(p).encode("utf-8")
    if len(data) > MAX_HTML_BYTES:
        raise BrailleFactoryError("Accessible HTML preview exceeds 32 MiB limit")
    return ProvisionalHTML(
        data=data, sha256=sha256(data).hexdigest(), pages=page_count,
    )
