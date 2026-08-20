from __future__ import annotations

"""Presentation-neutral semantic chess-book model.

BookDocument is deliberately independent from DOCX, HTML, PGN and ChessBase.
Importers convert source material into these semantic blocks; accessible UIs and
exporters consume the blocks without needing to understand the source format.
"""

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Iterable, Iterator

from .chesscore import canonical_fen
from .gametree import GameTreeContractError, parse_games
from .gametree_legality import (
    GameTreeLegalityContractError,
    link_game_legality,
)


BOOK_DOCUMENT_SCHEMA_VERSION = 2
MAX_BOOK_BLOCKS = 50_000
MAX_BOOK_WARNINGS = 10_000


class BookDocumentErrorCode(str, Enum):
    INVALID_FIELD = "invalid_field"
    INVALID_CHESS_CONTENT = "invalid_chess_content"
    UNKNOWN_FIELD = "unknown_field"
    UNSUPPORTED_SCHEMA = "unsupported_schema"
    UNSUPPORTED_BLOCK_KIND = "unsupported_block_kind"


class BookDocumentError(ValueError):
    """Stable failure for the presentation-neutral semantic book contract."""

    def __init__(self, message: str, *, code: BookDocumentErrorCode) -> None:
        super().__init__(message)
        self.code = BookDocumentErrorCode(code)


def _required_text(value: object, field_name: str) -> str:
    if not isinstance(value, str) or not value.strip():
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
    text = _required_text(value, field_name).strip()
    try:
        return canonical_fen(text, allow_four_fields=True)
    except (TypeError, ValueError) as exc:
        raise BookDocumentError(
            f"{field_name} is not a canonical playable FEN: {exc}",
            code=BookDocumentErrorCode.INVALID_FIELD,
        ) from exc


def _full_fen(fen: str) -> str:
    fields = fen.split()
    return fen if len(fields) == 6 else f"{fen} 0 1"


def _validate_pgn_text(
    value: str,
    field_name: str,
    *,
    root_fen: str | None = None,
    require_mainline_move: bool = False,
) -> None:
    """Validate one complete, lossless and legal GameTree without rewriting it."""

    try:
        games = parse_games(value)
        if len(games) != 1:
            raise ValueError("exactly one PGN game is required")
        game = games[0]
        if game.recovery_issues:
            raise ValueError("PGN contains unresolved recovery issues")
        if require_mainline_move and not game.line.moves:
            raise ValueError("PGN requires at least one main-line move")

        if root_fen is not None:
            expected_fen = _full_fen(root_fen)
            supplied_setup = game.tags.get("SetUp")
            supplied_fen = game.tags.get("FEN")
            if supplied_setup not in {None, "1"}:
                raise ValueError("embedded PGN SetUp conflicts with the block position")
            if supplied_fen is not None and supplied_setup != "1":
                raise ValueError("embedded PGN FEN requires SetUp \"1\"")
            if supplied_fen is not None:
                supplied_fen = canonical_fen(supplied_fen)
                if supplied_fen != expected_fen:
                    raise ValueError("embedded PGN FEN conflicts with the block position")
            game.tags = dict(game.tags)
            game.tags["SetUp"] = "1"
            game.tags["FEN"] = expected_fen

        report = link_game_legality(game)
        if (
            not report.all_moves_legal
            or report.has_errors
            or report.recovery_issue_codes
        ):
            raise ValueError("PGN contains illegal or unverifiable chess content")
    except (
        GameTreeContractError,
        GameTreeLegalityContractError,
        TypeError,
        ValueError,
    ) as exc:
        raise BookDocumentError(
            f"{field_name} is not one lossless legal PGN game: {exc}",
            code=BookDocumentErrorCode.INVALID_CHESS_CONTENT,
        ) from exc


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
            if value is not None and value != []:
                data[name] = value
        # Dataclass instances are intentionally mutable for authoring. Rebuild
        # the exact current payload before export so post-construction mutation
        # cannot bypass the semantic validators and leak corrupt wire data.
        # Export the rebuilt payload rather than the mutable source payload so
        # constructor-normalized identifiers and FEN remain canonical and the
        # schema-v1 wire value is stable across import/export round trips.
        rebuilt = block_from_dict(dict(data))
        canonical = {"kind": rebuilt.kind}
        for name in rebuilt.__dataclass_fields__:
            value = getattr(rebuilt, name)
            if value is not None and value != []:
                canonical[name] = value
        return canonical


@dataclass(slots=True)
class Heading(BookBlock):
    text: str = ""
    level: int = 1

    def __post_init__(self) -> None:
        BookBlock.__post_init__(self)
        self.text = _required_text(self.text, "Heading text")
        if (
            not isinstance(self.level, int)
            or isinstance(self.level, bool)
            or not 1 <= self.level <= 6
        ):
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
        if not isinstance(self.pgn, str):
            raise BookDocumentError(
                "Game PGN must be text",
                code=BookDocumentErrorCode.INVALID_FIELD,
            )
        self.title = _optional_text(self.title, "Game title")
        if self.game_id is not None and (
            not isinstance(self.game_id, int)
            or isinstance(self.game_id, bool)
            or self.game_id < 0
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
        if self.pgn.strip():
            _validate_pgn_text(self.pgn, "Game PGN")


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
        _validate_pgn_text(
            self.pgn,
            "VariationTree PGN",
            root_fen=self.root_fen,
            require_mainline_move=True,
        )


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
        if self.solution_pgn is not None:
            _validate_pgn_text(
                self.solution_pgn,
                "Exercise solution_pgn",
                root_fen=self.fen,
                require_mainline_move=True,
            )


@dataclass(slots=True)
class Note(BookBlock):
    text: str = ""
    note_type: str = "note"

    def __post_init__(self) -> None:
        BookBlock.__post_init__(self)
        self.text = _required_text(self.text, "Note text")
        self.note_type = _required_text(self.note_type, "Note note_type")


SemanticBlock = Heading | Paragraph | Position | Diagram | Game | VariationTree | Exercise | Note
_BLOCK_TYPES = {
    "Heading": Heading,
    "Paragraph": Paragraph,
    "Position": Position,
    "Diagram": Diagram,
    "Game": Game,
    "VariationTree": VariationTree,
    "Exercise": Exercise,
    "Note": Note,
}
_SEMANTIC_BLOCK_TYPES = tuple(_BLOCK_TYPES.values())


def block_from_dict(data: dict[str, Any]) -> SemanticBlock:
    """Rebuild one semantic block, rejecting unknown kinds instead of losing data silently."""
    if not isinstance(data, dict):
        raise BookDocumentError(
            "Book block must be a mapping",
            code=BookDocumentErrorCode.INVALID_FIELD,
        )
    kind = data.get("kind")
    if not isinstance(kind, str):
        raise BookDocumentError(
            f"Unsupported BookDocument block kind: {kind!r}",
            code=BookDocumentErrorCode.UNSUPPORTED_BLOCK_KIND,
        )
    cls = _BLOCK_TYPES.get(kind)
    if cls is None:
        raise BookDocumentError(
            f"Unsupported BookDocument block kind: {kind!r}",
            code=BookDocumentErrorCode.UNSUPPORTED_BLOCK_KIND,
        )
    payload = {key: value for key, value in data.items() if key != "kind"}
    allowed = set(cls.__dataclass_fields__)
    unknown = sorted(set(payload) - allowed, key=repr)
    if unknown:
        raise BookDocumentError(
            f"Unsupported fields for {kind}: {', '.join(map(repr, unknown))}",
            code=BookDocumentErrorCode.UNKNOWN_FIELD,
        )
    return cls(**payload)


@dataclass(slots=True)
class BookDocument:
    title: str
    blocks: list[SemanticBlock] = field(default_factory=list)
    language: str | None = None
    author: str | None = None
    source_name: str | None = None
    warnings: list[str] = field(default_factory=list)
    book_id: str | None = None

    def __post_init__(self) -> None:
        self.title = _required_text(self.title, "Book title")
        self.language = _optional_text(self.language, "Book language")
        self.author = _optional_text(self.author, "Book author")
        self.source_name = _optional_text(self.source_name, "Book source_name")
        self.book_id = _optional_identifier(self.book_id, "Book book_id")
        if not isinstance(self.blocks, list) or not all(
            isinstance(block, _SEMANTIC_BLOCK_TYPES) for block in self.blocks
        ):
            raise BookDocumentError(
                "Book blocks must be a list of supported semantic blocks",
                code=BookDocumentErrorCode.INVALID_FIELD,
            )
        if len(self.blocks) > MAX_BOOK_BLOCKS:
            raise BookDocumentError(
                "Book contains too many semantic blocks",
                code=BookDocumentErrorCode.INVALID_FIELD,
            )
        if not isinstance(self.warnings, list) or not all(
            isinstance(warning, str) and warning.strip()
            for warning in self.warnings
        ):
            raise BookDocumentError(
                "Book warnings must be a list of non-empty strings",
                code=BookDocumentErrorCode.INVALID_FIELD,
            )
        if len(self.warnings) > MAX_BOOK_WARNINGS:
            raise BookDocumentError(
                "Book contains too many warnings",
                code=BookDocumentErrorCode.INVALID_FIELD,
            )
        self.blocks = list(self.blocks)
        self.warnings = list(self.warnings)

    def append(self, block: SemanticBlock) -> SemanticBlock:
        if not isinstance(block, _SEMANTIC_BLOCK_TYPES):
            raise BookDocumentError(
                "Book block type is unsupported",
                code=BookDocumentErrorCode.UNSUPPORTED_BLOCK_KIND,
            )
        block.as_dict()
        if len(self.blocks) >= MAX_BOOK_BLOCKS:
            raise BookDocumentError(
                "Book contains too many semantic blocks",
                code=BookDocumentErrorCode.INVALID_FIELD,
            )
        self.blocks.append(block)
        return block

    def extend(self, blocks: Iterable[SemanticBlock]) -> None:
        additions = list(blocks)
        if not all(isinstance(block, _SEMANTIC_BLOCK_TYPES) for block in additions):
            raise BookDocumentError(
                "Book block type is unsupported",
                code=BookDocumentErrorCode.UNSUPPORTED_BLOCK_KIND,
            )
        for block in additions:
            block.as_dict()
        if len(self.blocks) + len(additions) > MAX_BOOK_BLOCKS:
            raise BookDocumentError(
                "Book contains too many semantic blocks",
                code=BookDocumentErrorCode.INVALID_FIELD,
            )
        self.blocks.extend(additions)

    def iter_kind(self, kind: type[SemanticBlock]) -> Iterator[SemanticBlock]:
        for block in self.blocks:
            if isinstance(block, kind):
                yield block

    def headings(self) -> list[Heading]:
        return [block for block in self.blocks if isinstance(block, Heading)]

    def exercises(self) -> list[Exercise]:
        return [block for block in self.blocks if isinstance(block, Exercise)]

    def validate_structure(self) -> list[str]:
        """Return non-destructive semantic warnings suitable for import reports."""
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
        _optional_identifier(self.book_id, "Book book_id")
        if type(self.blocks) is not list or not all(
            isinstance(block, _SEMANTIC_BLOCK_TYPES) for block in self.blocks
        ):
            raise BookDocumentError(
                "Book blocks must remain a list of supported semantic blocks",
                code=BookDocumentErrorCode.INVALID_FIELD,
            )
        if len(self.blocks) > MAX_BOOK_BLOCKS:
            raise BookDocumentError(
                "Book contains too many semantic blocks",
                code=BookDocumentErrorCode.INVALID_FIELD,
            )
        if type(self.warnings) is not list or not all(
            isinstance(warning, str) and warning.strip()
            for warning in self.warnings
        ):
            raise BookDocumentError(
                "Book warnings must remain a list of non-empty strings",
                code=BookDocumentErrorCode.INVALID_FIELD,
            )
        if len(self.warnings) > MAX_BOOK_WARNINGS:
            raise BookDocumentError(
                "Book contains too many warnings",
                code=BookDocumentErrorCode.INVALID_FIELD,
            )
        for block in self.blocks:
            block.as_dict()

    def as_dict(self) -> dict[str, Any]:
        self._validate_export_state()
        return {
            "schema_version": BOOK_DOCUMENT_SCHEMA_VERSION,
            "title": self.title,
            "language": self.language,
            "author": self.author,
            "source_name": self.source_name,
            "book_id": self.book_id,
            "warnings": list(self.warnings),
            "blocks": [block.as_dict() for block in self.blocks],
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "BookDocument":
        """Loss-aware semantic round-trip entry point for future import/export adapters."""
        if not isinstance(data, dict):
            raise BookDocumentError(
                "BookDocument must be a mapping",
                code=BookDocumentErrorCode.INVALID_FIELD,
            )
        raw_version = data.get("schema_version", 0)
        if (
            not isinstance(raw_version, int)
            or isinstance(raw_version, bool)
            or raw_version not in {0, 1, BOOK_DOCUMENT_SCHEMA_VERSION}
        ):
            raise BookDocumentError(
                f"Unsupported BookDocument schema_version: {raw_version!r}",
                code=BookDocumentErrorCode.UNSUPPORTED_SCHEMA,
            )
        allowed = {
            "schema_version",
            "title",
            "language",
            "author",
            "source_name",
            "book_id",
            "warnings",
            "blocks",
        }
        unknown = sorted(set(data) - allowed, key=repr)
        if unknown:
            raise BookDocumentError(
                f"Unsupported BookDocument fields: {', '.join(map(repr, unknown))}",
                code=BookDocumentErrorCode.UNKNOWN_FIELD,
            )
        raw_blocks = data.get("blocks", [])
        if not isinstance(raw_blocks, list):
            raise BookDocumentError(
                "BookDocument blocks must be a list",
                code=BookDocumentErrorCode.INVALID_FIELD,
            )
        if len(raw_blocks) > MAX_BOOK_BLOCKS:
            raise BookDocumentError(
                "BookDocument contains too many semantic blocks",
                code=BookDocumentErrorCode.INVALID_FIELD,
            )
        warnings = data.get("warnings", [])
        if not isinstance(warnings, list) or not all(
            isinstance(item, str) and item.strip() for item in warnings
        ):
            raise BookDocumentError(
                "BookDocument warnings must be a list of non-empty strings",
                code=BookDocumentErrorCode.INVALID_FIELD,
            )
        if len(warnings) > MAX_BOOK_WARNINGS:
            raise BookDocumentError(
                "BookDocument contains too many warnings",
                code=BookDocumentErrorCode.INVALID_FIELD,
            )
        return cls(
            title=data.get("title", ""),
            language=data.get("language"),
            author=data.get("author"),
            source_name=data.get("source_name"),
            book_id=data.get("book_id"),
            warnings=list(warnings),
            blocks=[block_from_dict(item) for item in raw_blocks],
        )
