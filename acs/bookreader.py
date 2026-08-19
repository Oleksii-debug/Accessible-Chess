from __future__ import annotations

"""Presentation-neutral accessible navigation over BookDocument.

The reader deliberately exposes semantic locations rather than UI key bindings.
NVDA/WebView clients can bind their remappable action IDs to these operations
without the data layer owning shortcuts.
"""

from dataclasses import dataclass

from .bookdocument import (
    BookDocument,
    BookDocumentError,
    BookDocumentErrorCode,
    Diagram,
    Exercise,
    Game,
    Heading,
    Position,
    VariationTree,
)


@dataclass(frozen=True, slots=True)
class ReadingLocation:
    index: int
    kind: str
    block_id: str | None
    source_anchor: str | None
    heading_path: tuple[str, ...]
    position_fen: str | None = None
    side_to_move: str | None = None


class BookReader:
    """Stable semantic cursor with return points and structure navigation."""

    def __init__(self, document: BookDocument):
        if not isinstance(document, BookDocument):
            raise BookDocumentError(
                "BookReader requires a BookDocument",
                code=BookDocumentErrorCode.INVALID_FIELD,
            )
        self._document = BookDocument.from_dict(document.as_dict())
        self._blocks = tuple(self._document.blocks)
        self._index = 0 if self._blocks else -1
        self._return_points: dict[str, int] = {}

    @property
    def document(self) -> BookDocument:
        """Return a detached copy of the reader's semantic snapshot."""

        return BookDocument.from_dict(self._document.as_dict())

    @property
    def index(self) -> int:
        return self._index

    def _require_content(self) -> None:
        if not self._blocks:
            raise LookupError("BookDocument has no readable blocks")

    def _heading_path(self, index: int) -> tuple[str, ...]:
        levels: list[str | None] = [None] * 6
        for block in self._blocks[: index + 1]:
            if isinstance(block, Heading):
                level = block.level - 1
                levels[level] = block.text
                for deeper in range(level + 1, 6):
                    levels[deeper] = None
        return tuple(item for item in levels if item is not None)

    def location(self) -> ReadingLocation:
        self._require_content()
        block = self._blocks[self._index]
        fen = None
        if isinstance(block, (Position, Diagram, Exercise)):
            fen = block.fen
        elif isinstance(block, VariationTree):
            fen = block.root_fen
        side = None
        if fen:
            fields = fen.split()
            if len(fields) >= 2 and fields[1] in {"w", "b"}:
                side = "white" if fields[1] == "w" else "black"
        return ReadingLocation(
            index=self._index,
            kind=block.kind,
            block_id=block.block_id,
            source_anchor=block.source_anchor,
            heading_path=self._heading_path(self._index),
            position_fen=fen,
            side_to_move=side,
        )

    def go_to(self, index: int) -> ReadingLocation:
        self._require_content()
        if not isinstance(index, int) or isinstance(index, bool):
            raise TypeError("Book reading index must be an integer")
        if not 0 <= index < len(self._blocks):
            raise IndexError("Book reading index is outside the document")
        self._index = index
        return self.location()

    def next_block(self) -> ReadingLocation:
        self._require_content()
        if self._index >= len(self._blocks) - 1:
            raise LookupError("End of book")
        return self.go_to(self._index + 1)

    def previous_block(self) -> ReadingLocation:
        self._require_content()
        if self._index <= 0:
            raise LookupError("Beginning of book")
        return self.go_to(self._index - 1)

    def _next_matching(self, predicate, *, direction: int) -> ReadingLocation:
        self._require_content()
        cursor = self._index + direction
        while 0 <= cursor < len(self._blocks):
            if predicate(self._blocks[cursor]):
                return self.go_to(cursor)
            cursor += direction
        raise LookupError("No matching semantic block in that direction")

    def next_heading(self) -> ReadingLocation:
        return self._next_matching(lambda block: isinstance(block, Heading), direction=1)

    def previous_heading(self) -> ReadingLocation:
        return self._next_matching(lambda block: isinstance(block, Heading), direction=-1)

    def next_position(self) -> ReadingLocation:
        return self._next_matching(
            lambda block: isinstance(block, (Position, Diagram, Exercise, VariationTree)), direction=1
        )

    def next_game(self) -> ReadingLocation:
        return self._next_matching(lambda block: isinstance(block, Game), direction=1)

    def save_return_point(self, name: str = "default") -> ReadingLocation:
        self._require_content()
        if not isinstance(name, str) or not name.strip():
            raise ValueError("Return point name must not be empty")
        self._return_points[name.strip()] = self._index
        return self.location()

    def restore_return_point(self, name: str = "default") -> ReadingLocation:
        if not isinstance(name, str) or not name.strip():
            raise ValueError("Return point name must not be empty")
        normalized = name.strip()
        if normalized not in self._return_points:
            raise LookupError(f"Unknown return point: {name}")
        return self.go_to(self._return_points[normalized])
