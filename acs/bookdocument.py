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


BOOK_DOCUMENT_SCHEMA_VERSION = 1
MAX_BOOK_DOCUMENT_BLOCKS = 50_000
MAX_BOOK_DOCUMENT_WARNINGS = 4_096
MAX_BOOK_DOCUMENT_FIELDS = 9


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
    # use built-in strings. Reject subclasses before calling strip() so hostile
    # Python-side ingress cannot execute custom text hooks inside validation.
    if type(value) is not str or not value.strip():
        raise BookDocumentError(
            f"{field_name} must be non-empty text",
            code=BookDocumentErrorCode.INVALID_FIELD,
        )
    return value


def _optional_text(value: object, field_name: str) -> str | None:
    if value is None:
        return None
    return _required_text(value, field_name)


def _optional_identifier(value: object, field_name: str) -> str | None:
    text = _optional_text(value, field_name)
    return None if text is None else text.strip()


def _fen_text(value: object, field_name: str) -> str:
    """Validate a Book FEN through the one canonical Board contract.

    Books may retain the historical compact four-field form or the full six-field
    form, but they do not own piece-placement, king, castling, en-passant or pawn
    legality rules. A rejected value never becomes a published semantic block.
    """

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
        self.block_id = _optional_identifier(self.block_id, "block_id")
        self.source_anchor = _optional_identifier(self.source_anchor, "source_anchor")

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
        validated_items: list[str] = []
        for item in self.items:
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

    def __post_init__(self) -> None:
        BookBlock.__post_init__(self)
        if type(self.pgn) is not str:
            raise BookDocumentError(
                "Game PGN must be text",
                code=BookDocumentErrorCode.INVALID_FIELD,
            )
        self.title = _optional_text(self.title, "Game title")
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
        self.pgn = _required_text(self.pgn, "VariationTree PGN")
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
        self.solution_pgn = _optional_text(
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
        for block in self.blocks:
            block.as_dict()
        if type(self.warnings) is not list:
            raise BookDocumentError(
                "Book warnings must be a list of non-empty strings",
                code=BookDocumentErrorCode.INVALID_FIELD,
            )
        if len(self.warnings) > MAX_BOOK_DOCUMENT_WARNINGS:
            raise BookDocumentError(
                f"BookDocument supports at most {MAX_BOOK_DOCUMENT_WARNINGS} warnings",
                code=BookDocumentErrorCode.INVALID_FIELD,
            )
        if not all(type(warning) is str and warning.strip() for warning in self.warnings):
            raise BookDocumentError(
                "Book warnings must be a list of non-empty strings",
                code=BookDocumentErrorCode.INVALID_FIELD,
            )
        self.blocks = list(self.blocks)
        self.warnings = list(self.warnings)

    def append(self, block: SemanticBlock) -> SemanticBlock:
        # Mutation is allowed only from a valid live document. Do not let a new
        # block publication hide pre-existing metadata/container corruption.
        self._validate_export_state()
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
        block.as_dict()
        self.blocks.append(block)
        return block

    def extend(self, blocks: Iterable[SemanticBlock]) -> None:
        self._validate_export_state()
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
            block.as_dict()
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
        """Return non-destructive semantic warnings suitable for import reports."""
        # BookDocument and its blocks remain mutable for authoring. Reuse the
        # canonical live export-state validator before warning inspection so
        # malformed containers, metadata or block fields fail through the stable
        # BookDocumentError boundary rather than leaking raw Python exceptions.
        self._validate_export_state()
        warnings = list(self.warnings)
        previous_level = 0
        seen_ids: set[str] = set()
        for index, block in enumerate(self.blocks):
            if block.block_id:
                if block.block_id in seen_ids:
                    warnings.append(f"duplicate block_id {block.block_id!r} at block {index}")
                seen_ids.add(block.block_id)
            if isinstance(block, Heading):
                if previous_level and block.level > previous_level + 1:
                    warnings.append(
                        f"heading level jumps from {previous_level} to {block.level} at block {index}"
                    )
                previous_level = block.level
            if isinstance(block, Diagram) and not block.alt_text:
                warnings.append(f"diagram at block {index} has no alt_text")
        return warnings

    def _validate_export_state(self) -> None:
        _required_text(self.title, "Book title")
        _optional_text(self.language, "Book language")
        _optional_text(self.author, "Book author")
        _optional_text(self.source_name, "Book source_name")
        _optional_text(self.source_uri, "Book source_uri")
        _optional_text(self.source_rights, "Book source_rights")
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
        if type(self.warnings) is not list:
            raise BookDocumentError(
                "Book warnings must remain a list of non-empty strings",
                code=BookDocumentErrorCode.INVALID_FIELD,
            )
        if len(self.warnings) > MAX_BOOK_DOCUMENT_WARNINGS:
            raise BookDocumentError(
                f"BookDocument supports at most {MAX_BOOK_DOCUMENT_WARNINGS} warnings",
                code=BookDocumentErrorCode.INVALID_FIELD,
            )
        if not all(type(warning) is str and warning.strip() for warning in self.warnings):
            raise BookDocumentError(
                "Book warnings must remain a list of non-empty strings",
                code=BookDocumentErrorCode.INVALID_FIELD,
            )
        for block in self.blocks:
            block.as_dict()

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
        if type(warnings) is not list:
            raise BookDocumentError(
                "BookDocument warnings must be a list of non-empty strings",
                code=BookDocumentErrorCode.INVALID_FIELD,
            )
        if len(warnings) > MAX_BOOK_DOCUMENT_WARNINGS:
            raise BookDocumentError(
                f"BookDocument supports at most {MAX_BOOK_DOCUMENT_WARNINGS} warnings",
                code=BookDocumentErrorCode.INVALID_FIELD,
            )
        if not all(type(item) is str and item.strip() for item in warnings):
            raise BookDocumentError(
                "BookDocument warnings must be a list of non-empty strings",
                code=BookDocumentErrorCode.INVALID_FIELD,
            )
        return cls(
            title=data.get("title", ""),
            language=data.get("language"),
            author=data.get("author"),
            source_name=data.get("source_name"),
            source_uri=data.get("source_uri"),
            source_rights=data.get("source_rights"),
            warnings=list(warnings),
            blocks=[block_from_dict(item) for item in raw_blocks],
        )
