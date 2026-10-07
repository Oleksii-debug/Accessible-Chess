from __future__ import annotations

"""Presentation-neutral semantic chess-book model.

BookDocument is deliberately independent from DOCX, HTML, PGN and ChessBase.
Importers convert source material into these semantic blocks; accessible UIs and
exporters consume the blocks without needing to understand the source format.
Chess position validation is delegated to the canonical chess core.
"""

from dataclasses import dataclass, field
from itertools import islice
from enum import Enum
from typing import Any, Iterable, Iterator

from .chesscore import Board
from .input_limits import MAX_FEN_CHARS


BOOK_DOCUMENT_SCHEMA_VERSION = 1
MAX_BOOK_DOCUMENT_BLOCKS = 50_000
MAX_BOOK_DOCUMENT_WARNINGS = 4_096
MAX_BOOK_DOCUMENT_FIELDS = 9
# Scalar/list ceilings preserve the widest currently supported canonical content
# while ensuring malformed exact built-ins fail before expensive strip/split scans.
MAX_BOOK_TEXT_FIELD_CHARS = 12 * 1024 * 1024
MAX_BOOK_PGN_CHARS = 64 * 1024 * 1024
MAX_BOOK_LIST_ITEMS = 65_536
MAX_BOOK_LIST_TOTAL_CHARS = 12 * 1024 * 1024
MAX_BOOK_WARNING_TOTAL_CHARS = 12 * 1024 * 1024
BOOK_STRUCTURE_WARNING_TRUNCATION_NOTICE = (
    "Additional structural warnings were omitted because the diagnostic limit was reached."
)
# Durable BookIndex target keys are capped at 4096 characters. These limits
# preserve the widest identifier that still fits its canonical target prefix.
MAX_BOOK_BLOCK_ID_CHARS = 4_090
MAX_BOOK_SOURCE_ANCHOR_CHARS = 4_089
# Whole-document semantic text is bounded independently of per-field limits.
# 256 MiB is twice the widest supported EPUB uncompressed-source envelope,
# leaving deterministic headroom for generated semantic identifiers/provenance
# while preventing direct/persisted BookDocument payloads from multiplying the
# 12/64 MiB per-field ceilings across tens of thousands of blocks.
MAX_BOOK_DOCUMENT_TOTAL_TEXT_CHARS = 256 * 1024 * 1024


class BookDocumentErrorCode(str, Enum):
    INVALID_FIELD = "invalid_field"
    UNKNOWN_FIELD = "unknown_field"
    UNSUPPORTED_SCHEMA = "unsupported_schema"
    UNSUPPORTED_BLOCK_KIND = "unsupported_block_kind"


class BookDocumentError(ValueError):
    """Stable failure for the presentation-neutral semantic book contract."""

    def __init__(self, message: str, *, code: BookDocumentErrorCode) -> None:
        super().__init__(message)
        self.code = BookDocumentErrorCode(code)


def _required_text(value: object, field_name: str) -> str:
    # Canonical Book payloads originate from JSON/text importers and therefore
    # use built-in strings. Reject subclasses and oversized exact strings before
    # strip() so malformed input cannot execute hooks or force an unbounded scan.
    if type(value) is not str:
        raise BookDocumentError(
            f"{field_name} must be non-empty text",
            code=BookDocumentErrorCode.INVALID_FIELD,
        )
    if len(value) > MAX_BOOK_TEXT_FIELD_CHARS:
        raise BookDocumentError(
            f"{field_name} exceeds the canonical text field limit",
            code=BookDocumentErrorCode.INVALID_FIELD,
        )
    if not value.strip():
        raise BookDocumentError(
            f"{field_name} must be non-empty text",
            code=BookDocumentErrorCode.INVALID_FIELD,
        )
    return value


def _optional_text(value: object, field_name: str) -> str | None:
    if value is None:
        return None
    return _required_text(value, field_name)


def _optional_identifier(
    value: object,
    field_name: str,
    *,
    max_chars: int,
) -> str | None:
    if value is None:
        return None
    # Reject provider-defined text subclasses and impossible target identities
    # before len/strip/hash work owned by the semantic navigation boundary.
    if type(value) is not str or len(value) > max_chars:
        raise BookDocumentError(
            f"{field_name} exceeds the canonical identifier limit",
            code=BookDocumentErrorCode.INVALID_FIELD,
        )
    return _required_text(value, field_name).strip()


def _required_pgn_text(value: object, field_name: str) -> str:
    if type(value) is not str:
        raise BookDocumentError(
            f"{field_name} must be non-empty text",
            code=BookDocumentErrorCode.INVALID_FIELD,
        )
    if len(value) > MAX_BOOK_PGN_CHARS:
        raise BookDocumentError(
            f"{field_name} exceeds the canonical PGN text limit",
            code=BookDocumentErrorCode.INVALID_FIELD,
        )
    if not value.strip():
        raise BookDocumentError(
            f"{field_name} must be non-empty text",
            code=BookDocumentErrorCode.INVALID_FIELD,
        )
    return value


def _optional_pgn_text(value: object, field_name: str) -> str | None:
    if value is None:
        return None
    return _required_pgn_text(value, field_name)


def _validate_warning_list(
    value: object,
    *,
    container_message: str,
) -> list[str]:
    if type(value) is not list:
        raise BookDocumentError(
            container_message,
            code=BookDocumentErrorCode.INVALID_FIELD,
        )
    if len(value) > MAX_BOOK_DOCUMENT_WARNINGS:
        raise BookDocumentError(
            f"BookDocument supports at most {MAX_BOOK_DOCUMENT_WARNINGS} warnings",
            code=BookDocumentErrorCode.INVALID_FIELD,
        )
    total_chars = 0
    for warning in value:
        if type(warning) is not str:
            raise BookDocumentError(
                container_message,
                code=BookDocumentErrorCode.INVALID_FIELD,
            )
        total_chars += len(warning)
        if total_chars > MAX_BOOK_WARNING_TOTAL_CHARS:
            raise BookDocumentError(
                "BookDocument warning text exceeds the canonical aggregate limit",
                code=BookDocumentErrorCode.INVALID_FIELD,
            )
        if not warning.strip():
            raise BookDocumentError(
                container_message,
                code=BookDocumentErrorCode.INVALID_FIELD,
            )
    return value


def _append_bounded_structure_warning(
    warnings: list[str],
    message: str,
    *,
    source_count: int,
    total_chars: int,
) -> tuple[int, bool]:
    """Append one generated diagnostic without exceeding canonical warning budgets.

    Stored importer warnings are preserved exactly. If generated structural
    diagnostics would overflow count or aggregate-text limits, generated entries
    are reclaimed as needed for one deterministic truncation notice. If the
    stored warnings already consume the complete budget, fail closed rather than
    silently pretending that structural diagnostics were complete.
    """

    if (
        len(warnings) < MAX_BOOK_DOCUMENT_WARNINGS
        and total_chars + len(message) <= MAX_BOOK_WARNING_TOTAL_CHARS
    ):
        warnings.append(message)
        return total_chars + len(message), True

    notice = BOOK_STRUCTURE_WARNING_TRUNCATION_NOTICE
    while len(warnings) > source_count and (
        len(warnings) >= MAX_BOOK_DOCUMENT_WARNINGS
        or total_chars + len(notice) > MAX_BOOK_WARNING_TOTAL_CHARS
    ):
        removed = warnings.pop()
        total_chars -= len(removed)

    if (
        len(warnings) >= MAX_BOOK_DOCUMENT_WARNINGS
        or total_chars + len(notice) > MAX_BOOK_WARNING_TOTAL_CHARS
    ):
        raise BookDocumentError(
            "Book structural warnings exceed the canonical diagnostic budget",
            code=BookDocumentErrorCode.INVALID_FIELD,
        )

    warnings.append(notice)
    return total_chars + len(notice), False


def _add_document_text_chars(total: int, value: object) -> int:
    """Add canonical semantic text to the whole-document resource budget.

    Callers pass only already-canonical BookDocument wire values. The helper
    nevertheless keeps an exact built-in boundary so future schema additions
    cannot silently introduce active containers or unbounded nested traversal.
    Structural kind values are excluded by the block helper below; durable
    identifiers, metadata, warnings and reader-visible/chess text all count.
    """

    if value is None or type(value) in {bool, int}:
        return total
    if type(value) is str:
        total += len(value)
        if total > MAX_BOOK_DOCUMENT_TOTAL_TEXT_CHARS:
            raise BookDocumentError(
                "BookDocument text exceeds the canonical aggregate limit",
                code=BookDocumentErrorCode.INVALID_FIELD,
            )
        return total
    if type(value) is list:
        for item in value:
            if type(item) is not str:
                raise BookDocumentError(
                    "BookDocument aggregate text contains an unsupported value",
                    code=BookDocumentErrorCode.INVALID_FIELD,
                )
            total += len(item)
            if total > MAX_BOOK_DOCUMENT_TOTAL_TEXT_CHARS:
                raise BookDocumentError(
                    "BookDocument text exceeds the canonical aggregate limit",
                    code=BookDocumentErrorCode.INVALID_FIELD,
                )
        return total
    raise BookDocumentError(
        "BookDocument aggregate text contains an unsupported value",
        code=BookDocumentErrorCode.INVALID_FIELD,
    )


def _document_metadata_text_chars(
    *,
    title: str,
    language: str | None,
    author: str | None,
    source_name: str | None,
    source_uri: str | None,
    source_rights: str | None,
) -> int:
    total = 0
    for value in (title, language, author, source_name, source_uri, source_rights):
        total = _add_document_text_chars(total, value)
    return total


def _add_block_payload_text_chars(total: int, payload: dict[str, Any]) -> int:
    if type(payload) is not dict:
        raise BookDocumentError(
            "Book block export must be a built-in mapping",
            code=BookDocumentErrorCode.INVALID_FIELD,
        )
    for key, value in payload.items():
        if key == "kind":
            continue
        total = _add_document_text_chars(total, value)
    return total

def _fen_text(value: object, field_name: str) -> str:
    """Validate a Book FEN through the one canonical Board contract.

    Books may retain the historical compact four-field form or the full six-field
    form, but they do not own piece-placement, king, castling, en-passant or pawn
    legality rules. A rejected value never becomes a published semantic block.
    """

    if type(value) is str and len(value) > MAX_FEN_CHARS:
        raise BookDocumentError(
            f"{field_name} exceeds the canonical FEN input limit",
            code=BookDocumentErrorCode.INVALID_FIELD,
        )
    text = _required_text(value, field_name).strip()
    fields = text.split()
    if len(fields) not in {4, 6}:
        raise BookDocumentError(
            f"{field_name} must contain exactly 4 or 6 FEN fields",
            code=BookDocumentErrorCode.INVALID_FIELD,
        )
    try:
        Board(text)
    except (TypeError, ValueError):
        raise BookDocumentError(
            f"{field_name} is not accepted by canonical Board validation",
            code=BookDocumentErrorCode.INVALID_FIELD,
        ) from None
    return text


@dataclass(slots=True)
class BookBlock:
    block_id: str | None = None
    source_anchor: str | None = None

    def __post_init__(self) -> None:
        self.block_id = _optional_identifier(
            self.block_id,
            "block_id",
            max_chars=MAX_BOOK_BLOCK_ID_CHARS,
        )
        self.source_anchor = _optional_identifier(
            self.source_anchor,
            "source_anchor",
            max_chars=MAX_BOOK_SOURCE_ANCHOR_CHARS,
        )

    @property
    def kind(self) -> str:
        return self.__class__.__name__

    def as_dict(self) -> dict[str, Any]:
        data = {"kind": self.kind}
        for name in self.__dataclass_fields__:
            value = getattr(self, name)
            if value is not None:
                data[name] = value
        # Dataclass instances are intentionally mutable for authoring. Rebuild
        # the exact current payload before export so post-construction mutation
        # cannot bypass semantic validators and leak corrupt wire data.
        rebuilt = block_from_dict(dict(data))
        canonical = {"kind": rebuilt.kind}
        for name in rebuilt.__dataclass_fields__:
            value = getattr(rebuilt, name)
            if value is not None:
                canonical[name] = value
        return canonical


@dataclass(slots=True)
class Heading(BookBlock):
    text: str = ""
    level: int = 1

    def __post_init__(self) -> None:
        BookBlock.__post_init__(self)
        self.text = _required_text(self.text, "Heading text")
        if type(self.level) is not int or not 1 <= self.level <= 6:
            raise BookDocumentError(
                "Heading level must be an integer between 1 and 6",
                code=BookDocumentErrorCode.INVALID_FIELD,
            )


@dataclass(slots=True)
class Paragraph(BookBlock):
    text: str = ""

    def __post_init__(self) -> None:
        BookBlock.__post_init__(self)
        self.text = _required_text(self.text, "Paragraph text")


@dataclass(slots=True)
class ListBlock(BookBlock):
    """Semantic ordered/unordered list; consumers must not flatten it to prose."""

    items: list[str] = field(default_factory=list)
    ordered: bool = False
    start: int | None = None

    @property
    def kind(self) -> str:
        return "List"

    def __post_init__(self) -> None:
        BookBlock.__post_init__(self)
        if type(self.items) is not list or not self.items:
            raise BookDocumentError(
                "List items must be a non-empty list of text items",
                code=BookDocumentErrorCode.INVALID_FIELD,
            )
        if len(self.items) > MAX_BOOK_LIST_ITEMS:
            raise BookDocumentError(
                f"List supports at most {MAX_BOOK_LIST_ITEMS} items",
                code=BookDocumentErrorCode.INVALID_FIELD,
            )
        validated_items: list[str] = []
        total_chars = 0
        for item in self.items:
            if type(item) is not str:
                raise BookDocumentError(
                    "List item must be non-empty text",
                    code=BookDocumentErrorCode.INVALID_FIELD,
                )
            total_chars += len(item)
            if total_chars > MAX_BOOK_LIST_TOTAL_CHARS:
                raise BookDocumentError(
                    "List text exceeds the canonical aggregate limit",
                    code=BookDocumentErrorCode.INVALID_FIELD,
                )
            validated_items.append(_required_text(item, "List item"))
        if type(self.ordered) is not bool:
            raise BookDocumentError(
                "List ordered must be a boolean",
                code=BookDocumentErrorCode.INVALID_FIELD,
            )
        if self.start is not None:
            if type(self.start) is not int or self.start < 1:
                raise BookDocumentError(
                    "List start must be a positive integer or None",
                    code=BookDocumentErrorCode.INVALID_FIELD,
                )
            if not self.ordered:
                raise BookDocumentError(
                    "List start is only valid for ordered lists",
                    code=BookDocumentErrorCode.INVALID_FIELD,
                )
        self.items = validated_items


@dataclass(slots=True)
class Position(BookBlock):
    fen: str = ""
    caption: str | None = None
    side_to_move_note: str | None = None

    def __post_init__(self) -> None:
        BookBlock.__post_init__(self)
        self.fen = _fen_text(self.fen, "Position FEN")
        self.caption = _optional_text(self.caption, "Position caption")
        self.side_to_move_note = _optional_text(
            self.side_to_move_note,
            "Position side_to_move_note",
        )


@dataclass(slots=True)
class Diagram(Position):
    alt_text: str | None = None

    def __post_init__(self) -> None:
        Position.__post_init__(self)
        self.alt_text = _optional_text(self.alt_text, "Diagram alt_text")


@dataclass(slots=True)
class Game(BookBlock):
    pgn: str = ""
    title: str | None = None
    game_id: int | None = None
    game_record_digest: str | None = None

    def __post_init__(self) -> None:
        BookBlock.__post_init__(self)
        if type(self.pgn) is not str:
            raise BookDocumentError(
                "Game PGN must be text",
                code=BookDocumentErrorCode.INVALID_FIELD,
            )
        if len(self.pgn) > MAX_BOOK_PGN_CHARS:
            raise BookDocumentError(
                "Game PGN exceeds the canonical PGN text limit",
                code=BookDocumentErrorCode.INVALID_FIELD,
            )
        self.title = _optional_text(self.title, "Game title")
        if self.game_record_digest is not None and (
            type(self.game_record_digest) is not str
            or len(self.game_record_digest) != 64
            or any(character not in "0123456789abcdef" for character in self.game_record_digest)
            or self.game_id is None
        ):
            raise BookDocumentError(
                "Game record digest requires a referenced game and canonical SHA-256 identity",
                code=BookDocumentErrorCode.INVALID_FIELD,
            )
        if self.game_id is not None and (
            type(self.game_id) is not int or self.game_id < 0
        ):
            raise BookDocumentError(
                "Game game_id must be a non-negative integer or None",
                code=BookDocumentErrorCode.INVALID_FIELD,
            )
        if not self.pgn.strip() and self.game_id is None:
            raise BookDocumentError(
                "Game requires PGN text or a game_id reference",
                code=BookDocumentErrorCode.INVALID_FIELD,
            )


@dataclass(slots=True)
class VariationTree(BookBlock):
    root_fen: str = ""
    pgn: str = ""
    title: str | None = None

    def __post_init__(self) -> None:
        BookBlock.__post_init__(self)
        self.root_fen = _fen_text(self.root_fen, "VariationTree root_fen")
        self.pgn = _required_pgn_text(self.pgn, "VariationTree PGN")
        self.title = _optional_text(self.title, "VariationTree title")


@dataclass(slots=True)
class Exercise(BookBlock):
    fen: str = ""
    prompt: str = ""
    solution_pgn: str | None = None
    answer_text: str | None = None
    difficulty: str | None = None

    def __post_init__(self) -> None:
        BookBlock.__post_init__(self)
        self.fen = _fen_text(self.fen, "Exercise FEN")
        self.prompt = _required_text(self.prompt, "Exercise prompt")
        self.solution_pgn = _optional_pgn_text(
            self.solution_pgn,
            "Exercise solution_pgn",
        )
        self.answer_text = _optional_text(
            self.answer_text,
            "Exercise answer_text",
        )
        self.difficulty = _optional_text(
            self.difficulty,
            "Exercise difficulty",
        )
        if self.solution_pgn is None and self.answer_text is None:
            raise BookDocumentError(
                "Exercise requires solution_pgn or answer_text",
                code=BookDocumentErrorCode.INVALID_FIELD,
            )


@dataclass(slots=True)
class Note(BookBlock):
    text: str = ""
    note_type: str = "note"

    def __post_init__(self) -> None:
        BookBlock.__post_init__(self)
        self.text = _required_text(self.text, "Note text")
        self.note_type = _required_text(self.note_type, "Note note_type")


SemanticBlock = Heading | Paragraph | ListBlock | Position | Diagram | Game | VariationTree | Exercise | Note
_BLOCK_TYPES = {
    "Heading": Heading,
    "Paragraph": Paragraph,
    "List": ListBlock,
    "Position": Position,
    "Diagram": Diagram,
    "Game": Game,
    "VariationTree": VariationTree,
    "Exercise": Exercise,
    "Note": Note,
}
_SEMANTIC_BLOCK_TYPES = tuple(_BLOCK_TYPES.values())
_MAX_BOOK_BLOCK_FIELDS = 1 + max(
    len(cls.__dataclass_fields__) for cls in _SEMANTIC_BLOCK_TYPES
)


def block_from_dict(data: dict[str, Any]) -> SemanticBlock:
    """Rebuild one semantic block, rejecting unknown kinds instead of losing data silently."""
    if type(data) is not dict:
        raise BookDocumentError(
            "Book block must be a built-in mapping",
            code=BookDocumentErrorCode.INVALID_FIELD,
        )
    # Reject impossible payload width from O(1) built-in dict metadata before
    # materializing keys.  One extra slot is reserved for the wire-only "kind".
    if len(data) > _MAX_BOOK_BLOCK_FIELDS:
        raise BookDocumentError(
            "Book block contains too many fields",
            code=BookDocumentErrorCode.UNKNOWN_FIELD,
        )
    # Inspect exact built-in key objects before dictionary/set operations can
    # invoke attacker-controlled __hash__/__eq__ hooks from exotic key types.
    keys = tuple(data)
    if any(type(key) is not str for key in keys):
        raise BookDocumentError(
            "Book block field names must be strings",
            code=BookDocumentErrorCode.UNKNOWN_FIELD,
        )
    kind = data.get("kind")
    if type(kind) is not str:
        raise BookDocumentError(
            "Unsupported BookDocument block kind",
            code=BookDocumentErrorCode.UNSUPPORTED_BLOCK_KIND,
        )
    cls = _BLOCK_TYPES.get(kind)
    if cls is None:
        raise BookDocumentError(
            f"Unsupported BookDocument block kind: {kind!r}",
            code=BookDocumentErrorCode.UNSUPPORTED_BLOCK_KIND,
        )
    allowed = set(cls.__dataclass_fields__)
    unknown = sorted(key for key in keys if key != "kind" and key not in allowed)
    if unknown:
        raise BookDocumentError(
            f"Unsupported fields for {kind}: {', '.join(map(repr, unknown))}",
            code=BookDocumentErrorCode.UNKNOWN_FIELD,
        )
    payload = {key: data[key] for key in keys if key != "kind"}
    return cls(**payload)


@dataclass(slots=True)
class BookDocument:
    title: str
    blocks: list[SemanticBlock] = field(default_factory=list)
    language: str | None = None
    author: str | None = None
    source_name: str | None = None
    source_uri: str | None = None
    source_rights: str | None = None
    warnings: list[str] = field(default_factory=list)

    def __post_init__(self) -> None:
        self.title = _required_text(self.title, "Book title")
        self.language = _optional_text(self.language, "Book language")
        self.author = _optional_text(self.author, "Book author")
        self.source_name = _optional_text(self.source_name, "Book source_name")
        self.source_uri = _optional_text(self.source_uri, "Book source_uri")
        self.source_rights = _optional_text(self.source_rights, "Book source_rights")
        if type(self.blocks) is not list:
            raise BookDocumentError(
                "Book blocks must be a list of supported semantic blocks",
                code=BookDocumentErrorCode.INVALID_FIELD,
            )
        if len(self.blocks) > MAX_BOOK_DOCUMENT_BLOCKS:
            raise BookDocumentError(
                f"BookDocument supports at most {MAX_BOOK_DOCUMENT_BLOCKS} blocks",
                code=BookDocumentErrorCode.INVALID_FIELD,
            )
        if not all(type(block) in _SEMANTIC_BLOCK_TYPES for block in self.blocks):
            raise BookDocumentError(
                "Book blocks must be a list of supported semantic blocks",
                code=BookDocumentErrorCode.INVALID_FIELD,
            )
        # Semantic blocks are mutable for authoring. Initial construction must
        # enforce the same live-state validator already used by append()/extend()
        # so a block corrupted after its own __post_init__ cannot become part of
        # a canonical BookDocument and fail only later at export or resolution.
        total_text = _document_metadata_text_chars(
            title=self.title,
            language=self.language,
            author=self.author,
            source_name=self.source_name,
            source_uri=self.source_uri,
            source_rights=self.source_rights,
        )
        for block in self.blocks:
            total_text = _add_block_payload_text_chars(total_text, block.as_dict())
        _validate_warning_list(
            self.warnings,
            container_message="Book warnings must be a list of non-empty strings",
        )
        _add_document_text_chars(total_text, self.warnings)
        self.blocks = list(self.blocks)
        self.warnings = list(self.warnings)

    def append(self, block: SemanticBlock) -> SemanticBlock:
        # Mutation is allowed only from a valid live document. Do not let a new
        # block publication hide pre-existing metadata/container corruption.
        total_text = self._validate_export_state()
        if type(block) not in _SEMANTIC_BLOCK_TYPES:
            raise BookDocumentError(
                "Book block type is unsupported",
                code=BookDocumentErrorCode.UNSUPPORTED_BLOCK_KIND,
            )
        if len(self.blocks) >= MAX_BOOK_DOCUMENT_BLOCKS:
            raise BookDocumentError(
                f"BookDocument supports at most {MAX_BOOK_DOCUMENT_BLOCKS} blocks",
                code=BookDocumentErrorCode.INVALID_FIELD,
            )
        _add_block_payload_text_chars(total_text, block.as_dict())
        self.blocks.append(block)
        return block

    def extend(self, blocks: Iterable[SemanticBlock]) -> None:
        total_text = self._validate_export_state()
        remaining = MAX_BOOK_DOCUMENT_BLOCKS - len(self.blocks)
        additions = list(islice(iter(blocks), remaining + 1))
        if len(additions) > remaining:
            raise BookDocumentError(
                f"BookDocument supports at most {MAX_BOOK_DOCUMENT_BLOCKS} blocks",
                code=BookDocumentErrorCode.INVALID_FIELD,
            )
        if not all(type(block) in _SEMANTIC_BLOCK_TYPES for block in additions):
            raise BookDocumentError(
                "Book block type is unsupported",
                code=BookDocumentErrorCode.UNSUPPORTED_BLOCK_KIND,
            )
        for block in additions:
            total_text = _add_block_payload_text_chars(total_text, block.as_dict())
        self.blocks.extend(additions)

    def iter_kind(self, kind: type[SemanticBlock]) -> Iterator[SemanticBlock]:
        self._validate_export_state()
        if type(kind) is not type or kind not in _SEMANTIC_BLOCK_TYPES:
            raise BookDocumentError(
                "Book query kind must be a canonical semantic block type",
                code=BookDocumentErrorCode.UNSUPPORTED_BLOCK_KIND,
            )
        for block in self.blocks:
            if type(block) is kind:
                yield block

    def headings(self) -> list[Heading]:
        return list(self.iter_kind(Heading))

    def lists(self) -> list[ListBlock]:
        return list(self.iter_kind(ListBlock))

    def exercises(self) -> list[Exercise]:
        return list(self.iter_kind(Exercise))

    def validate_structure(self) -> list[str]:
        """Return bounded non-destructive semantic warnings for import reports."""
        # BookDocument and its blocks remain mutable for authoring. Reuse the
        # canonical live export-state validator before warning inspection so
        # malformed containers, metadata or block fields fail through the stable
        # BookDocumentError boundary rather than leaking raw Python exceptions.
        self._validate_export_state()
        warnings = list(self.warnings)
        source_count = len(warnings)
        total_warning_chars = sum(len(warning) for warning in warnings)

        def report(message: str) -> bool:
            nonlocal total_warning_chars
            total_warning_chars, complete = _append_bounded_structure_warning(
                warnings,
                message,
                source_count=source_count,
                total_chars=total_warning_chars,
            )
            return complete

        previous_level = 0
        seen_ids: set[str] = set()
        for index, block in enumerate(self.blocks):
            if block.block_id:
                if block.block_id in seen_ids:
                    if not report(
                        f"duplicate block_id {block.block_id!r} at block {index}"
                    ):
                        return warnings
                seen_ids.add(block.block_id)
            if isinstance(block, Heading):
                if previous_level and block.level > previous_level + 1:
                    if not report(
                        f"heading level jumps from {previous_level} to {block.level} at block {index}"
                    ):
                        return warnings
                previous_level = block.level
            if isinstance(block, Diagram) and not block.alt_text:
                if not report(f"diagram at block {index} has no alt_text"):
                    return warnings
        return warnings

    def _validate_export_state(self) -> int:
        title = _required_text(self.title, "Book title")
        language = _optional_text(self.language, "Book language")
        author = _optional_text(self.author, "Book author")
        source_name = _optional_text(self.source_name, "Book source_name")
        source_uri = _optional_text(self.source_uri, "Book source_uri")
        source_rights = _optional_text(self.source_rights, "Book source_rights")
        if type(self.blocks) is not list:
            raise BookDocumentError(
                "Book blocks must remain a list of supported semantic blocks",
                code=BookDocumentErrorCode.INVALID_FIELD,
            )
        if len(self.blocks) > MAX_BOOK_DOCUMENT_BLOCKS:
            raise BookDocumentError(
                f"BookDocument supports at most {MAX_BOOK_DOCUMENT_BLOCKS} blocks",
                code=BookDocumentErrorCode.INVALID_FIELD,
            )
        if not all(type(block) in _SEMANTIC_BLOCK_TYPES for block in self.blocks):
            raise BookDocumentError(
                "Book blocks must remain a list of supported semantic blocks",
                code=BookDocumentErrorCode.INVALID_FIELD,
            )
        _validate_warning_list(
            self.warnings,
            container_message="Book warnings must remain a list of non-empty strings",
        )
        total_text = _document_metadata_text_chars(
            title=title,
            language=language,
            author=author,
            source_name=source_name,
            source_uri=source_uri,
            source_rights=source_rights,
        )
        total_text = _add_document_text_chars(total_text, self.warnings)
        for block in self.blocks:
            total_text = _add_block_payload_text_chars(total_text, block.as_dict())
        return total_text

    def as_dict(self) -> dict[str, Any]:
        self._validate_export_state()
        payload: dict[str, Any] = {
            "schema_version": BOOK_DOCUMENT_SCHEMA_VERSION,
            "title": self.title,
            "language": self.language,
            "author": self.author,
            "source_name": self.source_name,
            "warnings": list(self.warnings),
            "blocks": [block.as_dict() for block in self.blocks],
        }
        # Preserve exact legacy v1 payload shape when richer provenance is absent.
        # Existing snapshots/import fixtures therefore do not change merely by
        # passing through a newer BookDocument implementation.
        if self.source_uri is not None:
            payload["source_uri"] = self.source_uri
        if self.source_rights is not None:
            payload["source_rights"] = self.source_rights
        return payload

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "BookDocument":
        """Loss-aware semantic round-trip entry point for future import/export adapters."""
        if type(data) is not dict:
            raise BookDocumentError(
                "BookDocument must be a built-in mapping",
                code=BookDocumentErrorCode.INVALID_FIELD,
            )
        if len(data) > MAX_BOOK_DOCUMENT_FIELDS:
            raise BookDocumentError(
                "BookDocument contains too many fields",
                code=BookDocumentErrorCode.UNKNOWN_FIELD,
            )
        keys = tuple(data)
        if any(type(key) is not str for key in keys):
            raise BookDocumentError(
                "BookDocument field names must be strings",
                code=BookDocumentErrorCode.UNKNOWN_FIELD,
            )
        raw_version = data.get("schema_version", 0)
        if type(raw_version) is not int or raw_version not in {
            0,
            BOOK_DOCUMENT_SCHEMA_VERSION,
        }:
            raise BookDocumentError(
                "Unsupported BookDocument schema_version",
                code=BookDocumentErrorCode.UNSUPPORTED_SCHEMA,
            )
        allowed = {
            "schema_version",
            "title",
            "language",
            "author",
            "source_name",
            "source_uri",
            "source_rights",
            "warnings",
            "blocks",
        }
        unknown = sorted(key for key in keys if key not in allowed)
        if unknown:
            raise BookDocumentError(
                f"Unsupported BookDocument fields: {', '.join(map(repr, unknown))}",
                code=BookDocumentErrorCode.UNKNOWN_FIELD,
            )
        raw_blocks = data.get("blocks", [])
        if type(raw_blocks) is not list:
            raise BookDocumentError(
                "BookDocument blocks must be a list",
                code=BookDocumentErrorCode.INVALID_FIELD,
            )
        if len(raw_blocks) > MAX_BOOK_DOCUMENT_BLOCKS:
            raise BookDocumentError(
                f"BookDocument supports at most {MAX_BOOK_DOCUMENT_BLOCKS} blocks",
                code=BookDocumentErrorCode.INVALID_FIELD,
            )
        warnings = data.get("warnings", [])
        _validate_warning_list(
            warnings,
            container_message="BookDocument warnings must be a list of non-empty strings",
        )

        # Validate metadata before walking the block list. Direct/persisted
        # callers therefore cannot hide an invalid or oversized document root
        # behind expensive semantic block materialization.
        title = _required_text(data.get("title", ""), "Book title")
        language = _optional_text(data.get("language"), "Book language")
        author = _optional_text(data.get("author"), "Book author")
        source_name = _optional_text(data.get("source_name"), "Book source_name")
        source_uri = _optional_text(data.get("source_uri"), "Book source_uri")
        source_rights = _optional_text(data.get("source_rights"), "Book source_rights")
        total_text = _document_metadata_text_chars(
            title=title,
            language=language,
            author=author,
            source_name=source_name,
            source_uri=source_uri,
            source_rights=source_rights,
        )
        total_text = _add_document_text_chars(total_text, warnings)

        blocks: list[SemanticBlock] = []
        for item in raw_blocks:
            block = block_from_dict(item)
            total_text = _add_block_payload_text_chars(total_text, block.as_dict())
            blocks.append(block)

        return cls(
            title=title,
            language=language,
            author=author,
            source_name=source_name,
            source_uri=source_uri,
            source_rights=source_rights,
            warnings=list(warnings),
            blocks=blocks,
        )
