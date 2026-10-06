from __future__ import annotations

import json

"""Books-side adapter for resolving referenced Library games.

The semantic Book model identifies a Library game by the opaque ``games.id`` value
already stored in ACSDB.  This adapter implements :class:`BookGameLookup` without
moving SQL, schema, PGN parsing, or chess rules into Books: it calls only the
existing public :meth:`AcsDatabase.get_game` read API, then routes the stored PGN
through the existing bounded D06 ingress parser.

Database/provider details are deliberately kept behind a stable ``LookupError``
boundary.  The higher-level Book resolver already turns that boundary into a
presentation-safe Book error.
"""

from .acsdb import AcsDatabase
from .bookdocument import Game
from .game_identity import identity_for_game
from .gametree import GameTreeSerializationError, PgnGame, serialize_game
from .pgn_roundtrip import (
    MAX_PGN_LEXICAL_TOKENS,
    MAX_PGN_TEXT_CHARS,
    MAX_PGN_TOKEN_CHARS,
    PgnRoundTripError,
    parse_pgn_text,
)

_SQLITE_INTEGER_MAX = (1 << 63) - 1


class BookLibraryGameLookupError(LookupError):
    """Stable failure for the Books -> Library referenced-game adapter."""


class AcsdbBookGameLookup:
    """Resolve one Book ``game_id`` through the existing ACSDB read contract."""

    def __init__(self, database: AcsDatabase) -> None:
        if type(database) is not AcsDatabase:
            # This adapter owns a concrete ACSDB trust boundary, not an extensible
            # provider interface. Reject subclasses before later get_game()
            # dispatch can execute provider-defined code inside the Books ingress.
            raise TypeError("database must be an AcsDatabase")
        self._database = database

    @staticmethod
    def _game_id(value: object) -> int:
        if type(value) is not int:
            raise BookLibraryGameLookupError("book game identity is invalid")
        if value < 0 or value > _SQLITE_INTEGER_MAX:
            raise BookLibraryGameLookupError("book game identity is invalid")
        return value

    @staticmethod
    def _stored_warnings(row: dict) -> list[str]:
        raw = row.get("warnings_json")
        if type(raw) is not str or len(raw) > MAX_PGN_TEXT_CHARS:
            raise BookLibraryGameLookupError("stored book game warnings are invalid")
        try:
            warnings = json.loads(raw)
        except (ValueError, RecursionError):
            # json.loads() can raise ValueError for syntactically JSON input whose
            # integer conversion breaches Python's bounded decimal-digit guard.
            # Corrupt persisted diagnostics must stay behind the same sanitized
            # Books -> Library boundary as ordinary JSON syntax/depth failures.
            raise BookLibraryGameLookupError(
                "stored book game warnings are invalid"
            ) from None
        if (
            type(warnings) is not list
            or len(warnings) > MAX_PGN_LEXICAL_TOKENS
            or any(
                type(item) is not str
                or len(item) > MAX_PGN_TOKEN_CHARS
                or not item.strip()
                or "\x00" in item
                or any(0xD800 <= ord(character) <= 0xDFFF for character in item)
                for item in warnings
            )
        ):
            raise BookLibraryGameLookupError("stored book game warnings are invalid")
        return list(warnings)

    @staticmethod
    def _merge_warnings(
        persisted: list[str],
        reparsed: list[str],
    ) -> list[str]:
        if not persisted:
            return list(reparsed)
        merged = list(persisted)
        seen = set(persisted)
        for warning in reparsed:
            if warning not in seen:
                merged.append(warning)
                seen.add(warning)
        return merged

    def load_book_game(self, game_id: int) -> PgnGame:
        """Return one canonical GameTree game for an ACSDB ``games.id``.

        The stored PGN may be loss-aware/recovery input rather than strict output,
        so it intentionally uses D06 ``strict=False`` ingress.  Exactly one game
        must result: a Library row can never silently expand into multiple Book
        games.  ``source_index`` is restored from the Library row because parsing
        one isolated stored PGN naturally numbers it zero even when it originated
        later in a multi-game source.
        """

        identity = self._game_id(game_id)
        try:
            row = self._database.get_game(identity)
        except Exception:
            raise BookLibraryGameLookupError("book game lookup failed") from None

        if row is None:
            raise BookLibraryGameLookupError("book game was not found")
        if type(row) is not dict or type(row.get("id")) is not int or row["id"] != identity:
            raise BookLibraryGameLookupError("stored book game identity is invalid")

        source_index = row.get("source_index")
        if type(source_index) is not int or source_index < 0 or source_index > _SQLITE_INTEGER_MAX:
            raise BookLibraryGameLookupError("stored book game identity is invalid")

        pgn_text = row.get("pgn_text")
        # Bound the exact stored scalar before strip(), warning JSON decoding or
        # D06 parsing. A corrupt database row must not force a full scan/allocation
        # elsewhere in the record before its primary game payload is rejected.
        if type(pgn_text) is not str or len(pgn_text) > MAX_PGN_TEXT_CHARS:
            raise BookLibraryGameLookupError("stored book game is not canonical")
        if not pgn_text.strip():
            raise BookLibraryGameLookupError("stored book game is not canonical")

        persisted_warnings = self._stored_warnings(row)

        try:
            games = parse_pgn_text(pgn_text, strict=False)
        except (PgnRoundTripError, RecursionError):
            raise BookLibraryGameLookupError("stored book game is not canonical") from None
        if len(games) != 1:
            raise BookLibraryGameLookupError("stored book game must contain exactly one game")

        game = games[0]
        game.source_index = source_index
        game.warnings = self._merge_warnings(persisted_warnings, game.warnings)
        try:
            serialize_game(game)
        except GameTreeSerializationError:
            raise BookLibraryGameLookupError("stored book game is not canonical") from None
        return game

    def make_book_reference(self, game_id: int, *, title: str | None = None,
                            block_id: str | None = None, source_anchor: str | None = None) -> Game:
        """Bind authoring material to the canonical record, not only a local row ID.

        Legacy ID-only blocks remain database-local for compatibility. New
        references created here fail closed if that ID is reused or edited.
        """
        game = self.load_book_game(game_id)
        return Game(game_id=game_id, game_record_digest=identity_for_game(game).record_digest,
                    title=title, block_id=block_id, source_anchor=source_anchor)
