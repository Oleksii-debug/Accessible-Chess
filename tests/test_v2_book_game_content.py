from __future__ import annotations

import traceback
import unittest
from pathlib import Path

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
AFTER_E4_FEN_4 = "rnbqkbnr/pppppppp/8/8/4P3/8/PPPP1PPP/RNBQKBNR b KQkq -"
AFTER_E4_FEN_NONDEFAULT_COUNTERS = (
    "rnbqkbnr/pppppppp/8/8/4P3/8/PPPP1PPP/RNBQKBNR b KQkq - 12 37"
)

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

    def test_embedded_symbolic_nag_uses_canonical_d06_ingress_normalization(self) -> None:
        resolved = resolve_book_game(
            Game(
                pgn='''[Event "Attached NAG"]\n[Result "*"]\n\n1. e4?! e5 *\n''',
                block_id="attached-nag",
            )
        )

        first = resolved.game.line.moves[0]
        self.assertEqual(first.san, "e4")
        self.assertIn("?!", first.nags)
        self.assertNotIn("?!", first.san)
        self.assertEqual(resolved.block_id, "attached-nag")

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

    def test_reference_lookup_rejects_pgn_subclass_before_deepcopy_hook(self) -> None:
        class HostilePgnGame(PgnGame):
            touched = False

            def __deepcopy__(self, memo):
                type(self).touched = True
                raise AssertionError("hostile deepcopy hook must not execute")

        source = parse_games(EMBEDDED_PGN)[0]
        hostile = HostilePgnGame(
            tags=dict(source.tags),
            line=source.line,
            source_index=source.source_index,
            warnings=list(source.warnings),
        )
        lookup = _Lookup(hostile)

        with self.assertRaises(BookGameContentError) as caught:
            resolve_book_game(Game(game_id=17), lookup=lookup)

        self.assertEqual(
            caught.exception.code,
            BookGameContentErrorCode.INVALID_CANONICAL_GAME,
        )
        self.assertEqual(lookup.calls, [17])
        self.assertFalse(HostilePgnGame.touched)

    def test_reference_backend_failures_do_not_leak_paths_or_provider_details(self) -> None:
        with self.assertRaises(BookGameContentError) as caught:
            resolve_book_game(Game(game_id=9), lookup=_ExplodingLookup())
        self.assertEqual(caught.exception.code, BookGameContentErrorCode.GAME_NOT_FOUND)
        self.assertIsNone(caught.exception.__cause__)
        rendered = "".join(traceback.format_exception(caught.exception))
        self.assertNotIn("Users", rendered)
        self.assertNotIn("library.db", rendered)
        self.assertNotIn("sqlite", rendered)

    def test_missing_reference_has_stable_not_found_error(self) -> None:
        with self.assertRaises(BookGameContentError) as caught:
            resolve_book_game(Game(game_id=404), lookup=_MissingLookup())
        self.assertEqual(caught.exception.code, BookGameContentErrorCode.GAME_NOT_FOUND)
        self.assertIsNone(caught.exception.__cause__)
        rendered = "".join(traceback.format_exception(caught.exception))
        self.assertNotIn("404", rendered)

    def test_lookup_port_attribute_failure_is_sanitized(self) -> None:
        class ExplodingPort:
            @property
            def load_book_game(self):
                raise RuntimeError(
                    r"C:\Users\Oleksii\private\library.db provider=sqlite"
                )

        with self.assertRaises(BookGameContentError) as caught:
            resolve_book_game(
                Game(game_id=3),
                lookup=ExplodingPort(),  # type: ignore[arg-type]
            )

        self.assertEqual(
            caught.exception.code,
            BookGameContentErrorCode.INVALID_LOOKUP,
        )
        self.assertIsNone(caught.exception.__cause__)
        rendered = "".join(traceback.format_exception(caught.exception))
        self.assertNotIn("Users", rendered)
        self.assertNotIn("library.db", rendered)
        self.assertNotIn("sqlite", rendered)

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

    def test_mutated_game_source_fields_fail_closed_before_lookup(self) -> None:
        bad_pgn = Game(pgn=EMBEDDED_PGN)
        bad_pgn.pgn = None  # type: ignore[assignment]
        with self.assertRaises(BookGameContentError) as pgn_error:
            resolve_book_game(bad_pgn)
        self.assertEqual(pgn_error.exception.code, BookGameContentErrorCode.INVALID_BLOCK)

        source = parse_games(EMBEDDED_PGN)[0]
        lookup = _Lookup(source)
        bad_reference = Game(game_id=17)
        bad_reference.game_id = -1
        with self.assertRaises(BookGameContentError) as reference_error:
            resolve_book_game(bad_reference, lookup=lookup)
        self.assertEqual(reference_error.exception.code, BookGameContentErrorCode.INVALID_BLOCK)
        self.assertEqual(lookup.calls, [])

    def test_mutated_variation_non_root_fields_fail_closed_before_pgn_parse(self) -> None:
        block = VariationTree(root_fen=AFTER_E4_FEN, pgn="1... c5 *")
        block.pgn = None  # type: ignore[assignment]

        with self.assertRaises(BookGameContentError) as caught:
            resolve_book_variation(block)
        self.assertEqual(caught.exception.code, BookGameContentErrorCode.INVALID_BLOCK)

    def test_game_resolution_consumes_one_canonical_embedded_snapshot(self) -> None:
        class MutatesAfterSnapshot(Game):
            @property
            def kind(self) -> str:
                # Keep this test double inside the canonical BookDocument wire
                # schema; the test is about post-snapshot mutation, not a new kind.
                return "Game"

            def as_dict(self):
                snapshot = super().as_dict()
                self.pgn = None  # type: ignore[assignment]
                self.title = "mutated after snapshot"
                self.block_id = "mutated-block"
                self.source_anchor = "mutated-anchor"
                return snapshot

        block = MutatesAfterSnapshot(
            pgn=EMBEDDED_PGN,
            title="snapshot title",
            block_id="snapshot-block",
            source_anchor="snapshot-anchor",
        )
        resolved = resolve_book_game(block)

        self.assertEqual(resolved.source, BookGameSource.EMBEDDED)
        self.assertEqual(resolved.game.line.moves[0].san, "e4")
        self.assertEqual(resolved.title, "snapshot title")
        self.assertEqual(resolved.block_id, "snapshot-block")
        self.assertEqual(resolved.source_anchor, "snapshot-anchor")

    def test_game_reference_selection_and_identity_come_from_same_snapshot(self) -> None:
        class MutatesAfterSnapshot(Game):
            @property
            def kind(self) -> str:
                # Keep this test double inside the canonical BookDocument wire
                # schema; the test is about post-snapshot mutation, not a new kind.
                return "Game"

            def as_dict(self):
                snapshot = super().as_dict()
                self.game_id = 999
                self.pgn = EMBEDDED_PGN
                self.title = "mutated after snapshot"
                return snapshot

        source = parse_games(EMBEDDED_PGN)[0]
        lookup = _Lookup(source)
        block = MutatesAfterSnapshot(game_id=17, title="snapshot title")

        resolved = resolve_book_game(block, lookup=lookup)

        self.assertEqual(resolved.source, BookGameSource.REFERENCE)
        self.assertEqual(resolved.game_id, 17)
        self.assertEqual(resolved.title, "snapshot title")
        self.assertEqual(lookup.calls, [17])

    def test_variation_resolution_consumes_one_canonical_snapshot(self) -> None:
        class MutatesAfterSnapshot(VariationTree):
            @property
            def kind(self) -> str:
                # Preserve the canonical semantic block identity while the
                # overridden as_dict introduces the intended mutation race.
                return "VariationTree"

            def as_dict(self):
                snapshot = super().as_dict()
                self.pgn = None  # type: ignore[assignment]
                self.title = "mutated after snapshot"
                self.block_id = "mutated-block"
                self.source_anchor = "mutated-anchor"
                return snapshot

        block = MutatesAfterSnapshot(
            root_fen=AFTER_E4_FEN,
            pgn="1... c5 *",
            title="snapshot title",
            block_id="snapshot-block",
            source_anchor="snapshot-anchor",
        )
        resolved = resolve_book_variation(block)

        self.assertEqual(resolved.root_fen, AFTER_E4_FEN)
        self.assertEqual(resolved.game.line.moves[0].san, "c5")
        self.assertEqual(resolved.title, "snapshot title")
        self.assertEqual(resolved.block_id, "snapshot-block")
        self.assertEqual(resolved.source_anchor, "snapshot-anchor")

    def test_source_selection_rejects_text_subclass_before_enum_hooks(self) -> None:
        class HostileSource(str):
            touched = False

            def __hash__(self):
                type(self).touched = True
                raise AssertionError("hostile hash hook must not execute")

            def __eq__(self, other):
                type(self).touched = True
                raise AssertionError("hostile equality hook must not execute")

            def __str__(self):
                type(self).touched = True
                raise AssertionError("hostile string hook must not execute")

        with self.assertRaises(BookGameContentError) as caught:
            resolve_book_game(
                Game(pgn=EMBEDDED_PGN),
                source=HostileSource("auto"),
            )
        self.assertEqual(
            caught.exception.code,
            BookGameContentErrorCode.INVALID_BLOCK,
        )
        self.assertFalse(HostileSource.touched)

        plain = resolve_book_game(
            Game(pgn=EMBEDDED_PGN),
            source="embedded",
        )
        self.assertEqual(plain.source, BookGameSource.EMBEDDED)

        with self.assertRaises(BookGameContentError) as non_text:
            resolve_book_game(
                Game(pgn=EMBEDDED_PGN),
                source=0,  # type: ignore[arg-type]
            )
        self.assertEqual(
            non_text.exception.code,
            BookGameContentErrorCode.INVALID_BLOCK,
        )

    def test_mutated_text_subclasses_fail_before_custom_hooks(self) -> None:
        class HostileText(str):
            touched = False

            def strip(self, *_args, **_kwargs):
                type(self).touched = True
                raise AssertionError("hostile strip hook must not execute")

            def __str__(self):
                type(self).touched = True
                raise AssertionError("hostile string hook must not execute")

        variation = VariationTree(
            root_fen=AFTER_E4_FEN,
            pgn="1... c5 *",
        )
        variation.root_fen = HostileText(AFTER_E4_FEN)
        with self.assertRaises(BookGameContentError) as root_error:
            resolve_book_variation(variation)
        self.assertEqual(
            root_error.exception.code,
            BookGameContentErrorCode.INVALID_ROOT_FEN,
        )
        self.assertFalse(HostileText.touched)

        game = Game(pgn=EMBEDDED_PGN)
        game.pgn = HostileText(EMBEDDED_PGN)
        with self.assertRaises(BookGameContentError) as game_error:
            resolve_book_game(game)
        self.assertEqual(
            game_error.exception.code,
            BookGameContentErrorCode.INVALID_BLOCK,
        )
        self.assertFalse(HostileText.touched)

        variation = VariationTree(root_fen=AFTER_E4_FEN, pgn="1... c5 *")
        variation.pgn = HostileText("1... c5 *")
        with self.assertRaises(BookGameContentError) as variation_error:
            resolve_book_variation(variation)
        self.assertEqual(
            variation_error.exception.code,
            BookGameContentErrorCode.INVALID_BLOCK,
        )
        self.assertFalse(HostileText.touched)

    def test_variation_root_change_during_snapshot_fails_closed(self) -> None:
        class ChangesRootDuringSnapshot(VariationTree):
            @property
            def kind(self) -> str:
                return "VariationTree"

            def as_dict(self):
                self.root_fen = START_FEN
                return super().as_dict()

        block = ChangesRootDuringSnapshot(
            root_fen=AFTER_E4_FEN,
            pgn="1... c5 *",
        )

        with self.assertRaises(BookGameContentError) as caught:
            resolve_book_variation(block)
        self.assertEqual(caught.exception.code, BookGameContentErrorCode.INVALID_BLOCK)

    def test_deleted_mutable_game_field_fails_with_stable_invalid_block(self) -> None:
        block = Game(pgn=EMBEDDED_PGN)
        del block.pgn

        with self.assertRaises(BookGameContentError) as caught:
            resolve_book_game(block)
        self.assertEqual(caught.exception.code, BookGameContentErrorCode.INVALID_BLOCK)

    def test_deleted_variation_fields_fail_with_stable_codes(self) -> None:
        missing_root = VariationTree(root_fen=AFTER_E4_FEN, pgn="1... c5 *")
        del missing_root.root_fen
        with self.assertRaises(BookGameContentError) as root_error:
            resolve_book_variation(missing_root)
        self.assertEqual(
            root_error.exception.code,
            BookGameContentErrorCode.INVALID_ROOT_FEN,
        )

        missing_pgn = VariationTree(root_fen=AFTER_E4_FEN, pgn="1... c5 *")
        del missing_pgn.pgn
        with self.assertRaises(BookGameContentError) as pgn_error:
            resolve_book_variation(missing_pgn)
        self.assertEqual(pgn_error.exception.code, BookGameContentErrorCode.INVALID_BLOCK)

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

    def test_variation_pgn_position_tags_must_be_a_coherent_pair(self) -> None:
        cases = (
            (
                f'''[FEN "{AFTER_E4_FEN}"]\n[Result "*"]\n\n1... c5 *\n''',
                "FEN requires SetUp 1",
            ),
            (
                '''[SetUp "1"]\n[Result "*"]\n\n1... c5 *\n''',
                "SetUp without its required FEN tag",
            ),
            (
                f'''[SetUp "0"]\n[FEN "{AFTER_E4_FEN}"]\n[Result "*"]\n\n1... c5 *\n''',
                "FEN requires SetUp 1",
            ),
            (
                f'''[SetUp "yes"]\n[FEN "{AFTER_E4_FEN}"]\n[Result "*"]\n\n1... c5 *\n''',
                "FEN requires SetUp 1",
            ),
        )
        for pgn, message in cases:
            with self.subTest(pgn=pgn):
                with self.assertRaisesRegex(BookGameContentError, message) as caught:
                    resolve_book_variation(
                        VariationTree(root_fen=AFTER_E4_FEN, pgn=pgn)
                    )
                self.assertEqual(
                    caught.exception.code,
                    BookGameContentErrorCode.INVALID_CANONICAL_GAME,
                )

    def test_variation_without_position_tags_uses_book_root_authority(self) -> None:
        resolved = resolve_book_variation(
            VariationTree(
                root_fen=AFTER_E4_FEN,
                pgn='''[Result "*"]\n\n1... c5 *\n''',
            )
        )
        self.assertNotIn("SetUp", resolved.game.tags)
        self.assertNotIn("FEN", resolved.game.tags)
        self.assertEqual(resolved.root_fen, AFTER_E4_FEN)
        self.assertEqual(resolved.game.line.moves[0].san, "c5")

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

    def test_compact_book_root_ignores_unasserted_pgn_move_counters(self) -> None:
        pgn = f'''[SetUp "1"]
[FEN "{AFTER_E4_FEN_NONDEFAULT_COUNTERS}"]
[Result "*"]

37... c5 *
'''
        resolved = resolve_book_variation(
            VariationTree(root_fen=AFTER_E4_FEN_4, pgn=pgn)
        )
        self.assertEqual(resolved.root_fen, AFTER_E4_FEN_4)
        self.assertEqual(
            resolved.game.tags["FEN"],
            AFTER_E4_FEN_NONDEFAULT_COUNTERS,
        )

    def test_explicit_six_field_book_root_keeps_counter_conflict_strict(self) -> None:
        pgn = f'''[SetUp "1"]
[FEN "{AFTER_E4_FEN_NONDEFAULT_COUNTERS}"]
[Result "*"]

37... c5 *
'''
        with self.assertRaises(BookGameContentError) as caught:
            resolve_book_variation(
                VariationTree(root_fen=AFTER_E4_FEN, pgn=pgn)
            )
        self.assertEqual(
            caught.exception.code,
            BookGameContentErrorCode.ROOT_FEN_CONFLICT,
        )

    def test_mutated_invalid_variation_root_fen_fails_closed_at_resolution(self) -> None:
        for invalid_root in (
            "not a FEN",
            "rnbqkbnr/pppppppp/8/8/4P3/8/PPPP1PPP/RNBQKBNR b KQkq - 0",
        ):
            with self.subTest(root=invalid_root):
                block = VariationTree(
                    root_fen=AFTER_E4_FEN,
                    pgn="1... c5 *",
                )
                block.root_fen = invalid_root

                with self.assertRaises(BookGameContentError) as caught:
                    resolve_book_variation(block)
                self.assertEqual(
                    caught.exception.code,
                    BookGameContentErrorCode.INVALID_ROOT_FEN,
                )

    def test_matching_variation_fen_tag_is_preserved_not_rewritten(self) -> None:
        pgn = f'''[SetUp "1"]
[FEN "{AFTER_E4_FEN}"]
[Result "*"]

1... c5 *
'''
        resolved = resolve_book_variation(VariationTree(root_fen=AFTER_E4_FEN, pgn=pgn))
        self.assertEqual(resolved.game.tags["FEN"], AFTER_E4_FEN)
        self.assertEqual(resolved.root_fen, AFTER_E4_FEN)

    def test_fen_equivalence_workflow_uses_live_inherited_product_base(self) -> None:
        workflow = (
            Path(__file__).resolve().parents[1]
            / ".github"
            / "workflows"
            / "book-variation-fen-equivalence.yml"
        ).read_text(encoding="utf-8")

        self.assertIn(
            'PR_BASE_REF: ${{ github.event.pull_request.base.ref }}',
            workflow,
        )
        self.assertIn('git fetch --no-tags origin "$base_ref"', workflow)
        self.assertIn(
            'git merge-base --is-ancestor "$event_base" "$live_base"',
            workflow,
        )
        self.assertIn('git merge-base --is-ancestor "$live_base" HEAD', workflow)
        self.assertIn(
            'test "$(git merge-base "$live_base" HEAD)" = "$live_base"',
            workflow,
        )
        self.assertIn('upstream="$live_base"', workflow)
        self.assertIn(
            "'.github/workflows/book-variation-fen-equivalence.yml'",
            workflow,
        )
        self.assertIn("'acs/book_game_content.py'", workflow)
        self.assertIn("'tests/test_v2_book_game_content.py'", workflow)
        self.assertNotIn("w6-v2-package-assembler.yml", workflow)

    def test_parser_recovery_warnings_are_not_silently_dropped(self) -> None:
        block = Game(pgn="1. e4 {unterminated")
        resolved = resolve_book_game(block)
        self.assertTrue(resolved.warnings)
        self.assertTrue(any("unterminated brace comment" in warning for warning in resolved.warnings))


if __name__ == "__main__":
    unittest.main()
