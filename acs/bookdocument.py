from __future__ import annotations

"""Presentation-neutral semantic chess-book model.

BookDocument is deliberately independent from DOCX, HTML, PGN and ChessBase.
Importers convert source material into these semantic blocks; accessible UIs and
exporters consume the blocks without needing to understand the source format.
"""

from dataclasses import dataclass, field
from enum import Enum
import re
from typing import Any, Iterable, Iterator


BOOK_DOCUMENT_SCHEMA_VERSION = 1


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


_FEN_PIECES = frozenset("PNBRQKpnbrqk")
_FEN_CASTLING = frozenset("KQkq")
_FEN_EN_PASSANT_RE = re.compile(r"^[a-h][36]$")


def _fen_text(value: object, field_name: str) -> str:
    text = _required_text(value, field_name).strip()
    fields = text.split()
    if len(fields) not in {4, 6}:
        raise BookDocumentError(
            f"{field_name} must contain exactly 4 or 6 FEN fields",
            code=BookDocumentErrorCode.INVALID_FIELD,
        )
    board, turn, castling, en_passant = fields[:4]
    ranks = board.split("/")
    if len(ranks) != 8:
        raise BookDocumentError(
            f"{field_name} board must contain exactly 8 ranks",
            code=BookDocumentErrorCode.INVALID_FIELD,
        )
    for rank in ranks:
        if any(left.isdigit() and right.isdigit() for left, right in zip(rank, rank[1:])):
            raise BookDocumentError(
                f"{field_name} empty-square runs must use one canonical digit",
                code=BookDocumentErrorCode.INVALID_FIELD,
            )
        squares = 0
        for token in rank:
            if token in "12345678":
                squares += int(token)
            elif token in _FEN_PIECES:
                squares += 1
            else:
                raise BookDocumentError(
                    f"{field_name} contains an invalid board token",
                    code=BookDocumentErrorCode.INVALID_FIELD,
                )
        if squares != 8:
            raise BookDocumentError(
                f"{field_name} ranks must expand to exactly 8 squares",
                code=BookDocumentErrorCode.INVALID_FIELD,
            )
    if turn not in {"w", "b"}:
        raise BookDocumentError(
            f"{field_name} turn must be 'w' or 'b'",
            code=BookDocumentErrorCode.INVALID_FIELD,
        )
    if castling != "-" and (
        not castling
        or any(symbol not in _FEN_CASTLING for symbol in castling)
        or len(set(castling)) != len(castling)
        or castling != "".join(symbol for symbol in "KQkq" if symbol in castling)
    ):
        raise BookDocumentError(
            f"{field_name} castling rights are invalid",
            code=BookDocumentErrorCode.INVALID_FIELD,
        )
    if en_passant != "-":
        expected_rank = "6" if turn == "w" else "3"
        if (
            _FEN_EN_PASSANT_RE.fullmatch(en_passant) is None
            or en_passant[1] != expected_rank
        ):
            raise BookDocumentError(
                f"{field_name} en-passant square is invalid for the side to move",
                code=BookDocumentErrorCode.INVALID_FIELD,
            )
    if len(fields) == 6:
        halfmove, fullmove = fields[4:]
        if (
            not halfmove.isascii()
            or not halfmove.isdigit()
            or (len(halfmove) > 1 and halfmove.startswith("0"))
        ):
            raise BookDocumentError(
                f"{field_name} halfmove clock must be canonical decimal text",
                code=BookDocumentErrorCode.INVALID_FIELD,
            )
        if (
            not fullmove.isascii()
            or not fullmove.isdigit()
            or fullmove.startswith("0")
        ):
            raise BookDocumentError(
                f"{field_name} fullmove number must be canonical positive decimal text",
                code=BookDocumentErrorCode.INVALID_FIELD,
            )
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

    def __post_init__(self) -> None:
        self.title = _required_text(self.title, "Book title")
        self.language = _optional_text(self.language, "Book language")
        self.author = _optional_text(self.author, "Book author")
        self.source_name = _optional_text(self.source_name, "Book source_name")
        if not isinstance(self.blocks, list) or not all(
            isinstance(block, _SEMANTIC_BLOCK_TYPES) for block in self.blocks
        ):
            raise BookDocumentError(
                "Book blocks must be a list of supported semantic blocks",
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
        self.blocks = list(self.blocks)
        self.warnings = list(self.warnings)

    def append(self, block: SemanticBlock) -> SemanticBlock:
        if not isinstance(block, _SEMANTIC_BLOCK_TYPES):
            raise BookDocumentError(
                "Book block type is unsupported",
                code=BookDocumentErrorCode.UNSUPPORTED_BLOCK_KIND,
            )
        block.as_dict()
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
        if type(self.blocks) is not list or not all(
            isinstance(block, _SEMANTIC_BLOCK_TYPES) for block in self.blocks
        ):
            raise BookDocumentError(
                "Book blocks must remain a list of supported semantic blocks",
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
            or raw_version not in {0, BOOK_DOCUMENT_SCHEMA_VERSION}
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
        warnings = data.get("warnings", [])
        if not isinstance(warnings, list) or not all(
            isinstance(item, str) and item.strip() for item in warnings
        ):
            raise BookDocumentError(
                "BookDocument warnings must be a list of non-empty strings",
                code=BookDocumentErrorCode.INVALID_FIELD,
            )
        return cls(
            title=data.get("title", ""),
            language=data.get("language"),
            author=data.get("author"),
            source_name=data.get("source_name"),
            warnings=list(warnings),
            blocks=[block_from_dict(item) for item in raw_blocks],
        )
