from __future__ import annotations

import unittest

from acs.book_game_content import (
    BookGameContentError,
    BookGameContentErrorCode,
    BookGameSource,
    resolve_book_game,
    resolve_book_variation,
)
from acs.bookdocument import Game, Paragraph, VariationTree
from acs.gametree import PgnGame, parse_games, serialize_game


START_FEN = "rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w KQkq - 0 1"
AFTER_E4_FEN = "rnbqkbnr/pppppppp/8/8/4P3/8/PPPP1PPP/RNBQKBNR b KQkq - 0 1"

EMBEDDED_PGN = """[Event \"Book example\"]
[Result \"*\"]

1. e4 {King pawn} (1. d4 $1 {Queen pawn}) e5 *
"""


class _Lookup:
    def __init__(self, game: PgnGame) -> None:
        self.game = game
        self.calls: list[int] = []

    def load_book_game(self, game_id: int) -> PgnGame:
        self.calls.append(game_id)
        return self.game


class _MissingLookup:
    def load_book_game(self, game_id: int) -> PgnGame:
        raise LookupError(game_id)


class _ExplodingLookup:
    def load_book_game(self, game_id: int) -> PgnGame:
        raise RuntimeError(r"C:\Users\Oleksii\private\library.db provider=sqlite")


class BookCanonicalGameContentTests(unittest.TestCase):
    def test_embedded_book_game_uses_canonical_gametree_with_comments_nag_and_rav(self) -> None:
        block = Game(
            pgn=EMBEDDED_PGN,
            title="Example",
            block_id="game-1",
            source_anchor="chapter-2-game",
        )
        resolved = resolve_book_game(block)

        self.assertEqual(resolved.source, BookGameSource.EMBEDDED)
        self.assertEqual(resolved.block_id, "game-1")
        self.assertEqual(resolved.source_anchor, "chapter-2-game")
        self.assertEqual(resolved.title, "Example")
        self.assertIsNone(resolved.game_id)
        self.assertEqual(resolved.game.tags["Event"], "Book example")
        self.assertEqual([move.san for move in resolved.game.line.moves], ["e4", "e5"])
        first = resolved.game.line.moves[0]
        self.assertEqual(first.comments_after[0].text, "King pawn")
        self.assertEqual(len(first.variations), 1)
        variation_move = first.variations[0].moves[0]
        self.assertEqual(variation_move.san, "d4")
        self.assertIn("$1", variation_move.nags)
        self.assertEqual(variation_move.comments_after[0].text, "Queen pawn")
        # The resolved structure remains valid for the canonical serializer; no
        # Books-specific PGN representation was invented.
        self.assertIn("(1. d4 $1 {Queen pawn})", serialize_game(resolved.game))

    def test_reference_only_block_requires_explicit_application_lookup(self) -> None:
        block = Game(game_id=17, title="Library game")
        with self.assertRaises(BookGameContentError) as caught:
            resolve_book_game(block)
        self.assertEqual(caught.exception.code, BookGameContentErrorCode.LOOKUP_REQUIRED)

    def test_reference_lookup_returns_detached_canonical_game(self) -> None:
        source = parse_games(EMBEDDED_PGN)[0]
        lookup = _Lookup(source)
        resolved = resolve_book_game(Game(game_id=17), lookup=lookup)

        self.assertEqual(lookup.calls, [17])
        self.assertEqual(resolved.source, BookGameSource.REFERENCE)
        self.assertEqual(resolved.game_id, 17)
        self.assertIsNot(resolved.game, source)
        self.assertIsNot(resolved.game.line, source.line)
        original_san = resolved.game.line.moves[0].san
        source.line.moves[0].san = "corrupted-after-return"
        self.assertEqual(resolved.game.line.moves[0].san, original_san)

    def test_reference_backend_failures_do_not_leak_paths_or_provider_details(self) -> None:
        with self.assertRaises(BookGameContentError) as caught:
            resolve_book_game(Game(game_id=9), lookup=_ExplodingLookup())
        self.assertEqual(caught.exception.code, BookGameContentErrorCode.GAME_NOT_FOUND)
        message = str(caught.exception)
        self.assertNotIn("Users", message)
        self.assertNotIn("library.db", message)
        self.assertNotIn("sqlite", message)

    def test_missing_reference_has_stable_not_found_error(self) -> None:
        with self.assertRaises(BookGameContentError) as caught:
            resolve_book_game(Game(game_id=404), lookup=_MissingLookup())
        self.assertEqual(caught.exception.code, BookGameContentErrorCode.GAME_NOT_FOUND)

    def test_invalid_lookup_shape_or_return_type_fails_closed(self) -> None:
        class NoPort:
            pass

        class WrongType:
            def load_book_game(self, game_id: int):
                return "raw PGN is not a canonical game"

        for lookup, expected in (
            (NoPort(), BookGameContentErrorCode.INVALID_LOOKUP),
            (WrongType(), BookGameContentErrorCode.INVALID_CANONICAL_GAME),
        ):
            with self.subTest(lookup=type(lookup).__name__):
                with self.assertRaises(BookGameContentError) as caught:
                    resolve_book_game(Game(game_id=3), lookup=lookup)  # type: ignore[arg-type]
                self.assertEqual(caught.exception.code, expected)

    def test_embedded_and_reference_sources_are_ambiguous_in_auto_mode(self) -> None:
        block = Game(pgn=EMBEDDED_PGN, game_id=21)
        lookup = _Lookup(parse_games("1. d4 d5 *")[0])

        with self.assertRaises(BookGameContentError) as caught:
            resolve_book_game(block, lookup=lookup)
        self.assertEqual(caught.exception.code, BookGameContentErrorCode.AMBIGUOUS_SOURCE)
        self.assertEqual(lookup.calls, [])

        embedded = resolve_book_game(block, source=BookGameSource.EMBEDDED, lookup=lookup)
        self.assertEqual(embedded.game.line.moves[0].san, "e4")
        self.assertEqual(lookup.calls, [])

        referenced = resolve_book_game(block, source=BookGameSource.REFERENCE, lookup=lookup)
        self.assertEqual(referenced.game.line.moves[0].san, "d4")
        self.assertEqual(lookup.calls, [21])

    def test_one_book_game_block_cannot_silently_become_multiple_games(self) -> None:
        multi = """[Event \"One\"]

1. e4 *

[Event \"Two\"]

1. d4 *
"""
        with self.assertRaises(BookGameContentError) as caught:
            resolve_book_game(Game(pgn=multi))
        self.assertEqual(caught.exception.code, BookGameContentErrorCode.MULTI_GAME_BLOCK)

    def test_explicit_source_requires_that_source_to_exist(self) -> None:
        with self.assertRaises(BookGameContentError) as embedded:
            resolve_book_game(Game(game_id=1), source=BookGameSource.EMBEDDED)
        self.assertEqual(embedded.exception.code, BookGameContentErrorCode.EMBEDDED_GAME_MISSING)

        with self.assertRaises(BookGameContentError) as reference:
            resolve_book_game(Game(pgn=EMBEDDED_PGN), source=BookGameSource.REFERENCE)
        self.assertEqual(reference.exception.code, BookGameContentErrorCode.REFERENCED_GAME_MISSING)

    def test_wrong_block_type_is_rejected(self) -> None:
        with self.assertRaises(BookGameContentError) as caught:
            resolve_book_game(Paragraph(text="not a game"))  # type: ignore[arg-type]
        self.assertEqual(caught.exception.code, BookGameContentErrorCode.INVALID_BLOCK)

    def test_variation_tree_keeps_root_position_separate_from_canonical_structure(self) -> None:
        block = VariationTree(
            root_fen=AFTER_E4_FEN,
            pgn="1... c5 {Sicilian} (1... e5 $5) *",
            title="Replies to e4",
            block_id="variation-1",
        )
        resolved = resolve_book_variation(block)

        self.assertEqual(resolved.root_fen, AFTER_E4_FEN)
        self.assertEqual(resolved.block_id, "variation-1")
        self.assertEqual(resolved.title, "Replies to e4")
        self.assertEqual(resolved.game.line.moves[0].san, "c5")
        self.assertEqual(resolved.game.line.moves[0].comments_after[0].text, "Sicilian")
        alt = resolved.game.line.moves[0].variations[0].moves[0]
        self.assertEqual(alt.san, "e5")
        self.assertIn("$5", alt.nags)

    def test_variation_pgn_fen_tag_must_not_conflict_with_book_root(self) -> None:
        pgn = f'''[SetUp "1"]
[FEN "{START_FEN}"]
[Result "*"]

1. e4 *
'''
        block = VariationTree(root_fen=AFTER_E4_FEN, pgn=pgn)
        with self.assertRaises(BookGameContentError) as caught:
            resolve_book_variation(block)
        self.assertEqual(caught.exception.code, BookGameContentErrorCode.ROOT_FEN_CONFLICT)

    def test_matching_variation_fen_tag_is_preserved_not_rewritten(self) -> None:
        pgn = f'''[SetUp "1"]
[FEN "{AFTER_E4_FEN}"]
[Result "*"]

1... c5 *
'''
        resolved = resolve_book_variation(VariationTree(root_fen=AFTER_E4_FEN, pgn=pgn))
        self.assertEqual(resolved.game.tags["FEN"], AFTER_E4_FEN)
        self.assertEqual(resolved.root_fen, AFTER_E4_FEN)

    def test_parser_recovery_warnings_are_not_silently_dropped(self) -> None:
        block = Game(pgn="1. e4 {unterminated")
        resolved = resolve_book_game(block)
        self.assertTrue(resolved.warnings)
        self.assertTrue(any("unterminated brace comment" in warning for warning in resolved.warnings))


if __name__ == "__main__":
    unittest.main()
