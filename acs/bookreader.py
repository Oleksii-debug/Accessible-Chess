from __future__ import annotations

"""Presentation-neutral accessible navigation over BookDocument.

The reader deliberately exposes semantic locations rather than UI key bindings.
NVDA/WebView clients can bind their remappable action IDs to these operations
without the data layer owning shortcuts.
"""

from dataclasses import dataclass
import hashlib
import json
from typing import Mapping

from .bookdocument import (
    BookDocument,
    BookDocumentError,
    BookDocumentErrorCode,
    Diagram,
    Exercise,
    Game,
    Heading,
    Note,
    Paragraph,
    Position,
    VariationTree,
    block_from_dict,
)
from .gametree import parse_games
from .gametree_legality import link_game_legality


BOOK_READING_LOCATION_SCHEMA_VERSION = 1


@dataclass(frozen=True, slots=True)
class ReadingLocation:
    index: int
    kind: str
    block_id: str | None
    source_anchor: str | None
    heading_path: tuple[str, ...]
    position_fen: str | None = None
    side_to_move: str | None = None
    book_id: str = ""
    snapshot_id: str = ""
    chapter_index: int | None = None
    chapter_block_id: str | None = None
    chapter_source_anchor: str | None = None
    reading_offset: int = 0

    def as_dict(self) -> dict[str, object]:
        return {
            "schema_version": BOOK_READING_LOCATION_SCHEMA_VERSION,
            "book_id": self.book_id,
            "snapshot_id": self.snapshot_id,
            "index": self.index,
            "kind": self.kind,
            "block_id": self.block_id,
            "source_anchor": self.source_anchor,
            "heading_path": list(self.heading_path),
            "position_fen": self.position_fen,
            "side_to_move": self.side_to_move,
            "chapter_index": self.chapter_index,
            "chapter_block_id": self.chapter_block_id,
            "chapter_source_anchor": self.chapter_source_anchor,
            "reading_offset": self.reading_offset,
        }


@dataclass(frozen=True, slots=True)
class ChessBlockContext:
    origin: ReadingLocation
    block: ReadingLocation
    position_fen: str
    pgn: str | None = None
    game_id: int | None = None


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
        wire = json.dumps(
            self._document.as_dict(),
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
        self._snapshot_id = hashlib.sha256(wire).hexdigest()
        self._book_id = self._document.book_id or f"sha256:{self._snapshot_id}"
        self._reading_offset = 0
        self._return_points: dict[str, ReadingLocation] = {}
        self._embedded: ChessBlockContext | None = None

    @property
    def document(self) -> BookDocument:
        """Return a detached copy of the reader's semantic snapshot."""

        return BookDocument.from_dict(self._document.as_dict())

    @property
    def index(self) -> int:
        return self._index

    @property
    def book_id(self) -> str:
        return self._book_id

    @property
    def snapshot_id(self) -> str:
        return self._snapshot_id

    @property
    def title(self) -> str:
        return self._document.title

    @property
    def embedded_context(self) -> ChessBlockContext | None:
        return self._embedded

    def _require_content(self) -> None:
        if not self._blocks:
            raise LookupError("BookDocument has no readable blocks")

    def block_at(self, index: int | None = None):
        """Return one detached semantic block without copying the whole book."""

        self._require_content()
        target = self._index if index is None else index
        if type(target) is not int:
            raise TypeError("Book block index must be an integer")
        if not 0 <= target < len(self._blocks):
            raise IndexError("Book block index is outside the document")
        return block_from_dict(self._blocks[target].as_dict())

    def _heading_path(self, index: int) -> tuple[str, ...]:
        levels: list[str | None] = [None] * 6
        for block in self._blocks[: index + 1]:
            if isinstance(block, Heading):
                level = block.level - 1
                levels[level] = block.text
                for deeper in range(level + 1, 6):
                    levels[deeper] = None
        return tuple(item for item in levels if item is not None)

    def _chapter_heading(self, index: int) -> tuple[int, Heading] | None:
        for cursor in range(index, -1, -1):
            block = self._blocks[cursor]
            if isinstance(block, Heading):
                return cursor, block
        return None

    @staticmethod
    def _reading_text(block) -> str:
        if isinstance(block, (Heading, Paragraph, Note)):
            return block.text
        if isinstance(block, Exercise):
            return block.prompt
        if isinstance(block, (Position, Diagram)):
            return block.caption or ""
        if isinstance(block, (Game, VariationTree)):
            return block.title or ""
        return ""

    def _validate_reading_offset(self, index: int, offset: int) -> int:
        if type(offset) is not int:
            raise TypeError("Book reading offset must be an integer")
        maximum = len(self._reading_text(self._blocks[index]))
        if not 0 <= offset <= maximum:
            raise IndexError("Book reading offset is outside the semantic block")
        return offset

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
        chapter = self._chapter_heading(self._index)
        chapter_index = chapter[0] if chapter is not None else None
        chapter_block = chapter[1] if chapter is not None else None
        return ReadingLocation(
            index=self._index,
            kind=block.kind,
            block_id=block.block_id,
            source_anchor=block.source_anchor,
            heading_path=self._heading_path(self._index),
            position_fen=fen,
            side_to_move=side,
            book_id=self._book_id,
            snapshot_id=self._snapshot_id,
            chapter_index=chapter_index,
            chapter_block_id=(chapter_block.block_id if chapter_block else None),
            chapter_source_anchor=(
                chapter_block.source_anchor if chapter_block else None
            ),
            reading_offset=self._reading_offset,
        )

    def go_to(self, index: int, *, reading_offset: int = 0) -> ReadingLocation:
        self._require_content()
        if not isinstance(index, int) or isinstance(index, bool):
            raise TypeError("Book reading index must be an integer")
        if not 0 <= index < len(self._blocks):
            raise IndexError("Book reading index is outside the document")
        offset = self._validate_reading_offset(index, reading_offset)
        self._index = index
        self._reading_offset = offset
        return self.location()

    def set_reading_offset(self, offset: int) -> ReadingLocation:
        self._require_content()
        normalized = self._validate_reading_offset(self._index, offset)
        self._reading_offset = normalized
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
        location = self.location()
        self._return_points[name.strip()] = location
        return location

    def restore_return_point(self, name: str = "default") -> ReadingLocation:
        if not isinstance(name, str) or not name.strip():
            raise ValueError("Return point name must not be empty")
        normalized = name.strip()
        if normalized not in self._return_points:
            raise LookupError(f"Unknown return point: {name}")
        return self.restore_location(self._return_points[normalized])

    def restore_location(
        self,
        location: ReadingLocation | Mapping[str, object],
    ) -> ReadingLocation:
        """Restore one exact source context without cross-book/index fallback."""

        if isinstance(location, Mapping):
            location = self._location_from_dict(location)
        if not isinstance(location, ReadingLocation):
            raise TypeError("Book reading location must be ReadingLocation or a mapping")
        if location.book_id != self._book_id or location.snapshot_id != self._snapshot_id:
            raise LookupError("Book reading location belongs to a different snapshot")
        if not 0 <= location.index < len(self._blocks):
            raise LookupError("Book reading location is outside this snapshot")
        block = self._blocks[location.index]
        if (
            block.kind != location.kind
            or block.block_id != location.block_id
            or block.source_anchor != location.source_anchor
            or self._heading_path(location.index) != location.heading_path
        ):
            raise LookupError("Book reading location no longer identifies the exact block")
        previous_index, previous_offset = self._index, self._reading_offset
        try:
            expected = self.go_to(
                location.index,
                reading_offset=location.reading_offset,
            )
        finally:
            self._index = previous_index
            self._reading_offset = previous_offset
        if expected != location:
            raise LookupError("Book reading location metadata does not match the snapshot")
        return self.go_to(location.index, reading_offset=location.reading_offset)

    @staticmethod
    def _location_from_dict(payload: Mapping[str, object]) -> ReadingLocation:
        data = dict(payload)
        expected = {
            "schema_version",
            "book_id",
            "snapshot_id",
            "index",
            "kind",
            "block_id",
            "source_anchor",
            "heading_path",
            "position_fen",
            "side_to_move",
            "chapter_index",
            "chapter_block_id",
            "chapter_source_anchor",
            "reading_offset",
        }
        if (
            set(data) != expected
            or type(data.get("schema_version")) is not int
            or data.get("schema_version") != BOOK_READING_LOCATION_SCHEMA_VERSION
        ):
            raise ValueError("Book reading location schema is unsupported or incomplete")
        text_fields = ("book_id", "snapshot_id", "kind")
        if any(type(data[name]) is not str or not data[name] for name in text_fields):
            raise ValueError("Book reading location identity fields must be text")
        for name in (
            "block_id",
            "source_anchor",
            "position_fen",
            "side_to_move",
            "chapter_block_id",
            "chapter_source_anchor",
        ):
            if data[name] is not None and type(data[name]) is not str:
                raise ValueError(f"Book reading location {name} must be text or None")
        if type(data["heading_path"]) is not list or any(
            type(item) is not str for item in data["heading_path"]
        ):
            raise ValueError("Book reading location heading_path must be a text list")
        for name in ("index", "reading_offset"):
            if type(data[name]) is not int or data[name] < 0:
                raise ValueError(f"Book reading location {name} must be non-negative")
        if data["chapter_index"] is not None and (
            type(data["chapter_index"]) is not int or data["chapter_index"] < 0
        ):
            raise ValueError("Book reading location chapter_index must be non-negative or None")
        return ReadingLocation(
            index=data["index"],
            kind=data["kind"],
            block_id=data["block_id"],
            source_anchor=data["source_anchor"],
            heading_path=tuple(data["heading_path"]),
            position_fen=data["position_fen"],
            side_to_move=data["side_to_move"],
            book_id=data["book_id"],
            snapshot_id=data["snapshot_id"],
            chapter_index=data["chapter_index"],
            chapter_block_id=data["chapter_block_id"],
            chapter_source_anchor=data["chapter_source_anchor"],
            reading_offset=data["reading_offset"],
        )

    def open_chess_block(
        self,
        index: int | None = None,
        *,
        resolved_game_pgn: str | None = None,
    ) -> ChessBlockContext:
        """Open isolated chess content while retaining the exact text origin."""

        self._require_content()
        origin = self.location()
        target_index = self._index if index is None else index
        if type(target_index) is not int:
            raise TypeError("Book chess block index must be an integer")
        if not 0 <= target_index < len(self._blocks):
            raise IndexError("Book chess block index is outside the document")
        block = self._blocks[target_index]
        fen: str | None = None
        pgn: str | None = None
        game_id: int | None = None
        if isinstance(block, (Position, Diagram, Exercise)):
            fen = block.fen
            pgn = block.solution_pgn if isinstance(block, Exercise) else None
        elif isinstance(block, VariationTree):
            fen = block.root_fen
            pgn = block.pgn
        elif isinstance(block, Game):
            pgn = block.pgn or None
            game_id = block.game_id
            if pgn is None and resolved_game_pgn is not None:
                if type(resolved_game_pgn) is not str or not resolved_game_pgn.strip():
                    raise TypeError("resolved game PGN must be non-empty text")
                pgn = resolved_game_pgn
            if pgn:
                games = parse_games(pgn)
                if len(games) != 1 or games[0].recovery_issues:
                    raise ValueError("resolved game is not one lossless PGN game")
                report = link_game_legality(games[0])
                if (
                    not report.all_moves_legal
                    or report.has_errors
                    or report.recovery_issue_codes
                ):
                    raise ValueError("resolved game is not legal chess content")
                fen = report.start_fen
        if fen is None:
            raise LookupError("Semantic block has no self-contained chess position")
        previous_index, previous_offset = self._index, self._reading_offset
        try:
            block_location = self.go_to(target_index)
        finally:
            self._index = previous_index
            self._reading_offset = previous_offset
        context = ChessBlockContext(origin, block_location, fen, pgn, game_id)
        self._embedded = context
        return context

    def return_to_text(self) -> ReadingLocation:
        if self._embedded is None:
            raise LookupError("No embedded chess exploration is open")
        origin = self._embedded.origin
        restored = self.restore_location(origin)
        self._embedded = None
        return restored
