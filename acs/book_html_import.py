from __future__ import annotations

"""Bounded HTML/XHTML ingestion into the semantic :mod:`acs.bookdocument` model.

This adapter owns source decoding and structure projection only.  It does not
implement chess rules or a PGN parser: explicit positions are validated by the
canonical :class:`acs.chesscore.Board`, and embedded PGN candidates are considered
only after an exact standalone ``{PGN N}`` source marker. The existing bounded
D06 ingress owns parsing; each resulting Game block holds exactly one game.

Image-only diagrams remain image notes unless the source carries an explicit
``data-acs-fen`` marker.  The importer never guesses a chess position or game from
pixels, alt text, coordinates, ordinary prose, or unmarked PGN-looking text.
"""

from dataclasses import dataclass, field
from enum import Enum
from hashlib import sha256
from html.parser import HTMLParser
from io import StringIO
import re
from types import MappingProxyType
from typing import Callable
from urllib.parse import urlsplit

from .bookdocument import (
    MAX_BOOK_DOCUMENT_BLOCKS,
    MAX_BOOK_SOURCE_ANCHOR_CHARS,
    MAX_BOOK_TEXT_FIELD_CHARS,
    BookDocument,
    BookDocumentError,
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
from .gametree import GameTreeSerializationError, serialize_game
from .pgn_roundtrip import PgnRoundTripError, parse_pgn_text


MAX_HTML_SOURCE_BYTES = 8 * 1024 * 1024
MAX_HTML_VISIBLE_CHARS = 12 * 1024 * 1024
MAX_HTML_BLOCKS = MAX_BOOK_DOCUMENT_BLOCKS
MAX_HTML_IMAGES = 10_000
MAX_HTML_PGN_GAMES = 1_024
MAX_HTML_PGN_CANDIDATES = MAX_HTML_PGN_GAMES * 4
MAX_HTML_PGN_CHARS = 1 * 1024 * 1024
MAX_HTML_WARNINGS = 2_048
MAX_HTML_AVAILABLE_ASSET_TOTAL_CHARS = MAX_HTML_SOURCE_BYTES * 2


class BookHtmlImportErrorCode(str, Enum):
    INVALID_ARGUMENT = "invalid_argument"
    UNSUPPORTED_ENCODING = "unsupported_encoding"
    RESOURCE_LIMIT = "resource_limit"
    MALFORMED_CHESS_CONTENT = "malformed_chess_content"
    NO_READABLE_CONTENT = "no_readable_content"


class BookHtmlImportError(ValueError):
    """Stable HTML-ingress failure without local paths or parser internals."""

    def __init__(self, message: str, *, code: BookHtmlImportErrorCode) -> None:
        super().__init__(message)
        self.code = BookHtmlImportErrorCode(code)


@dataclass(frozen=True, slots=True)
class BookHtmlImportResult:
    document: BookDocument
    source_sha256: str
    book_key: str
    pgn_games: int
    image_references: tuple[str, ...]
    missing_assets: tuple[str, ...]
    warnings: tuple[str, ...]


@dataclass(slots=True)
class _InlineSemanticEvent:
    part_index: int
    block: object
    structural: bool = False
    forces_split: bool = False
    resume_part_index: int | None = None


@dataclass(frozen=True, slots=True)
class _PgnCandidate:
    text: str
    marker_offset: int
    source_anchor: str | None = None


@dataclass(frozen=True, slots=True)
class _PgnSlot:
    candidate: _PgnCandidate


@dataclass(slots=True)
class _Capture:
    tag: str
    kind: str
    attrs: dict[str, str]
    parts: list[str]
    visible_start_offset: int
    boundary_count: int = 0
    list_depth: int = 0
    inline_semantics: list[_InlineSemanticEvent] = field(default_factory=list)
    parent_inline_owner: _Capture | None = field(default=None, repr=False, compare=False)
    parent_part_index: int | None = None
    block_start_index: int = 0


@dataclass(slots=True)
class _ListCapture:
    tag: str
    attrs: dict[str, str]
    items: list[str] = field(default_factory=list)
    identity_items: list[str] = field(default_factory=list)
    unsupported: bool = False
    structural_unsupported: bool = False
    nested: bool = False
    inline_semantic_fallback: bool = False
    legacy_identity_block: object | None = field(default=None, repr=False, compare=False)


_BLOCK_BOUNDARY_TAGS = frozenset(
    {
        "address", "article", "aside", "blockquote", "br", "dd", "div", "dl",
        "dt", "figcaption", "figure", "footer", "form", "h1", "h2", "h3",
        "h4", "h5", "h6", "header", "hr", "li", "main", "nav", "ol", "p",
        "pre", "section", "table", "tbody", "td", "tfoot", "th", "thead", "tr", "ul",
    }
)
_SUPPRESSED_TAGS = frozenset({"script", "style", "noscript", "template"})
_VOID_TAGS = frozenset(
    {
        "area", "base", "br", "col", "embed", "hr", "img", "input",
        "link", "meta", "param", "source", "track", "wbr",
    }
)
_CAPTURE_KINDS = {
    "title": "title",
    "h1": "heading",
    "h2": "heading",
    "h3": "heading",
    "h4": "heading",
    "h5": "heading",
    "h6": "heading",
    "p": "paragraph",
    "li": "list_item",
    "blockquote": "paragraph",
    "figcaption": "paragraph",
    "tr": "table_row",
    "pre": "pre",
}
_PGN_EVENT_RE = re.compile(r'^\[Event\s+"', re.IGNORECASE)
_PGN_MARKER_RE = re.compile(r'^\{PGN\s+\d+\}\s*$', re.IGNORECASE)
_END_PGN_RE = re.compile(r'^End of PGN Supplement\s*$', re.IGNORECASE)
_HTML_INTEGER_RE = re.compile(r"^[+-]?\d+$")
_CSS_WHITESPACE = " \t\r\n\f"
_CSS_IMPORTANT_RE = re.compile(r"[ \t\r\n\f]*![ \t\r\n\f]*important[ \t\r\n\f]*$")

_CSS_DISPLAY_SINGLE_VALUES = frozenset(
    {
        "none", "contents", "block", "inline", "run-in", "flow", "flow-root",
        "table", "flex", "grid", "ruby", "math", "grid-lanes", "inline-grid-lanes",
        "list-item", "inline-block", "inline-table", "inline-flex", "inline-grid",
        "table-row-group",
        "table-header-group", "table-footer-group", "table-row", "table-cell",
        "table-column-group", "table-column", "table-caption", "ruby-base",
        "ruby-text", "ruby-base-container", "ruby-text-container",
        "initial", "unset",
    }
)
_CSS_DISPLAY_OUTSIDE = frozenset({"block", "inline", "run-in"})
# CSS Display Level 4 permits math as the inside alternative paired with an
# outside display keyword (for example, "block math").
_CSS_DISPLAY_INSIDE = frozenset({"flow", "flow-root", "table", "flex", "grid", "ruby", "math"})


def _deterministic_display_value(value: str) -> str | None:
    """Return one bounded valid display value, or None for invalid/indeterminate CSS."""

    tokens = tuple(
        token for token in re.split(r"[ \t\r\n\f]+", value) if token
    )
    if len(tokens) == 1 and tokens[0] in _CSS_DISPLAY_SINGLE_VALUES:
        return tokens[0]
    if len(tokens) not in {2, 3} or len(set(tokens)) != len(tokens):
        return None

    token_set = set(tokens)
    outside = token_set & _CSS_DISPLAY_OUTSIDE
    inside = token_set & _CSS_DISPLAY_INSIDE
    if len(tokens) == 2 and len(outside) == 1 and len(inside) == 1:
        return " ".join(tokens)

    if "list-item" in token_set:
        remaining = token_set - {"list-item"}
        outside = remaining & _CSS_DISPLAY_OUTSIDE
        flow_inside = remaining & {"flow", "flow-root"}
        if (
            remaining == outside | flow_inside
            and len(outside) <= 1
            and len(flow_inside) <= 1
        ):
            return " ".join(tokens)
    return None


_CSS_CONTENT_VISIBILITY_VALUES = frozenset(
    {"visible", "auto", "hidden", "initial", "unset"}
)


def _deterministic_content_visibility_value(value: str) -> str | None:
    """Return one bounded content-visibility value or None if cascade-dependent."""

    if value in _CSS_CONTENT_VISIBILITY_VALUES:
        return value
    # revert/revert-layer depend on other cascade origins/layers that this
    # bounded inline adapter deliberately does not model.
    return None



def _css_ascii_lower(
    value: str,
    control_checkpoint: Callable[[], None] | None = None,
) -> str:
    """Apply CSS ASCII case-insensitive folding without Unicode case expansion."""

    if control_checkpoint is None:
        return "".join(
            chr(ord(char) + 32) if "A" <= char <= "Z" else char
            for char in value
        )
    chunks: list[str] = []
    for offset in range(0, len(value), 4_096):
        control_checkpoint()
        chunk = value[offset : offset + 4_096]
        chunks.append(
            "".join(
                chr(ord(char) + 32) if "A" <= char <= "Z" else char
                for char in chunk
            )
        )
    control_checkpoint()
    return "".join(chunks)


def _inline_style_without_comments(
    style: str,
    control_checkpoint: Callable[[], None] | None = None,
) -> str:
    """Remove real CSS comments as whitespace before bounded display parsing.

    Comment-looking text inside quoted CSS strings or behind a backslash escape
    is data, not comment syntax. Preserve it verbatim so bounded display parsing
    cannot accidentally consume a later real declaration. An unterminated real
    comment still consumes the remainder.
    """

    parts: list[str] = []
    cursor = 0
    quote: str | None = None
    while cursor < len(style):
        if control_checkpoint is not None and (cursor + 1) % 4096 == 0:
            control_checkpoint()
        char = style[cursor]
        if char == "\\":
            parts.append(char)
            if cursor + 1 < len(style):
                parts.append(style[cursor + 1])
                cursor += 2
            else:
                cursor += 1
            continue
        if quote is not None:
            parts.append(char)
            if char == quote:
                quote = None
            cursor += 1
            continue
        if char in {'"', "'"}:
            quote = char
            parts.append(char)
            cursor += 1
            continue
        if char == "/" and cursor + 1 < len(style) and style[cursor + 1] == "*":
            # Preserve a token boundary even when a preceding hexadecimal
            # CSS escape consumes one following whitespace code point.
            parts.append("  ")
            end = style.find("*/", cursor + 2)
            if end < 0:
                break
            cursor = end + 2
            continue
        parts.append(char)
        cursor += 1
    return "".join(parts)

def _split_inline_style_declarations(
    style: str,
    control_checkpoint: Callable[[], None] | None = None,
) -> tuple[str, ...]:
    """Split only top-level declarations in one bounded inline style."""

    declarations: list[str] = []
    current: list[str] = []
    quote: str | None = None
    nesting: list[str] = []
    matching = {")": "(", "]": "[", "}": "{"}
    cursor = 0
    while cursor < len(style):
        if control_checkpoint is not None and (cursor + 1) % 4096 == 0:
            control_checkpoint()
        char = style[cursor]
        if char == "\\":
            current.append(char)
            if cursor + 1 < len(style):
                current.append(style[cursor + 1])
                cursor += 2
            else:
                cursor += 1
            continue
        if quote is not None:
            current.append(char)
            if char == quote:
                quote = None
            cursor += 1
            continue
        if char in {'"', "'"}:
            quote = char
            current.append(char)
            cursor += 1
            continue
        if char in "([{":
            nesting.append(char)
            current.append(char)
            cursor += 1
            continue
        if char in ")]}":
            if nesting and nesting[-1] == matching[char]:
                nesting.pop()
            current.append(char)
            cursor += 1
            continue
        if char == ";" and not nesting:
            declarations.append("".join(current))
            current = []
            cursor += 1
            continue
        current.append(char)
        cursor += 1
    declarations.append("".join(current))
    return tuple(declarations)

def _css_unescape_token(
    value: str,
    control_checkpoint: Callable[[], None] | None = None,
) -> str:
    """Decode CSS escapes for one bounded property/value token."""

    parts: list[str] = []
    cursor = 0
    hexdigits = "0123456789abcdefABCDEF"
    while cursor < len(value):
        if control_checkpoint is not None and (cursor + 1) % 4096 == 0:
            control_checkpoint()
        char = value[cursor]
        if char != "\\":
            parts.append(char)
            cursor += 1
            continue
        cursor += 1
        if cursor >= len(value):
            # A trailing escape is invalid CSS. Preserve an impossible token
            # rather than manufacturing a valid display keyword.
            parts.append("\\")
            break
        escaped = value[cursor]
        if escaped in "\n\r\f":
            # Backslash + newline is not a valid CSS identifier escape. Keep
            # an impossible token instead of joining text into display/none.
            parts.append("\\")
            parts.append(escaped)
            cursor += 1
            continue
        if escaped in hexdigits:
            end = cursor
            while end < len(value) and end - cursor < 6 and value[end] in hexdigits:
                end += 1
            codepoint = int(value[cursor:end], 16)
            if codepoint == 0 or codepoint > 0x10FFFF or 0xD800 <= codepoint <= 0xDFFF:
                parts.append("\uFFFD")
            else:
                parts.append(chr(codepoint))
            cursor = end
            if cursor < len(value) and value[cursor] in " \t\r\n\f":
                if value[cursor] == "\r" and cursor + 1 < len(value) and value[cursor + 1] == "\n":
                    cursor += 2
                else:
                    cursor += 1
            continue
        parts.append(escaped)
        cursor += 1
    return "".join(parts)

def _inline_style_hides(
    style: str,
    control_checkpoint: Callable[[], None] | None = None,
) -> bool:
    """Recognize deterministic inline subtree-hiding declarations.

    This intentionally is not a CSS engine. display:none and
    content-visibility:hidden both suppress an element's rendered/accessibility
    subtree and cannot be reversed by a descendant. Stylesheet class rules and
    cascade-dependent CSS-wide values stay outside this bounded HTML adapter.
    """

    effective_display: tuple[str, bool] | None = None
    effective_content_visibility: tuple[str, bool] | None = None

    for declaration_index, declaration in enumerate(
        _split_inline_style_declarations(
            _inline_style_without_comments(style, control_checkpoint),
            control_checkpoint,
        ),
        start=1,
    ):
        if control_checkpoint is not None and declaration_index % 128 == 0:
            control_checkpoint()
        name, separator, raw_value = declaration.partition(":")
        if not separator:
            continue
        property_name = _css_ascii_lower(
            _css_unescape_token(
                name.strip(_CSS_WHITESPACE),
                control_checkpoint,
            ),
            control_checkpoint,
        )
        if property_name not in {"display", "content-visibility"}:
            continue

        value = _css_ascii_lower(
            _css_unescape_token(
                raw_value.strip(_CSS_WHITESPACE),
                control_checkpoint,
            ),
            control_checkpoint,
        )
        important_match = _CSS_IMPORTANT_RE.search(value)
        important = important_match is not None
        if important_match is not None:
            value = value[: important_match.start()].strip(_CSS_WHITESPACE)

        if property_name == "display":
            deterministic_value = _deterministic_display_value(value)
            if deterministic_value is None:
                continue
            if effective_display is not None and effective_display[1] and not important:
                continue
            effective_display = (deterministic_value, important)
            continue

        deterministic_content_visibility = _deterministic_content_visibility_value(value)
        if deterministic_content_visibility is None:
            continue
        if (
            effective_content_visibility is not None
            and effective_content_visibility[1]
            and not important
        ):
            continue
        effective_content_visibility = (deterministic_content_visibility, important)

    display_hidden = effective_display is not None and effective_display[0] == "none"
    content_hidden = (
        effective_content_visibility is not None
        and effective_content_visibility[0] == "hidden"
    )
    return display_hidden or content_hidden

def _controlled_strip(
    value: str,
    control_checkpoint: Callable[[], None] | None = None,
) -> str:
    """Match str.strip() while polling trusted cancellation on long metadata."""

    if control_checkpoint is None:
        return value.strip()
    start = 0
    end = len(value)
    while start < end:
        if start % 4_096 == 0:
            control_checkpoint()
        if not value[start].isspace():
            break
        start += 1
    scanned_from_end = 0
    while end > start:
        if scanned_from_end % 4_096 == 0:
            control_checkpoint()
        if not value[end - 1].isspace():
            break
        end -= 1
        scanned_from_end += 1
    control_checkpoint()
    return value[start:end]


def _controlled_rstrip(
    value: str,
    control_checkpoint: Callable[[], None] | None = None,
) -> str:
    if control_checkpoint is None:
        return value.rstrip()
    end = len(value)
    scanned = 0
    while end:
        if scanned % 4_096 == 0:
            control_checkpoint()
        if not value[end - 1].isspace():
            break
        end -= 1
        scanned += 1
    control_checkpoint()
    return value[:end]


def _controlled_join_strings(
    values,
    separator: str,
    control_checkpoint: Callable[[], None] | None = None,
) -> str:
    if control_checkpoint is None:
        return separator.join(values)
    output = StringIO()
    for value_index, value in enumerate(values):
        if value_index % 128 == 0:
            control_checkpoint()
        if value_index:
            output.write(separator)
        output.write(value)
    control_checkpoint()
    return output.getvalue()


def _iter_text_lines(
    value: str,
    control_checkpoint: Callable[[], None] | None = None,
):
    """Yield source lines without an eager whole-string replace/split pass."""

    line_start = 0
    cursor = 0
    next_control_offset = 0
    while cursor < len(value):
        if control_checkpoint is not None and cursor >= next_control_offset:
            control_checkpoint()
            next_control_offset = cursor + 16_384
        character = value[cursor]
        if character == "\r":
            yield line_start, value[line_start:cursor]
            cursor += (
                2
                if cursor + 1 < len(value) and value[cursor + 1] == "\n"
                else 1
            )
            line_start = cursor
            continue
        if character == "\n":
            yield line_start, value[line_start:cursor]
            cursor += 1
            line_start = cursor
            continue
        cursor += 1
    if control_checkpoint is not None:
        control_checkpoint()
    yield line_start, value[line_start:]


def _text(
    value: object,
    field: str,
    *,
    optional: bool = False,
    control_checkpoint: Callable[[], None] | None = None,
) -> str | None:
    if value is None and optional:
        return None
    if type(value) is not str:
        raise BookHtmlImportError(
            f"{field} must be non-empty text",
            code=BookHtmlImportErrorCode.INVALID_ARGUMENT,
        )
    if len(value) > MAX_BOOK_TEXT_FIELD_CHARS:
        raise BookHtmlImportError(
            f"{field} exceeds the canonical BookDocument text field limit",
            code=BookHtmlImportErrorCode.RESOURCE_LIMIT,
        )
    stripped = _controlled_strip(value, control_checkpoint)
    if not stripped:
        raise BookHtmlImportError(
            f"{field} must be non-empty text",
            code=BookHtmlImportErrorCode.INVALID_ARGUMENT,
        )
    return stripped

def _source_text(
    source: object,
    control_checkpoint: Callable[[], None] | None = None,
) -> tuple[str, bytes, bool]:
    if type(source) is str:
        # Every Unicode scalar requires at least one UTF-8 byte. Reject an
        # impossible source before allocating the encoded representation.
        if len(source) > MAX_HTML_SOURCE_BYTES:
            raise BookHtmlImportError(
                "HTML book source exceeds the supported size",
                code=BookHtmlImportErrorCode.RESOURCE_LIMIT,
            )
        if control_checkpoint is None:
            try:
                encoded = source.encode("utf-8")
            except UnicodeEncodeError as exc:
                raise BookHtmlImportError(
                    "HTML book source must be valid Unicode text",
                    code=BookHtmlImportErrorCode.UNSUPPORTED_ENCODING,
                ) from exc
            if len(encoded) > MAX_HTML_SOURCE_BYTES:
                raise BookHtmlImportError(
                    "HTML book source exceeds the supported size",
                    code=BookHtmlImportErrorCode.RESOURCE_LIMIT,
                )
            return source, encoded, False

        encoded = bytearray()
        for offset in range(0, len(source), 16_384):
            control_checkpoint()
            try:
                chunk = source[offset : offset + 16_384].encode("utf-8")
            except UnicodeEncodeError as exc:
                raise BookHtmlImportError(
                    "HTML book source must be valid Unicode text",
                    code=BookHtmlImportErrorCode.UNSUPPORTED_ENCODING,
                ) from exc
            if len(encoded) + len(chunk) > MAX_HTML_SOURCE_BYTES:
                raise BookHtmlImportError(
                    "HTML book source exceeds the supported size",
                    code=BookHtmlImportErrorCode.RESOURCE_LIMIT,
                )
            encoded.extend(chunk)
        control_checkpoint()
        return source, bytes(encoded), False
    if type(source) is bytes:
        if len(source) > MAX_HTML_SOURCE_BYTES:
            raise BookHtmlImportError(
                "HTML book source exceeds the supported size",
                code=BookHtmlImportErrorCode.RESOURCE_LIMIT,
            )
        if control_checkpoint is not None:
            control_checkpoint()
        try:
            decoded = decode_book_text_bytes(source, html=True)
        except LegacyTextEncodingError as exc:
            raise BookHtmlImportError(
                "HTML book source must use UTF-8, BOM UTF-16 or qualified Windows-1251 encoding",
                code=BookHtmlImportErrorCode.UNSUPPORTED_ENCODING,
            ) from exc
        if control_checkpoint is not None:
            control_checkpoint()
        return decoded.text, source, decoded.legacy
    raise BookHtmlImportError(
        "HTML book source must be text or bytes",
        code=BookHtmlImportErrorCode.INVALID_ARGUMENT,
    )

def _compact(
    value: str,
    control_checkpoint: Callable[[], None] | None = None,
) -> str:
    if control_checkpoint is None:
        # Preserve the historical fast path and its exact Python whitespace
        # semantics when no active-import cancellation authority is present.
        return " ".join(value.replace("\xa0", " ").split())

    output = StringIO()
    wrote_text = False
    pending_space = False
    for offset in range(0, len(value), 4_096):
        control_checkpoint()
        chunk = value[offset : offset + 4_096].replace("\xa0", " ")
        parts = chunk.split()
        if not parts:
            if wrote_text:
                pending_space = True
            continue
        leading_space = chunk[0].isspace()
        trailing_space = chunk[-1].isspace()
        if wrote_text and (pending_space or leading_space):
            output.write(" ")
        output.write(" ".join(parts))
        wrote_text = True
        pending_space = trailing_space
    # A cancel that races with the final bounded chunk must still win before
    # the compacted semantic text can be published as a Book block.
    control_checkpoint()
    return output.getvalue()


def _asset_name(
    value: str,
    control_checkpoint: Callable[[], None] | None = None,
) -> str:
    if control_checkpoint is not None:
        control_checkpoint()
    try:
        parts = urlsplit(value.strip())
    except ValueError:
        return ""
    if control_checkpoint is not None:
        control_checkpoint()
    if parts.scheme or parts.netloc or not parts.path:
        return ""
    raw_segments = parts.path.replace("\\", "/").split("/")
    if control_checkpoint is not None:
        control_checkpoint()
    segments: list[str] = []
    parent_seen = False
    for segment_index, segment in enumerate(raw_segments, start=1):
        if control_checkpoint is not None and segment_index % 128 == 1:
            control_checkpoint()
        if segment in {"", "."}:
            continue
        if segment == "..":
            parent_seen = True
        segments.append(segment)
    if not segments or parent_seen:
        return ""
    if control_checkpoint is not None:
        control_checkpoint()
    return "/".join(segments)


_HTML_WARNING_SUPPRESSION_NOTICE = "additional HTML import warnings were suppressed"


def _append_bounded_import_warning(warnings: list[str], message: str) -> bool:
    """Append one diagnostic without exceeding the HTML importer warning budget."""

    if MAX_HTML_WARNINGS <= 0:
        return False
    if len(warnings) < MAX_HTML_WARNINGS:
        warnings.append(message)
        return True
    warnings[MAX_HTML_WARNINGS - 1] = _HTML_WARNING_SUPPRESSION_NOTICE
    del warnings[MAX_HTML_WARNINGS:]
    return False


def _explicit_pgn_pre(
    raw: str,
    control_checkpoint: Callable[[], None] | None = None,
) -> bool:
    """Return whether a ``pre`` starts with an explicit PGN marker and Event tag."""

    meaningful: list[str] = []
    for _, line in _iter_text_lines(raw, control_checkpoint):
        stripped = _controlled_strip(line, control_checkpoint)
        if not stripped:
            continue
        meaningful.append(stripped)
        if len(meaningful) == 2:
            break
    return (
        len(meaningful) >= 2
        and _PGN_MARKER_RE.fullmatch(meaningful[0]) is not None
        and _PGN_EVENT_RE.match(meaningful[1]) is not None
    )


class _SemanticHtmlParser(HTMLParser):
    def __init__(
        self,
        *,
        available_assets: frozenset[str] | None,
        control_checkpoint: Callable[[], None] | None = None,
    ) -> None:
        super().__init__(convert_charrefs=True)
        self.available_assets = available_assets
        self.control_checkpoint = control_checkpoint
        self._control_failure: BaseException | None = None
        self.blocks = []
        self.warnings: list[str] = []
        self._warnings_suppressed = False
        self.title: str | None = None
        self.language: str | None = None
        self.author: str | None = None
        self.visible_parts: list[str] = []
        self.visible_chars = 0
        self.image_references: list[str] = []
        self.missing_assets: set[str] = set()
        self._captures: list[_Capture] = []
        self._lists: list[_ListCapture] = []
        self._suppressed_depth = 0
        self._suppressed_tags: list[str] = []
        self._hidden_tags: list[str] = []
        self._head_depth = 0
        self._node_count = 0
        self._control_event_count = 0
        self._text_boundary_count = 0
        self._ids: dict[str, int] = {}
        self._warned_table_flatten = False
        self._warned_list_fallback = False

    def _checkpoint(self) -> None:
        if self.control_checkpoint is None:
            return
        try:
            self.control_checkpoint()
        except BaseException as exc:
            self._control_failure = exc
            raise

    def _source_anchor(self, attrs: dict[str, str]) -> str | None:
        value = attrs.get("id")
        if not value:
            return None
        if len(value) > MAX_BOOK_SOURCE_ANCHOR_CHARS:
            raise BookHtmlImportError(
                "HTML semantic source anchor exceeds the canonical BookDocument identifier limit",
                code=BookHtmlImportErrorCode.RESOURCE_LIMIT,
            )
        return value


    def _compact_text(self, value: str) -> str:
        return _compact(
            value,
            self._checkpoint if self.control_checkpoint is not None else None,
        )

    def _parser_event_checkpoint(self) -> None:
        """Bound trusted cancellation latency inside a single HTMLParser feed chunk."""
        if self.control_checkpoint is None:
            return
        self._control_event_count += 1
        if self._control_event_count % 128 == 1:
            self._checkpoint()

    def _warning(self, message: str) -> None:
        if self._warnings_suppressed:
            return
        if len(self.warnings) < MAX_HTML_WARNINGS:
            self.warnings.append(message)
            return
        # The configured maximum is a total-output bound, not a pre-marker
        # allowance. Only a real overflow sacrifices the final warning slot.
        if MAX_HTML_WARNINGS > 0:
            self.warnings[-1] = _HTML_WARNING_SUPPRESSION_NOTICE
        self._warnings_suppressed = True

    def _list_warning(self, message: str) -> None:
        if not self._warned_list_fallback:
            self._warning(message)
            self._warned_list_fallback = True

    def _append_visible(self, text: str) -> None:
        if not text:
            return
        self.visible_chars += len(text)
        if self.visible_chars > MAX_HTML_VISIBLE_CHARS:
            raise BookHtmlImportError(
                "HTML book visible text exceeds the supported size",
                code=BookHtmlImportErrorCode.RESOURCE_LIMIT,
            )
        self.visible_parts.append(text)

    def _append_text_boundary(self) -> None:
        """Record one semantic separator without an O(capture-depth) boundary walk."""
        self._append_visible("\n")
        # Data already fans out through every active semantic capture. Record the
        # boundary once here, then let the next data event synchronize each capture
        # it already visits. This preserves boundaries in ancestor captures too
        # (for example nested list/blockquote text) without making markup-only
        # boundary handling O(capture depth).
        self._text_boundary_count += 1

    def _block_id(self, kind: str, payload: str) -> str:
        digest = sha256((kind + "\0" + payload).encode("utf-8")).hexdigest()[:20]
        key = f"{kind}:{digest}"
        occurrence = self._ids.get(key, 0) + 1
        self._ids[key] = occurrence
        return f"html-{digest}-{occurrence}"

    def _append_block(self, block) -> None:
        if len(self.blocks) >= MAX_HTML_BLOCKS:
            raise BookHtmlImportError(
                "HTML book contains too many semantic blocks",
                code=BookHtmlImportErrorCode.RESOURCE_LIMIT,
            )
        self.blocks.append(block)

    def _insert_block(self, index: int, block) -> None:
        if len(self.blocks) >= MAX_HTML_BLOCKS:
            raise BookHtmlImportError(
                "HTML book contains too many semantic blocks",
                code=BookHtmlImportErrorCode.RESOURCE_LIMIT,
            )
        self.blocks.insert(index, block)

    def _block_identity_index(self, target: object) -> int:
        for index, block in enumerate(self.blocks):
            if self.control_checkpoint is not None and index % 128 == 0:
                self._checkpoint()
            if block is target:
                return index
        raise BookHtmlImportError(
            "HTML inline semantic ordering anchor was lost",
            code=BookHtmlImportErrorCode.INVALID_ARGUMENT,
        )

    def _find_capture_index(
        self,
        predicate: Callable[[_Capture], bool],
        *,
        reverse: bool = False,
    ) -> int | None:
        """Find one semantic capture while bounding deep-stack cancellation latency."""

        indexes = (
            range(len(self._captures) - 1, -1, -1)
            if reverse
            else range(len(self._captures))
        )
        for scan_count, index in enumerate(indexes, start=1):
            if self.control_checkpoint is not None and scan_count % 128 == 0:
                self._checkpoint()
            if predicate(self._captures[index]):
                return index
        return None

    def _recover_capture_tail(self, target_length: int) -> None:
        """Recover a malformed capture tail with bounded cancellation latency."""
        recovered = 0
        while len(self._captures) > target_length:
            if self.control_checkpoint is not None and recovered % 128 == 0:
                self._checkpoint()
            capture = self._captures.pop()
            self._finish_capture_and_record_parent(capture, recovered=True)
            recovered += 1

    def _inline_requires_split(self, capture: _Capture) -> bool:
        for event_index, event in enumerate(capture.inline_semantics, start=1):
            if self.control_checkpoint is not None and event_index % 128 == 0:
                self._checkpoint()
            if (not event.structural) or event.forces_split:
                return True
        return False

    def _blocks_have_pgn_slot_from(self, start_index: int) -> bool:
        for block_offset, block_index in enumerate(
            range(start_index, len(self.blocks)),
            start=1,
        ):
            if self.control_checkpoint is not None and block_offset % 128 == 0:
                self._checkpoint()
            if isinstance(self.blocks[block_index], _PgnSlot):
                return True
        return False

    @staticmethod
    def _ordered_start(attrs: dict[str, str]) -> tuple[int | None, bool]:
        if "start" not in attrs:
            return None, True
        raw = attrs.get("start", "").strip()
        if _HTML_INTEGER_RE.fullmatch(raw) is None:
            return None, False
        try:
            value = int(raw)
        except (ValueError, OverflowError):
            return None, False
        return (value, value >= 1)

    def _emit_list(self, captured: _ListCapture) -> None:
        items: list[str] = []
        for item_index, item in enumerate(captured.items, start=1):
            if self.control_checkpoint is not None and item_index % 128 == 1:
                self._checkpoint()
            if item:
                items.append(item)
        identity_items: list[str] = []
        for item_index, item in enumerate(captured.identity_items, start=1):
            if self.control_checkpoint is not None and item_index % 128 == 1:
                self._checkpoint()
            if item:
                identity_items.append(item)
        ordered = captured.tag == "ol"
        start, start_valid = self._ordered_start(captured.attrs) if ordered else (None, True)

        if (
            captured.inline_semantic_fallback
            and not captured.structural_unsupported
            and captured.legacy_identity_block is not None
            and identity_items
        ):
            # Preserve the exact pre-split canonical ListBlock target so durable
            # BookProgress restores to the beginning of a list whose text is
            # unchanged but whose rich inline semantics now require flattening.
            legacy_identity = (
                ("ordered" if ordered else "unordered")
                + "\0"
                + (str(start) if start is not None else "")
                + "\0"
                + "\0".join(identity_items)
            )
            captured.legacy_identity_block.block_id = self._block_id(
                "List",
                legacy_identity,
            )
            captured.legacy_identity_block.source_anchor = (
                self._source_anchor(captured.attrs)
            )

        if not items:
            return
        unsupported = captured.unsupported or not start_valid

        if unsupported:
            if captured.inline_semantic_fallback:
                self._list_warning(
                    "HTML list items containing inline semantic content cannot be represented by the flat canonical List block and were preserved as readable bullet text around semantic blocks"
                )
            elif ordered and not start_valid:
                self._list_warning(
                    "HTML ordered list start could not be represented canonically and was preserved as reading text because canonical List start must be positive"
                )
            else:
                self._list_warning(
                    "HTML list numbering or nesting could not be represented canonically and was preserved as readable text"
                )
            for item_index, item in enumerate(items, start=1):
                if self.control_checkpoint is not None and item_index % 128 == 1:
                    self._checkpoint()
                # Once numbering semantics are outside the canonical ListBlock model
                # (reversed lists, per-item value overrides, invalid starts, nesting),
                # never synthesize a numeric sequence. Preserve the source item text
                # and list membership only; the warning above makes structure loss
                # explicit without publishing invented ordering as book truth.
                text = f"• {item}"
                identity_kind = (
                    "ListFallbackItem"
                    if captured.inline_semantic_fallback
                    else "Paragraph"
                )
                self._append_block(
                    Paragraph(
                        text=text,
                        block_id=self._block_id(identity_kind, text),
                        source_anchor=self._source_anchor(captured.attrs),
                    )
                )
            return

        identity = (
            ("ordered" if ordered else "unordered")
            + "\0"
            + (str(start) if start is not None else "")
            + "\0"
            + "\0".join(items)
        )
        self._append_block(
            ListBlock(
                items=items,
                ordered=ordered,
                start=start if ordered else None,
                block_id=self._block_id("List", identity),
                source_anchor=self._source_anchor(captured.attrs),
            )
        )

    def _validate_fen(self, fen: str) -> str:
        try:
            return Board(fen).fen()
        except (TypeError, ValueError) as exc:
            raise BookHtmlImportError(
                "HTML book contains an invalid explicitly marked chess position",
                code=BookHtmlImportErrorCode.MALFORMED_CHESS_CONTENT,
            ) from exc

    def _emit_explicit_position(self, tag: str, attrs: dict[str, str]) -> None:
        raw_fen = attrs.get("data-acs-fen")
        if raw_fen is None:
            return
        fen = self._validate_fen(raw_fen)
        source_anchor = self._source_anchor(attrs)
        if tag == "img":
            alt = self._compact_text(attrs.get("alt", "")) or None
            payload = fen + "\0" + (alt or "")
            self._append_block(
                Diagram(
                    fen=fen,
                    alt_text=alt,
                    block_id=self._block_id("Diagram", payload),
                    source_anchor=source_anchor,
                )
            )
        else:
            self._append_block(
                Position(
                    fen=fen,
                    block_id=self._block_id("Position", fen),
                    source_anchor=source_anchor,
                )
            )

    def _nearest_structural_owner_capture(self) -> _Capture | None:
        """Return the nearest capture whose text may need semantic splitting."""
        index = self._find_capture_index(
            lambda capture: capture.kind in {"paragraph", "heading", "list_item", "table_row", "pre"},
            reverse=True,
        )
        return self._captures[index] if index is not None else None

    def _nearest_inline_owner_capture(self) -> _Capture | None:
        index = self._find_capture_index(
            lambda capture: capture.kind in {"paragraph", "heading", "list_item", "table_row", "pre"},
            reverse=True,
        )
        return self._captures[index] if index is not None else None

    def _record_inline_semantic(
        self,
        block: object,
        *,
        owner: _Capture | None = None,
        part_index: int | None = None,
        structural: bool = False,
        forces_split: bool = False,
        resume_part_index: int | None = None,
    ) -> None:
        # Direct image/position semantics trigger splitting for the nearest
        # paragraph or heading owner. Nested captures are recorded only as
        # structural boundaries on their explicit parent owner so source order is
        # preserved without inventing chess or document structure.
        capture = owner if owner is not None else self._nearest_inline_owner_capture()
        if capture is None:
            return
        boundary = len(capture.parts) if part_index is None else part_index
        capture.inline_semantics.append(
            _InlineSemanticEvent(
                part_index=boundary,
                block=block,
                structural=structural,
                forces_split=forces_split,
                resume_part_index=resume_part_index,
            )
        )

    def handle_starttag(self, tag: str, attrs_list: list[tuple[str, str | None]]) -> None:
        self._parser_event_checkpoint()
        tag = tag.lower()
        self._node_count += 1
        if self._node_count > MAX_HTML_BLOCKS * 20:
            raise BookHtmlImportError(
                "HTML book contains too many markup nodes",
                code=BookHtmlImportErrorCode.RESOURCE_LIMIT,
            )
        if tag in _SUPPRESSED_TAGS:
            self._suppressed_depth += 1
            self._suppressed_tags.append(tag)
            return
        if self._suppressed_depth:
            return
        if self._hidden_tags:
            if tag not in _VOID_TAGS:
                self._hidden_tags.append(tag)
            return
        if tag == "head":
            self._head_depth += 1
            return
        if self._head_depth and tag == "body":
            # In the HTML tree builder, an explicit BODY start ends the HEAD
            # insertion mode even when the source omitted </head>. Mirror that
            # deterministic boundary so readable BODY content cannot remain
            # trapped as metadata merely because HTMLParser does not build a DOM.
            title_index = self._find_capture_index(
                lambda capture: capture.kind == "title"
            )
            if title_index is not None:
                self._recover_capture_tail(title_index)
            self._head_depth = 0
            self._warning("malformed HTML head was implicitly closed by body start")
        if self._head_depth and tag not in {"title", "meta"}:
            # HEAD is metadata, not a source of readable or chess-semantic
            # blocks. In particular, an explicit marker in hidden metadata
            # must never publish a position/image note or a PGN game.
            return
        attrs: dict[str, str] = {}
        for attr_index, (name, value) in enumerate(attrs_list, start=1):
            if self.control_checkpoint is not None and attr_index % 128 == 0:
                self._checkpoint()
            normalized_name = name.lower()
            if normalized_name in attrs:
                if normalized_name == "data-acs-fen":
                    raise BookHtmlImportError(
                        "HTML book contains a repeated explicitly marked chess position",
                        code=BookHtmlImportErrorCode.MALFORMED_CHESS_CONTENT,
                    )
                # HTML parsing keeps the first attribute when a start tag repeats
                # the same ASCII-case-insensitive name. Preserve that browser
                # authority instead of letting dict assignment make later
                # malformed duplicates change semantic/image/progress metadata.
                continue
            attrs[normalized_name] = value or ""
        aria_hidden = attrs.get("aria-hidden", "").strip().casefold()
        inline_style_hidden = _inline_style_hides(
            attrs.get("style", ""),
            self._checkpoint if self.control_checkpoint is not None else None,
        )
        if "hidden" in attrs or "inert" in attrs or aria_hidden == "true" or inline_style_hidden:
            # HTML hidden/inert, ARIA-hidden=true and deterministic inline
            # display:none are boundaries for this accessibility-first semantic
            # import. Text,
            # image metadata and explicit chess markers excluded from the
            # rendered/accessibility surface must not reappear in BookDocument
            # or screen-reader output.
            # Track all non-void descendants so malformed nesting stays
            # fail-closed instead of resuming ingestion too early.
            if tag not in _VOID_TAGS:
                self._hidden_tags.append(tag)
            return
        if tag in _BLOCK_BOUNDARY_TAGS:
            # HTMLParser does not place markup in capture.parts. Preserve the
            # same block boundary already published to visible_text inside the
            # directly containing semantic capture so adjacent words cannot collapse.
            self._append_text_boundary()
        if tag == "html" and not self.language:
            lang = self._compact_text(attrs.get("lang", ""))
            if lang:
                self.language = lang
        if tag == "meta":
            name = (attrs.get("name") or attrs.get("property") or "").strip().lower()
            content = self._compact_text(attrs.get("content", ""))
            if content and name in {"author", "dc.creator", "dcterms.creator"} and not self.author:
                self.author = content
            if content and name in {"language", "dc.language", "dcterms.language"} and not self.language:
                self.language = content
        if tag == "img":
            if len(self.image_references) >= MAX_HTML_IMAGES:
                raise BookHtmlImportError(
                    "HTML book contains too many image references",
                    code=BookHtmlImportErrorCode.RESOURCE_LIMIT,
                )
            src = attrs.get("src", "").strip()
            alt = self._compact_text(attrs.get("alt", ""))
            if src:
                self.image_references.append(src)
                local_name = _asset_name(
                    src,
                    self._checkpoint if self.control_checkpoint is not None else None,
                )
                if self.available_assets is not None and local_name and local_name not in self.available_assets:
                    self.missing_assets.add(local_name)
            block_count = len(self.blocks)
            if "data-acs-fen" in attrs:
                self._emit_explicit_position(tag, attrs)
            elif alt:
                self._append_block(
                    Note(
                        text=alt,
                        note_type="image",
                        block_id=self._block_id("ImageNote", src + "\0" + alt),
                        source_anchor=self._source_anchor(attrs),
                    )
                )
            else:
                self._warning("an image reference has no accessible text and no explicit chess position")
            if len(self.blocks) == block_count + 1:
                self._record_inline_semantic(self.blocks[-1])
        elif "data-acs-fen" in attrs and not self._head_depth:
            block_count = len(self.blocks)
            self._emit_explicit_position(tag, attrs)
            if len(self.blocks) == block_count + 1:
                self._record_inline_semantic(self.blocks[-1])

        if tag in {"ol", "ul"} and self._lists:
            for capture_index, capture in enumerate(self._captures, start=1):
                if self.control_checkpoint is not None and capture_index % 128 == 0:
                    self._checkpoint()
                if capture.kind == "list_item" and capture.list_depth == len(self._lists):
                    capture.parts.append(" ")

        if tag in {"ol", "ul"}:
            nested = bool(self._lists)
            if nested:
                self._lists[-1].unsupported = True
                self._lists[-1].structural_unsupported = True
            unsupported = nested or "reversed" in attrs
            if tag == "ol":
                _, start_valid = self._ordered_start(attrs)
                unsupported = unsupported or not start_valid
            self._lists.append(
                _ListCapture(
                    tag=tag,
                    attrs=attrs,
                    unsupported=unsupported,
                    structural_unsupported=unsupported,
                    nested=nested,
                )
            )

        kind = _CAPTURE_KINDS.get(tag)
        if kind is not None:
            if kind == "list_item" and self._lists and "value" in attrs:
                self._lists[-1].unsupported = True
                self._lists[-1].structural_unsupported = True
            if kind == "list_item" and self._lists:
                for capture_index, capture in enumerate(self._captures, start=1):
                    if self.control_checkpoint is not None and capture_index % 128 == 0:
                        self._checkpoint()
                    if capture.kind == "list_item" and capture.list_depth < len(self._lists):
                        capture.parts.append(" ")
            parent_inline_owner = self._nearest_structural_owner_capture()
            parent_part_index = (
                len(parent_inline_owner.parts) if parent_inline_owner is not None else None
            )
            self._captures.append(
                _Capture(
                    tag=tag,
                    kind=kind,
                    attrs=attrs,
                    parts=[],
                    visible_start_offset=self.visible_chars,
                    boundary_count=self._text_boundary_count,
                    list_depth=len(self._lists) if kind == "list_item" else 0,
                    parent_inline_owner=parent_inline_owner,
                    parent_part_index=parent_part_index,
                    block_start_index=len(self.blocks),
                )
            )

    def handle_startendtag(self, tag: str, attrs_list: list[tuple[str, str | None]]) -> None:
        self.handle_starttag(tag, attrs_list)
        if tag.lower() not in _VOID_TAGS:
            self.handle_endtag(tag)

    def handle_endtag(self, tag: str) -> None:
        self._parser_event_checkpoint()
        tag = tag.lower()
        if tag in _SUPPRESSED_TAGS:
            if self._suppressed_depth:
                if not self._suppressed_tags or self._suppressed_tags[-1] != tag:
                    self._warning(
                        "malformed HTML mismatched suppressed elements; readable text may have been omitted"
                    )
                    return
                self._suppressed_depth -= 1
                self._suppressed_tags.pop()
            return
        if self._suppressed_depth:
            return
        if self._hidden_tags:
            if self._hidden_tags[-1] != tag:
                self._warning(
                    "malformed HTML mismatched hidden elements; readable text may have been omitted"
                )
                return
            self._hidden_tags.pop()
            return
        if tag == "head":
            # A malformed unclosed <title> must not survive the explicit end of
            # metadata. Otherwise handle_data() keeps treating later BODY text as
            # title metadata and omits it from the semantic document.
            title_index = self._find_capture_index(
                lambda capture: capture.kind == "title"
            )
            if title_index is not None:
                self._recover_capture_tail(title_index)
            if self._head_depth:
                self._head_depth -= 1
            return
        if self._head_depth and tag not in {"title", "meta"}:
            return
        matching_capture_index = self._find_capture_index(
            lambda capture: capture.tag == tag,
            reverse=True,
        )
        if matching_capture_index is not None:
            # HTMLParser reports source tags but does not repair malformed
            # nesting. If an explicit closing tag belongs to an ancestor capture,
            # recover any still-open semantic descendants first, then honor the
            # explicit close. Leaving the ancestor live until EOF would let
            # following source text leak into a region the source already closed.
            self._recover_capture_tail(matching_capture_index + 1)
            capture = self._captures.pop()
            self._finish_capture_and_record_parent(capture)
        if tag in {"ol", "ul"} and self._lists and self._lists[-1].tag == tag:
            # HTMLParser intentionally does not repair malformed nesting. If a
            # list container closes while its current <li> (or a semantic child
            # of that item) is still open, recover that subtree *before* the
            # list owner disappears. Otherwise later source text can continue
            # fanning out into the stale item capture until EOF and be
            # misattributed to the already-closed list.
            list_depth = len(self._lists)
            open_item_index = self._find_capture_index(
                lambda capture: (
                    capture.kind == "list_item"
                    and capture.list_depth == list_depth
                ),
                reverse=True,
            )
            if open_item_index is not None:
                self._recover_capture_tail(open_item_index)
            captured = self._lists.pop()
            if captured.nested:
                for capture_index, capture in enumerate(self._captures, start=1):
                    if self.control_checkpoint is not None and capture_index % 128 == 0:
                        self._checkpoint()
                    if capture.kind == "list_item" and capture.list_depth == len(self._lists):
                        capture.parts.append(" ")
                # Text from a nested list is already retained by the enclosing
                # list-item capture. Suppress a second flattened copy and make the
                # outer list fall back with an explicit structure-loss warning.
                self._list_warning(
                    "Nested HTML list structure cannot be represented by the flat canonical List block and was preserved as readable parent-item text"
                )
            else:
                self._emit_list(captured)
        if tag in _BLOCK_BOUNDARY_TAGS:
            # The closing edge matters when inline text resumes after a nested
            # block (for example Alpha<div>Beta</div>Gamma).
            self._append_text_boundary()

    def handle_data(self, data: str) -> None:
        self._parser_event_checkpoint()
        if self._suppressed_depth or self._hidden_tags:
            return
        title_capture_present = False
        if self._head_depth:
            title_capture_present = True
        else:
            for capture_index, capture in enumerate(self._captures, start=1):
                if self.control_checkpoint is not None and capture_index % 128 == 0:
                    self._checkpoint()
                if capture.kind == "title":
                    title_capture_present = True
                    break
        if title_capture_present:
            # HTML title still supplies the book title; it and all other
            # non-rendered HEAD text are excluded from the visible stream that
            # owns explicit {PGN N} markers. Do not fan metadata into an
            # unclosed outer Paragraph/Heading capture either.
            for capture_index, capture in enumerate(self._captures, start=1):
                if self.control_checkpoint is not None and capture_index % 128 == 0:
                    self._checkpoint()
                if capture.kind == "title":
                    capture.parts.append(data)
            return
        self._append_visible(data)
        for capture_index, capture in enumerate(self._captures, start=1):
            if self.control_checkpoint is not None and capture_index % 128 == 0:
                self._checkpoint()
            pending_boundaries = self._text_boundary_count - capture.boundary_count
            if pending_boundaries > 0:
                capture.parts.append("\n" * pending_boundaries)
                capture.boundary_count = self._text_boundary_count
            capture.parts.append(data)

    def _finish_inline_paragraph(
        self,
        capture: _Capture,
        *,
        legacy_text: str,
        source_anchor: str | None,
    ) -> None:
        """Project inline semantics in source order without losing progress IDs."""
        cursor = 0
        legacy_identity_available = True
        for event_index, event in enumerate(capture.inline_semantics, start=1):
            if self.control_checkpoint is not None and event_index % 128 == 0:
                self._checkpoint()
            resume_part_index = (
                event.resume_part_index
                if event.resume_part_index is not None
                else event.part_index
            )
            if (
                event.part_index < cursor
                or event.part_index > len(capture.parts)
                or resume_part_index < event.part_index
                or resume_part_index > len(capture.parts)
            ):
                raise BookHtmlImportError(
                    "HTML inline semantic boundary is invalid",
                    code=BookHtmlImportErrorCode.INVALID_ARGUMENT,
                )
            segment = self._compact_text("".join(capture.parts[cursor:event.part_index]))
            if segment:
                identity_text = legacy_text if legacy_identity_available else segment
                identity_kind = "Paragraph" if legacy_identity_available else "ParagraphInlineFragment"
                paragraph = Paragraph(
                    text=segment,
                    block_id=self._block_id(identity_kind, identity_text),
                    source_anchor=source_anchor if legacy_identity_available else None,
                )
                self._insert_block(self._block_identity_index(event.block), paragraph)
                legacy_identity_available = False
            cursor = resume_part_index

        trailing = self._compact_text("".join(capture.parts[cursor:]))
        if trailing:
            identity_text = legacy_text if legacy_identity_available else trailing
            identity_kind = "Paragraph" if legacy_identity_available else "ParagraphInlineFragment"
            paragraph = Paragraph(
                text=trailing,
                block_id=self._block_id(identity_kind, identity_text),
                source_anchor=source_anchor if legacy_identity_available else None,
            )
            # A trailing fragment belongs at capture-close time. Semantic blocks
            # emitted after the last inline image but before this capture closes
            # (for example a nested blockquote or explicit position) already own
            # their source-order slots in self.blocks and must not be jumped over.
            self._append_block(paragraph)

    def _finish_inline_heading(
        self,
        capture: _Capture,
        *,
        legacy_text: str,
        source_anchor: str | None,
        level: int,
    ) -> None:
        """Project inline heading semantics without inventing extra headings."""
        cursor = 0
        legacy_identity_available = True

        def heading_or_fragment(segment: str):
            nonlocal legacy_identity_available
            if legacy_identity_available:
                block = Heading(
                    text=segment,
                    level=level,
                    block_id=self._block_id("Heading", f"{level}\0{legacy_text}"),
                    source_anchor=source_anchor,
                )
                legacy_identity_available = False
                return block
            return Paragraph(
                text=segment,
                block_id=self._block_id(
                    "HeadingInlineFragment",
                    f"{level}\0{segment}",
                ),
                source_anchor=None,
            )

        for event_index, event in enumerate(capture.inline_semantics, start=1):
            if self.control_checkpoint is not None and event_index % 128 == 0:
                self._checkpoint()
            resume_part_index = (
                event.resume_part_index
                if event.resume_part_index is not None
                else event.part_index
            )
            if (
                event.part_index < cursor
                or event.part_index > len(capture.parts)
                or resume_part_index < event.part_index
                or resume_part_index > len(capture.parts)
            ):
                raise BookHtmlImportError(
                    "HTML inline semantic boundary is invalid",
                    code=BookHtmlImportErrorCode.INVALID_ARGUMENT,
                )
            segment = self._compact_text("".join(capture.parts[cursor:event.part_index]))
            if segment:
                self._insert_block(
                    self._block_identity_index(event.block),
                    heading_or_fragment(segment),
                )
            cursor = resume_part_index

        trailing = self._compact_text("".join(capture.parts[cursor:]))
        if trailing:
            self._append_block(heading_or_fragment(trailing))

    def _finish_inline_list_item(
        self,
        capture: _Capture,
        *,
        captured_list: _ListCapture | None,
        source_anchor: str | None,
    ) -> None:
        """Flatten one rich list item without reordering its semantic blocks."""
        events = capture.inline_semantics

        self._list_warning(
            "HTML list items containing inline semantic content cannot be represented by the flat canonical List block and were preserved as readable bullet text around semantic blocks"
        )

        if captured_list is not None:
            logical_text = self._compact_text("".join(capture.parts))
            if logical_text:
                captured_list.identity_items.append(logical_text)
            captured_list.unsupported = True
            captured_list.inline_semantic_fallback = True
            # Plain items preceding this rich item are still buffered in the
            # canonical list capture. Publish them immediately before the first
            # semantic event so an already-emitted image/position cannot jump
            # ahead of earlier list content.
            first_event = events[0]
            for item_index, item in enumerate((item for item in captured_list.items if item), start=1):
                if self.control_checkpoint is not None and item_index % 128 == 0:
                    self._checkpoint()
                fallback_text = f"• {item}"
                fallback = Paragraph(
                    text=fallback_text,
                    block_id=self._block_id("ListFallbackItem", fallback_text),
                    source_anchor=captured_list.self._source_anchor(attrs),
                )
                self._insert_block(
                    self._block_identity_index(first_event.block),
                    fallback,
                )
                if captured_list.legacy_identity_block is None:
                    captured_list.legacy_identity_block = fallback
            captured_list.items.clear()

        cursor = 0
        item_text_started = False
        for event_index, event in enumerate(events, start=1):
            if self.control_checkpoint is not None and event_index % 128 == 0:
                self._checkpoint()
            resume_part_index = (
                event.resume_part_index
                if event.resume_part_index is not None
                else event.part_index
            )
            if (
                event.part_index < cursor
                or event.part_index > len(capture.parts)
                or resume_part_index < event.part_index
                or resume_part_index > len(capture.parts)
            ):
                raise BookHtmlImportError(
                    "HTML inline semantic boundary is invalid",
                    code=BookHtmlImportErrorCode.INVALID_ARGUMENT,
                )
            segment = self._compact_text("".join(capture.parts[cursor:event.part_index]))
            if segment:
                projected = f"• {segment}" if not item_text_started else segment
                identity_kind = (
                    "ListFallbackItem"
                    if not item_text_started
                    else "ListInlineFragment"
                )
                fragment = Paragraph(
                    text=projected,
                    block_id=self._block_id(identity_kind, projected),
                    source_anchor=source_anchor if not item_text_started else None,
                )
                self._insert_block(
                    self._block_identity_index(event.block),
                    fragment,
                )
                if (
                    captured_list is not None
                    and captured_list.legacy_identity_block is None
                ):
                    captured_list.legacy_identity_block = fragment
                item_text_started = True
            elif not item_text_started:
                # A rich list item may begin with an image/position. Preserve an
                # explicit list-membership marker before that semantic block
                # rather than letting it appear outside the item in reading order.
                marker = Paragraph(
                    text="•",
                    block_id=self._block_id("ListInlineItemMarker", "•"),
                    source_anchor=source_anchor,
                )
                self._insert_block(
                    self._block_identity_index(event.block),
                    marker,
                )
                if (
                    captured_list is not None
                    and captured_list.legacy_identity_block is None
                ):
                    captured_list.legacy_identity_block = marker
                item_text_started = True
            cursor = resume_part_index

        trailing = self._compact_text("".join(capture.parts[cursor:]))
        if trailing:
            projected = f"• {trailing}" if not item_text_started else trailing
            identity_kind = (
                "ListFallbackItem" if not item_text_started else "ListInlineFragment"
            )
            fragment = Paragraph(
                text=projected,
                block_id=self._block_id(identity_kind, projected),
                source_anchor=source_anchor if not item_text_started else None,
            )
            self._append_block(fragment)
            if (
                captured_list is not None
                and captured_list.legacy_identity_block is None
            ):
                captured_list.legacy_identity_block = fragment

    def _finish_capture(self, capture: _Capture, *, recovered: bool = False) -> None:
        raw = "".join(capture.parts)
        text = self._compact_text(raw)
        if recovered:
            self._warning(f"malformed HTML left an unclosed {capture.tag} element; readable text was recovered")
        if capture.kind == "title":
            if text and not self.title:
                self.title = text
            return
        source_anchor = capture.self._source_anchor(attrs)
        requires_semantic_split = self._inline_requires_split(capture)
        if capture.kind == "list_item" and requires_semantic_split:
            active_list = (
                self._lists[-1]
                if self._lists and capture.list_depth == len(self._lists)
                else None
            )
            self._finish_inline_list_item(
                capture,
                captured_list=active_list,
                source_anchor=source_anchor,
            )
            return
        if not text:
            return
        if capture.kind == "heading":
            level = int(capture.tag[1])
            if capture.inline_semantics and requires_semantic_split:
                self._finish_inline_heading(
                    capture,
                    legacy_text=text,
                    source_anchor=source_anchor,
                    level=level,
                )
            else:
                self._append_block(
                    Heading(
                        text=text,
                        level=level,
                        block_id=self._block_id("Heading", f"{level}\0{text}"),
                        source_anchor=source_anchor,
                    )
                )
            return
        if capture.kind in {"paragraph", "table_row"} and requires_semantic_split:
            if capture.kind == "table_row" and not self._warned_table_flatten:
                self._warning(
                    "HTML table structure is preserved as row text because BookDocument has no table block kind"
                )
                self._warned_table_flatten = True
            self._finish_inline_paragraph(
                capture,
                legacy_text=text,
                source_anchor=source_anchor,
            )
            return
        if (
            capture.kind == "pre"
            and requires_semantic_split
            and not _explicit_pgn_pre(
                raw,
                self._checkpoint if self.control_checkpoint is not None else None,
            )
        ):
            self._finish_inline_paragraph(
                capture,
                legacy_text=text,
                source_anchor=source_anchor,
            )
            return
        if capture.kind == "list_item":
            if self._lists and capture.list_depth == len(self._lists):
                self._lists[-1].items.append(text)
                self._lists[-1].identity_items.append(text)
                return
            self._list_warning(
                "HTML list item occurred outside a representable list container and was preserved as readable text"
            )
            text = "• " + text
        elif capture.kind == "table_row":
            if not self._warned_table_flatten:
                self._warning("HTML table structure is preserved as row text because BookDocument has no table block kind")
                self._warned_table_flatten = True
        elif capture.kind == "pre" and _explicit_pgn_pre(
            raw,
            self._checkpoint if self.control_checkpoint is not None else None,
        ):
            # Keep a bounded placeholder at the exact semantic source location.
            # Canonical PGN validation still happens only after parsing through
            # the existing D06 round-trip authority; rejected candidates remain
            # readable prose at this location, never guessed chess content.
            for candidate in _pgn_candidates(
                raw,
                self._checkpoint if self.control_checkpoint is not None else None,
            ):
                self._append_block(
                    _PgnSlot(
                        candidate=_PgnCandidate(
                            text=candidate.text,
                            marker_offset=(
                                capture.visible_start_offset + candidate.marker_offset
                            ),
                            source_anchor=source_anchor,
                        )
                    )
                )
            return
        self._append_block(
            Paragraph(
                text=text,
                block_id=self._block_id("Paragraph", text),
                source_anchor=source_anchor,
            )
        )

    def _finish_capture_and_record_parent(
        self,
        capture: _Capture,
        *,
        recovered: bool = False,
    ) -> None:
        self._finish_capture(capture, recovered=recovered)
        parent = capture.parent_inline_owner
        part_index = capture.parent_part_index
        if (
            parent is None
            or part_index is None
            or self._find_capture_index(lambda candidate: candidate is parent) is None
            or len(self.blocks) <= capture.block_start_index
        ):
            return
        # Anchor the nested semantic subtree at its source start. A plain nested
        # child remains structural-only so legacy unsplit projection is unchanged.
        # A child that itself had to split around rich semantics propagates that
        # requirement upward; otherwise its already-published subtree would be
        # duplicated by a parent's flat text projection.
        child_forces_split = (
            self._inline_requires_split(capture)
            or self._blocks_have_pgn_slot_from(capture.block_start_index)
        )
        self._record_inline_semantic(
            self.blocks[capture.block_start_index],
            owner=parent,
            part_index=part_index,
            structural=True,
            forces_split=child_forces_split,
            # A nested semantic capture already published its readable content as
            # one or more canonical blocks. When the parent later needs splitting
            # around a direct image/position event, resume after all source text
            # consumed by this child so the nested text is not duplicated into a
            # parent fragment. Legacy unsplit projection remains unchanged because
            # structural events are consulted only by the split paths.
            resume_part_index=len(parent.parts),
        )

    def close(self) -> None:
        super().close()
        if self._head_depth:
            self._warning(
                "malformed HTML left head metadata unclosed; subsequent readable text may have been omitted"
            )
            self._head_depth = 0
        if self._suppressed_depth:
            self._warning(
                "malformed HTML left suppressed content unclosed; subsequent readable text may have been omitted"
            )
            self._suppressed_depth = 0
            self._suppressed_tags.clear()
        if self._hidden_tags:
            self._warning(
                "malformed HTML left hidden content unclosed; subsequent readable text may have been omitted"
            )
            self._hidden_tags.clear()
        self._recover_capture_tail(0)
        recovered_lists = 0
        while self._lists:
            if self.control_checkpoint is not None and recovered_lists % 128 == 0:
                self._checkpoint()
            captured = self._lists.pop()
            captured.unsupported = True
            captured.structural_unsupported = True
            self._emit_list(captured)
            recovered_lists += 1


def _pgn_candidates(
    visible_text: str,
    control_checkpoint: Callable[[], None] | None = None,
) -> list[_PgnCandidate]:
    """Return explicitly marked PGN regions with stable source offsets."""
    lines = list(_iter_text_lines(visible_text, control_checkpoint))

    candidates: list[_PgnCandidate] = []
    for marker_index, (marker_offset, line) in enumerate(lines):
        if control_checkpoint is not None and marker_index % 128 == 0:
            control_checkpoint()
        if _PGN_MARKER_RE.fullmatch(_controlled_strip(line, control_checkpoint)) is None:
            continue

        start = marker_index + 1
        skipped_blank_lines = 0
        while start < len(lines) and not _controlled_strip(lines[start][1], control_checkpoint):
            skipped_blank_lines += 1
            if control_checkpoint is not None and skipped_blank_lines % 128 == 0:
                control_checkpoint()
            start += 1
        if start >= len(lines) or _PGN_EVENT_RE.match(_controlled_strip(lines[start][1], control_checkpoint)) is None:
            continue

        chunk_lines: list[str] = []
        for candidate_line_index in range(start, len(lines)):
            if control_checkpoint is not None and (candidate_line_index - start) % 128 == 0:
                control_checkpoint()
            candidate_line = lines[candidate_line_index][1]
            stripped = candidate__controlled_strip(line, control_checkpoint)
            if chunk_lines and (_PGN_MARKER_RE.fullmatch(stripped) or _END_PGN_RE.fullmatch(stripped)):
                break
            chunk_lines.append(_controlled_rstrip(candidate_line, control_checkpoint))
        trimmed_blank_lines = 0
        while chunk_lines and not _controlled_strip(chunk_lines[-1], control_checkpoint):
            trimmed_blank_lines += 1
            if control_checkpoint is not None and trimmed_blank_lines % 128 == 0:
                control_checkpoint()
            chunk_lines.pop()
        candidate = _controlled_strip(
            _controlled_join_strings(chunk_lines, "\n", control_checkpoint),
            control_checkpoint,
        )
        if candidate:
            if len(candidates) >= MAX_HTML_PGN_CANDIDATES:
                raise BookHtmlImportError(
                    "HTML book contains too many explicitly marked PGN regions",
                    code=BookHtmlImportErrorCode.RESOURCE_LIMIT,
                )
            candidates.append(
                _PgnCandidate(
                    text=candidate,
                    marker_offset=marker_offset,
                )
            )
    return candidates


def _canonical_pgn_games(
    candidates: list[_PgnCandidate],
    warnings: list[str],
    control_checkpoint: Callable[[], None] | None = None,
) -> list[tuple[_PgnCandidate, Game]]:
    games: list[tuple[_PgnCandidate, Game]] = []
    identities: dict[str, int] = {}
    for candidate_index, candidate_record in enumerate(candidates, start=1):
        if control_checkpoint is not None:
            control_checkpoint()
        candidate = candidate_record.text
        if len(candidate) > MAX_HTML_PGN_CHARS:
            if len(warnings) < MAX_HTML_WARNINGS:
                warnings.append(f"PGN candidate {candidate_index} exceeded the per-game limit and was ignored")
            continue
        try:
            parsed = parse_pgn_text(candidate, strict=False)
        except (PgnRoundTripError, RecursionError, ValueError):
            if len(warnings) < MAX_HTML_WARNINGS:
                warnings.append(f"PGN candidate {candidate_index} could not be represented canonically and was ignored")
            continue
        if not parsed:
            if len(warnings) < MAX_HTML_WARNINGS:
                warnings.append(f"PGN candidate {candidate_index} contains no canonical game and was ignored")
            continue
        if len(games) + len(parsed) > MAX_HTML_PGN_GAMES:
            raise BookHtmlImportError(
                "HTML book contains too many embedded PGN games",
                code=BookHtmlImportErrorCode.RESOURCE_LIMIT,
            )
        # A marked region can be a PGN collection. Split it only through the
        # canonical serializer, so Book Game still means exactly one game and
        # every branch/comment/tag remains attached to its owning game. Prepare
        # the entire region before publication; never publish a partial split.
        try:
            if len(parsed) == 1:
                sources = [candidate]
            else:
                sources = []
                for parsed_game in parsed:
                    if control_checkpoint is not None:
                        control_checkpoint()
                    sources.append(serialize_game(parsed_game))
        except (GameTreeSerializationError, RecursionError, ValueError):
            if len(warnings) < MAX_HTML_WARNINGS:
                warnings.append(f"PGN candidate {candidate_index} could not be split canonically and was ignored")
            continue
        if len(parsed) > 1 and len(warnings) < MAX_HTML_WARNINGS:
            warnings.append(
                f"PGN candidate {candidate_index}: collection split into {len(parsed)} canonical games; source formatting normalized"
            )
        for game_index, (game, game_source) in enumerate(zip(parsed, sources), start=1):
            if control_checkpoint is not None:
                control_checkpoint()
            # Recovery is useful for reading damaged historical sources, but it
            # is not lossless conversion. Preserve canonical diagnostics.
            for warning in game.warnings:
                if len(warnings) >= MAX_HTML_WARNINGS:
                    break
                prefix = f"PGN candidate {candidate_index}"
                if len(parsed) > 1:
                    prefix += f", game {game_index}"
                warnings.append(f"{prefix}: {warning}")
            title = " — ".join(
                part for part in (game.tags.get("White"), game.tags.get("Black")) if part and part != "?"
            ) or game.tags.get("Event") or f"Embedded game {candidate_index}.{game_index}"
            digest = sha256(game_source.encode("utf-8")).hexdigest()[:20]
            occurrence = identities.get(digest, 0) + 1
            identities[digest] = occurrence
            games.append(
                (
                    candidate_record,
                    Game(
                        pgn=game_source,
                        title=title,
                        block_id=f"html-pgn-{digest}-{occurrence}",
                        source_anchor=candidate_record.source_anchor or f"pgn:{candidate_index}",
                    ),
                )
            )
    return games

def _asset_set(
    available_assets: object,
    control_checkpoint: Callable[[], None] | None = None,
) -> frozenset[str] | None:
    if available_assets is None:
        return None
    # Exact built-ins only: container subclasses can override __len__/__iter__
    # and execute arbitrary provider code during an otherwise bounded import.
    if type(available_assets) not in {set, frozenset, tuple, list}:
        raise BookHtmlImportError(
            "available_assets must be a finite built-in collection of relative asset names",
            code=BookHtmlImportErrorCode.INVALID_ARGUMENT,
        )
    if len(available_assets) > MAX_HTML_IMAGES * 2:
        raise BookHtmlImportError(
            "available_assets contains too many entries",
            code=BookHtmlImportErrorCode.RESOURCE_LIMIT,
        )
    if control_checkpoint is not None:
        control_checkpoint()
    normalized: set[str] = set()
    total_chars = 0
    for item_index, item in enumerate(available_assets, start=1):
        if control_checkpoint is not None and item_index % 128 == 1:
            control_checkpoint()
        if type(item) is not str:
            raise BookHtmlImportError(
                "available_assets entries must be non-empty text",
                code=BookHtmlImportErrorCode.INVALID_ARGUMENT,
            )
        # Bound exact host strings before strip/url parsing. A single asset name
        # longer than the maximum source cannot be referenced by a valid source,
        # and the aggregate budget prevents a finite inventory from multiplying
        # parser work far beyond the bounded HTML source envelope.
        item_chars = len(item)
        if item_chars > MAX_HTML_SOURCE_BYTES:
            raise BookHtmlImportError(
                "available_assets entry exceeds the supported asset-name size",
                code=BookHtmlImportErrorCode.RESOURCE_LIMIT,
            )
        total_chars += item_chars
        if total_chars > MAX_HTML_AVAILABLE_ASSET_TOTAL_CHARS:
            raise BookHtmlImportError(
                "available_assets exceeds the supported aggregate name size",
                code=BookHtmlImportErrorCode.RESOURCE_LIMIT,
            )
        if not item.strip():
            raise BookHtmlImportError(
                "available_assets entries must be non-empty text",
                code=BookHtmlImportErrorCode.INVALID_ARGUMENT,
            )
        name = _asset_name(item, control_checkpoint)
        if not name:
            raise BookHtmlImportError(
                "available_assets entries must be relative asset names",
                code=BookHtmlImportErrorCode.INVALID_ARGUMENT,
            )
        normalized.add(name)
    if control_checkpoint is not None:
        control_checkpoint()
    return frozenset(normalized)

def import_html_book(
    source: str | bytes,
    *,
    source_name: str,
    title: str | None = None,
    author: str | None = None,
    language: str | None = None,
    available_assets: object = None,
    control_checkpoint: Callable[[], None] | None = None,
) -> BookHtmlImportResult:
    """Import UTF-8, BOM UTF-16 or qualified Windows-1251 into ``BookDocument``.

    Network/file access is deliberately outside this adapter.  A trusted host may
    provide a source byte string and, optionally, the names of assets it has
    already resolved.  Missing images are reported but never converted into fake
    chess positions.  ``data-acs-fen`` is the only HTML-level position marker;
    an exact standalone ``{PGN N}`` line immediately followed by a PGN Event tag
    is the only HTML-level game marker.  Both paths still delegate canonical chess
    validation before semantic publication.
    """

    if control_checkpoint is not None:
        if not callable(control_checkpoint):
            raise TypeError("control_checkpoint must be callable")
        control_checkpoint()
    display_source = _text(
        source_name, "source_name", control_checkpoint=control_checkpoint
    )
    override_title = _text(
        title, "title", optional=True, control_checkpoint=control_checkpoint
    )
    override_author = _text(
        author, "author", optional=True, control_checkpoint=control_checkpoint
    )
    override_language = _text(
        language, "language", optional=True, control_checkpoint=control_checkpoint
    )
    text, raw, legacy_windows_1251 = _source_text(source, control_checkpoint)
    assets = _asset_set(available_assets, control_checkpoint)

    parser = _SemanticHtmlParser(
        available_assets=assets,
        control_checkpoint=control_checkpoint,
    )
    # Keep trusted host control outside parser exception translation. A cancelled
    # import must propagate to its transaction owner, never become damaged prose.
    chunks = (text,) if control_checkpoint is None else (
        text[offset:offset + 16_384] for offset in range(0, len(text), 16_384)
    )
    for chunk in chunks:
        if control_checkpoint is not None:
            control_checkpoint()
        try:
            parser.feed(chunk)
        except BookHtmlImportError:
            raise
        except Exception as exc:
            if parser._control_failure is exc:
                raise
            raise BookHtmlImportError(
                "HTML book could not be parsed safely",
                code=BookHtmlImportErrorCode.INVALID_ARGUMENT,
            ) from exc
    if control_checkpoint is not None:
        control_checkpoint()
    try:
        parser.close()
    except BookHtmlImportError:
        raise
    except Exception as exc:
        if parser._control_failure is exc:
            raise
        raise BookHtmlImportError(
            "HTML book could not be parsed safely",
            code=BookHtmlImportErrorCode.INVALID_ARGUMENT,
        ) from exc
    if control_checkpoint is not None:
        control_checkpoint()

    visible_text = _controlled_join_strings(parser.visible_parts, "", control_checkpoint)
    warnings = list(parser.warnings)
    if legacy_windows_1251:
        _append_bounded_import_warning(
            warnings,
            "Legacy Windows-1251 HTML was decoded losslessly.",
        )
    # The global visible-text scan preserves historical marker acceptance,
    # including markers outside a semantic capture. Exact marked <pre> captures
    # override the same marker offset with their bounded local candidate so text
    # after </pre> can never be swallowed into that game's canonicalization.
    candidates_by_marker: dict[int, _PgnCandidate] = {}
    for candidate_index, candidate in enumerate(
        _pgn_candidates(visible_text, control_checkpoint), start=1
    ):
        if control_checkpoint is not None and candidate_index % 128 == 1:
            control_checkpoint()
        candidates_by_marker[candidate.marker_offset] = candidate
    for block_index, block in enumerate(parser.blocks, start=1):
        if control_checkpoint is not None and block_index % 128 == 1:
            control_checkpoint()
        if isinstance(block, _PgnSlot):
            candidates_by_marker[block.candidate.marker_offset] = block.candidate
    canonical_games = _canonical_pgn_games(
        sorted(candidates_by_marker.values(), key=lambda item: item.marker_offset),
        warnings,
        control_checkpoint,
    )
    games_by_marker: dict[int, list[Game]] = {}
    for game_index, (candidate, game) in enumerate(canonical_games, start=1):
        if control_checkpoint is not None and game_index % 128 == 1:
            control_checkpoint()
        games_by_marker.setdefault(candidate.marker_offset, []).append(game)
    consumed_markers: set[int] = set()
    ordered_blocks = []
    for block_index, block in enumerate(parser.blocks, start=1):
        if control_checkpoint is not None and block_index % 128 == 1:
            control_checkpoint()
        if isinstance(block, _PgnSlot):
            marker_offset = block.candidate.marker_offset
            region_games = games_by_marker.get(marker_offset)
            if region_games is not None:
                ordered_blocks.extend(region_games)
                consumed_markers.add(marker_offset)
            else:
                # The source is still valuable reading/evidence. Its failed
                # chess interpretation must not erase the text or its place
                # between surrounding paragraphs. Preserve it without a Game
                # role or a Board action, under the existing prose limits.
                candidate = block.candidate
                digest = sha256(candidate.text.encode("utf-8")).hexdigest()[:20]
                ordered_blocks.append(
                    Paragraph(
                        text=candidate.text,
                        block_id=f"html-pgn-text-{digest}-{marker_offset}",
                        source_anchor=candidate.source_anchor,
                    )
                )
            continue
        ordered_blocks.append(block)
        if len(ordered_blocks) > MAX_HTML_BLOCKS:
            raise BookHtmlImportError(
                "HTML book contains too many semantic blocks",
                code=BookHtmlImportErrorCode.RESOURCE_LIMIT,
            )
    parser.blocks = ordered_blocks
    if len(parser.blocks) > MAX_HTML_BLOCKS:
        raise BookHtmlImportError(
            "HTML book contains too many semantic blocks",
            code=BookHtmlImportErrorCode.RESOURCE_LIMIT,
        )
    for game_index, (candidate, game) in enumerate(canonical_games, start=1):
        if control_checkpoint is not None and game_index % 128 == 1:
            control_checkpoint()
        if candidate.marker_offset not in consumed_markers:
            parser._append_block(game)
    embedded_games = [game for _, game in canonical_games]

    resolved_title = override_title or parser.title
    if not resolved_title:
        for block_index, block in enumerate(parser.blocks, start=1):
            if control_checkpoint is not None and block_index % 128 == 1:
                control_checkpoint()
            if isinstance(block, Heading):
                resolved_title = block.text
                break
    if not resolved_title:
        resolved_title = display_source

    if not parser.blocks:
        raise BookHtmlImportError(
            "HTML book contains no readable semantic content",
            code=BookHtmlImportErrorCode.NO_READABLE_CONTENT,
        )

    missing = tuple(sorted(parser.missing_assets))
    if missing:
        for missing_index, name in enumerate(missing, start=1):
            if control_checkpoint is not None and missing_index % 128 == 1:
                control_checkpoint()
            if not _append_bounded_import_warning(
                warnings,
                f"referenced asset is unavailable: {name}",
            ):
                break

    try:
        document = BookDocument(
            title=resolved_title,
            author=override_author or parser.author,
            language=override_language or parser.language,
            source_name=display_source,
            blocks=list(parser.blocks),
            warnings=list(warnings),
        )
    except BookDocumentError as exc:
        raise BookHtmlImportError(
            "HTML semantic projection exceeds canonical BookDocument limits",
            code=BookHtmlImportErrorCode.RESOURCE_LIMIT,
        ) from exc
    digest = sha256(raw).hexdigest()
    return BookHtmlImportResult(
        document=document,
        source_sha256=digest,
        book_key=f"html-sha256:{digest}",
        pgn_games=len(embedded_games),
        image_references=tuple(parser.image_references),
        missing_assets=missing,
        warnings=tuple(warnings),
    )


SUPPORTED_HTML_BOOK_CAPABILITY = MappingProxyType(
    {
        "format": "HTML/XHTML",
        "encoding": "UTF-8; BOM-declared UTF-16; evidence-gated Windows-1251",
        "semantic_blocks": (
            "Heading",
            "Paragraph",
            "List(ordered/unordered)",
            "Note(image)",
            "Game(explicit {PGN N} marker)",
            "Position(data-acs-fen)",
            "Diagram(img[data-acs-fen])",
        ),
        "does_not_claim": (
            "implicit PGN inference from ordinary text",
            "image-to-position recognition",
            "legacy encodings other than qualified Windows-1251",
            "network asset fetching",
            "TXT",
            "Markdown",
            "DOCX",
            "EPUB",
            "PDF/OCR",
        ),
    }
)
