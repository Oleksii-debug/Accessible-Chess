from __future__ import annotations

"""Presentation-neutral accessible navigation over BookDocument.

The reader deliberately exposes semantic locations rather than UI key bindings.
NVDA/WebView clients can bind their remappable action IDs to these operations
without the data layer owning shortcuts.
"""

from contextlib import contextmanager
from dataclasses import dataclass
import hashlib
import json
from itertools import islice
from typing import Iterator, Mapping

from .book_index import BookIndex
from .bookdocument import (
    BookDocument,
    MAX_BOOK_TEXT_FIELD_CHARS,
    Diagram,
    Exercise,
    Game,
    Heading,
    Position,
    VariationTree,
    _SEMANTIC_BLOCK_TYPES,
    block_from_dict,
)


BOOK_READER_SNAPSHOT_SCHEMA_VERSION = 2
_BOOK_READER_SNAPSHOT_FIELDS = frozenset(
    {"schema_version", "current_target", "return_points", "fallback_digests"}
)
_MAX_RETURN_POINTS = 1000
_MAX_RETURN_POINT_NAME_CHARS = 256
_MAX_TARGET_KEY_CHARS = 4096
_MAX_SNAPSHOT_FIELD_CHARS = max(len(field) for field in _BOOK_READER_SNAPSHOT_FIELDS)


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
        if type(document) is not BookDocument:
            # BookDocument is a mutable authoring DTO. Reject subclasses before
            # any provider-defined as_dict()/attribute hook can execute.
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

    def document_warning_count(self) -> int:
        """Return the warning count bound to this reader's indexed document snapshot."""
        self._require_indexed_revision()
        return len(self._indexed_document.warnings)

    def _reading_metadata_after_verified(self) -> tuple[str, str | None, str | None]:
        """Detach canonical indexed metadata without active-root/scalar hooks."""

        document = self._indexed_document
        if type(document) is not BookDocument:
            raise TypeError("indexed BookDocument metadata root is invalid")
        title = document.title
        author = document.author
        language = document.language

        def canonical_text(value: object, *, optional: bool) -> str | None:
            if value is None:
                if optional:
                    return None
                raise TypeError("indexed Book reading metadata is invalid")
            if type(value) is not str or len(value) > MAX_BOOK_TEXT_FIELD_CHARS:
                raise TypeError("indexed Book reading metadata is invalid")
            if not value.strip():
                raise TypeError("indexed Book reading metadata is invalid")
            return value

        return (
            canonical_text(title, optional=False),
            canonical_text(author, optional=True),
            canonical_text(language, optional=True),
        )

    def document_language_snapshot(self) -> str | None:
        """Source language from the same detached revision as readable blocks."""
        self._require_indexed_revision()
        return self._reading_metadata_after_verified()[2]

    def document_title_author_snapshot(self) -> tuple[str, str | None]:
        """Reading metadata from the immutable indexed document revision."""
        self._require_indexed_revision()
        title, author, _language = self._reading_metadata_after_verified()
        return title, author

    def block_reading_snapshot(self, index: int):
        """One validated block plus its detached document reading metadata.

        Sharing block_snapshot's revision check avoids rescanning a large book
        separately for title, author and language. No live authoring metadata or
        mutable indexed block is returned.
        """
        block = self.block_snapshot(index)
        title, author, language = self._reading_metadata_after_verified()
        return (block, title, author, language)

    def document_warnings_snapshot(
        self,
        *,
        limit: int | None = None,
    ) -> tuple[str, ...]:
        """Return bounded importer warnings from this reader's indexed snapshot."""
        self._require_indexed_revision()
        if limit is None:
            return tuple(self._indexed_document.warnings)
        if type(limit) is not int:
            raise TypeError("Book warning snapshot limit must be an integer")
        if limit < 0:
            raise ValueError("Book warning snapshot limit must not be negative")
        return tuple(islice(self._indexed_document.warnings, limit))

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
    def document_snapshot(self) -> BookDocument:
        """Return a detached canonical BookDocument from this indexed revision.

        Book-facing application flows must not traverse the mutable public
        document after revision validation. This snapshot keeps semantic
        provenance on the same immutable BookIndex revision while live authoring
        state remains only a fail-closed equality/revision authority.
        """
        self._require_indexed_revision()
        snapshot = BookDocument.from_dict(self._indexed_document.as_dict())
        self._require_indexed_revision()
        return snapshot

    @staticmethod
    def _return_point_name(name: str) -> str:
        if type(name) is not str:
            raise TypeError("Return point name must be a string")
        # Return-point names are persisted identity keys. Reject an oversized raw
        # key from O(1) length metadata before strip scans attacker-controlled
        # snapshot or host input.
        if len(name) > _MAX_RETURN_POINT_NAME_CHARS:
            raise ValueError(
                f"Return point name exceeds {_MAX_RETURN_POINT_NAME_CHARS} characters"
            )
        if not name.strip():
            raise ValueError("Return point name must not be empty")
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
        # Live authoring state is mutable after BookReader construction. Prove
        # the canonical passive container and exact semantic block roots before
        # iteration or method dispatch can execute provider-defined hooks.
        if type(blocks) is not list:
            raise TypeError("BookDocument blocks must remain a built-in list")
        if any(type(block) not in _SEMANTIC_BLOCK_TYPES for block in blocks):
            raise TypeError("BookDocument blocks must remain canonical semantic blocks")
        # Preserve the exact historical canonical JSON-array byte stream while
        # hashing it incrementally. Large books therefore do not require an
        # additional whole-document list-of-dicts, JSON string and UTF-8 bytes
        # allocation on every keyboard/persistence revision barrier.
        digest = hashlib.sha256()
        digest.update(b"[")
        for index, block in enumerate(blocks):
            if index:
                digest.update(b",")
            payload = json.dumps(
                block.as_dict(),
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
            ).encode("utf-8")
            digest.update(payload)
        digest.update(b"]")
        return digest.hexdigest()

    def _document_revision_digest(self) -> str:
        """Fingerprint the current live authoring blocks."""
        # The public source reference is mutable too. Prove its exact passive
        # canonical root before reading blocks so a rejected provider-defined
        # BookDocument subclass cannot execute __getattribute__ merely because
        # navigation performs its fail-closed revision check.
        document = self.document
        if type(document) is not BookDocument:
            raise TypeError("BookReader document must remain a canonical BookDocument")
        return self._revision_digest(document.blocks)

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

    def _target_key_after_verified(self, index: int | None = None) -> str:
        target_index = self._index if index is None else index
        return self._book_index.entries[target_index].target.key

    def _target_key(self, index: int | None = None) -> str:
        self._require_content()
        return self._target_key_after_verified(index)

    def _durable_target_key_after_verified(self, index: int | None = None) -> str:
        key = self._durable_target(self._target_key_after_verified(index))
        self._book_index.resolve(key)
        return key

    def _durable_target_key(self, index: int | None = None) -> str:
        """Return a target only when it is uniquely resolvable in this snapshot.

        ``BookIndex`` deliberately permits duplicate source identifiers so import
        diagnostics can inspect imperfect source material, but durable progress
        must never serialize an ambiguous semantic key. Validate before mutating
        return-point state or publishing a snapshot so every emitted target is
        immediately restorable against the same document snapshot.
        """
        self._require_content()
        return self._durable_target_key_after_verified(index)

    def _fallback_digest_after_verified(self, key: str) -> str:
        if not key.startswith("index:"):
            raise ValueError("fallback digest is only defined for index targets")
        entry = self._book_index.resolve(key)
        return self._fallback_digest_for_block(self._indexed_document.blocks[entry.target.index])

    def _fallback_digest(self, key: str) -> str:
        self._require_indexed_revision()
        return self._fallback_digest_after_verified(key)

    def _go_to_target(self, key: str) -> ReadingLocation:
        # Callers own the preflight revision barrier. Keep this seam as the
        # target-navigation publication boundary so restore/return-point tests
        # can inject a concurrent edit after navigation and rely on the caller's
        # final barrier to reject it.
        validated_key = self._durable_target(key)
        entry = self._book_index.resolve(validated_key)
        return self._go_to_after_verified(entry.target.index)

    def _location_after_verified(self) -> ReadingLocation:
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

    def location(self) -> ReadingLocation:
        self._require_content()
        return self._location_after_verified()

    def _go_to_after_verified(self, index: int) -> ReadingLocation:
        if type(index) is not int:
            raise TypeError("Book reading index must be an integer")
        if not 0 <= index < len(self._book_index.entries):
            raise IndexError("Book reading index is outside the document")
        previous_index = self._index
        self._index = index
        try:
            location = self._location_after_verified()
            # Keep the original two-sided live-authoring contract, but do not
            # recursively re-hash the whole document through location()/go_to().
            self._require_indexed_revision()
            return location
        except Exception:
            self._index = previous_index
            raise

    def go_to(self, index: int) -> ReadingLocation:
        self._require_content()
        return self._go_to_after_verified(index)

    def next_block(self) -> ReadingLocation:
        self._require_content()
        if self._index >= len(self._book_index.entries) - 1:
            raise LookupError("End of book")
        return self._go_to_after_verified(self._index + 1)

    def previous_block(self) -> ReadingLocation:
        self._require_content()
        if self._index <= 0:
            raise LookupError("Beginning of book")
        return self._go_to_after_verified(self._index - 1)

    def _next_matching(self, predicate, *, direction: int) -> ReadingLocation:
        self._require_content()
        cursor = self._index + direction
        while 0 <= cursor < len(self._indexed_document.blocks):
            if predicate(self._indexed_document.blocks[cursor]):
                return self._go_to_after_verified(cursor)
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
        key = self._durable_target_key_after_verified()
        had_previous = validated_name in self._return_points
        previous_key = self._return_points.get(validated_name)
        self._return_points[validated_name] = key
        try:
            location = self._location_after_verified()
            self._require_indexed_revision()
            return location
        except BaseException:
            # Preserve the original final live-revision barrier without paying
            # for additional whole-document hashes through nested helper calls.
            if had_previous:
                assert previous_key is not None
                self._return_points[validated_name] = previous_key
            else:
                self._return_points.pop(validated_name, None)
            raise

    @contextmanager
    def provisional_return_point(
        self,
        name: str = "default",
    ) -> Iterator[ReadingLocation]:
        """Publish a return point only if the guarded operation succeeds.

        Board/game handoffs need the return target to exist before dispatch so a
        successful external transition can always come back to the exact reading
        location.  If dispatch fails, restore the previous binding (or remove the
        newly-created one) on this same reader instance so callers holding the
        canonical reader never observe a phantom handoff.
        """
        validated_name = self._return_point_name(name)
        had_previous = validated_name in self._return_points
        previous_key = self._return_points.get(validated_name)
        location = self.save_return_point(validated_name)
        try:
            yield location
        except BaseException:
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
        self._require_content()
        return self._go_to_target(self._return_points[validated_name])

    def snapshot(self) -> dict[str, object]:
        """Return strict schema-v2 reading progress without positional drift."""
        self._require_indexed_revision()
        if len(self._return_points) > _MAX_RETURN_POINTS:
            raise ValueError(f"Book reader supports at most {_MAX_RETURN_POINTS} return points")
        current_target = (
            None if self._index < 0 else self._durable_target_key_after_verified()
        )
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
            key: self._fallback_digest_after_verified(key)
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
    def validate_snapshot_contract(
        cls,
        snapshot: Mapping[str, object],
    ) -> dict[str, object]:
        """Validate document-independent durable snapshot structure.

        This is the single scalar/schema authority shared by persistence ingress
        and document-bound restore. It deliberately does not resolve semantic
        targets against a BookDocument; restore_snapshot owns that later step.
        """
        # Persisted progress is JSON-derived and canonical in-memory snapshots are
        # emitted as built-in dicts. Reject mapping subclasses before len/iter/getitem
        # can execute provider-defined hooks during recovery validation.
        if type(snapshot) is not dict:
            raise TypeError("Book reader snapshot must be a mapping")
        expected_count = len(_BOOK_READER_SNAPSHOT_FIELDS)
        try:
            snapshot_count = len(snapshot)
        except Exception as exc:
            raise TypeError("Book reader snapshot must be a stable mapping") from exc
        if snapshot_count != expected_count:
            raise ValueError("invalid BookReader snapshot field count")
        try:
            snapshot_keys = tuple(islice(iter(snapshot), expected_count + 1))
        except Exception as exc:
            raise TypeError("Book reader snapshot must be a stable mapping") from exc
        if len(snapshot_keys) != snapshot_count:
            raise ValueError("Book reader snapshot changed while being read")
        if any(type(field) is not str for field in snapshot_keys):
            raise ValueError(
                "invalid BookReader snapshot fields (field names must be strings)"
            )
        if any(len(field) > _MAX_SNAPSHOT_FIELD_CHARS for field in snapshot_keys):
            raise ValueError(
                "invalid BookReader snapshot fields (field name exceeds supported bound)"
            )
        if len(set(snapshot_keys)) != len(snapshot_keys):
            raise ValueError("invalid BookReader snapshot fields (duplicate fields)")
        fields = set(snapshot_keys)
        if fields != _BOOK_READER_SNAPSHOT_FIELDS:
            missing = sorted(_BOOK_READER_SNAPSHOT_FIELDS - fields)
            unknown = sorted(fields - _BOOK_READER_SNAPSHOT_FIELDS)
            detail = []
            if missing:
                detail.append("missing fields: " + ", ".join(missing))
            if unknown:
                detail.append("unknown fields: " + ", ".join(unknown))
            raise ValueError("invalid BookReader snapshot fields (" + "; ".join(detail) + ")")

        snapshot_data: dict[str, object] = {}
        try:
            for key in snapshot_keys:
                snapshot_data[key] = snapshot[key]
        except Exception as exc:
            raise TypeError("Book reader snapshot must be a stable mapping") from exc

        schema_version = snapshot_data["schema_version"]
        if type(schema_version) is not int:
            raise TypeError("Book reader snapshot schema_version must be an integer")
        if schema_version != BOOK_READER_SNAPSHOT_SCHEMA_VERSION:
            raise ValueError(f"unsupported BookReader snapshot schema_version: {schema_version}")

        current_target = snapshot_data["current_target"]
        if current_target is not None:
            current_target = cls._durable_target(
                current_target,
                name="Book reader snapshot current_target",
            )

        raw_return_points = snapshot_data["return_points"]
        if type(raw_return_points) is not dict:
            raise TypeError("Book reader snapshot return_points must be a mapping")
        try:
            return_point_count = len(raw_return_points)
        except Exception as exc:
            raise TypeError(
                "Book reader snapshot return_points must be a stable mapping"
            ) from exc
        if return_point_count > _MAX_RETURN_POINTS:
            raise ValueError(f"Book reader snapshot exceeds {_MAX_RETURN_POINTS} return points")
        try:
            return_point_keys = tuple(
                islice(iter(raw_return_points), return_point_count + 1)
            )
        except Exception as exc:
            raise TypeError(
                "Book reader snapshot return_points must be a stable mapping"
            ) from exc
        if len(return_point_keys) != return_point_count:
            raise ValueError("Book reader snapshot return_points changed while being read")
        validated_return_point_keys: list[tuple[str, str]] = []
        seen_return_point_names: set[str] = set()
        for name in return_point_keys:
            if type(name) is not str:
                raise TypeError("Return point name must be a string")
            # Bound each raw scalar before hashing it for duplicate detection.
            # Mapping-count limits alone do not cap CPU when a hostile snapshot
            # supplies a small number of enormous string keys.
            validated_name = cls._return_point_name(name)
            if validated_name in seen_return_point_names:
                raise ValueError(
                    "Book reader snapshot contains duplicate return point names"
                )
            seen_return_point_names.add(validated_name)
            validated_return_point_keys.append((name, validated_name))
        try:
            raw_return_point_items = tuple(
                (validated_name, raw_return_points[raw_name])
                for raw_name, validated_name in validated_return_point_keys
            )
        except Exception as exc:
            raise TypeError(
                "Book reader snapshot return_points must be a stable mapping"
            ) from exc
        return_points: dict[str, str] = {}
        for validated_name, key in raw_return_point_items:
            validated_key = cls._durable_target(
                key,
                name="Book reader snapshot target key",
            )
            return_points[validated_name] = validated_key

        raw_fallback_digests = snapshot_data["fallback_digests"]
        if type(raw_fallback_digests) is not dict:
            raise TypeError("Book reader snapshot fallback_digests must be a mapping")
        max_fallback_digests = _MAX_RETURN_POINTS + 1
        try:
            fallback_digest_count = len(raw_fallback_digests)
        except Exception as exc:
            raise TypeError(
                "Book reader snapshot fallback_digests must be a stable mapping"
            ) from exc
        if fallback_digest_count > max_fallback_digests:
            raise ValueError("Book reader snapshot contains too many fallback digests")
        try:
            fallback_digest_keys = tuple(
                islice(iter(raw_fallback_digests), fallback_digest_count + 1)
            )
        except Exception as exc:
            raise TypeError(
                "Book reader snapshot fallback_digests must be a stable mapping"
            ) from exc
        if len(fallback_digest_keys) != fallback_digest_count:
            raise ValueError("Book reader snapshot fallback_digests changed while being read")
        validated_fallback_digest_keys: list[tuple[str, str]] = []
        seen_fallback_digest_keys: set[str] = set()
        for key in fallback_digest_keys:
            if type(key) is not str:
                raise TypeError(
                    "Book reader fallback digest keys and values must be strings"
                )
            # Validate the raw key length before set insertion hashes attacker-
            # controlled text. This keeps the advertised mapping-count bound a
            # real aggregate work bound rather than only an item-count bound.
            validated_key = cls._durable_target(
                key,
                name="Book reader fallback digest key",
            )
            if not validated_key.startswith("index:"):
                raise ValueError(
                    "Book reader fallback digests may only bind index targets"
                )
            if validated_key in seen_fallback_digest_keys:
                raise ValueError(
                    "Book reader snapshot contains duplicate fallback digest keys"
                )
            seen_fallback_digest_keys.add(validated_key)
            validated_fallback_digest_keys.append((key, validated_key))
        try:
            raw_fallback_digest_items = tuple(
                (validated_key, raw_fallback_digests[raw_key])
                for raw_key, validated_key in validated_fallback_digest_keys
            )
        except Exception as exc:
            raise TypeError(
                "Book reader snapshot fallback_digests must be a stable mapping"
            ) from exc
        fallback_digests: dict[str, str] = {}
        for validated_key, digest in raw_fallback_digest_items:
            if type(digest) is not str:
                raise TypeError("Book reader fallback digest keys and values must be strings")
            if len(digest) != 64 or any(character not in "0123456789abcdef" for character in digest):
                raise ValueError("Book reader fallback digest must be lowercase SHA-256 hex")
            fallback_digests[validated_key] = digest

        referenced_targets = set(return_points.values())
        if current_target is not None:
            referenced_targets.add(current_target)
        required_fallbacks = {key for key in referenced_targets if key.startswith("index:")}
        if set(fallback_digests) != required_fallbacks:
            raise ValueError("Book reader snapshot fallback_digests do not match referenced index targets")

        return {
            "schema_version": BOOK_READER_SNAPSHOT_SCHEMA_VERSION,
            "current_target": current_target,
            "return_points": return_points,
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
        if type(document) is not BookDocument:
            raise TypeError("document must be a BookDocument")
        validated = cls.validate_snapshot_contract(snapshot)
        current_target = validated["current_target"]
        return_points = validated["return_points"]
        fallback_digests = validated["fallback_digests"]
        assert current_target is None or type(current_target) is str
        assert isinstance(return_points, dict)
        assert isinstance(fallback_digests, dict)

        reader = cls(document)
        referenced_targets = set(return_points.values())
        if current_target is not None:
            referenced_targets.add(current_target)

        if not reader._book_index.entries:
            if current_target is not None or return_points or fallback_digests:
                raise LookupError("Book reader snapshot targets require readable content")
            reader._require_indexed_revision()
            return reader
        if current_target is None:
            raise ValueError("Book reader snapshot current_target is required for non-empty content")

        # One preflight and one final live-revision barrier are sufficient for
        # restore. Every intermediate lookup/digest uses the immutable indexed
        # snapshot; repeating the full live-document hash once per return point
        # would make recovery O(snapshot targets * book size).
        reader._require_indexed_revision()
        for key in referenced_targets:
            reader._book_index.resolve(key)
        for key, expected_digest in fallback_digests.items():
            if reader._fallback_digest_after_verified(key) != expected_digest:
                raise LookupError(f"Book reader index fallback no longer identifies the same block: {key}")

        reader._go_to_target(current_target)
        reader._return_points = return_points
        reader._require_indexed_revision()
        return reader
