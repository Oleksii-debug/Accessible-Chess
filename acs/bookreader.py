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
from .bookdocument import (
    BookDocument,
    Diagram,
    Exercise,
    Game,
    Heading,
    Position,
    VariationTree,
    block_from_dict,
)


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
        if not isinstance(document, BookDocument):
            raise TypeError("document must be a BookDocument")
        self.document = document
        self._indexed_document = BookDocument.from_dict(document.as_dict())
        self._index = 0 if self._indexed_document.blocks else -1
        self._book_index = BookIndex(self._indexed_document)
        self._return_points: dict[str, str] = {}
        self._indexed_revision_digest = self._revision_digest(self._indexed_document.blocks)
        self._require_indexed_revision()

    @property
    def index(self) -> int:
        return self._index

    def _require_content(self) -> None:
        self._require_indexed_revision()
        if not self._book_index.entries:
            raise LookupError("BookDocument has no readable blocks")

    def block_snapshot(self, index: int):
        """Return a detached canonical block from the reader's indexed revision."""
        self._require_indexed_revision()
        if type(index) is not int:
            raise TypeError("Book reading index must be an integer")
        if not 0 <= index < len(self._indexed_document.blocks):
            raise IndexError("Book reading index is outside the document")
        return block_from_dict(self._indexed_document.blocks[index].as_dict())

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

    @staticmethod
    def _revision_digest(blocks) -> str:
        payload = json.dumps(
            [block.as_dict() for block in blocks],
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
        return hashlib.sha256(payload).hexdigest()

    def _document_revision_digest(self) -> str:
        """Fingerprint the current live authoring blocks."""
        return self._revision_digest(self.document.blocks)

    def _require_indexed_revision(self) -> None:
        """Reject durable target work after the indexed document changed in place."""
        try:
            current_revision = self._document_revision_digest()
        except Exception:
            # Mutable authoring code can temporarily put BookDocument into an
            # invalid state. Treat an uncanonicalizable live revision exactly as
            # semantic drift instead of leaking parser/attribute failures through
            # an otherwise fail-closed reader.
            raise RuntimeError(
                "BookDocument changed after BookReader creation; create a fresh reader for this revision"
            ) from None
        if current_revision != self._indexed_revision_digest:
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
        return self._fallback_digest_for_block(self._indexed_document.blocks[entry.target.index])

    def _go_to_target(self, key: str) -> ReadingLocation:
        self._require_indexed_revision()
        validated_key = self._durable_target(key)
        entry = self._book_index.resolve(validated_key)
        return self.go_to(entry.target.index)

    def location(self) -> ReadingLocation:
        self._require_content()
        entry = self._book_index.entries[self._index]
        block = self._indexed_document.blocks[self._index]
        return ReadingLocation(
            index=self._index,
            kind=block.kind,
            block_id=entry.target.block_id,
            source_anchor=entry.target.source_anchor,
            heading_path=entry.heading_path,
            position_fen=entry.position_fen,
            side_to_move=entry.side_to_move,
        )

    def go_to(self, index: int) -> ReadingLocation:
        self._require_content()
        if type(index) is not int:
            raise TypeError("Book reading index must be an integer")
        if not 0 <= index < len(self._book_index.entries):
            raise IndexError("Book reading index is outside the document")
        previous_index = self._index
        self._index = index
        try:
            return self.location()
        except Exception:
            # location() performs the second live-revision check. If authoring
            # mutates the BookDocument after the initial validation, navigation
            # must fail without publishing a cursor that was never accepted.
            self._index = previous_index
            raise

    def next_block(self) -> ReadingLocation:
        self._require_content()
        if self._index >= len(self._book_index.entries) - 1:
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
        while 0 <= cursor < len(self._indexed_document.blocks):
            if predicate(self._indexed_document.blocks[cursor]):
                return self.go_to(cursor)
            cursor += direction
        self._require_indexed_revision()
        raise LookupError("No matching semantic block in that direction")

    def navigation_availability(self) -> dict[str, bool]:
        """Return non-mutating semantic navigation reachability at the cursor.

        Each side of the cursor is scanned at most once. WebView snapshots request
        all semantic directions together, so six independent linear scans would
        add avoidable keyboard-navigation latency for large books.
        """
        self._require_content()
        availability = {
            "previous": self._index > 0,
            "next": self._index < len(self._indexed_document.blocks) - 1,
            "previous_heading": False,
            "next_heading": False,
            "previous_position": False,
            "next_position": False,
            "previous_game": False,
            "next_game": False,
        }

        for direction, prefix in ((-1, "previous"), (1, "next")):
            cursor = self._index + direction
            while 0 <= cursor < len(self._indexed_document.blocks):
                block = self._indexed_document.blocks[cursor]
                if isinstance(block, Heading):
                    availability[f"{prefix}_heading"] = True
                if isinstance(block, (Position, Diagram, Exercise, VariationTree)):
                    availability[f"{prefix}_position"] = True
                if isinstance(block, Game):
                    availability[f"{prefix}_game"] = True
                if (
                    availability[f"{prefix}_heading"]
                    and availability[f"{prefix}_position"]
                    and availability[f"{prefix}_game"]
                ):
                    break
                cursor += direction

        # A long semantic scan must not publish reachability for a document
        # revision that changed after the initial validation.
        self._require_indexed_revision()
        return availability

    def next_heading(self) -> ReadingLocation:
        return self._next_matching(lambda block: isinstance(block, Heading), direction=1)

    def previous_heading(self) -> ReadingLocation:
        return self._next_matching(lambda block: isinstance(block, Heading), direction=-1)

    def next_position(self) -> ReadingLocation:
        return self._next_matching(
            lambda block: isinstance(block, (Position, Diagram, Exercise, VariationTree)), direction=1
        )

    def previous_position(self) -> ReadingLocation:
        return self._next_matching(
            lambda block: isinstance(block, (Position, Diagram, Exercise, VariationTree)), direction=-1
        )

    def next_game(self) -> ReadingLocation:
        return self._next_matching(lambda block: isinstance(block, Game), direction=1)

    def previous_game(self) -> ReadingLocation:
        return self._next_matching(lambda block: isinstance(block, Game), direction=-1)

    def save_return_point(self, name: str = "default") -> ReadingLocation:
        self._require_content()
        validated_name = self._return_point_name(name)
        if validated_name not in self._return_points and len(self._return_points) >= _MAX_RETURN_POINTS:
            raise ValueError(f"Book reader supports at most {_MAX_RETURN_POINTS} return points")
        key = self._durable_target_key()
        had_previous = validated_name in self._return_points
        previous_key = self._return_points.get(validated_name)
        self._return_points[validated_name] = key
        try:
            return self.location()
        except Exception:
            # The final location() call is also a live-revision barrier. A
            # concurrent BookDocument edit after target validation must not leave
            # behind a bookmark that the failed save never successfully published.
            if had_previous:
                assert previous_key is not None
                self._return_points[validated_name] = previous_key
            else:
                self._return_points.pop(validated_name, None)
            raise

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
        validated_return_points: dict[str, str] = {}
        for name, key in self._return_points.items():
            validated_name = self._return_point_name(name)
            validated_key = self._durable_target(
                key,
                name="Book reader return point target key",
            )
            self._book_index.resolve(validated_key)
            validated_return_points[validated_name] = validated_key

        referenced_targets = set(validated_return_points.values())
        if current_target is not None:
            referenced_targets.add(current_target)
        fallback_digests = {
            key: self._fallback_digest(key)
            for key in sorted(referenced_targets)
            if key.startswith("index:")
        }
        result = {
            "schema_version": BOOK_READER_SNAPSHOT_SCHEMA_VERSION,
            "current_target": current_target,
            "return_points": dict(sorted(validated_return_points.items())),
            "fallback_digests": fallback_digests,
        }
        self._require_indexed_revision()
        return result

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
        if any(type(field) is not str for field in fields):
            raise ValueError(
                "invalid BookReader snapshot fields (field names must be strings)"
            )
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
            current_target = cls._durable_target(
                current_target,
                name="Book reader snapshot current_target",
            )

        raw_return_points = snapshot["return_points"]
        if not isinstance(raw_return_points, Mapping):
            raise TypeError("Book reader snapshot return_points must be a mapping")
        if len(raw_return_points) > _MAX_RETURN_POINTS:
            raise ValueError(f"Book reader snapshot exceeds {_MAX_RETURN_POINTS} return points")
        return_points: dict[str, str] = {}
        for name, key in raw_return_points.items():
            validated_name = cls._return_point_name(name)
            validated_key = cls._durable_target(
                key,
                name="Book reader snapshot target key",
            )
            return_points[validated_name] = validated_key

        raw_fallback_digests = snapshot["fallback_digests"]
        if not isinstance(raw_fallback_digests, Mapping):
            raise TypeError("Book reader snapshot fallback_digests must be a mapping")
        if len(raw_fallback_digests) > _MAX_RETURN_POINTS + 1:
            raise ValueError("Book reader snapshot contains too many fallback digests")
        fallback_digests: dict[str, str] = {}
        for key, digest in raw_fallback_digests.items():
            validated_key = cls._durable_target(
                key,
                name="Book reader fallback digest key",
            )
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

        if not reader._book_index.entries:
            if current_target is not None or return_points or fallback_digests:
                raise LookupError("Book reader snapshot targets require readable content")
            reader._require_indexed_revision()
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
        reader._require_indexed_revision()
        return reader
