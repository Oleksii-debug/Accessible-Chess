from __future__ import annotations

"""Preservation-first duplicate classification for Library/ACSDB records.

This module reports evidence; it never deletes or silently coalesces records.
Canonical chess/document identity and source-record identity are intentionally
separate so the Library can recognise equivalent chess content without losing
which exact source/record supplied comments, NAGs, metadata or provenance.
"""

from dataclasses import dataclass
import hashlib
import re
from typing import Literal

from .acsdb import AcsDatabase
from .game_identity import (
    IDENTITY_SCHEMA_VERSION,
    MOVE_IDENTITY_SCHEMA_VERSION,
    identity_for_game,
    move_identity_for_game,
)
from .gametree import parse_games

DuplicateKind = Literal["exact_source", "record", "tree", "moves"]
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")


@dataclass(frozen=True, slots=True)
class SourceRecordIdentity:
    """Identity of one record inside one immutable source byte stream.

    ``source_format`` participates in source identity by design. Identical bytes
    presented as different declared formats are not silently treated as the same
    source. A CBV container record and an extracted CBH record therefore remain
    distinct provenance records even when they resolve to the same canonical
    chess-content identity.
    """

    source_format: str
    source_sha256: str
    source_index: int

    def __post_init__(self) -> None:
        if type(self.source_format) is not str or not self.source_format:
            raise TypeError("source_format must be canonical non-empty text")
        if self.source_format != self.source_format.strip().lower():
            raise ValueError("source_format must be stripped lowercase text")
        if type(self.source_sha256) is not str or _SHA256_RE.fullmatch(self.source_sha256) is None:
            raise ValueError("source_sha256 must be a lowercase SHA-256 digest")
        if type(self.source_index) is not int:
            raise TypeError("source_index must be an integer")
        if self.source_index < 0:
            raise ValueError("source_index must be non-negative")


def source_record_identity(
    source_format: object,
    source_sha256: object,
    source_index: object,
) -> SourceRecordIdentity:
    """Return a normalized source-record key without touching semantic identity."""

    if type(source_format) is not str:
        raise TypeError("source_format must be text")
    normalized_format = source_format.strip().lower()
    if not normalized_format:
        raise ValueError("source_format must not be blank")
    if type(source_sha256) is not str:
        raise TypeError("source_sha256 must be text")
    normalized_sha = source_sha256.lower()
    if _SHA256_RE.fullmatch(normalized_sha) is None:
        raise ValueError("source_sha256 must be a 64-character hexadecimal digest")
    if type(source_index) is not int:
        raise TypeError("source_index must be an integer")
    return SourceRecordIdentity(
        source_format=normalized_format,
        source_sha256=normalized_sha,
        source_index=source_index,
    )


@dataclass(frozen=True, slots=True)
class DuplicateMatch:
    kind: DuplicateKind
    existing_source_id: int
    existing_game_id: int | None = None
    incoming_game_index: int | None = None
    identity_schema_version: int | None = None
    digest: str | None = None
    existing_source_record: SourceRecordIdentity | None = None
    incoming_source_record: SourceRecordIdentity | None = None


@dataclass(frozen=True, slots=True)
class DuplicateReport:
    source_format: str
    source_sha256: str
    matches: tuple[DuplicateMatch, ...]

    @property
    def has_exact_source(self) -> bool:
        return any(match.kind == "exact_source" for match in self.matches)

    @property
    def has_semantic_duplicates(self) -> bool:
        return any(match.kind in {"record", "tree", "moves"} for match in self.matches)


def _stored_source_record(row) -> SourceRecordIdentity | None:
    sha256 = row["source_sha256"]
    source_format = row["source_format"]
    if not isinstance(sha256, str) or not isinstance(source_format, str):
        return None
    try:
        return source_record_identity(source_format, sha256, row["source_index"])
    except (TypeError, ValueError):
        # Legacy/corrupt provenance must not abort read-only duplicate reporting.
        # The semantic record is still inspectable, but no fabricated source key
        # is emitted for invalid source metadata.
        return None


def detect_pgn_duplicates(database: AcsDatabase, text: str) -> DuplicateReport:
    """Return deterministic duplicate evidence without mutating the database.

    Strengths, from strongest to weakest:

    ``exact_source``
        The exact PGN byte stream already exists under source format ``pgn``.
        Source equality uses ``(source_format, sha256)`` to match the canonical
        Library import boundary.
    ``record``
        Full GameTree content and semantic PGN tags are equal.
    ``tree``
        Full recursive chess/document content including comments/NAG/result is
        equal, but semantic tags differ. Both source records remain distinct.
    ``moves``
        Starting position plus recursive move/variation structure is equal while
        annotations, result and/or metadata differ. This is classification only:
        comments, NAGs, metadata and provenance must not be silently merged.

    The detector builds digest lookup maps once, avoiding the previous
    stored-games x incoming-games nested comparison. It still reparses stored PGN
    because no persistent semantic-identity index is owned by this component;
    introducing such an index requires a separately owned schema migration.
    """

    if not isinstance(database, AcsDatabase):
        raise TypeError("database must be an AcsDatabase")
    if type(text) is not str:
        raise TypeError("text must be PGN text")

    source_format = "pgn"
    source_sha256 = hashlib.sha256(text.encode("utf-8")).hexdigest()
    matches: list[DuplicateMatch] = []

    exact_sources = database.conn.execute(
        "SELECT id FROM sources WHERE source_format=? AND sha256=? ORDER BY id",
        (source_format, source_sha256),
    ).fetchall()
    matches.extend(
        DuplicateMatch(
            kind="exact_source",
            existing_source_id=int(row[0]),
            digest=source_sha256,
        )
        for row in exact_sources
    )

    incoming_games = parse_games(text)
    if not incoming_games:
        return DuplicateReport(
            source_format=source_format,
            source_sha256=source_sha256,
            matches=tuple(matches),
        )

    incoming_records: dict[str, list[tuple[int, SourceRecordIdentity]]] = {}
    incoming_trees: dict[str, list[tuple[int, SourceRecordIdentity]]] = {}
    incoming_moves: dict[str, list[tuple[int, SourceRecordIdentity]]] = {}
    for game in incoming_games:
        full_identity = identity_for_game(game)
        move_identity = move_identity_for_game(game)
        incoming_source_record = source_record_identity(
            source_format,
            source_sha256,
            game.source_index,
        )
        item = (int(game.source_index), incoming_source_record)
        incoming_records.setdefault(full_identity.record_digest, []).append(item)
        incoming_trees.setdefault(full_identity.tree_digest, []).append(item)
        incoming_moves.setdefault(move_identity.move_digest, []).append(item)

    stored_rows = database.conn.execute(
        """
        SELECT
            g.id,
            g.source_id,
            g.source_index,
            g.pgn_text,
            s.source_format,
            s.sha256 AS source_sha256
        FROM games AS g
        JOIN sources AS s ON s.id = g.source_id
        ORDER BY g.id
        """
    ).fetchall()

    for row in stored_rows:
        try:
            stored_games = parse_games(str(row["pgn_text"]))
            if len(stored_games) != 1:
                continue
            stored_full_identity = identity_for_game(stored_games[0])
            stored_move_identity = move_identity_for_game(stored_games[0])
        except Exception:
            # One malformed legacy row must not prevent duplicate inspection of
            # the remainder of the Library. No mutation or repair is attempted.
            continue

        existing_source_record = _stored_source_record(row)
        record_items = incoming_records.get(stored_full_identity.record_digest)
        tree_items = incoming_trees.get(stored_full_identity.tree_digest)
        move_items = incoming_moves.get(stored_move_identity.move_digest)

        if record_items:
            kind: DuplicateKind = "record"
            schema_version = IDENTITY_SCHEMA_VERSION
            digest = stored_full_identity.record_digest
            selected = record_items
        elif tree_items:
            kind = "tree"
            schema_version = IDENTITY_SCHEMA_VERSION
            digest = stored_full_identity.tree_digest
            selected = tree_items
        elif move_items:
            kind = "moves"
            schema_version = MOVE_IDENTITY_SCHEMA_VERSION
            digest = stored_move_identity.move_digest
            selected = move_items
        else:
            continue

        for incoming_index, incoming_source_record in selected:
            matches.append(
                DuplicateMatch(
                    kind=kind,
                    existing_source_id=int(row["source_id"]),
                    existing_game_id=int(row["id"]),
                    incoming_game_index=incoming_index,
                    identity_schema_version=schema_version,
                    digest=digest,
                    existing_source_record=existing_source_record,
                    incoming_source_record=incoming_source_record,
                )
            )

    return DuplicateReport(
        source_format=source_format,
        source_sha256=source_sha256,
        matches=tuple(matches),
    )
