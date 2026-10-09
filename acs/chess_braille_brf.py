from __future__ import annotations

"""Conservative provisional 6-dot PEF -> BRF (NABCC/Braille ASCII) conversion.

The converter is NOT a qualified embosser driver or print-ready certificate.
It consumes only a Section-55-owned UNVERIFIED PEF with matching SHA-256. It
does not translate languages, infer chess semantics, or rewrite BookDocument.

Braille-ASCII map: the 64 six-dot patterns in U+2800..U+283F order, matching
the Liblouis en-us-brf.dis six-dot display map (LGPL-2.1-or-later).
Compatibility must be verified against the actual target embosser.
"""

from dataclasses import dataclass
from hashlib import sha256
from xml.etree import ElementTree as ET

from .chess_braille_factory import BrailleFactoryError, BraillePreparation, PEF_NS

# North American Braille ASCII in Unicode six-dot sequence, not ASCII text.
# Ordered by increasing braille pattern bitmask 0 through 63.
_BRAILLE_ASCII = " A1B'K2L@CIF/MSP\"E3H9O6R^DJG>NTQ,*5<-U8V.%[$+X!&;:4\\0Z7(_?W]#Y)="
if len(_BRAILLE_ASCII) != 64 or len(set(_BRAILLE_ASCII)) != 64:
    raise RuntimeError("Invalid complete six-dot Braille ASCII mapping")
MAX_PEF_BYTES = 32 * 1024 * 1024
MAX_PAGES = 10000
MAX_PAGE_ROWS = 60
MAX_ROW_COLS = 80
NABCC_DISPLAY_TABLE = "en-us-brf.dis"


@dataclass(frozen=True, slots=True)
class ProvisionalBRF:
    data: bytes
    sha256: str
    pages: int
    display_table: str
    status: str = "UNVERIFIED_REQUIRES_DECISION"
    print_ready: bool = False


def _required_attributes(element: ET.Element, fields: set[str]) -> None:
    if set(element.attrib) != fields:
        raise BrailleFactoryError("PEF has unknown or missing layout attributes")


def pef_to_provisional_brf(
    preparation: BraillePreparation, *, display_table: str,
) -> ProvisionalBRF:
    """Convert a SHA-pinned, known generated six-dot simplex PEF to provisional BRF.

    It rejects unsupported PEF features rather than silently flattening them,
    including duplex, multifile volumes, variable row gaps, changed metadata,
    extra XML nodes, corrupt or unknown Braille cells.
    """
    if type(preparation) is not BraillePreparation:
        raise BrailleFactoryError("Canonical Section-55 PEF preparation is required")
    if display_table != NABCC_DISPLAY_TABLE:
        raise BrailleFactoryError("NABCC BRF requires explicitly selected en-us-brf.dis")
    if preparation.manifest.get("status") != "UNVERIFIED_REQUIRES_DECISION" or preparation.manifest.get("print_ready") is not False:
        raise BrailleFactoryError("Only unverified Section-55 PEF can enter BRF preparation")
    raw = preparation.pef
    if type(raw) is not bytes or not raw or len(raw) > MAX_PEF_BYTES:
        raise BrailleFactoryError("PEF bytes are missing or exceed limits")
    if sha256(raw).hexdigest() != preparation.manifest.get("output_pef_sha256"):
        raise BrailleFactoryError("PEF differs from its SHA-256 manifest")
    if b"<!DOCTYPE" in raw.upper() or b"<!ENTITY" in raw.upper():
        raise BrailleFactoryError("PEF DTD/entity declarations are unsupported")
    try:
        root = ET.fromstring(raw)
    except ET.ParseError as exc:
        raise BrailleFactoryError("Malformed PEF") from exc
    ns = "{" + PEF_NS + "}"
    if root.tag != ns + "pef" or root.attrib != {"version": "2008-1"}:
        raise BrailleFactoryError("Unsupported PEF root or version")
    if [child.tag for child in root] != [ns + "head", ns + "body"]:
        raise BrailleFactoryError("Unsupported PEF document structure")
    body = root[1]
    if list(body) == [] or len(body) != 1 or body[0].tag != ns + "volume":
        raise BrailleFactoryError("One PEF volume is supported")
    volume = body[0]
    _required_attributes(volume, {"cols", "rows", "rowgap", "duplex"})
    try:
        cols = int(volume.attrib["cols"])
        rows_per_page = int(volume.attrib["rows"])
    except (ValueError, OverflowError) as exc:
        raise BrailleFactoryError("Non-numeric PEF dimensions") from exc
    if not 10 <= cols <= MAX_ROW_COLS or not 10 <= rows_per_page <= MAX_PAGE_ROWS:
        raise BrailleFactoryError("PEF dimensions are outside supported bounds")
    if volume.attrib["duplex"] != "false" or volume.attrib["rowgap"] != "0":
        raise BrailleFactoryError("Duplex or raised row-gap layout is unsupported")
    if len(volume) != 1 or volume[0].tag != ns + "section" or volume[0].attrib:
        raise BrailleFactoryError("One unmodified simplex section is required")
    section = volume[0]
    if not len(section) or len(section) > MAX_PAGES:
        raise BrailleFactoryError("PEF has no pages or too many pages")
    pages: list[bytes] = []
    for page in section:
        if page.tag != ns + "page" or page.attrib:
            raise BrailleFactoryError("Unsupported page layout or attributes")
        if not len(page) or len(page) > rows_per_page:
            raise BrailleFactoryError("Page row count is invalid")
        lines: list[bytes] = []
        for row in page:
            if row.tag != ns + "row" or row.attrib or len(row):
                raise BrailleFactoryError("Unsupported row data or attributes")
            cells = row.text or ""
            if len(cells) > cols or not cells:
                raise BrailleFactoryError("PEF row is blank or exceeds device width")
            if any(not "\u2800" <= cell <= "\u283f" for cell in cells):
                raise BrailleFactoryError("PEF row contains unsupported eight-dot/plaintext cells")
            lines.append("".join(_BRAILLE_ASCII[ord(cell) - 0x2800] for cell in cells).encode("ascii"))
        pages.append(b"\r\n".join(lines))
    # Form feed retains the boundary between source PEF pages. Output is BRF-
    # style bytes only; a concrete device still needs profile qualification.
    result = b"\f".join(pages)
    return ProvisionalBRF(data=result, sha256=sha256(result).hexdigest(),
                          pages=len(pages), display_table=display_table)
