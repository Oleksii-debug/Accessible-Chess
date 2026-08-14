from __future__ import annotations

"""Presentation-neutral semantic chess-book model.

BookDocument is deliberately independent from DOCX, HTML, PGN and ChessBase.
Importers convert source material into these semantic blocks; accessible UIs and
exporters consume the blocks without needing to understand the source format.
"""

from dataclasses import dataclass, field
from typing import Any, Iterable, Iterator


@dataclass(slots=True)
class BookBlock:
    block_id: str | None = None
    source_anchor: str | None = None

    @property
    def kind(self) -> str:
        return self.__class__.__name__

    def as_dict(self) -> dict[str, Any]:
        data = {"kind": self.kind}
        for name in self.__dataclass_fields__:
            value = getattr(self, name)
            if value is not None and value != []:
                data[name] = value
        return data


@dataclass(slots=True)
class Heading(BookBlock):
    text: str = ""
    level: int = 1

    def __post_init__(self) -> None:
        if not 1 <= int(self.level) <= 6:
            raise ValueError("Heading level must be between 1 and 6")
        if not self.text.strip():
            raise ValueError("Heading text must not be empty")


@dataclass(slots=True)
class Paragraph(BookBlock):
    text: str = ""

    def __post_init__(self) -> None:
        if not self.text.strip():
            raise ValueError("Paragraph text must not be empty")


@dataclass(slots=True)
class Position(BookBlock):
    fen: str = ""
    caption: str | None = None
    side_to_move_note: str | None = None

    def __post_init__(self) -> None:
        parts = self.fen.strip().split()
        if len(parts) < 4:
            raise ValueError("Position FEN must include placement, turn, castling and en-passant fields")


@dataclass(slots=True)
class Diagram(Position):
    alt_text: str | None = None


@dataclass(slots=True)
class Game(BookBlock):
    pgn: str = ""
    title: str | None = None
    game_id: int | None = None

    def __post_init__(self) -> None:
        if not self.pgn.strip() and self.game_id is None:
            raise ValueError("Game requires PGN text or a game_id reference")


@dataclass(slots=True)
class VariationTree(BookBlock):
    root_fen: str = ""
    pgn: str = ""
    title: str | None = None

    def __post_init__(self) -> None:
        if not self.root_fen.strip():
            raise ValueError("VariationTree requires root_fen")
        if not self.pgn.strip():
            raise ValueError("VariationTree requires PGN variation text")


@dataclass(slots=True)
class Exercise(BookBlock):
    fen: str = ""
    prompt: str = ""
    solution_pgn: str | None = None
    answer_text: str | None = None
    difficulty: str | None = None

    def __post_init__(self) -> None:
        if len(self.fen.strip().split()) < 4:
            raise ValueError("Exercise FEN is invalid or incomplete")
        if not self.prompt.strip():
            raise ValueError("Exercise prompt must not be empty")
        if not (self.solution_pgn or self.answer_text):
            raise ValueError("Exercise requires solution_pgn or answer_text")


@dataclass(slots=True)
class Note(BookBlock):
    text: str = ""
    note_type: str = "note"

    def __post_init__(self) -> None:
        if not self.text.strip():
            raise ValueError("Note text must not be empty")


SemanticBlock = Heading | Paragraph | Position | Diagram | Game | VariationTree | Exercise | Note


@dataclass(slots=True)
class BookDocument:
    title: str
    blocks: list[SemanticBlock] = field(default_factory=list)
    language: str | None = None
    author: str | None = None
    source_name: str | None = None
    warnings: list[str] = field(default_factory=list)

    def __post_init__(self) -> None:
        if not self.title.strip():
            raise ValueError("Book title must not be empty")

    def append(self, block: SemanticBlock) -> SemanticBlock:
        self.blocks.append(block)
        return block

    def extend(self, blocks: Iterable[SemanticBlock]) -> None:
        self.blocks.extend(blocks)

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

    def as_dict(self) -> dict[str, Any]:
        return {
            "title": self.title,
            "language": self.language,
            "author": self.author,
            "source_name": self.source_name,
            "warnings": list(self.warnings),
            "blocks": [block.as_dict() for block in self.blocks],
        }
