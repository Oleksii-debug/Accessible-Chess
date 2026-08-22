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

from .book_index import BookIndex
from .bookdocument import BookDocument, Diagram, Exercise, Game, Heading, Position, VariationTree


BOOK_READER_SNAPSHOT_SCHEMA_VERSION = 2
_BOOK_READER_SNAPSHOT_FIELDS = frozenset(
    {"schema_version", "current_target", "return_points", "fallback_digests"}
)
_MAX_RETURN_POINTS = 1000
_MAX_RETURN_POINT_NAME_CHARS = 256
_MAX_TARGET_KEY_CHARS = 4096


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
    """Stable semantic cursor with durable return points and structure navigation.

    Return points are stored as ``BookIndex`` semantic target keys rather than raw
    list offsets. Blocks with a ``block_id`` or ``source_anchor`` therefore keep
    their reading identity if a source-preserving edit reorders surrounding
    content. Index-only targets carry a strict semantic digest in durable
    snapshots so they fail closed if the document revision changes their meaning.

    A reader is bound to the exact ``BookDocument.blocks`` snapshot used to build
    its immutable ``BookIndex``. Authoring/import code may mutate ``BookDocument``
    in place, but durable progress operations then fail closed instead of resolving
    through stale index entries. Persist progress before editing and restore it
    into a fresh ``BookReader`` for the new document revision.
    """

    def __init__(self, document: BookDocument):
        self.document = document
        self._index = 0 if document.blocks else -1
        self._book_index = BookIndex(document)
        self._return_points: dict[str, str] = {}
        self._indexed_revision_digest = self._document_revision_digest()

    @property
    def index(self) -> int:
        return self._index

    def _require_content(self) -> None:
        if not self.document.blocks:
            raise LookupError("BookDocument has no readable blocks")

    @staticmethod
    def _return_point_name(name: str) -> str:
        if type(name) is not str:
            raise TypeError("Return point name must be a string")
        if not name.strip():
            raise ValueError("Return point name must not be empty")
        if len(name) > _MAX_RETURN_POINT_NAME_CHARS:
            raise ValueError(
                f"Return point name exceeds {_MAX_RETURN_POINT_NAME_CHARS} characters"
            )
        return name

    @staticmethod
    def _durable_target(value: object, *, name: str = "Book target key") -> str:
        if type(value) is not str:
            raise TypeError(f"{name} must be a string")
        if not value:
            raise ValueError(f"{name} must not be empty")
        if len(value) > _MAX_TARGET_KEY_CHARS:
            raise ValueError(f"{name} exceeds {_MAX_TARGET_KEY_CHARS} characters")
        return value

    @staticmethod
    def _fallback_digest_for_block(block) -> str:
        """Return strict semantic identity for an index-only fallback block."""
        payload = json.dumps(
            block.as_dict(),
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
        return hashlib.sha256(payload).hexdigest()

    def _document_revision_digest(self) -> str:
        """Fingerprint semantic blocks used by the immutable ``BookIndex``."""
        payload = json.dumps(
            [block.as_dict() for block in self.document.blocks],
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
        return hashlib.sha256(payload).hexdigest()

    def _require_indexed_revision(self) -> None:
        """Reject durable target work after the indexed document changed in place."""
        if self._document_revision_digest() != self._indexed_revision_digest:
            raise RuntimeError(
                "BookDocument changed after BookReader creation; create a fresh reader for this revision"
            )

    def _target_key(self, index: int | None = None) -> str:
        self._require_indexed_revision()
        self._require_content()
        target_index = self._index if index is None else index
        return self._book_index.entries[target_index].target.key

    def _durable_target_key(self, index: int | None = None) -> str:
        """Return a target only when it is uniquely resolvable in this snapshot.

        ``BookIndex`` deliberately permits duplicate source identifiers so import
        diagnostics can inspect imperfect source material, but durable progress
        must never serialize an ambiguous semantic key. Validate before mutating
        return-point state or publishing a snapshot so every emitted target is
        immediately restorable against the same document snapshot.
        """
        key = self._durable_target(self._target_key(index))
        self._book_index.resolve(key)
        return key

    def _fallback_digest(self, key: str) -> str:
        self._require_indexed_revision()
        if not key.startswith("index:"):
            raise ValueError("fallback digest is only defined for index targets")
        entry = self._book_index.resolve(key)
        return self._fallback_digest_for_block(self.document.blocks[entry.target.index])

    def _go_to_target(self, key: str) -> ReadingLocation:
        self._require_indexed_revision()
        validated_key = self._durable_target(key)
        entry = self._book_index.resolve(validated_key)
        return self.go_to(entry.target.index)

    def _heading_path(self, index: int) -> tuple[str, ...]:
        levels: list[str | None] = [None] * 6
        for block in self.document.blocks[: index + 1]:
            if isinstance(block, Heading):
                level = block.level - 1
                levels[level] = block.text
                for deeper in range(level + 1, 6):
                    levels[deeper] = None
        return tuple(item for item in levels if item is not None)

    def location(self) -> ReadingLocation:
        self._require_content()
        block = self.document.blocks[self._index]
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
        if type(index) is not int:
            raise TypeError("Book reading index must be an integer")
        if not 0 <= index < len(self.document.blocks):
            raise IndexError("Book reading index is outside the document")
        self._index = index
        return self.location()

    def next_block(self) -> ReadingLocation:
        self._require_content()
        if self._index >= len(self.document.blocks) - 1:
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
        while 0 <= cursor < len(self.document.blocks):
            if predicate(self.document.blocks[cursor]):
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
        validated_name = self._return_point_name(name)
        if validated_name not in self._return_points and len(self._return_points) >= _MAX_RETURN_POINTS:
            raise ValueError(f"Book reader supports at most {_MAX_RETURN_POINTS} return points")
        key = self._durable_target_key()
        self._return_points[validated_name] = key
        return self.location()

    def restore_return_point(self, name: str = "default") -> ReadingLocation:
        validated_name = self._return_point_name(name)
        if validated_name not in self._return_points:
            raise LookupError(f"Unknown return point: {validated_name}")
        return self._go_to_target(self._return_points[validated_name])

    def snapshot(self) -> dict[str, object]:
        """Return strict schema-v2 reading progress without positional drift."""
        self._require_indexed_revision()
        if len(self._return_points) > _MAX_RETURN_POINTS:
            raise ValueError(f"Book reader supports at most {_MAX_RETURN_POINTS} return points")
        current_target = None if self._index < 0 else self._durable_target_key()
        referenced_targets = set(self._return_points.values())
        if current_target is not None:
            referenced_targets.add(current_target)
        for key in referenced_targets:
            self._durable_target(key)
            self._book_index.resolve(key)
        fallback_digests = {
            key: self._fallback_digest(key)
            for key in sorted(referenced_targets)
            if key.startswith("index:")
        }
        return {
            "schema_version": BOOK_READER_SNAPSHOT_SCHEMA_VERSION,
            "current_target": current_target,
            "return_points": dict(sorted(self._return_points.items())),
            "fallback_digests": fallback_digests,
        }

    @classmethod
    def restore_snapshot(cls, document: BookDocument, snapshot: Mapping[str, object]) -> "BookReader":
        """Restore reading progress using stable semantic targets.

        Unknown/missing fields and scalar coercion fail closed. A target that no
        longer exists, or that became ambiguous because source identities were
        duplicated, is surfaced by ``BookIndex.resolve`` rather than silently
        selecting a different block. Index-only targets additionally require an
        exact semantic digest for the block currently occupying that fallback.
        """
        if not isinstance(snapshot, Mapping):
            raise TypeError("Book reader snapshot must be a mapping")
        if len(snapshot) != len(_BOOK_READER_SNAPSHOT_FIELDS):
            raise ValueError("invalid BookReader snapshot field count")
        fields = set(snapshot)
        if fields != _BOOK_READER_SNAPSHOT_FIELDS:
            missing = sorted(_BOOK_READER_SNAPSHOT_FIELDS - fields)
            unknown = sorted(fields - _BOOK_READER_SNAPSHOT_FIELDS)
            detail = []
            if missing:
                detail.append("missing fields: " + ", ".join(missing))
            if unknown:
                detail.append("unknown fields: " + ", ".join(unknown))
            raise ValueError("invalid BookReader snapshot fields (" + "; ".join(detail) + ")")

        schema_version = snapshot["schema_version"]
        if type(schema_version) is not int:
            raise TypeError("Book reader snapshot schema_version must be an integer")
        if schema_version != BOOK_READER_SNAPSHOT_SCHEMA_VERSION:
            raise ValueError(f"unsupported BookReader snapshot schema_version: {schema_version}")

        current_target = snapshot["current_target"]
        if current_target is not None:
            current_target = cls._durable_target(current_target, name="Book reader snapshot current_target")

        raw_return_points = snapshot["return_points"]
        if not isinstance(raw_return_points, Mapping):
            raise TypeError("Book reader snapshot return_points must be a mapping")
        if len(raw_return_points) > _MAX_RETURN_POINTS:
            raise ValueError(f"Book reader snapshot exceeds {_MAX_RETURN_POINTS} return points")
        return_points: dict[str, str] = {}
        for name, key in raw_return_points.items():
            validated_name = cls._return_point_name(name)
            validated_key = cls._durable_target(key, name="Book reader snapshot target key")
            return_points[validated_name] = validated_key

        raw_fallback_digests = snapshot["fallback_digests"]
        if not isinstance(raw_fallback_digests, Mapping):
            raise TypeError("Book reader snapshot fallback_digests must be a mapping")
        if len(raw_fallback_digests) > _MAX_RETURN_POINTS + 1:
            raise ValueError("Book reader snapshot contains too many fallback digests")
        fallback_digests: dict[str, str] = {}
        for key, digest in raw_fallback_digests.items():
            validated_key = cls._durable_target(key, name="Book reader fallback digest key")
            if type(digest) is not str:
                raise TypeError("Book reader fallback digest keys and values must be strings")
            if not validated_key.startswith("index:"):
                raise ValueError("Book reader fallback digests may only bind index targets")
            if len(digest) != 64 or any(character not in "0123456789abcdef" for character in digest):
                raise ValueError("Book reader fallback digest must be lowercase SHA-256 hex")
            fallback_digests[validated_key] = digest

        reader = cls(document)
        referenced_targets = set(return_points.values())
        if current_target is not None:
            referenced_targets.add(current_target)
        required_fallbacks = {key for key in referenced_targets if key.startswith("index:")}
        if set(fallback_digests) != required_fallbacks:
            raise ValueError("Book reader snapshot fallback_digests do not match referenced index targets")

        if not document.blocks:
            if current_target is not None or return_points or fallback_digests:
                raise LookupError("Book reader snapshot targets require readable content")
            return reader
        if current_target is None:
            raise ValueError("Book reader snapshot current_target is required for non-empty content")

        for key in referenced_targets:
            reader._book_index.resolve(key)
        for key, expected_digest in fallback_digests.items():
            if reader._fallback_digest(key) != expected_digest:
                raise LookupError(f"Book reader index fallback no longer identifies the same block: {key}")

        reader._go_to_target(current_target)
        reader._return_points = return_points
        return reader
