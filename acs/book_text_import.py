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
from typing import Callable

from .bookdocument import (
    BookDocument,
    Diagram,
    Game,
    Heading,
    ListBlock,
    Note,
    Paragraph,
    Position,
)
from .chesscore import Board
from .legacy_text_encoding import LegacyTextEncodingError, decode_book_text_bytes
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


def _source_text(source: object) -> tuple[str, bytes, bool]:
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
        return source, raw, False
    if type(source) is bytes:
        if len(source) > MAX_TEXT_SOURCE_BYTES:
            raise BookTextImportError(
                "Text book source exceeds the supported size",
                code=BookTextImportErrorCode.RESOURCE_LIMIT,
            )
        try:
            decoded = decode_book_text_bytes(source)
        except LegacyTextEncodingError as exc:
            raise BookTextImportError(
                "Text book source must use UTF-8, BOM UTF-16 or qualified Windows-1251 encoding",
                code=BookTextImportErrorCode.UNSUPPORTED_ENCODING,
            ) from exc
        return decoded.text, source, decoded.legacy
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
        self._warnings_suppressed = False
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
        if self._warnings_suppressed:
            return
        if len(self.warnings) < MAX_TEXT_WARNINGS:
            self.warnings.append(text)
            return
        # MAX_TEXT_WARNINGS is the complete publication budget, including the
        # suppression marker. Preserve every warning when there is no overflow;
        # on the first overflow replace only the final budget slot.
        if MAX_TEXT_WARNINGS > 0:
            self.warnings[-1] = "additional text import warnings were suppressed"
        self._warnings_suppressed = True

    def paragraph(
        self,
        text: str,
        line: int,
        *,
        identity_text: str | None = None,
    ) -> None:
        text = text.strip()
        if not text:
            return
        identity = text if identity_text is None else identity_text.strip()
        if not identity:
            identity = text
        self._append(
            Paragraph(
                text=text,
                block_id=self._id("Paragraph", identity),
                source_anchor=f"line:{line}",
            )
        )

    def heading(
        self,
        text: str,
        level: int,
        line: int,
        *,
        identity_text: str | None = None,
    ) -> None:
        text = text.strip()
        if not text:
            return
        identity = text if identity_text is None else identity_text.strip()
        if not identity:
            identity = text
        self._append(
            Heading(
                text=text,
                level=level,
                block_id=self._id("Heading", f"{level}\0{identity}"),
                source_anchor=f"line:{line}",
            )
        )

    def list_block(
        self,
        items: list[str],
        line: int,
        *,
        ordered: bool,
        start: int | None,
    ) -> None:
        clean = [item.strip() for item in items if item.strip()]
        if not clean:
            return
        identity = (
            ("ordered" if ordered else "unordered")
            + "\0"
            + (str(start) if start is not None else "")
            + "\0"
            + "\0".join(clean)
        )
        self._append(
            ListBlock(
                items=clean,
                ordered=ordered,
                start=start,
                block_id=self._id("List", identity),
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
        if game.warnings:
            self.warning(
                "Explicit PGN block required canonical recovery; review the game before relying on recovered content"
            )
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


_HEADING_RE = re.compile(r"^(#{1,6})[ \t]+(.+?)(?:[ \t]+#+)?[ \t]*$")
_LEGACY_HEADING_ID_RE = re.compile(r"^(#{1,6})[ \t]+(.+?)\s*#*\s*$")
_FENCE_RE = re.compile(r"^ {0,3}(`{3,}|~{3,})([^`]*)$")
_IMAGE_RE = re.compile(r"!\[([^\]]+)\]\([^\)]+\)")
_IMAGE_OPEN_RE = re.compile(r"!\[([^\]]+)\]\(")
_LIST_RE = re.compile(
    r"^(?P<indent>[ \t]*)(?:(?P<bullet>[-+*])|(?P<number>[0-9]{1,9})(?P<delimiter>[.)]))\s+(?P<text>.+)$"
)
_QUOTE_RE = re.compile(r"^\s*>\s?(.*)$")


@dataclass(frozen=True, slots=True)
class _SemanticImageMatch:
    start_index: int
    end_index: int
    alt: str

    def start(self) -> int:
        return self.start_index

    def end(self) -> int:
        return self.end_index

    def group(self, index: int) -> str:
        if index != 1:
            raise IndexError("semantic image match exposes only alt-text group 1")
        return self.alt


def _iter_semantic_images(line: str):
    """Yield bounded inline images outside conservative backtick literals.

    This remains a single-pass recognizer, not a second Markdown parser.
    Escaped punctuation and backtick-delimited text stay readable source text.
    Image destinations are consumed through their balanced closing parenthesis
    so nested or escaped parentheses cannot leak URL fragments into semantic
    BookDocument text. Unclosed destinations remain literal source text.
    """

    index = 0
    code_ticks = 0
    length = len(line)
    while index < length:
        char = line[index]
        if char == "`":
            end = index + 1
            while end < length and line[end] == "`":
                end += 1
            run_length = end - index
            if code_ticks == 0:
                code_ticks = run_length
            elif run_length == code_ticks:
                code_ticks = 0
            index = end
            continue
        if code_ticks:
            # Backslashes are literal inside a code span; they must not escape
            # the matching closing backtick run.
            index += 1
            continue
        if char == "\\":
            index = min(length, index + 2)
            continue

        opener = _IMAGE_OPEN_RE.match(line, index)
        if opener is not None:
            destination_start = opener.end()
            cursor = destination_start
            depth = 1
            while cursor < length:
                destination_char = line[cursor]
                if destination_char == "\\":
                    cursor = min(length, cursor + 2)
                    continue
                if destination_char == "(":
                    depth += 1
                    cursor += 1
                    continue
                if destination_char == ")":
                    depth -= 1
                    if depth == 0:
                        if cursor > destination_start:
                            yield _SemanticImageMatch(
                                start_index=index,
                                end_index=cursor + 1,
                                alt=opener.group(1),
                            )
                            index = cursor + 1
                        break
                    cursor += 1
                    continue
                cursor += 1
            if depth == 0 and index == cursor + 1:
                continue

        index += 1


def _accessible_list_item_text(text: str) -> tuple[str, bool]:
    """Preserve inline image alt text inside a flat canonical list item.

    BookDocument ListBlock has no nested image child kind.  A Markdown image in
    a list item therefore stays in the list as selectable/readable alt text,
    while the caller emits an explicit structural-loss warning.  Asset URLs are
    never fetched or exposed as inferred chess semantics.
    """

    matches = _iter_semantic_images(text)
    first = next(matches, None)
    if first is None:
        return text.strip(), False

    parts: list[str] = []
    cursor = 0
    match = first
    while match is not None:
        parts.append(text[cursor:match.start()])
        alt = match.group(1).strip()
        if alt:
            parts.append(alt)
        cursor = match.end()
        match = next(matches, None)
    parts.append(text[cursor:])
    return re.sub(r"[ \t]+", " ", "".join(parts)).strip(), True


def _readable_list_fallback(match: re.Match[str]) -> tuple[str, bool]:
    """Flatten an unrepresentable list row without leaking image destinations.

    Keep the authored marker visible so reading order and list intent survive the
    fallback, but reduce semantic inline images to their accessible alt text.
    This never fetches assets or infers chess content.
    """

    ordered = match.group("number") is not None
    marker = (
        f"{match.group('number')}{match.group('delimiter')}"
        if ordered
        else match.group("bullet")
    )
    item, had_image = _accessible_list_item_text(match.group("text"))
    return f"{marker} {item}".rstrip(), had_image


def _is_fence_close(line: str, marker: str) -> bool:
    leading_spaces = len(line) - len(line.lstrip(" "))
    if leading_spaces > 3:
        return False
    candidate = line[leading_spaces:].rstrip(" \t")
    return (
        len(candidate) >= len(marker)
        and bool(candidate)
        and set(candidate) == {marker[0]}
    )


def _parse_txt(text: str, builder: _Builder, control_checkpoint: Callable[[], None] | None = None) -> None:
    lines = _normalize_newlines(text).split("\n")
    paragraph: list[str] = []
    start = 1
    visible = 0
    for number, line in enumerate(lines, start=1):
        if control_checkpoint is not None and number % 128 == 1:
            control_checkpoint()
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


def _parse_markdown(text: str, builder: _Builder, control_checkpoint: Callable[[], None] | None = None) -> None:
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
        if control_checkpoint is not None:
            control_checkpoint()
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
                if control_checkpoint is not None and index % 128 == 0:
                    control_checkpoint()
                current = lines[index]
                if _is_fence_close(current, marker):
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
            legacy_heading = _LEGACY_HEADING_ID_RE.match(line)
            identity_text = (
                legacy_heading.group(2)
                if legacy_heading is not None
                else heading.group(2)
            )
            builder.heading(
                heading.group(2),
                len(heading.group(1)),
                number,
                identity_text=identity_text,
            )
            index += 1
            continue

        if not line.strip():
            flush()
            index += 1
            continue

        image_matches = _iter_semantic_images(line)
        first_image = next(image_matches, None)
        if first_image is not None and _LIST_RE.match(line) is None:
            flush()
            # Before this source-order repair, all regex-shaped image Notes were
            # appended first and one combined Paragraph containing the remaining
            # prose was appended last. Keep that historical Paragraph identity
            # while recognizing only unescaped images outside literal code now.
            legacy_paragraph_identity = _IMAGE_RE.sub("", line).strip() or None
            legacy_identity_available = legacy_paragraph_identity is not None
            cursor = 0
            match = first_image
            while match is not None:
                leading = line[cursor:match.start()].strip()
                if leading:
                    builder.paragraph(
                        leading,
                        number,
                        identity_text=(
                            legacy_paragraph_identity
                            if legacy_identity_available
                            else None
                        ),
                    )
                    legacy_identity_available = False
                alt = match.group(1).strip()
                if alt:
                    builder.image_note(alt, number)
                cursor = match.end()
                match = next(image_matches, None)
            trailing = line[cursor:].strip()
            if trailing:
                builder.paragraph(
                    trailing,
                    number,
                    identity_text=(
                        legacy_paragraph_identity
                        if legacy_identity_available
                        else None
                    ),
                )
            index += 1
            continue

        list_match = _LIST_RE.match(line)
        quote_match = _QUOTE_RE.match(line)
        if list_match:
            flush()
            indent = list_match.group("indent")
            ordered = list_match.group("number") is not None
            start_value = int(list_match.group("number")) if ordered else None

            if "\t" in indent or len(indent) > 3:
                fallback_text, fallback_had_image = _readable_list_fallback(
                    list_match
                )
                builder.paragraph(fallback_text, number)
                builder.warning(
                    "Markdown list indentation or nesting could not be represented canonically and was preserved as readable text"
                )
                if fallback_had_image:
                    builder.warning(
                        "Markdown image inside an unrepresentable list item was preserved as accessible text; no asset was fetched and nested image structure is not represented"
                    )
                index += 1
                continue

            if ordered and start_value is not None and start_value < 1:
                fallback_text, fallback_had_image = _readable_list_fallback(
                    list_match
                )
                builder.paragraph(fallback_text, number)
                builder.warning(
                    "Markdown ordered list with non-positive start was preserved as reading text because canonical List start must be positive"
                )
                if fallback_had_image:
                    builder.warning(
                        "Markdown image inside an unrepresentable list item was preserved as accessible text; no asset was fetched and nested image structure is not represented"
                    )
                index += 1
                continue

            first_item, list_image_warning = _accessible_list_item_text(
                list_match.group("text")
            )
            items = [first_item]
            marker_identity = (
                list_match.group("delimiter")
                if ordered
                else list_match.group("bullet")
            )
            next_index = index + 1
            while next_index < len(lines):
                if control_checkpoint is not None and next_index % 128 == 0:
                    control_checkpoint()
                candidate = lines[next_index]
                candidate_match = _LIST_RE.match(candidate)
                if candidate_match is None or candidate_match.group("indent") != indent:
                    break
                candidate_ordered = candidate_match.group("number") is not None
                if candidate_ordered != ordered:
                    break
                candidate_marker_identity = (
                    candidate_match.group("delimiter")
                    if candidate_ordered
                    else candidate_match.group("bullet")
                )
                if candidate_marker_identity != marker_identity:
                    break
                # Markdown numbering after the first ordered marker does not
                # define the rendered sequence. The first marker establishes
                # the canonical start; later authored numbers remain list items
                # unless the delimiter or indentation changes. Requiring +1
                # here created false list boundaries for keyboard/NVDA readers.
                visible += len(candidate)
                if visible > MAX_TEXT_VISIBLE_CHARS:
                    raise BookTextImportError(
                        "Markdown book visible text exceeds the supported size",
                        code=BookTextImportErrorCode.RESOURCE_LIMIT,
                    )
                candidate_item, candidate_had_image = _accessible_list_item_text(
                    candidate_match.group("text")
                )
                items.append(candidate_item)
                list_image_warning = list_image_warning or candidate_had_image
                next_index += 1

            builder.list_block(
                items,
                number,
                ordered=ordered,
                start=start_value if ordered else None,
            )
            if list_image_warning:
                builder.warning(
                    "Markdown image inside a list item was preserved as accessible list-item text; no asset was fetched and nested image structure is not represented"
                )

            # One to three leading spaces can represent a top-level Markdown
            # list when the whole list uses that indentation.  A deeper list
            # marker immediately following this list, however, is authored
            # nesting. BookDocument has no nested-list model, so never flatten
            # that child into a second peer ListBlock. Preserve its text and
            # surface the structural loss explicitly.
            nested_warning_emitted = False
            while next_index < len(lines):
                if control_checkpoint is not None and next_index % 128 == 0:
                    control_checkpoint()
                nested_line = lines[next_index]
                nested_match = _LIST_RE.match(nested_line)
                if nested_match is None:
                    break
                nested_indent = nested_match.group("indent")
                is_deeper = (
                    "\t" in nested_indent
                    or len(nested_indent) > len(indent)
                )
                if not is_deeper:
                    break
                visible += len(nested_line)
                if visible > MAX_TEXT_VISIBLE_CHARS:
                    raise BookTextImportError(
                        "Markdown book visible text exceeds the supported size",
                        code=BookTextImportErrorCode.RESOURCE_LIMIT,
                    )
                fallback_text, fallback_had_image = _readable_list_fallback(
                    nested_match
                )
                builder.paragraph(fallback_text, next_index + 1)
                if fallback_had_image:
                    builder.warning(
                        "Markdown image inside an unrepresentable list item was preserved as accessible text; no asset was fetched and nested image structure is not represented"
                    )
                if not nested_warning_emitted:
                    builder.warning(
                        "Markdown list indentation or nesting could not be represented canonically and was preserved as readable text"
                    )
                    nested_warning_emitted = True
                next_index += 1

            index = next_index
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
    control_checkpoint: Callable[[], None] | None = None,
) -> BookTextImportResult:
    """Import UTF-8, BOM UTF-16 or qualified Windows-1251 into ``BookDocument``.

    The adapter performs no filesystem or network access. Plain TXT is readable
    text only: it never guesses headings, games, FENs, or ASCII chess diagrams.
    Markdown chess semantics require explicit fenced ``pgn``/``fen`` markers.
    """

    if control_checkpoint is not None:
        if not callable(control_checkpoint):
            raise TypeError("control_checkpoint must be callable")
        control_checkpoint()
    display_source = _required_text(source_name, "source_name")
    resolved_format = _format(source_format)
    override_title = _optional_text(title, "title")
    override_author = _optional_text(author, "author")
    override_language = _optional_text(language, "language")
    text, raw, legacy_windows_1251 = _source_text(source)
    builder = _Builder(resolved_format)
    if legacy_windows_1251:
        builder.warning("Legacy Windows-1251 book text was decoded losslessly.")

    if resolved_format is BookTextFormat.TXT:
        _parse_txt(text, builder, control_checkpoint)
    else:
        _parse_markdown(text, builder, control_checkpoint)

    if control_checkpoint is not None:
        control_checkpoint()

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
            "encoding": "UTF-8; BOM-declared UTF-16; evidence-gated Windows-1251",
            "semantics": ("Paragraph",),
            "chess_inference": "NONE",
        },
        "Markdown": {
            "status": "PARTIAL",
            "encoding": "UTF-8; BOM-declared UTF-16; evidence-gated Windows-1251",
            "semantics": (
                "Heading",
                "Paragraph",
                "List(ordered/unordered)",
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
            "legacy encodings other than qualified Windows-1251",
            "ASCII-diagram recognition",
            "implicit PGN/FEN recognition from prose",
            "network or filesystem source fetching",
        ),
    }
)
