from __future__ import annotations

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
from .gametree import PgnGame
from .pgn_roundtrip import PgnRoundTripError, parse_pgn_text

_SQLITE_INTEGER_MAX = (1 << 63) - 1


class BookLibraryGameLookupError(LookupError):
    """Stable failure for the Books -> Library referenced-game adapter."""


class AcsdbBookGameLookup:
    """Resolve one Book ``game_id`` through the existing ACSDB read contract."""

    def __init__(self, database: AcsDatabase) -> None:
        if not isinstance(database, AcsDatabase):
            raise TypeError("database must be an AcsDatabase")
        self._database = database

    @staticmethod
    def _game_id(value: object) -> int:
        if type(value) is not int:
            raise BookLibraryGameLookupError("book game identity is invalid")
        if value < 0 or value > _SQLITE_INTEGER_MAX:
            raise BookLibraryGameLookupError("book game identity is invalid")
        return value

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
        except Exception as exc:
            raise BookLibraryGameLookupError("book game lookup failed") from exc

        if row is None:
            raise BookLibraryGameLookupError("book game was not found")
        if type(row) is not dict or type(row.get("id")) is not int or row["id"] != identity:
            raise BookLibraryGameLookupError("stored book game identity is invalid")

        source_index = row.get("source_index")
        if type(source_index) is not int or source_index < 0 or source_index > _SQLITE_INTEGER_MAX:
            raise BookLibraryGameLookupError("stored book game identity is invalid")

        pgn_text = row.get("pgn_text")
        if type(pgn_text) is not str or not pgn_text.strip():
            raise BookLibraryGameLookupError("stored book game is not canonical")

        try:
            games = parse_pgn_text(pgn_text, strict=False)
        except (PgnRoundTripError, RecursionError) as exc:
            raise BookLibraryGameLookupError("stored book game is not canonical") from exc
        if len(games) != 1:
            raise BookLibraryGameLookupError("stored book game must contain exactly one game")

        game = games[0]
        game.source_index = source_index
        return game
