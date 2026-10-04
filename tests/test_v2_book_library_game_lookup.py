from __future__ import annotations

import json
import traceback
from pathlib import Path
import unittest
from unittest import mock

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

    def test_imported_recovery_warnings_survive_canonical_storage_and_book_lookup(self) -> None:
        damaged = '[Event "Recovered"]\n[Result "*"]\n\n1. e4 e5'
        with AcsDatabase() as database:
            report = database.import_pgn_text(damaged, "recovered-library.pgn")
            self.assertEqual(report.warning, 1)
            self.assertEqual(len(report.game_ids), 1)

            row = database.get_game(report.game_ids[0])
            self.assertIsNotNone(row)
            assert row is not None
            persisted = json.loads(row["warnings_json"])
            self.assertTrue(persisted)
            self.assertFalse(
                parse_pgn_text(row["pgn_text"], strict=False)[0].warnings,
                "canonical stored PGN should not be the only warning authority",
            )

            lookup = AcsdbBookGameLookup(database)
            loaded = lookup.load_book_game(report.game_ids[0])
            self.assertEqual(loaded.warnings, persisted)

            resolved = resolve_book_game(
                Game(game_id=report.game_ids[0], block_id="recovered-ref"),
                lookup=lookup,
            )
            self.assertEqual(resolved.warnings, tuple(persisted))
            self.assertEqual(resolved.game.warnings, persisted)

    def test_raw_recovery_warnings_are_not_duplicated_when_metadata_agrees(self) -> None:
        damaged = '[Event "Raw recovery"]\n[Result "*"]\n\n1. d4 d5'
        with AcsDatabase() as database:
            source_id = database.add_source("raw-recovery.pgn", "pgn", "b" * 64)
            recovered = parse_pgn_text(damaged, strict=False)[0]
            self.assertTrue(recovered.warnings)
            game_id = database.store_game(recovered, source_id, raw_pgn=damaged)

            loaded = AcsdbBookGameLookup(database).load_book_game(game_id)
            self.assertEqual(loaded.warnings, recovered.warnings)

    def test_fresh_stored_pgn_recovery_warning_is_retained_when_metadata_is_empty(self) -> None:
        damaged = '[Event "Fresh recovery"]\n[Result "*"]\n\n1. c4 e5'
        with AcsDatabase() as database:
            game_id = self._stored_game(database)
            with database.conn:
                database.conn.execute(
                    "UPDATE games SET pgn_text=?, warnings_json='[]' WHERE id=?",
                    (damaged, game_id),
                )

            loaded = AcsdbBookGameLookup(database).load_book_game(game_id)
            self.assertTrue(loaded.warnings)
            self.assertEqual(
                loaded.warnings,
                parse_pgn_text(damaged, strict=False)[0].warnings,
            )

    def test_corrupt_persisted_warning_metadata_fails_closed(self) -> None:
        malformed = (
            "{",
            '{"warning":"not-a-list"}',
            '["text", 7]',
            '["\\ud800"]',
            "null",
        )
        with AcsDatabase() as database:
            game_id = self._stored_game(database)
            lookup = AcsdbBookGameLookup(database)

            for payload in malformed:
                with self.subTest(payload=payload):
                    with database.conn:
                        database.conn.execute(
                            "UPDATE games SET warnings_json=? WHERE id=?",
                            (payload, game_id),
                        )
                    with self.assertRaises(BookLibraryGameLookupError) as caught:
                        lookup.load_book_game(game_id)
                    self.assertEqual(
                        str(caught.exception),
                        "stored book game warnings are invalid",
                    )
                    self.assertIsNone(caught.exception.__cause__)
                    rendered = "".join(traceback.format_exception(caught.exception))
                    self.assertNotIn(payload, rendered)

    def test_warning_metadata_respects_canonical_pgn_resource_bounds(self) -> None:
        cases = (
            ("MAX_PGN_TEXT_CHARS", 4, '["x"]'),
            ("MAX_PGN_LEXICAL_TOKENS", 1, '["one","two"]'),
            ("MAX_PGN_TOKEN_CHARS", 3, '["four"]'),
        )
        with AcsDatabase() as database:
            game_id = self._stored_game(database)
            lookup = AcsdbBookGameLookup(database)

            for constant, limit, payload in cases:
                with self.subTest(constant=constant):
                    with database.conn:
                        database.conn.execute(
                            "UPDATE games SET warnings_json=? WHERE id=?",
                            (payload, game_id),
                        )
                    with mock.patch(
                        f"acs.book_library_game_lookup.{constant}",
                        limit,
                    ):
                        with self.assertRaises(BookLibraryGameLookupError) as caught:
                            lookup.load_book_game(game_id)
                    self.assertEqual(
                        str(caught.exception),
                        "stored book game warnings are invalid",
                    )
                    self.assertIsNone(caught.exception.__cause__)

    def test_empty_nul_and_whitespace_warning_metadata_fail_closed(self) -> None:
        malformed = (
            '[""]',
            '["   "]',
            '["prefix\\u0000suffix"]',
        )
        with AcsDatabase() as database:
            game_id = self._stored_game(database)
            lookup = AcsdbBookGameLookup(database)
            for payload in malformed:
                with self.subTest(payload=payload):
                    with database.conn:
                        database.conn.execute(
                            "UPDATE games SET warnings_json=? WHERE id=?",
                            (payload, game_id),
                        )
                    with self.assertRaises(BookLibraryGameLookupError) as caught:
                        lookup.load_book_game(game_id)
                    self.assertEqual(
                        str(caught.exception),
                        "stored book game warnings are invalid",
                    )
                    self.assertIsNone(caught.exception.__cause__)

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

    def test_corrupt_stored_pgn_parser_failure_has_no_internal_cause(self) -> None:
        with AcsDatabase() as database:
            game_id = self._stored_game(database)
            with database.conn:
                database.conn.execute(
                    "UPDATE games SET pgn_text=? WHERE id=?",
                    ("[Event \"unterminated", game_id),
                )

            with self.assertRaises(BookLibraryGameLookupError) as caught:
                AcsdbBookGameLookup(database).load_book_game(game_id)

            self.assertEqual(
                str(caught.exception),
                "stored book game is not canonical",
            )
            self.assertIsNone(caught.exception.__cause__)
            rendered = "".join(traceback.format_exception(caught.exception))
            self.assertNotIn("unterminated", rendered)

    def test_database_failure_is_sanitized_and_book_boundary_stays_public(self) -> None:
        database = AcsDatabase()
        game_id = self._stored_game(database)
        lookup = AcsdbBookGameLookup(database)
        database.close()

        with self.assertRaises(BookLibraryGameLookupError) as direct:
            lookup.load_book_game(game_id)
        self.assertEqual(str(direct.exception), "book game lookup failed")
        self.assertIsNone(direct.exception.__cause__)
        rendered = "".join(traceback.format_exception(direct.exception)).lower()
        self.assertNotIn("closed database", rendered)
        self.assertNotIn("sqlite", rendered)

        with self.assertRaises(BookGameContentError) as public:
            resolve_book_game(Game(game_id=game_id), lookup=lookup)
        self.assertEqual(public.exception.code, BookGameContentErrorCode.GAME_NOT_FOUND)
        self.assertEqual(str(public.exception), "referenced book game was not found")

    def test_qualification_gate_late_binds_canonical_product(self) -> None:
        workflow = (
            Path(__file__).resolve().parents[1]
            / ".github"
            / "workflows"
            / "v2-book-library-game-lookup.yml"
        ).read_text(encoding="utf-8")

        self.assertIn(
            "PRODUCT_BRANCH: integration/book-variation-fen-equivalence-apex-20261004-sol6p3",
            workflow,
        )
        self.assertIn('git fetch --no-tags origin "$PRODUCT_BRANCH"', workflow)
        self.assertIn('live_product="$(git rev-parse FETCH_HEAD)"', workflow)
        self.assertIn(
            'git merge-base --is-ancestor "$PR_BASE_SHA" "$live_product"',
            workflow,
        )
        self.assertIn('upstream="$live_product"', workflow)
        self.assertNotIn("CURRENT_PRODUCT_BASE:", workflow)

    def test_windows_blob_readback_tracks_current_head_instead_of_stale_stage1_digests(self) -> None:
        workflow = (
            Path(__file__).resolve().parents[1]
            / ".github"
            / "workflows"
            / "v2-book-library-game-lookup.yml"
        ).read_text(encoding="utf-8")

        self.assertIn('expected="$(git rev-parse "HEAD:$path")"', workflow)
        self.assertIn('git cat-file blob "HEAD:$path" > "$path"', workflow)
        self.assertIn('git hash-object --no-filters "$path"', workflow)
        self.assertNotIn("b8586a26b9ab20c3d3ec0b0a3dbbbd53e38e94e6", workflow)
        self.assertNotIn("FROZEN_STAGE1", workflow)

    def test_constructor_rejects_noncanonical_database_adapter(self) -> None:
        with self.assertRaises(TypeError):
            AcsdbBookGameLookup(object())  # type: ignore[arg-type]


if __name__ == "__main__":
    unittest.main()
