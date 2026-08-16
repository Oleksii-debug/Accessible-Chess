from __future__ import annotations

"""High-volume ACSDB catalog/search layer.

This module extends the stable v2 AcsDatabase without duplicating PGN parsing.
Canonical PGN structure comes from acs.gametree / acs.pgn_workspace.  The catalog
adds normalized reference entities, deterministic duplicate fingerprints, exact
GameTree retrieval, indexed metadata/comment search, and atomic bulk collection
import.  External sources remain read-only.
"""

from dataclasses import dataclass, field
import hashlib
import json
import sqlite3
from typing import Iterable

from .acsdb import AcsDatabase
from .gametree import PgnGame, parse_games, serialize_game
from .pgn_workspace import PgnWorkspace

CATALOG_SCHEMA_VERSION = 1


@dataclass(slots=True)
class BulkImportOutcome:
    source_id: int
    inserted_game_ids: list[int] = field(default_factory=list)
    duplicate_game_ids: list[int] = field(default_factory=list)
    failed: list[dict] = field(default_factory=list)

    @property
    def inserted(self) -> int:
        return len(self.inserted_game_ids)

    @property
    def duplicates(self) -> int:
        return len(self.duplicate_game_ids)


class AcsCatalogDatabase(AcsDatabase):
    """Versioned catalog/search repository layered on the stable ACSDB schema."""

    def __init__(self, path: str = ":memory:") -> None:
        super().__init__(path)
        self._migrate_catalog()

    def _migrate_catalog(self) -> None:
        with self.conn:
            self.conn.execute(
                "CREATE TABLE IF NOT EXISTS catalog_meta(key TEXT PRIMARY KEY, value TEXT NOT NULL)"
            )
            row = self.conn.execute(
                "SELECT value FROM catalog_meta WHERE key='schema_version'"
            ).fetchone()
            current = int(row[0]) if row else 0
            if current > CATALOG_SCHEMA_VERSION:
                raise RuntimeError(
                    f"ACSDB catalog schema {current} is newer than supported {CATALOG_SCHEMA_VERSION}"
                )
            if current < 1:
                self.conn.executescript(
                    """
                    CREATE TABLE catalog_entities(
                        id INTEGER PRIMARY KEY,
                        kind TEXT NOT NULL CHECK(kind IN ('player','event','annotator','opening')),
                        name TEXT NOT NULL,
                        normalized_name TEXT NOT NULL,
                        UNIQUE(kind, normalized_name)
                    );
                    CREATE TABLE game_entities(
                        game_id INTEGER NOT NULL REFERENCES games(id) ON DELETE CASCADE,
                        entity_id INTEGER NOT NULL REFERENCES catalog_entities(id) ON DELETE CASCADE,
                        role TEXT NOT NULL,
                        PRIMARY KEY(game_id, entity_id, role)
                    );
                    CREATE TABLE game_fingerprints(
                        game_id INTEGER PRIMARY KEY REFERENCES games(id) ON DELETE CASCADE,
                        fingerprint TEXT NOT NULL UNIQUE
                    );
                    CREATE TABLE game_search(
                        game_id INTEGER PRIMARY KEY REFERENCES games(id) ON DELETE CASCADE,
                        text_content TEXT NOT NULL
                    );
                    CREATE INDEX idx_catalog_entity_kind_name
                        ON catalog_entities(kind, normalized_name);
                    CREATE INDEX idx_game_entities_entity ON game_entities(entity_id, game_id);
                    CREATE INDEX idx_game_search_game ON game_search(game_id);
                    """
                )
                self.conn.execute(
                    "INSERT OR REPLACE INTO catalog_meta(key,value) VALUES('schema_version','1')"
                )

    @staticmethod
    def _norm(value: str | None) -> str:
        return " ".join((value or "").casefold().split())

    @staticmethod
    def game_fingerprint(game: PgnGame) -> str:
        # Canonical serializer is intentionally reused; source index/provenance is excluded.
        canonical = serialize_game(game).encode("utf-8")
        return hashlib.sha256(canonical).hexdigest()

    def _entity(self, kind: str, name: str) -> int:
        normalized = self._norm(name)
        self.conn.execute(
            "INSERT OR IGNORE INTO catalog_entities(kind,name,normalized_name) VALUES(?,?,?)",
            (kind, name, normalized),
        )
        row = self.conn.execute(
            "SELECT id FROM catalog_entities WHERE kind=? AND normalized_name=?",
            (kind, normalized),
        ).fetchone()
        return int(row[0])

    def _index_game(self, game_id: int, game: PgnGame, fingerprint: str) -> None:
        tags = game.tags
        refs = (
            ("player", tags.get("White"), "white"),
            ("player", tags.get("Black"), "black"),
            ("event", tags.get("Event"), "event"),
            ("annotator", tags.get("Annotator"), "annotator"),
            ("opening", tags.get("Opening") or tags.get("ECO"), "opening"),
        )
        for kind, value, role in refs:
            if value:
                entity_id = self._entity(kind, value)
                self.conn.execute(
                    "INSERT OR IGNORE INTO game_entities(game_id,entity_id,role) VALUES(?,?,?)",
                    (game_id, entity_id, role),
                )
        searchable = serialize_game(game)
        self.conn.execute(
            "INSERT INTO game_fingerprints(game_id,fingerprint) VALUES(?,?)",
            (game_id, fingerprint),
        )
        self.conn.execute(
            "INSERT INTO game_search(game_id,text_content) VALUES(?,?)",
            (game_id, searchable),
        )

    def import_collection_atomic(
        self,
        text: str,
        *,
        source_name: str = "collection.pgn",
        reject_duplicates: bool = False,
    ) -> BulkImportOutcome:
        """Atomically import a complete PGN collection and build all catalog indexes.

        Duplicate games are reported and skipped.  With reject_duplicates=True the
        entire transaction fails instead.  Parser diagnostics stay in canonical
        PgnGame warnings; no malformed evidence is silently rewritten.
        """
        digest = hashlib.sha256(text.encode("utf-8")).hexdigest()
        games = parse_games(text)
        if not games:
            raise ValueError("PGN collection contains no games")
        outcome = BulkImportOutcome(source_id=-1)
        with self.conn:
            source_id = self._insert_source(source_name, "pgn", digest)
            outcome.source_id = source_id
            for game in games:
                fp = self.game_fingerprint(game)
                duplicate = self.conn.execute(
                    "SELECT game_id FROM game_fingerprints WHERE fingerprint=?", (fp,)
                ).fetchone()
                if duplicate:
                    if reject_duplicates:
                        raise ValueError(f"duplicate game fingerprint {fp}")
                    outcome.duplicate_game_ids.append(int(duplicate[0]))
                    continue
                status = "warning" if game.warnings else "full"
                game_id = self._insert_game(game, source_id, import_status=status)
                self._index_game(game_id, game, fp)
                outcome.inserted_game_ids.append(game_id)
        return outcome

    def import_many_atomic(
        self,
        sources: Iterable[tuple[str, str]],
        *,
        reject_duplicates: bool = False,
    ) -> list[BulkImportOutcome]:
        """Import many independent sources in one transaction.

        This is deliberately all-or-nothing for database consistency. Callers that
        need fault isolation should call import_collection_atomic per source and keep
        their own source-level report; one malformed proprietary sample must not block
        unrelated work outside this transaction.
        """
        outcomes: list[BulkImportOutcome] = []
        with self.conn:
            for source_name, text in sources:
                outcomes.append(
                    self.import_collection_atomic(
                        text, source_name=source_name, reject_duplicates=reject_duplicates
                    )
                )
        return outcomes

    def retrieve_game_tree(self, game_id: int) -> PgnGame:
        row = self.conn.execute("SELECT pgn_text FROM games WHERE id=?", (int(game_id),)).fetchone()
        if not row:
            raise KeyError(f"unknown game id {game_id}")
        games = parse_games(str(row[0]))
        if len(games) != 1:
            raise RuntimeError(f"stored game {game_id} is corrupt: expected one PGN game")
        return games[0]

    def search_catalog(
        self,
        *,
        player: str | None = None,
        event: str | None = None,
        annotator: str | None = None,
        opening: str | None = None,
        text: str | None = None,
        source_id: int | None = None,
        limit: int = 100,
        offset: int = 0,
    ) -> list[dict]:
        clauses: list[str] = []
        params: list[object] = []
        aliases = (("player", player), ("event", event), ("annotator", annotator), ("opening", opening))
        for kind, value in aliases:
            if value:
                clauses.append(
                    "EXISTS (SELECT 1 FROM game_entities ge JOIN catalog_entities ce ON ce.id=ge.entity_id "
                    "WHERE ge.game_id=g.id AND ce.kind=? AND ce.normalized_name LIKE ?)"
                )
                params.extend((kind, f"%{self._norm(value)}%"))
        if text:
            clauses.append("LOWER(gs.text_content) LIKE ?")
            params.append(f"%{text.casefold()}%")
        if source_id is not None:
            clauses.append("g.source_id=?")
            params.append(int(source_id))
        sql = (
            "SELECT g.*, gf.fingerprint FROM games g "
            "JOIN game_fingerprints gf ON gf.game_id=g.id "
            "JOIN game_search gs ON gs.game_id=g.id"
        )
        if clauses:
            sql += " WHERE " + " AND ".join(clauses)
        sql += " ORDER BY g.id LIMIT ? OFFSET ?"
        params.extend((max(1, min(int(limit), 5000)), max(0, int(offset))))
        return [dict(row) for row in self.conn.execute(sql, params).fetchall()]

    def duplicate_groups(self, fingerprints: Iterable[str]) -> dict[str, int]:
        result: dict[str, int] = {}
        for fp in fingerprints:
            row = self.conn.execute(
                "SELECT game_id FROM game_fingerprints WHERE fingerprint=?", (fp,)
            ).fetchone()
            if row:
                result[fp] = int(row[0])
        return result

    def integrity_report(self) -> dict:
        quick = str(self.conn.execute("PRAGMA quick_check").fetchone()[0])
        foreign = [tuple(row) for row in self.conn.execute("PRAGMA foreign_key_check").fetchall()]
        return {
            "quick_check": quick,
            "foreign_key_errors": foreign,
            "schema_version": self.schema_version,
            "catalog_schema_version": int(
                self.conn.execute(
                    "SELECT value FROM catalog_meta WHERE key='schema_version'"
                ).fetchone()[0]
            ),
            "games": int(self.conn.execute("SELECT COUNT(*) FROM games").fetchone()[0]),
            "indexed_games": int(self.conn.execute("SELECT COUNT(*) FROM game_fingerprints").fetchone()[0]),
        }
