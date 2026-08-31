from __future__ import annotations

"""Bounded TXT/Markdown ingestion into the canonical semantic BookDocument.

This adapter owns text decoding and document-structure projection only. It never
infers chess semantics from ordinary prose, ASCII diagrams, old descriptive
notation, or visually suggestive text. Chess content is accepted only through
explicit Markdown fenced blocks and is delegated to existing canonical services:
FEN -> ``chesscore.Board`` and PGN -> bounded D06 ``parse_pgn_text``.
"""

from dataclasses import dataclass
from enum import Enum
from hashlib import sha256
import re
from types import MappingProxyType

from .bookdocument import BookDocument, Diagram, Game, Heading, Note, Paragraph, Position
from .chesscore import Board
from .pgn_roundtrip import PgnRoundTripError, parse_pgn_text


MAX_TEXT_SOURCE_BYTES = 8 * 1024 * 1024
MAX_TEXT_VISIBLE_CHARS = 12 * 1024 * 1024
MAX_TEXT_BLOCKS = 50_000
MAX_TEXT_FENCE_CHARS = 1 * 1024 * 1024
MAX_TEXT_WARNINGS = 2_048


class BookTextFormat(str, Enum):
    TXT = "txt"
    MARKDOWN = "markdown"


class BookTextImportErrorCode(str, Enum):
    INVALID_ARGUMENT = "invalid_argument"
    UNSUPPORTED_ENCODING = "unsupported_encoding"
    UNSUPPORTED_FORMAT = "unsupported_format"
    RESOURCE_LIMIT = "resource_limit"
    MALFORMED_MARKDOWN = "malformed_markdown"
    MALFORMED_CHESS_CONTENT = "malformed_chess_content"
    NO_READABLE_CONTENT = "no_readable_content"


class BookTextImportError(ValueError):
    """Stable text-ingress failure without local path/provider internals."""

    def __init__(self, message: str, *, code: BookTextImportErrorCode) -> None:
        super().__init__(message)
        self.code = BookTextImportErrorCode(code)


@dataclass(frozen=True, slots=True)
class BookTextImportResult:
    document: BookDocument
    source_sha256: str
    book_key: str
    source_format: BookTextFormat
    pgn_games: int
    positions: int
    warnings: tuple[str, ...]


def _required_text(value: object, field: str) -> str:
    if type(value) is not str or not value.strip():
        raise BookTextImportError(
            f"{field} must be non-empty text",
            code=BookTextImportErrorCode.INVALID_ARGUMENT,
        )
    return value.strip()


def _optional_text(value: object, field: str) -> str | None:
    if value is None:
        return None
    return _required_text(value, field)


def _source_text(source: object) -> tuple[str, bytes]:
    if type(source) is str:
        try:
            raw = source.encode("utf-8")
        except UnicodeEncodeError as exc:
            raise BookTextImportError(
                "Text book source must be valid Unicode text",
                code=BookTextImportErrorCode.UNSUPPORTED_ENCODING,
            ) from exc
        if len(raw) > MAX_TEXT_SOURCE_BYTES:
            raise BookTextImportError(
                "Text book source exceeds the supported size",
                code=BookTextImportErrorCode.RESOURCE_LIMIT,
            )
        return source, raw
    if type(source) is bytes:
        if len(source) > MAX_TEXT_SOURCE_BYTES:
            raise BookTextImportError(
                "Text book source exceeds the supported size",
                code=BookTextImportErrorCode.RESOURCE_LIMIT,
            )
        try:
            return source.decode("utf-8-sig"), source
        except UnicodeDecodeError as exc:
            raise BookTextImportError(
                "Text book source must use UTF-8 encoding",
                code=BookTextImportErrorCode.UNSUPPORTED_ENCODING,
            ) from exc
    raise BookTextImportError(
        "Text book source must be text or bytes",
        code=BookTextImportErrorCode.INVALID_ARGUMENT,
    )


def _format(value: object) -> BookTextFormat:
    if isinstance(value, BookTextFormat):
        return value
    if type(value) is str:
        normalized = value.strip().lower()
        aliases = {
            "txt": BookTextFormat.TXT,
            "text": BookTextFormat.TXT,
            "plain": BookTextFormat.TXT,
            "plain-text": BookTextFormat.TXT,
            "md": BookTextFormat.MARKDOWN,
            "markdown": BookTextFormat.MARKDOWN,
        }
        if normalized in aliases:
            return aliases[normalized]
    raise BookTextImportError(
        "Book text format must be TXT or Markdown",
        code=BookTextImportErrorCode.UNSUPPORTED_FORMAT,
    )


def _normalize_newlines(text: str) -> str:
    return text.replace("\r\n", "\n").replace("\r", "\n")


def _compact_paragraph(lines: list[str]) -> str:
    return " ".join(part.strip() for part in lines if part.strip()).strip()


class _Builder:
    def __init__(self, source_format: BookTextFormat) -> None:
        self.source_format = source_format
        self.blocks: list[object] = []
        self.warnings: list[str] = []
        self.pgn_games = 0
        self.positions = 0
        self._identities: dict[str, int] = {}

    def _id(self, kind: str, payload: str) -> str:
        digest = sha256((kind + "\0" + payload).encode("utf-8")).hexdigest()[:20]
        key = f"{kind}:{digest}"
        occurrence = self._identities.get(key, 0) + 1
        self._identities[key] = occurrence
        return f"{self.source_format.value}-{digest}-{occurrence}"

    def _append(self, block: object) -> None:
        if len(self.blocks) >= MAX_TEXT_BLOCKS:
            raise BookTextImportError(
                "Text book contains too many semantic blocks",
                code=BookTextImportErrorCode.RESOURCE_LIMIT,
            )
        self.blocks.append(block)

    def warning(self, text: str) -> None:
        if len(self.warnings) < MAX_TEXT_WARNINGS:
            self.warnings.append(text)
        elif len(self.warnings) == MAX_TEXT_WARNINGS:
            self.warnings.append("additional text import warnings were suppressed")

    def paragraph(self, text: str, line: int) -> None:
        text = text.strip()
        if not text:
            return
        self._append(
            Paragraph(
                text=text,
                block_id=self._id("Paragraph", text),
                source_anchor=f"line:{line}",
            )
        )

    def heading(self, text: str, level: int, line: int) -> None:
        text = text.strip()
        if not text:
            return
        self._append(
            Heading(
                text=text,
                level=level,
                block_id=self._id("Heading", f"{level}\0{text}"),
                source_anchor=f"line:{line}",
            )
        )

    def code_note(self, language: str, body: str, line: int) -> None:
        label = language or "code"
        self._append(
            Note(
                text=body,
                note_type=f"code:{label}",
                block_id=self._id("Code", label + "\0" + body),
                source_anchor=f"line:{line}",
            )
        )

    def image_note(self, alt: str, line: int) -> None:
        self._append(
            Note(
                text=alt,
                note_type="image",
                block_id=self._id("Image", alt),
                source_anchor=f"line:{line}",
            )
        )
        self.warning("Markdown image reference was preserved as accessible text; no asset was fetched and no chess position was inferred")

    def fen(self, body: str, line: int, *, diagram: bool) -> None:
        lines = [part.strip() for part in body.splitlines() if part.strip()]
        if not lines:
            raise BookTextImportError(
                "Explicit FEN block is empty",
                code=BookTextImportErrorCode.MALFORMED_CHESS_CONTENT,
            )
        fen_text = lines[0]
        try:
            canonical = Board(fen_text).fen()
        except (TypeError, ValueError) as exc:
            raise BookTextImportError(
                "Explicit FEN block contains an invalid canonical chess position",
                code=BookTextImportErrorCode.MALFORMED_CHESS_CONTENT,
            ) from exc
        caption = " ".join(lines[1:]).strip() or None
        if diagram:
            self._append(
                Diagram(
                    fen=canonical,
                    alt_text=caption,
                    caption=caption,
                    block_id=self._id("Diagram", canonical + "\0" + (caption or "")),
                    source_anchor=f"line:{line}",
                )
            )
        else:
            self._append(
                Position(
                    fen=canonical,
                    caption=caption,
                    block_id=self._id("Position", canonical + "\0" + (caption or "")),
                    source_anchor=f"line:{line}",
                )
            )
        self.positions += 1

    def pgn(self, body: str, line: int) -> None:
        if len(body) > MAX_TEXT_FENCE_CHARS:
            raise BookTextImportError(
                "Explicit PGN block exceeds the supported size",
                code=BookTextImportErrorCode.RESOURCE_LIMIT,
            )
        try:
            games = parse_pgn_text(body, strict=False)
        except (PgnRoundTripError, RecursionError, ValueError) as exc:
            raise BookTextImportError(
                "Explicit PGN block cannot be represented by the canonical PGN model",
                code=BookTextImportErrorCode.MALFORMED_CHESS_CONTENT,
            ) from exc
        if len(games) != 1:
            raise BookTextImportError(
                "Explicit PGN block must contain exactly one canonical game",
                code=BookTextImportErrorCode.MALFORMED_CHESS_CONTENT,
            )
        game = games[0]
        title = " — ".join(
            part for part in (game.tags.get("White"), game.tags.get("Black"))
            if part and part != "?"
        ) or game.tags.get("Event") or "Embedded game"
        clean = body.strip()
        self._append(
            Game(
                pgn=clean,
                title=title,
                block_id=self._id("Game", clean),
                source_anchor=f"line:{line}",
            )
        )
        self.pgn_games += 1


_HEADING_RE = re.compile(r"^(#{1,6})[ \t]+(.+?)\s*#*\s*$")
_FENCE_RE = re.compile(r"^\s*(`{3,}|~{3,})([^`]*)$")
_IMAGE_RE = re.compile(r"!\[([^\]]+)\]\([^\)]+\)")
_LIST_RE = re.compile(r"^\s*(?:[-+*]|\d+[.)])\s+(.+)$")
_QUOTE_RE = re.compile(r"^\s*>\s?(.*)$")


def _parse_txt(text: str, builder: _Builder) -> None:
    lines = _normalize_newlines(text).split("\n")
    paragraph: list[str] = []
    start = 1
    visible = 0
    for number, line in enumerate(lines, start=1):
        visible += len(line)
        if visible > MAX_TEXT_VISIBLE_CHARS:
            raise BookTextImportError(
                "Text book visible text exceeds the supported size",
                code=BookTextImportErrorCode.RESOURCE_LIMIT,
            )
        if line.strip():
            if not paragraph:
                start = number
            paragraph.append(line)
            continue
        if paragraph:
            builder.paragraph(_compact_paragraph(paragraph), start)
            paragraph = []
    if paragraph:
        builder.paragraph(_compact_paragraph(paragraph), start)


def _parse_markdown(text: str, builder: _Builder) -> None:
    lines = _normalize_newlines(text).split("\n")
    paragraph: list[str] = []
    paragraph_start = 1
    visible = 0
    index = 0

    def flush() -> None:
        nonlocal paragraph
        if paragraph:
            builder.paragraph(_compact_paragraph(paragraph), paragraph_start)
            paragraph = []

    while index < len(lines):
        line = lines[index]
        number = index + 1
        visible += len(line)
        if visible > MAX_TEXT_VISIBLE_CHARS:
            raise BookTextImportError(
                "Markdown book visible text exceeds the supported size",
                code=BookTextImportErrorCode.RESOURCE_LIMIT,
            )
        fence = _FENCE_RE.match(line)
        if fence:
            flush()
            marker = fence.group(1)
            language = fence.group(2).strip().lower().split(None, 1)[0] if fence.group(2).strip() else ""
            body_lines: list[str] = []
            fence_chars = 0
            index += 1
            closed = False
            while index < len(lines):
                current = lines[index]
                if current.strip() and current.strip()[0] == marker[0] and len(current.strip()) >= len(marker) and set(current.strip()) == {marker[0]}:
                    closed = True
                    break
                body_lines.append(current)
                fence_chars += len(current) + 1
                if fence_chars > MAX_TEXT_FENCE_CHARS:
                    raise BookTextImportError(
                        "Markdown fenced block exceeds the supported size",
                        code=BookTextImportErrorCode.RESOURCE_LIMIT,
                    )
                index += 1
            if not closed:
                raise BookTextImportError(
                    "Markdown fenced block is not closed",
                    code=BookTextImportErrorCode.MALFORMED_MARKDOWN,
                )
            body = "\n".join(body_lines).strip()
            if language in {"pgn", "chess-pgn", "acs-pgn"}:
                builder.pgn(body, number)
            elif language in {"fen", "acs-fen"}:
                builder.fen(body, number, diagram=False)
            elif language in {"diagram-fen", "acs-diagram-fen"}:
                builder.fen(body, number, diagram=True)
            elif body:
                builder.code_note(language, body, number)
            index += 1
            continue

        heading = _HEADING_RE.match(line)
        if heading:
            flush()
            builder.heading(heading.group(2), len(heading.group(1)), number)
            index += 1
            continue

        if not line.strip():
            flush()
            index += 1
            continue

        images = _IMAGE_RE.findall(line)
        if images:
            flush()
            for alt in images:
                alt = alt.strip()
                if alt:
                    builder.image_note(alt, number)
            remaining = _IMAGE_RE.sub("", line).strip()
            if remaining:
                builder.paragraph(remaining, number)
            index += 1
            continue

        list_match = _LIST_RE.match(line)
        quote_match = _QUOTE_RE.match(line)
        if list_match:
            flush()
            builder.paragraph("• " + list_match.group(1).strip(), number)
            builder.warning("Markdown list structure was preserved as ordered reading text because the current BookDocument has no list block kind")
            index += 1
            continue
        if quote_match:
            flush()
            quote = quote_match.group(1).strip()
            if quote:
                builder.paragraph(quote, number)
            builder.warning("Markdown block quote structure was preserved as reading text because the current BookDocument has no quote block kind")
            index += 1
            continue

        if not paragraph:
            paragraph_start = number
        paragraph.append(line)
        index += 1

    flush()


def import_text_book(
    source: str | bytes,
    *,
    source_name: str,
    source_format: BookTextFormat | str,
    title: str | None = None,
    author: str | None = None,
    language: str | None = None,
) -> BookTextImportResult:
    """Import UTF-8 TXT or Markdown into an existing semantic ``BookDocument``.

    The adapter performs no filesystem or network access. Plain TXT is readable
    text only: it never guesses headings, games, FENs, or ASCII chess diagrams.
    Markdown chess semantics require explicit fenced ``pgn``/``fen`` markers.
    """

    display_source = _required_text(source_name, "source_name")
    resolved_format = _format(source_format)
    override_title = _optional_text(title, "title")
    override_author = _optional_text(author, "author")
    override_language = _optional_text(language, "language")
    text, raw = _source_text(source)
    builder = _Builder(resolved_format)

    if resolved_format is BookTextFormat.TXT:
        _parse_txt(text, builder)
    else:
        _parse_markdown(text, builder)

    if not builder.blocks:
        raise BookTextImportError(
            "Text book contains no readable semantic content",
            code=BookTextImportErrorCode.NO_READABLE_CONTENT,
        )

    resolved_title = override_title
    if resolved_title is None and resolved_format is BookTextFormat.MARKDOWN:
        resolved_title = next(
            (block.text for block in builder.blocks if isinstance(block, Heading)),
            None,
        )
    resolved_title = resolved_title or display_source

    document = BookDocument(
        title=resolved_title,
        author=override_author,
        language=override_language,
        source_name=display_source,
        blocks=list(builder.blocks),
        warnings=list(builder.warnings),
    )
    digest = sha256(raw).hexdigest()
    return BookTextImportResult(
        document=document,
        source_sha256=digest,
        book_key=f"{resolved_format.value}-sha256:{digest}",
        source_format=resolved_format,
        pgn_games=builder.pgn_games,
        positions=builder.positions,
        warnings=tuple(builder.warnings),
    )


BOOK_TEXT_CAPABILITIES = MappingProxyType(
    {
        "TXT": {
            "status": "SUPPORTED",
            "encoding": "UTF-8",
            "semantics": ("Paragraph",),
            "chess_inference": "NONE",
        },
        "Markdown": {
            "status": "PARTIAL",
            "encoding": "UTF-8",
            "semantics": (
                "Heading",
                "Paragraph",
                "Note(image/code)",
                "Game(explicit fenced PGN)",
                "Position(explicit fenced FEN)",
                "Diagram(explicit fenced diagram-FEN)",
            ),
            "chess_inference": "EXPLICIT_FENCES_ONLY",
        },
        "does_not_claim": (
            "HTML/XHTML",
            "DOCX",
            "EPUB",
            "PDF/OCR",
            "arbitrary legacy encodings",
            "ASCII-diagram recognition",
            "implicit PGN/FEN recognition from prose",
            "network or filesystem source fetching",
        ),
    }
)
