from __future__ import annotations

"""Neutral duplicate detection for PGN/ACSDB records."""

from dataclasses import dataclass
import hashlib
import re
from typing import Literal

from .acsdb import AcsDatabase
from .game_identity import (
    IDENTITY_SCHEMA_VERSION,
    GameIdentityContractError,
    identity_for_game,
)
from .gametree import parse_games

DuplicateKind = Literal["exact_source", "record", "tree"]
_DUPLICATE_KINDS = frozenset({"exact_source", "record", "tree"})
_DIGEST_RE = re.compile(r"^[0-9a-f]{64}$")


@dataclass(frozen=True, slots=True)
class DuplicateMatch:
    kind: DuplicateKind
    existing_source_id: int
    existing_game_id: int | None = None
    incoming_game_index: int | None = None
    identity_schema_version: int | None = None
    digest: str | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.kind, str) or self.kind not in _DUPLICATE_KINDS:
            raise ValueError("duplicate kind is invalid")
        if type(self.existing_source_id) is not int or self.existing_source_id <= 0:
            raise ValueError("existing_source_id must be a positive integer")
        if not isinstance(self.digest, str) or _DIGEST_RE.fullmatch(self.digest) is None:
            raise ValueError("duplicate digest must be a lowercase SHA-256 digest")
        if self.kind == "exact_source":
            if any(
                value is not None
                for value in (
                    self.existing_game_id,
                    self.incoming_game_index,
                    self.identity_schema_version,
                )
            ):
                raise ValueError("exact-source matches cannot carry semantic identity fields")
            return
        if type(self.existing_game_id) is not int or self.existing_game_id <= 0:
            raise ValueError("semantic match existing_game_id must be positive")
        if type(self.incoming_game_index) is not int or self.incoming_game_index < 0:
            raise ValueError("semantic match incoming_game_index must be non-negative")
        if (
            type(self.identity_schema_version) is not int
            or self.identity_schema_version != IDENTITY_SCHEMA_VERSION
        ):
            raise ValueError("semantic match identity schema version is unsupported")


@dataclass(frozen=True, slots=True)
class DuplicateReport:
    source_sha256: str
    matches: tuple[DuplicateMatch, ...]
    skipped_stored_game_ids: tuple[int, ...] = ()

    def __post_init__(self) -> None:
        if (
            not isinstance(self.source_sha256, str)
            or _DIGEST_RE.fullmatch(self.source_sha256) is None
        ):
            raise ValueError("source_sha256 must be a lowercase SHA-256 digest")
        if (
            not isinstance(self.matches, tuple)
            or any(not isinstance(match, DuplicateMatch) for match in self.matches)
        ):
            raise TypeError("matches must be a tuple of DuplicateMatch")
        if any(
            match.kind == "exact_source" and match.digest != self.source_sha256
            for match in self.matches
        ):
            raise ValueError("exact-source match digest must equal report source digest")
        if (
            not isinstance(self.skipped_stored_game_ids, tuple)
            or any(
                type(game_id) is not int or game_id <= 0
                for game_id in self.skipped_stored_game_ids
            )
            or len(set(self.skipped_stored_game_ids))
            != len(self.skipped_stored_game_ids)
        ):
            raise TypeError("skipped stored game IDs must be unique positive integers")

    @property
    def has_exact_source(self) -> bool:
        return any(match.kind == "exact_source" for match in self.matches)

    @property
    def has_semantic_duplicates(self) -> bool:
        return any(match.kind in {"record", "tree"} for match in self.matches)

    @property
    def has_incomplete_evidence(self) -> bool:
        return bool(self.skipped_stored_game_ids)


def detect_pgn_duplicates(database: AcsDatabase, text: str) -> DuplicateReport:
    """Return duplicate evidence without mutating the database.

    Exact-source matches use persisted SHA-256 provenance. Semantic matches use
    the versioned neutral GameTree identity. ``record`` is stronger than
    ``tree``; a tree-only match means recursive chess/document content is equal
    while semantic tags differ. No row is deleted or silently coalesced.
    """
    if not isinstance(database, AcsDatabase):
        raise TypeError("database must be AcsDatabase")
    if not isinstance(text, str):
        raise TypeError("text must be PGN text")
    source_sha256 = hashlib.sha256(text.encode("utf-8")).hexdigest()
    matches: list[DuplicateMatch] = []
    skipped_stored_game_ids: list[int] = []

    exact_sources = database.conn.execute(
        "SELECT id FROM sources WHERE sha256=? ORDER BY id", (source_sha256,)
    ).fetchall()
    matches.extend(
        DuplicateMatch(
            kind="exact_source",
            existing_source_id=row[0],
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
        stored_game_id = row["id"]
        if type(stored_game_id) is not int or stored_game_id <= 0:
            continue
        stored_text = row["pgn_text"]
        if not isinstance(stored_text, str):
            skipped_stored_game_ids.append(stored_game_id)
            continue
        try:
            stored_games = parse_games(stored_text)
        except Exception:
            skipped_stored_game_ids.append(stored_game_id)
            continue
        if len(stored_games) != 1:
            skipped_stored_game_ids.append(stored_game_id)
            continue
        try:
            stored_identity = identity_for_game(stored_games[0])
        except GameIdentityContractError:
            skipped_stored_game_ids.append(stored_game_id)
            continue
        for incoming_index, incoming_identity in incoming:
            if stored_identity.record_digest == incoming_identity.record_digest:
                matches.append(
                    DuplicateMatch(
                        kind="record",
                        existing_source_id=row["source_id"],
                        existing_game_id=stored_game_id,
                        incoming_game_index=incoming_index,
                        identity_schema_version=IDENTITY_SCHEMA_VERSION,
                        digest=incoming_identity.record_digest,
                    )
                )
            elif stored_identity.tree_digest == incoming_identity.tree_digest:
                matches.append(
                    DuplicateMatch(
                        kind="tree",
                        existing_source_id=row["source_id"],
                        existing_game_id=stored_game_id,
                        incoming_game_index=incoming_index,
                        identity_schema_version=IDENTITY_SCHEMA_VERSION,
                        digest=incoming_identity.tree_digest,
                    )
                )

    return DuplicateReport(
        source_sha256=source_sha256,
        matches=tuple(matches),
        skipped_stored_game_ids=tuple(skipped_stored_game_ids),
    )
