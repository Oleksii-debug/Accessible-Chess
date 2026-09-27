from __future__ import annotations

"""Presentation-neutral index and stable navigation targets for BookDocument.

The data layer exposes semantic entries only. UI/NVDA clients decide how entries
are rendered and bind application action IDs to navigation; this module owns no
keyboard shortcuts and has no WebView/DOM dependency.
"""

from dataclasses import dataclass
from enum import Enum

from .bookdocument import (
    BookDocument,
    Diagram,
    Exercise,
    Game,
    Heading,
    ListBlock,
    Note,
    Paragraph,
    Position,
    VariationTree,
)


class BookEntryKind(str, Enum):
    HEADING = "heading"
    GAME = "game"
    POSITION = "position"
    EXERCISE = "exercise"
    VARIATION = "variation"
    NOTE = "note"
    PARAGRAPH = "paragraph"
    LIST = "list"


@dataclass(frozen=True, slots=True)
class BookTarget:
    """Stable semantic target plus the current linear fallback index."""

    key: str
    index: int
    block_id: str | None
    source_anchor: str | None


@dataclass(frozen=True, slots=True)
class BookIndexEntry:
    target: BookTarget
    kind: BookEntryKind
    label: str
    heading_path: tuple[str, ...]
    position_fen: str | None = None
    side_to_move: str | None = None
    heading_level: int | None = None


class AmbiguousBookTargetError(LookupError):
    pass


class BookIndex:
    """Immutable semantic index built from one validated BookDocument snapshot."""

    def __init__(self, document: BookDocument):
        if not isinstance(document, BookDocument):
            raise TypeError("document must be a BookDocument")
        # BookDocument blocks are authoring-mutable. Validate their exact current
        # semantic state before taking the immutable index snapshot so a caller
        # cannot mutate a previously-valid block and then publish stale/corrupt
        # index semantics.
        document.as_dict()
        self.document = document
        self._entries = tuple(self._build_entries())
        by_key: dict[str, list[BookIndexEntry]] = {}
        for entry in self._entries:
            by_key.setdefault(entry.target.key, []).append(entry)
        self._by_key = {key: tuple(entries) for key, entries in by_key.items()}

    @property
    def entries(self) -> tuple[BookIndexEntry, ...]:
        return self._entries

    def _target(self, index: int) -> BookTarget:
        block = self.document.blocks[index]
        if block.block_id:
            key = f"block:{block.block_id}"
        elif block.source_anchor:
            key = f"source:{block.source_anchor}"
        else:
            key = f"index:{index}"
        return BookTarget(key, index, block.block_id, block.source_anchor)

    @staticmethod
    def _position(block) -> tuple[str | None, str | None]:
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
        return fen, side

    @staticmethod
    def _kind_and_label(block) -> tuple[BookEntryKind, str]:
        if isinstance(block, Heading):
            return BookEntryKind.HEADING, block.text
        if isinstance(block, Exercise):
            return BookEntryKind.EXERCISE, block.prompt
        if isinstance(block, Diagram):
            return BookEntryKind.POSITION, block.caption or block.alt_text or "Diagram"
        if isinstance(block, Position):
            return BookEntryKind.POSITION, block.caption or "Position"
        if isinstance(block, VariationTree):
            return BookEntryKind.VARIATION, block.title or "Variation"
        if isinstance(block, Game):
            return BookEntryKind.GAME, block.title or (f"Game {block.game_id}" if block.game_id is not None else "Game")
        if isinstance(block, Note):
            return BookEntryKind.NOTE, block.text
        if isinstance(block, Paragraph):
            return BookEntryKind.PARAGRAPH, block.text
        if isinstance(block, ListBlock):
            # Index/search needs one concise deterministic label, while the
            # BookDocument retains item boundaries and ordering as semantic data.
            return BookEntryKind.LIST, block.items[0]
        raise TypeError(f"Unsupported BookDocument block type: {type(block).__name__}")

    def _build_entries(self):
        levels: list[str | None] = [None] * 6
        for index, block in enumerate(self.document.blocks):
            heading_level = None
            if isinstance(block, Heading):
                heading_level = block.level
                level = heading_level - 1
                levels[level] = block.text
                for deeper in range(level + 1, 6):
                    levels[deeper] = None
            heading_path = tuple(item for item in levels if item is not None)
            kind, label = self._kind_and_label(block)
            fen, side = self._position(block)
            yield BookIndexEntry(
                target=self._target(index),
                kind=kind,
                label=label,
                heading_path=heading_path,
                position_fen=fen,
                side_to_move=side,
                heading_level=heading_level,
            )

    def contents(self, *, max_heading_level: int = 6) -> tuple[BookIndexEntry, ...]:
        if type(max_heading_level) is not int:
            raise TypeError("max_heading_level must be an integer")
        if not 1 <= max_heading_level <= 6:
            raise ValueError("max_heading_level must be between 1 and 6")
        return tuple(
            entry
            for entry in self._entries
            if entry.kind is BookEntryKind.HEADING
            and entry.heading_level is not None
            and entry.heading_level <= max_heading_level
        )

    def of_kind(self, kind: BookEntryKind) -> tuple[BookIndexEntry, ...]:
        if not isinstance(kind, BookEntryKind):
            raise TypeError("Book entry kind must be a BookEntryKind")
        return tuple(entry for entry in self._entries if entry.kind is kind)

    def resolve(self, target: BookTarget | str) -> BookIndexEntry:
        """Resolve a target without silently choosing among duplicate semantic keys.

        A key based on block_id/source_anchor remains useful if blocks move after a
        source-preserving conversion. Index-only targets intentionally describe a
        snapshot and therefore resolve by their exact generated key.
        """
        if not isinstance(target, (BookTarget, str)):
            raise TypeError("Book target must be a BookTarget or string")
        key = target.key if isinstance(target, BookTarget) else target
        matches = self._by_key.get(key, ())
        if not matches:
            raise LookupError(f"Unknown book target: {key}")
        if len(matches) != 1:
            raise AmbiguousBookTargetError(f"Book target is ambiguous: {key}")
        return matches[0]

    def find(self, text: str, *, kinds: set[BookEntryKind] | None = None) -> tuple[BookIndexEntry, ...]:
        """Case-insensitive semantic label search preserving linear reading order."""
        if type(text) is not str:
            raise TypeError("Search text must be a string")
        if kinds is not None:
            if type(kinds) is not set or not all(
                isinstance(kind, BookEntryKind) for kind in kinds
            ):
                raise TypeError("Search kinds must be a set of BookEntryKind values")
        needle = text.strip().casefold()
        if not needle:
            raise ValueError("Search text must not be empty")
        return tuple(
            entry
            for entry in self._entries
            if (kinds is None or entry.kind in kinds) and needle in entry.label.casefold()
        )
