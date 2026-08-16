from __future__ import annotations

"""Indexed duplicate detection for PGN/ACSDB records.

Exact-source identity and versioned semantic identities are queried from ACSDB
indexes. No duplicate is deleted or silently coalesced; callers choose import
policy explicitly.
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
    source_sha256 = hashlib.sha256(text.encode("utf-8")).hexdigest()
    matches: list[DuplicateMatch] = []

    for row in database.conn.execute(
        "SELECT id FROM sources WHERE sha256=? ORDER BY id", (source_sha256,)
    ).fetchall():
        matches.append(
            DuplicateMatch(
                kind="exact_source",
                existing_source_id=int(row[0]),
                digest=source_sha256,
            )
        )

    for game in parse_games(text):
        identity = identity_for_game(game)
        record_rows = database.conn.execute(
            """
            SELECT c.game_id, g.source_id
            FROM game_catalog c JOIN games g ON g.id=c.game_id
            WHERE c.identity_schema_version=? AND c.record_digest=?
            ORDER BY c.game_id
            """,
            (IDENTITY_SCHEMA_VERSION, identity.record_digest),
        ).fetchall()
        if record_rows:
            for row in record_rows:
                matches.append(
                    DuplicateMatch(
                        kind="record",
                        existing_source_id=int(row["source_id"]),
                        existing_game_id=int(row["game_id"]),
                        incoming_game_index=int(game.source_index),
                        identity_schema_version=IDENTITY_SCHEMA_VERSION,
                        digest=identity.record_digest,
                    )
                )
            continue

        for row in database.conn.execute(
            """
            SELECT c.game_id, g.source_id
            FROM game_catalog c JOIN games g ON g.id=c.game_id
            WHERE c.identity_schema_version=? AND c.tree_digest=?
            ORDER BY c.game_id
            """,
            (IDENTITY_SCHEMA_VERSION, identity.tree_digest),
        ).fetchall():
            matches.append(
                DuplicateMatch(
                    kind="tree",
                    existing_source_id=int(row["source_id"]),
                    existing_game_id=int(row["game_id"]),
                    incoming_game_index=int(game.source_index),
                    identity_schema_version=IDENTITY_SCHEMA_VERSION,
                    digest=identity.tree_digest,
                )
            )

    return DuplicateReport(source_sha256=source_sha256, matches=tuple(matches))
