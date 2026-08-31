from __future__ import annotations

"""Bounded HTML/XHTML ingestion into the semantic :mod:`acs.bookdocument` model.

This adapter owns source decoding and structure projection only.  It does not
implement chess rules or a PGN parser: explicit positions are validated by the
canonical :class:`acs.chesscore.Board`, and embedded PGN candidates are accepted
only when the existing bounded D06 ingress can represent exactly one game.

Image-only diagrams remain image notes unless the source carries an explicit
``data-acs-fen`` marker.  The importer never guesses a chess position from pixels,
alt text, coordinates, or surrounding prose.
"""

from dataclasses import dataclass
from enum import Enum
from hashlib import sha256
from html.parser import HTMLParser
import re
from types import MappingProxyType
from urllib.parse import urlsplit

from .bookdocument import BookDocument, Diagram, Game, Heading, Note, Paragraph, Position
from .chesscore import Board
from .pgn_roundtrip import PgnRoundTripError, parse_pgn_text


MAX_HTML_SOURCE_BYTES = 8 * 1024 * 1024
MAX_HTML_VISIBLE_CHARS = 12 * 1024 * 1024
MAX_HTML_BLOCKS = 50_000
MAX_HTML_IMAGES = 10_000
MAX_HTML_PGN_GAMES = 1_024
MAX_HTML_PGN_CHARS = 1 * 1024 * 1024
MAX_HTML_WARNINGS = 2_048


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
class _Capture:
    tag: str
    kind: str
    attrs: dict[str, str]
    parts: list[str]


_BLOCK_BOUNDARY_TAGS = frozenset(
    {
        "address", "article", "aside", "blockquote", "br", "dd", "div", "dl",
        "dt", "figcaption", "figure", "footer", "form", "h1", "h2", "h3",
        "h4", "h5", "h6", "header", "hr", "li", "main", "nav", "ol", "p",
        "pre", "section", "table", "tbody", "td", "tfoot", "th", "thead", "tr", "ul",
    }
)
_SUPPRESSED_TAGS = frozenset({"script", "style", "noscript", "template"})
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


def _text(value: object, field: str, *, optional: bool = False) -> str | None:
    if value is None and optional:
        return None
    if type(value) is not str or not value.strip():
        raise BookHtmlImportError(
            f"{field} must be non-empty text",
            code=BookHtmlImportErrorCode.INVALID_ARGUMENT,
        )
    return value.strip()


def _source_text(source: object) -> tuple[str, bytes]:
    if type(source) is str:
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
        return source, encoded
    if type(source) is bytes:
        if len(source) > MAX_HTML_SOURCE_BYTES:
            raise BookHtmlImportError(
                "HTML book source exceeds the supported size",
                code=BookHtmlImportErrorCode.RESOURCE_LIMIT,
            )
        try:
            return source.decode("utf-8-sig"), source
        except UnicodeDecodeError as exc:
            raise BookHtmlImportError(
                "HTML book source must use UTF-8 encoding",
                code=BookHtmlImportErrorCode.UNSUPPORTED_ENCODING,
            ) from exc
    raise BookHtmlImportError(
        "HTML book source must be text or bytes",
        code=BookHtmlImportErrorCode.INVALID_ARGUMENT,
    )


def _compact(value: str) -> str:
    return " ".join(value.replace("\xa0", " ").split())


def _asset_name(value: str) -> str:
    parts = urlsplit(value.strip())
    if parts.scheme or parts.netloc or not parts.path:
        return ""
    segments = [segment for segment in parts.path.replace("\\", "/").split("/") if segment not in {"", "."}]
    if not segments or ".." in segments:
        return ""
    return "/".join(segments)


class _SemanticHtmlParser(HTMLParser):
    def __init__(self, *, available_assets: frozenset[str] | None) -> None:
        super().__init__(convert_charrefs=True)
        self.available_assets = available_assets
        self.blocks = []
        self.warnings: list[str] = []
        self.title: str | None = None
        self.language: str | None = None
        self.author: str | None = None
        self.visible_parts: list[str] = []
        self.visible_chars = 0
        self.image_references: list[str] = []
        self.missing_assets: set[str] = set()
        self._captures: list[_Capture] = []
        self._suppressed_depth = 0
        self._node_count = 0
        self._ids: dict[str, int] = {}
        self._warned_table_flatten = False
        self._warned_list_flatten = False

    def _warning(self, message: str) -> None:
        if len(self.warnings) < MAX_HTML_WARNINGS:
            self.warnings.append(message)
        elif len(self.warnings) == MAX_HTML_WARNINGS:
            self.warnings.append("additional HTML import warnings were suppressed")

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
        source_anchor = attrs.get("id") or None
        if tag == "img":
            alt = _compact(attrs.get("alt", "")) or None
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

    def handle_starttag(self, tag: str, attrs_list: list[tuple[str, str | None]]) -> None:
        tag = tag.lower()
        self._node_count += 1
        if self._node_count > MAX_HTML_BLOCKS * 20:
            raise BookHtmlImportError(
                "HTML book contains too many markup nodes",
                code=BookHtmlImportErrorCode.RESOURCE_LIMIT,
            )
        attrs = {name.lower(): value or "" for name, value in attrs_list}
        if tag in _SUPPRESSED_TAGS:
            self._suppressed_depth += 1
            return
        if self._suppressed_depth:
            return
        if tag in _BLOCK_BOUNDARY_TAGS:
            self._append_visible("\n")
        if tag == "html" and not self.language:
            lang = _compact(attrs.get("lang", ""))
            if lang:
                self.language = lang
        if tag == "meta":
            name = (attrs.get("name") or attrs.get("property") or "").strip().lower()
            content = _compact(attrs.get("content", ""))
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
            alt = _compact(attrs.get("alt", ""))
            if src:
                self.image_references.append(src)
                local_name = _asset_name(src)
                if self.available_assets is not None and local_name and local_name not in self.available_assets:
                    self.missing_assets.add(local_name)
            if "data-acs-fen" in attrs:
                self._emit_explicit_position(tag, attrs)
            elif alt:
                self._append_block(
                    Note(
                        text=alt,
                        note_type="image",
                        block_id=self._block_id("ImageNote", src + "\0" + alt),
                        source_anchor=attrs.get("id") or None,
                    )
                )
            else:
                self._warning("an image reference has no accessible text and no explicit chess position")
        elif "data-acs-fen" in attrs:
            self._emit_explicit_position(tag, attrs)

        kind = _CAPTURE_KINDS.get(tag)
        if kind is not None:
            self._captures.append(_Capture(tag=tag, kind=kind, attrs=attrs, parts=[]))

    def handle_startendtag(self, tag: str, attrs_list: list[tuple[str, str | None]]) -> None:
        self.handle_starttag(tag, attrs_list)
        if tag.lower() not in {"img", "meta", "br", "hr", "input", "link"}:
            self.handle_endtag(tag)

    def handle_endtag(self, tag: str) -> None:
        tag = tag.lower()
        if tag in _SUPPRESSED_TAGS:
            if self._suppressed_depth:
                self._suppressed_depth -= 1
            return
        if self._suppressed_depth:
            return
        if self._captures and self._captures[-1].tag == tag:
            capture = self._captures.pop()
            self._finish_capture(capture)
        if tag in _BLOCK_BOUNDARY_TAGS:
            self._append_visible("\n")

    def handle_data(self, data: str) -> None:
        if self._suppressed_depth:
            return
        self._append_visible(data)
        for capture in self._captures:
            capture.parts.append(data)

    def _finish_capture(self, capture: _Capture, *, recovered: bool = False) -> None:
        raw = "".join(capture.parts)
        text = _compact(raw)
        if recovered:
            self._warning(f"malformed HTML left an unclosed {capture.tag} element; readable text was recovered")
        if capture.kind == "title":
            if text and not self.title:
                self.title = text
            return
        if not text:
            return
        source_anchor = capture.attrs.get("id") or None
        if capture.kind == "heading":
            level = int(capture.tag[1])
            self._append_block(
                Heading(
                    text=text,
                    level=level,
                    block_id=self._block_id("Heading", f"{level}\0{text}"),
                    source_anchor=source_anchor,
                )
            )
            return
        if capture.kind == "list_item":
            if not self._warned_list_flatten:
                self._warning("HTML list structure is preserved as ordered reading text because BookDocument has no list block kind")
                self._warned_list_flatten = True
            text = "• " + text
        elif capture.kind == "table_row":
            if not self._warned_table_flatten:
                self._warning("HTML table structure is preserved as row text because BookDocument has no table block kind")
                self._warned_table_flatten = True
        elif capture.kind == "pre" and "[Event" in raw:
            return
        self._append_block(
            Paragraph(
                text=text,
                block_id=self._block_id("Paragraph", text),
                source_anchor=source_anchor,
            )
        )

    def close(self) -> None:
        super().close()
        while self._captures:
            self._finish_capture(self._captures.pop(), recovered=True)


def _pgn_candidates(visible_text: str) -> list[str]:
    """Return source-order PGN-shaped regions; canonical D06 decides validity."""
    lines = visible_text.replace("\r\n", "\n").replace("\r", "\n").split("\n")
    starts = [index for index, line in enumerate(lines) if _PGN_EVENT_RE.match(line.strip())]
    candidates: list[str] = []
    for position, start in enumerate(starts):
        stop = starts[position + 1] if position + 1 < len(starts) else len(lines)
        chunk_lines: list[str] = []
        for line in lines[start:stop]:
            stripped = line.strip()
            if chunk_lines and (_PGN_MARKER_RE.match(stripped) or _END_PGN_RE.match(stripped)):
                break
            chunk_lines.append(line.rstrip())
        while chunk_lines and not chunk_lines[-1].strip():
            chunk_lines.pop()
        candidate = "\n".join(chunk_lines).strip()
        if candidate:
            candidates.append(candidate)
    return candidates


def _canonical_pgn_games(candidates: list[str], warnings: list[str]) -> list[Game]:
    games: list[Game] = []
    identities: dict[str, int] = {}
    for candidate_index, candidate in enumerate(candidates, start=1):
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
        if len(parsed) != 1:
            if len(warnings) < MAX_HTML_WARNINGS:
                warnings.append(f"PGN candidate {candidate_index} did not resolve to exactly one canonical game and was ignored")
            continue
        if len(games) >= MAX_HTML_PGN_GAMES:
            raise BookHtmlImportError(
                "HTML book contains too many embedded PGN games",
                code=BookHtmlImportErrorCode.RESOURCE_LIMIT,
            )
        game = parsed[0]
        title = " — ".join(
            part for part in (game.tags.get("White"), game.tags.get("Black")) if part and part != "?"
        ) or game.tags.get("Event") or f"Embedded game {candidate_index}"
        digest = sha256(candidate.encode("utf-8")).hexdigest()[:20]
        occurrence = identities.get(digest, 0) + 1
        identities[digest] = occurrence
        games.append(
            Game(
                pgn=candidate,
                title=title,
                block_id=f"html-pgn-{digest}-{occurrence}",
                source_anchor=f"pgn:{candidate_index}",
            )
        )
    return games


def _asset_set(available_assets: object) -> frozenset[str] | None:
    if available_assets is None:
        return None
    if not isinstance(available_assets, (set, frozenset, tuple, list)):
        raise BookHtmlImportError(
            "available_assets must be a finite collection of relative asset names",
            code=BookHtmlImportErrorCode.INVALID_ARGUMENT,
        )
    normalized: set[str] = set()
    if len(available_assets) > MAX_HTML_IMAGES * 2:
        raise BookHtmlImportError(
            "available_assets contains too many entries",
            code=BookHtmlImportErrorCode.RESOURCE_LIMIT,
        )
    for item in available_assets:
        if type(item) is not str or not item.strip():
            raise BookHtmlImportError(
                "available_assets entries must be non-empty text",
                code=BookHtmlImportErrorCode.INVALID_ARGUMENT,
            )
        name = _asset_name(item)
        if not name:
            raise BookHtmlImportError(
                "available_assets entries must be relative asset names",
                code=BookHtmlImportErrorCode.INVALID_ARGUMENT,
            )
        normalized.add(name)
    return frozenset(normalized)


def import_html_book(
    source: str | bytes,
    *,
    source_name: str,
    title: str | None = None,
    author: str | None = None,
    language: str | None = None,
    available_assets: object = None,
) -> BookHtmlImportResult:
    """Import one UTF-8 HTML/XHTML document into semantic ``BookDocument``.

    Network/file access is deliberately outside this adapter.  A trusted host may
    provide a source byte string and, optionally, the names of assets it has
    already resolved.  Missing images are reported but never converted into fake
    chess positions.  ``data-acs-fen`` is the only HTML-level position marker;
    it is validated through the canonical Board before publication.
    """

    display_source = _text(source_name, "source_name")
    override_title = _text(title, "title", optional=True)
    override_author = _text(author, "author", optional=True)
    override_language = _text(language, "language", optional=True)
    text, raw = _source_text(source)
    assets = _asset_set(available_assets)

    parser = _SemanticHtmlParser(available_assets=assets)
    try:
        parser.feed(text)
        parser.close()
    except BookHtmlImportError:
        raise
    except Exception as exc:
        raise BookHtmlImportError(
            "HTML book could not be parsed safely",
            code=BookHtmlImportErrorCode.INVALID_ARGUMENT,
        ) from exc

    visible_text = "".join(parser.visible_parts)
    warnings = list(parser.warnings)
    embedded_games = _canonical_pgn_games(_pgn_candidates(visible_text), warnings)
    for block in embedded_games:
        parser._append_block(block)

    resolved_title = override_title or parser.title
    if not resolved_title:
        for block in parser.blocks:
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
        room = max(0, MAX_HTML_WARNINGS - len(warnings))
        for name in missing[:room]:
            warnings.append(f"referenced asset is unavailable: {name}")
        if len(missing) > room and len(warnings) < MAX_HTML_WARNINGS + 1:
            warnings.append("additional missing asset warnings were suppressed")

    document = BookDocument(
        title=resolved_title,
        author=override_author or parser.author,
        language=override_language or parser.language,
        source_name=display_source,
        blocks=list(parser.blocks),
        warnings=list(warnings),
    )
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
        "encoding": "UTF-8",
        "semantic_blocks": (
            "Heading",
            "Paragraph",
            "Note(image)",
            "Game(PGN)",
            "Position(data-acs-fen)",
            "Diagram(img[data-acs-fen])",
        ),
        "does_not_claim": (
            "image-to-position recognition",
            "arbitrary legacy encodings",
            "network asset fetching",
            "TXT",
            "Markdown",
            "DOCX",
            "EPUB",
            "PDF/OCR",
        ),
    }
)
