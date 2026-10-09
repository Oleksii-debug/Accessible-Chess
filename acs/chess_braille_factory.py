from __future__ import annotations

"""Section 55: fail-closed, optional chess BookDocument -> six-dot PEF boundary.

This is a foundation, not a qualified embosser or an automatic print-ready
factory. No OCR, remote provider, alternate chess parser, invented braille
alphabet, or implicit license grant is introduced.
"""

from dataclasses import dataclass
from hashlib import sha256
import json
import re
from typing import Protocol
from xml.etree import ElementTree as ET

from .bookdocument import BookDocument
from .chesscore import Board
from .pgn_roundtrip import parse_pgn_text


PEF_NS = "http://www.daisy.org/ns/2008/pef"
DC_NS = "http://purl.org/dc/elements/1.1/"
MAX_SEGMENTS = 50000
MAX_CELLS = 4_000_000
MAX_PAGES = 10000
_HEX64 = re.compile(r"^[0-9a-f]{64}$")


class BrailleFactoryError(ValueError):
    """A safe, unambiguous failure: no print-ready status was issued."""


def _nonempty(value: object, label: str, limit: int = 160) -> str:
    if type(value) is not str or not 0 < len(value.strip()) <= limit:
        raise BrailleFactoryError(f"{label} must be nonempty bounded text")
    return value.strip()


@dataclass(frozen=True, slots=True)
class BrailleProfile:
    language: str
    table_id: str
    table_version: str
    table_sha256: str
    device_model: str
    cells_per_line: int
    lines_per_page: int
    dots: int = 6

    def __post_init__(self) -> None:
        for key in ("language", "table_id", "table_version", "device_model"):
            _nonempty(getattr(self, key), key)
        if type(self.table_sha256) is not str or not _HEX64.fullmatch(self.table_sha256):
            raise BrailleFactoryError("A pinned 64-character table SHA-256 is required")
        if type(self.cells_per_line) is not int or not 10 <= self.cells_per_line <= 80:
            raise BrailleFactoryError("cells_per_line must be in [10, 80]")
        if type(self.lines_per_page) is not int or not 10 <= self.lines_per_page <= 60:
            raise BrailleFactoryError("lines_per_page must be in [10, 60]")
        if type(self.dots) is not int or self.dots != 6:
            raise BrailleFactoryError("Only unqualified six-dot PEF preparation is supported")


class FormalBrailleTranslator(Protocol):
    table_id: str
    table_version: str
    table_sha256: str

    def translate(self, source: str) -> str:
        """Return Unicode six-dot Braille cells from a formal rule table."""


class LiblouisTranslator:
    """Optional liblouis adapter. Table dependency closure is not yet attested.

    Pin the actual externally installed table and its metadata before using it.
    An installed liblouis dependency and a table digest are prerequisites; the
    caller remains responsible for verifying any included rule-table files.
    """

    def __init__(self, *, table_id: str, table_version: str, table_bytes: bytes) -> None:
        self.table_id = _nonempty(table_id, "table_id")
        self.table_version = _nonempty(table_version, "table_version")
        if type(table_bytes) is not bytes or not table_bytes:
            raise BrailleFactoryError("Table bytes are required for fingerprinting")
        self.table_sha256 = sha256(table_bytes).hexdigest()

    def translate(self, source: str) -> str:
        try:
            import louis  # type: ignore[import-not-found]
        except ImportError as exc:
            raise BrailleFactoryError("Liblouis is unavailable; translation was not attempted") from exc
        try:
            value = louis.translateString([self.table_id], source, mode=louis.dotsIO | louis.ucBrl)
        except Exception as exc:
            raise BrailleFactoryError("Liblouis translation failed") from exc
        if type(value) is not str:
            raise BrailleFactoryError("Liblouis returned an invalid result")
        return value


@dataclass(frozen=True, slots=True)
class BraillePreparation:
    pef: bytes
    manifest: dict[str, object]
    warnings: tuple[str, ...]


def _canonical_lines(document: BookDocument) -> tuple[list[str], str]:
    # Round trip the current mutable in-memory model through its existing
    # canonical wire validator; never trust an out-of-band stale block instance.
    canonical = BookDocument.from_dict(document.as_dict())
    if canonical.warnings or canonical.validate_structure():
        raise BrailleFactoryError("Book contains unresolved semantic/structural warnings")
    result: list[str] = [canonical.title]
    for block in canonical.blocks:
        data = block.as_dict()
        kind = data["kind"]
        if kind in {"Heading", "Paragraph", "Note"}:
            result.append(data["text"])
        elif kind == "List":
            result.extend(f"{i}. {item}" for i, item in enumerate(data["items"], start=data.get("start") or 1))
        elif kind in {"Position", "Diagram", "Exercise"}:
            fen = Board(data["fen"]).fen()
            label = "Chess diagram" if kind == "Diagram" else ("Exercise" if kind == "Exercise" else "Chess position")
            result.append(f"{label}. FEN: {fen}")
            for field in ("caption", "alt_text", "prompt", "answer_text", "side_to_move_note"):
                if data.get(field):
                    result.append(data[field])
            if data.get("solution_pgn"):
                result.append("Solution PGN: " + data["solution_pgn"])
        elif kind in {"Game", "VariationTree"}:
            if kind == "Game" and not data["pgn"].strip():
                raise BrailleFactoryError("Detached library game requires resolved canonical PGN")
            try:
                games = parse_pgn_text(data["pgn"], strict=False)
            except (ValueError, RecursionError) as exc:
                raise BrailleFactoryError("PGN cannot be proven by the canonical parser") from exc
            if len(games) != 1 or games[0].warnings:
                raise BrailleFactoryError("Game/variation PGN has unresolved canonical parsing warnings")
            if kind == "VariationTree":
                result.append("Variation root FEN: " + Board(data["root_fen"]).fen())
            if data.get("title"):
                result.append(data["title"])
            result.append("PGN: " + data["pgn"])
        else:
            raise BrailleFactoryError("Unsupported semantic book block")
    if len(result) > MAX_SEGMENTS:
        raise BrailleFactoryError("Book exceeds the supported Braille segment budget")
    # This is a content fingerprint, NOT an edition or rights certification.
    digest = sha256(json.dumps(canonical.as_dict(), ensure_ascii=False, sort_keys=True,
                               separators=(",", ":")).encode("utf-8")).hexdigest()
    return result, digest


def _braille_lines(segments: list[str], translator: FormalBrailleTranslator,
                   columns: int) -> list[str]:
    lines: list[str] = []
    cell_count = 0
    blank = "\u2800"
    for source in segments:
        translated = translator.translate(source)
        if type(translated) is not str or not translated:
            raise BrailleFactoryError("Formal translator produced empty/invalid Braille")
        if len(translated) > MAX_CELLS - cell_count:
            raise BrailleFactoryError("Braille cell resource budget exceeded")
        cell_count += len(translated)
        if any(not ("\u2800" <= c <= "\u283f") for c in translated):
            raise BrailleFactoryError("Translator output is not six-dot Unicode Braille")
        # PEF is a prepaginated cell format. Never silently cut words or cells.
        if translated.startswith(blank) or translated.endswith(blank) or blank + blank in translated:
            raise BrailleFactoryError("Ambiguous Braille whitespace cannot be paginated losslessly")
        words = translated.split(blank)
        row = ""
        for word in words:
            if len(word) > columns:
                raise BrailleFactoryError("A translated word exceeds the selected device width")
            candidate = (row + blank + word) if row else word
            if len(candidate) > columns:
                lines.append(row)
                row = word
            else:
                row = candidate
        if row:
            lines.append(row)
        if not row and not words:
            lines.append("")
    if not lines:
        raise BrailleFactoryError("No Braille content was produced")
    return lines


def prepare_chess_book_pef(
    document: BookDocument, profile: BrailleProfile,
    translator: FormalBrailleTranslator, *,
    rights_confirmed: bool, rights_basis: str,
) -> BraillePreparation:
    """Produce an explicitly UNVERIFIED internal PEF and machine-readable report.

    Never upgrades this artifact to PRINT_READY_AUTOMATICALLY_VERIFIED. That gate
    requires tested chess notation, real table dependencies, certified device
    and independent physical/semantic proof not supplied by this function.
    """
    if not isinstance(document, BookDocument) or not isinstance(profile, BrailleProfile):
        raise BrailleFactoryError("Canonical BookDocument and BrailleProfile are required")
    if rights_confirmed is not True:
        raise BrailleFactoryError("Explicit lawful rights confirmation is required")
    rights_basis = _nonempty(rights_basis, "rights_basis", 500)
    if any(getattr(translator, key, None) != getattr(profile, key)
           for key in ("table_id", "table_version", "table_sha256")):
        raise BrailleFactoryError("Unpinned or mismatched formal translation table")
    segments, source_sha = _canonical_lines(document)
    rows = _braille_lines(segments, translator, profile.cells_per_line)
    # A production-grade publisher will replace this bounded single-volume
    # preparation with verified multi-volume/device/duplex layout.
    pages = [rows[i:i + profile.lines_per_page]
             for i in range(0, len(rows), profile.lines_per_page)]
    if len(pages) > MAX_PAGES:
        raise BrailleFactoryError("Braille output exceeds the page budget")
    ET.register_namespace("", PEF_NS)
    ET.register_namespace("dc", DC_NS)
    root = ET.Element(f"{{{PEF_NS}}}pef", {"version": "2008-1"})
    head = ET.SubElement(root, f"{{{PEF_NS}}}head")
    meta = ET.SubElement(head, f"{{{PEF_NS}}}meta")
    ET.SubElement(meta, f"{{{DC_NS}}}format").text = "application/x-pef+xml"
    ET.SubElement(meta, f"{{{DC_NS}}}identifier").text = "urn:sha256:" + source_sha
    ET.SubElement(meta, f"{{{DC_NS}}}title").text = document.title
    ET.SubElement(meta, f"{{{DC_NS}}}language").text = profile.language
    body = ET.SubElement(root, f"{{{PEF_NS}}}body")
    volume = ET.SubElement(body, f"{{{PEF_NS}}}volume", {
        "cols": str(profile.cells_per_line), "rows": str(profile.lines_per_page),
        "rowgap": "0", "duplex": "false",
    })
    section = ET.SubElement(volume, f"{{{PEF_NS}}}section")
    for page_rows in pages:
        page = ET.SubElement(section, f"{{{PEF_NS}}}page")
        for text in page_rows:
            ET.SubElement(page, f"{{{PEF_NS}}}row").text = text
    pef = ET.tostring(root, encoding="utf-8", xml_declaration=True)
    # Structural independent reparse proves page dimensions only, not print readiness.
    check = ET.fromstring(pef)
    fmt = check.find(f"./{{{PEF_NS}}}head/{{{PEF_NS}}}meta/{{{DC_NS}}}format")
    identifier = check.find(f"./{{{PEF_NS}}}head/{{{PEF_NS}}}meta/{{{DC_NS}}}identifier")
    if fmt is None or fmt.text != "application/x-pef+xml" or identifier is None or identifier.text != "urn:sha256:" + source_sha:
        raise BrailleFactoryError("PEF required metadata failed qualification")
    actual = check.findall(f".//{{{PEF_NS}}}page")
    if len(actual) != len(pages) or any(
        len(page.findall(f"{{{PEF_NS}}}row")) > profile.lines_per_page
        or any(len((row.text or "")) > profile.cells_per_line
               for row in page.findall(f"{{{PEF_NS}}}row"))
        for page in actual
    ):
        raise BrailleFactoryError("PEF serialization failed structural qualification")
    manifest: dict[str, object] = {
        "schema_version": 1,
        "section": 55,
        "status": "UNVERIFIED_REQUIRES_DECISION",
        "print_ready": False,
        "format": "PEF",
        "source_book_sha256": source_sha,
        "output_pef_sha256": sha256(pef).hexdigest(),
        "table_id": profile.table_id,
        "table_version": profile.table_version,
        "table_sha256": profile.table_sha256,
        "language": profile.language,
        "device_model": profile.device_model,
        "device_verified": False,
        "rights_confirmed": True,
        "rights_basis": rights_basis,
        "source_warning_count": 0,
        "pages": len(pages),
        "cells_per_line": profile.cells_per_line,
        "lines_per_page": profile.lines_per_page,
        "qualification": "internal-structural-only",
    }
    warnings = (
        "Formal table dependency closure, translation semantics, chess-notation standard and backtranslation not independently qualified",
        "Physical embosser profile/duplex/tactile legibility and actual print-read acceptance unverified",
        "Only six-dot single-volume PEF is prepared; BRF/eBRL/OCR/queue/UI are not implemented",
    )
    return BraillePreparation(pef=pef, manifest=manifest, warnings=warnings)
