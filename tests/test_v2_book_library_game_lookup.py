from __future__ import annotations

import unittest

from acs.acsdb import AcsDatabase
from acs.book_game_content import (
    BookGameContentError,
    BookGameContentErrorCode,
    BookGameSource,
    resolve_book_game,
)
from acs.book_library_game_lookup import (
    AcsdbBookGameLookup,
    BookLibraryGameLookupError,
)
from acs.bookdocument import Game
from acs.gametree import serialize_game
from acs.pgn_roundtrip import parse_pgn_text


REALISTIC_PGN = '''[Event "Book reference"]
[Site "Kyiv"]
[Result "*"]

1. e4?! {Main comment} (1. d4 $1 {Alternative}) e5 *
'''


class BookLibraryGameLookupTests(unittest.TestCase):
    def _stored_game(
        self,
        database: AcsDatabase,
        *,
        raw_pgn: str = REALISTIC_PGN,
        source_index: int = 37,
    ) -> int:
        source_id = database.add_source("referenced-library.pgn", "pgn", "a" * 64)
        game = parse_pgn_text(raw_pgn, strict=False)[0]
        game.source_index = source_index
        return database.store_game(game, source_id, raw_pgn=raw_pgn)

    def test_reference_resolves_through_public_acsdb_read_and_canonical_d06_ingress(self) -> None:
        with AcsDatabase() as database:
            game_id = self._stored_game(database)
            lookup = AcsdbBookGameLookup(database)
            changes_before = database.conn.total_changes

            resolved = resolve_book_game(
                Game(game_id=game_id, title="Library reference", block_id="g-ref"),
                lookup=lookup,
            )

            self.assertEqual(database.conn.total_changes, changes_before)
            self.assertEqual(resolved.source, BookGameSource.REFERENCE)
            self.assertEqual(resolved.game_id, game_id)
            self.assertEqual(resolved.block_id, "g-ref")
            self.assertEqual(resolved.game.source_index, 37)
            first = resolved.game.line.moves[0]
            self.assertEqual(first.san, "e4")
            self.assertIn("?!", first.nags)
            self.assertEqual(first.comments_after[0].text, "Main comment")
            self.assertEqual(first.variations[0].moves[0].san, "d4")
            self.assertIn("$1", first.variations[0].moves[0].nags)
            self.assertIn("{Alternative}", serialize_game(resolved.game))

    def test_each_load_returns_a_fresh_canonical_graph(self) -> None:
        with AcsDatabase() as database:
            game_id = self._stored_game(database)
            lookup = AcsdbBookGameLookup(database)

            first = lookup.load_book_game(game_id)
            second = lookup.load_book_game(game_id)
            self.assertIsNot(first, second)
            self.assertIsNot(first.line, second.line)
            first.line.moves[0].san = "mutated"
            self.assertEqual(second.line.moves[0].san, "e4")

    def test_missing_and_invalid_identities_fail_before_any_book_guessing(self) -> None:
        with AcsDatabase() as database:
            lookup = AcsdbBookGameLookup(database)
            for invalid in (True, False, "1", 1.0, -1, 1 << 63):
                with self.subTest(value=invalid):
                    with self.assertRaises(BookLibraryGameLookupError):
                        lookup.load_book_game(invalid)  # type: ignore[arg-type]

            with self.assertRaises(BookLibraryGameLookupError) as missing:
                lookup.load_book_game(404)
            self.assertEqual(str(missing.exception), "book game was not found")

    def test_one_library_row_cannot_expand_into_multiple_book_games(self) -> None:
        with AcsDatabase() as database:
            game_id = self._stored_game(database)
            multi = '''[Event "One"]\n[Result "*"]\n\n1. e4 *\n\n[Event "Two"]\n[Result "*"]\n\n1. d4 *\n'''
            with database.conn:
                database.conn.execute(
                    "UPDATE games SET pgn_text=? WHERE id=?",
                    (multi, game_id),
                )

            with self.assertRaises(BookLibraryGameLookupError) as caught:
                AcsdbBookGameLookup(database).load_book_game(game_id)
            self.assertEqual(
                str(caught.exception),
                "stored book game must contain exactly one game",
            )

    def test_corrupt_library_identity_and_empty_pgn_fail_closed(self) -> None:
        with AcsDatabase() as database:
            game_id = self._stored_game(database)
            lookup = AcsdbBookGameLookup(database)

            with database.conn:
                database.conn.execute(
                    "UPDATE games SET source_index=-1 WHERE id=?",
                    (game_id,),
                )
            with self.assertRaises(BookLibraryGameLookupError) as identity:
                lookup.load_book_game(game_id)
            self.assertEqual(str(identity.exception), "stored book game identity is invalid")

            with database.conn:
                database.conn.execute(
                    "UPDATE games SET source_index=37, pgn_text='   ' WHERE id=?",
                    (game_id,),
                )
            with self.assertRaises(BookLibraryGameLookupError) as empty:
                lookup.load_book_game(game_id)
            self.assertEqual(str(empty.exception), "stored book game is not canonical")

    def test_database_failure_is_sanitized_and_book_boundary_stays_public(self) -> None:
        database = AcsDatabase()
        game_id = self._stored_game(database)
        lookup = AcsdbBookGameLookup(database)
        database.close()

        with self.assertRaises(BookLibraryGameLookupError) as direct:
            lookup.load_book_game(game_id)
        self.assertEqual(str(direct.exception), "book game lookup failed")
        self.assertNotIn("closed database", str(direct.exception).lower())
        self.assertNotIn("sqlite", str(direct.exception).lower())

        with self.assertRaises(BookGameContentError) as public:
            resolve_book_game(Game(game_id=game_id), lookup=lookup)
        self.assertEqual(public.exception.code, BookGameContentErrorCode.GAME_NOT_FOUND)
        self.assertEqual(str(public.exception), "referenced book game was not found")

    def test_constructor_rejects_noncanonical_database_adapter(self) -> None:
        with self.assertRaises(TypeError):
            AcsdbBookGameLookup(object())  # type: ignore[arg-type]


if __name__ == "__main__":
    unittest.main()
