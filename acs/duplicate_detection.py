from __future__ import annotations

"""Neutral duplicate detection for PGN/ACSDB records.

The service deliberately separates source-byte identity from semantic game
identity. Exact-source matches use the already indexed ``sources.sha256`` value;
semantic matches are derived from versioned ``GameTree`` identities and never
from SQLite row ids, PGN whitespace, or UI state.

No duplicate is deleted or silently coalesced. Callers receive evidence and can
choose policy at the application layer.
"""

from dataclasses import dataclass
import hashlib
from typing import Literal

from .acsdb import AcsDatabase
from .game_identity import IDENTITY_SCHEMA_VERSION, identity_for_game
from .gametree import parse_games

DuplicateKind = Literal["exact_source", "record", "tree"]


@dataclass(frozen=True, slots=True)
class DuplicateMatch:
    kind: DuplicateKind
    existing_source_id: int
    existing_game_id: int | None = None
    incoming_game_index: int | None = None
    identity_schema_version: int | None = None
    digest: str | None = None


@dataclass(frozen=True, slots=True)
class DuplicateReport:
    source_sha256: str
    matches: tuple[DuplicateMatch, ...]

    @property
    def has_exact_source(self) -> bool:
        return any(match.kind == "exact_source" for match in self.matches)

    @property
    def has_semantic_duplicates(self) -> bool:
        return any(match.kind in {"record", "tree"} for match in self.matches)


def detect_pgn_duplicates(database: AcsDatabase, text: str) -> DuplicateReport:
    """Return duplicate evidence without mutating the database.

    ``record`` is stronger than ``tree``: when record identity matches, only a
    record match is emitted for that pair. A tree match therefore means the
    recursive chess/document content is equal while semantic tags differ.
    Malformed stored PGN is skipped rather than guessed at; its import warning
    remains the authoritative quality signal in ACSDB.
    """

    source_sha256 = hashlib.sha256(text.encode("utf-8")).hexdigest()
    matches: list[DuplicateMatch] = []

    exact_sources = database.conn.execute(
        "SELECT id FROM sources WHERE sha256=? ORDER BY id", (source_sha256,)
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
        return DuplicateReport(source_sha256=source_sha256, matches=tuple(matches))

    incoming = [(game.source_index, identity_for_game(game)) for game in incoming_games]
    stored_rows = database.conn.execute(
        "SELECT id, source_id, pgn_text FROM games ORDER BY id"
    ).fetchall()

    for row in stored_rows:
        try:
            stored_games = parse_games(str(row["pgn_text"]))
        except Exception:
            continue
        if len(stored_games) != 1:
            continue
        stored_identity = identity_for_game(stored_games[0])
        for incoming_index, incoming_identity in incoming:
            if stored_identity.record_digest == incoming_identity.record_digest:
                matches.append(
                    DuplicateMatch(
                        kind="record",
                        existing_source_id=int(row["source_id"]),
                        existing_game_id=int(row["id"]),
                        incoming_game_index=int(incoming_index),
                        identity_schema_version=IDENTITY_SCHEMA_VERSION,
                        digest=incoming_identity.record_digest,
                    )
                )
            elif stored_identity.tree_digest == incoming_identity.tree_digest:
                matches.append(
                    DuplicateMatch(
                        kind="tree",
                        existing_source_id=int(row["source_id"]),
                        existing_game_id=int(row["id"]),
                        incoming_game_index=int(incoming_index),
                        identity_schema_version=IDENTITY_SCHEMA_VERSION,
                        digest=incoming_identity.tree_digest,
                    )
                )

    return DuplicateReport(source_sha256=source_sha256, matches=tuple(matches))
