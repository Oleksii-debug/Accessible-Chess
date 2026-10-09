from __future__ import annotations

import unittest
from unittest.mock import patch

from acs import book_game_content
from acs.book_game_content import (
    BookGameContentError,
    BookGameContentErrorCode,
    BookGameSource,
    resolve_book_game,
)
from acs.bookdocument import Game
from acs.gametree import (
    Comment,
    MoveNode,
    PgnGame,
    VariationLine,
    parse_games,
    serialize_game,
)


PGN = """[Event \"Nested provider hook\"]
[Result \"*\"]

1. e4 {King pawn} e5 *
"""


class _Lookup:
    def __init__(self, game: PgnGame) -> None:
        self.game = game
        self.calls: list[int] = []

    def load_book_game(self, game_id: int) -> PgnGame:
        self.calls.append(game_id)
        return self.game


class BookLookupDetachedCanonicalizationTests(unittest.TestCase):
    def test_nested_provider_subclass_is_rejected_before_any_hook_runs(self) -> None:
        class HostileMoveNode(MoveNode):
            touched = False

            def __getattribute__(self, name):
                if name in {
                    "san",
                    "move_number",
                    "nags",
                    "comments_before",
                    "comments_after",
                    "variations",
                }:
                    type(self).touched = True
                    raise RuntimeError(
                        r"C:\Users\Oleksii\private\provider.db attribute hook"
                    )
                return super().__getattribute__(name)

            def __deepcopy__(self, memo):
                type(self).touched = True
                raise RuntimeError(
                    r"C:\Users\Oleksii\private\provider.db deepcopy hook"
                )

        source = parse_games(PGN)[0]
        original = source.line.moves[0]
        hostile = HostileMoveNode(
            san=original.san,
            move_number=original.move_number,
            nags=list(original.nags),
            comments_before=list(original.comments_before),
            comments_after=list(original.comments_after),
            variations=list(original.variations),
        )
        source.line.moves[0] = hostile
        lookup = _Lookup(source)

        with self.assertRaises(BookGameContentError) as caught:
            resolve_book_game(Game(game_id=17), lookup=lookup)

        self.assertEqual(lookup.calls, [17])
        self.assertEqual(
            caught.exception.code,
            BookGameContentErrorCode.INVALID_CANONICAL_GAME,
        )
        self.assertFalse(HostileMoveNode.touched)
        self.assertNotIn("provider.db", str(caught.exception))

    def test_nested_scalar_subclass_is_rejected_before_string_hooks_run(self) -> None:
        class HostileText(str):
            touched = False

            def strip(self, *args, **kwargs):
                type(self).touched = True
                raise RuntimeError("hostile text strip hook")

            def isspace(self):
                type(self).touched = True
                raise RuntimeError("hostile text isspace hook")

        source = parse_games(PGN)[0]
        source.line.moves[0].san = HostileText("e4")

        with self.assertRaises(BookGameContentError) as caught:
            resolve_book_game(Game(game_id=18), lookup=_Lookup(source))

        self.assertEqual(
            caught.exception.code,
            BookGameContentErrorCode.INVALID_CANONICAL_GAME,
        )
        self.assertFalse(HostileText.touched)

    def test_provider_warning_count_is_bounded_before_warning_iteration(self) -> None:
        source = PgnGame(
            tags={},
            line=VariationLine(moves=[MoveNode("e4")]),
            warnings=["warning one", "warning two"],
        )
        with patch.object(book_game_content, "MAX_BOOK_PROVIDER_WARNINGS", 1):
            with self.assertRaises(BookGameContentError) as caught:
                resolve_book_game(Game(game_id=31), lookup=_Lookup(source))

        self.assertEqual(
            caught.exception.code,
            BookGameContentErrorCode.INVALID_CANONICAL_GAME,
        )

    def test_provider_tag_count_is_bounded_before_tag_iteration(self) -> None:
        source = PgnGame(
            tags={"Event": "One", "Site": "Two"},
            line=VariationLine(moves=[MoveNode("e4")]),
        )
        with patch.object(book_game_content, "MAX_PGN_TAGS_PER_GAME", 1):
            with self.assertRaises(BookGameContentError) as caught:
                resolve_book_game(Game(game_id=32), lookup=_Lookup(source))

        self.assertEqual(
            caught.exception.code,
            BookGameContentErrorCode.INVALID_CANONICAL_GAME,
        )

    def test_provider_preflight_does_not_invent_a_tag_name_token_cap(self) -> None:
        long_tag_name = "T" * 5000
        source = PgnGame(
            tags={long_tag_name: "value"},
            line=VariationLine(moves=[MoveNode("e4")]),
        )

        resolved = resolve_book_game(Game(game_id=37), lookup=_Lookup(source))

        self.assertEqual(resolved.game.tags[long_tag_name], "value")

    def test_provider_comment_text_is_bounded_before_serializer_scan(self) -> None:
        source = PgnGame(
            tags={},
            line=VariationLine(
                moves=[
                    MoveNode(
                        "e4",
                        comments_after=[Comment("xxxxx")],
                    )
                ]
            ),
        )
        with patch.object(book_game_content, "MAX_PGN_COMMENT_CHARS", 4):
            with self.assertRaises(BookGameContentError) as caught:
                resolve_book_game(Game(game_id=33), lookup=_Lookup(source))

        self.assertEqual(
            caught.exception.code,
            BookGameContentErrorCode.INVALID_CANONICAL_GAME,
        )

    def test_provider_token_text_is_bounded_before_serializer_grammar(self) -> None:
        source = PgnGame(
            tags={},
            line=VariationLine(moves=[MoveNode("Nf3")]),
        )
        with patch.object(book_game_content, "MAX_PGN_TOKEN_CHARS", 2):
            with self.assertRaises(BookGameContentError) as caught:
                resolve_book_game(Game(game_id=34), lookup=_Lookup(source))

        self.assertEqual(
            caught.exception.code,
            BookGameContentErrorCode.INVALID_CANONICAL_GAME,
        )

    def test_provider_aggregate_lexical_items_are_bounded_across_lists(self) -> None:
        source = PgnGame(
            tags={},
            line=VariationLine(
                leading_comments=[Comment("one")],
                moves=[
                    MoveNode(
                        "e4",
                        comments_after=[Comment("two")],
                    )
                ],
            ),
        )
        with patch.object(book_game_content, "MAX_PGN_LEXICAL_TOKENS", 1):
            with self.assertRaises(BookGameContentError) as caught:
                resolve_book_game(Game(game_id=35), lookup=_Lookup(source))

        self.assertEqual(
            caught.exception.code,
            BookGameContentErrorCode.INVALID_CANONICAL_GAME,
        )

    def test_provider_lexical_budget_counts_serializer_emitted_move_tokens(self) -> None:
        source = PgnGame(
            tags={"Result": "*"},
            line=VariationLine(
                moves=[MoveNode("e4", move_number="1.")],
                result="*",
            ),
        )
        # D06 sees four lexical units: Result tag, move number, SAN and result.
        with patch.object(book_game_content, "MAX_PGN_LEXICAL_TOKENS", 3):
            with self.assertRaises(BookGameContentError) as caught:
                resolve_book_game(Game(game_id=38), lookup=_Lookup(source))

        self.assertEqual(
            caught.exception.code,
            BookGameContentErrorCode.INVALID_CANONICAL_GAME,
        )

    def test_provider_lexical_budget_counts_synthesized_result_tag(self) -> None:
        source = PgnGame(
            tags={},
            line=VariationLine(moves=[MoveNode("e4")], result=None),
        )
        # serialize_game injects [Result "*"] even when the provider omitted it.
        # The synthetic header plus SAN therefore exceed a one-token D06 budget.
        with patch.object(book_game_content, "MAX_PGN_LEXICAL_TOKENS", 1):
            with self.assertRaises(BookGameContentError) as caught:
                resolve_book_game(Game(game_id=39), lookup=_Lookup(source))

        self.assertEqual(
            caught.exception.code,
            BookGameContentErrorCode.INVALID_CANONICAL_GAME,
        )

    def test_provider_lexical_budget_counts_variation_parentheses(self) -> None:
        source = PgnGame(
            tags={"Result": "*"},
            line=VariationLine(
                moves=[
                    MoveNode(
                        "e4",
                        variations=[VariationLine(moves=[MoveNode("e5")])],
                    )
                ]
            ),
        )
        # Result tag + root SAN + '(' + child SAN + ')' = five D06 tokens.
        with patch.object(book_game_content, "MAX_PGN_LEXICAL_TOKENS", 4):
            with self.assertRaises(BookGameContentError) as caught:
                resolve_book_game(Game(game_id=40), lookup=_Lookup(source))

        self.assertEqual(
            caught.exception.code,
            BookGameContentErrorCode.INVALID_CANONICAL_GAME,
        )

    def test_provider_content_text_has_one_aggregate_d06_budget(self) -> None:
        source = PgnGame(
            tags={},
            line=VariationLine(
                moves=[
                    MoveNode(
                        "e4",
                        comments_after=[Comment("abcd")],
                    )
                ],
            ),
        )
        with patch.object(book_game_content, "MAX_PGN_TEXT_CHARS", 5):
            with self.assertRaises(BookGameContentError) as caught:
                resolve_book_game(Game(game_id=36), lookup=_Lookup(source))

        self.assertEqual(
            caught.exception.code,
            BookGameContentErrorCode.INVALID_CANONICAL_GAME,
        )

    def test_provider_text_budget_counts_serialized_pgn_framing(self) -> None:
        source = PgnGame(
            tags={},
            line=VariationLine(moves=[MoveNode("e4")]),
        )
        # Raw provider scalars contain only two characters, but serialize_game
        # must also emit the synthetic Result header, blank line and final newline.
        with patch.object(book_game_content, "MAX_PGN_TEXT_CHARS", 2):
            with self.assertRaises(BookGameContentError) as caught:
                resolve_book_game(Game(game_id=41), lookup=_Lookup(source))

        self.assertEqual(
            caught.exception.code,
            BookGameContentErrorCode.INVALID_CANONICAL_GAME,
        )

    def test_provider_text_budget_counts_tag_escape_expansion(self) -> None:
        source = PgnGame(
            tags={"Event": '"', "Result": "*"},
            line=VariationLine(),
        )
        # The raw key/value payload is 13 characters. The canonical header must
        # additionally escape the quote and include PGN framing/newlines.
        with patch.object(book_game_content, "MAX_PGN_TEXT_CHARS", 13):
            with self.assertRaises(BookGameContentError) as caught:
                resolve_book_game(Game(game_id=42), lookup=_Lookup(source))

        self.assertEqual(
            caught.exception.code,
            BookGameContentErrorCode.INVALID_CANONICAL_GAME,
        )

    def test_exact_graph_is_detached_and_preserves_provider_metadata(self) -> None:
        source = parse_games(PGN)[0]
        source.source_index = 7
        source.warnings = ["recovered source warning"]
        lookup = _Lookup(source)

        resolved = resolve_book_game(Game(game_id=19), lookup=lookup)

        self.assertEqual(lookup.calls, [19])
        self.assertEqual(resolved.source, BookGameSource.REFERENCE)
        self.assertIs(type(resolved.game.line), VariationLine)
        self.assertIs(type(resolved.game.line.moves[0]), MoveNode)
        self.assertIsNot(resolved.game, source)
        self.assertIsNot(resolved.game.line, source.line)
        self.assertEqual(resolved.game.source_index, 7)
        self.assertEqual(resolved.game.warnings, ["recovered source warning"])
        self.assertEqual(resolved.warnings, ("recovered source warning",))

        source.line.moves[0].san = "corrupted-after-return"
        source.warnings.append("late provider mutation")
        self.assertEqual(resolved.game.line.moves[0].san, "e4")
        self.assertEqual(resolved.game.warnings, ["recovered source warning"])
        self.assertIn("e4", serialize_game(resolved.game))

    def test_shared_exact_comment_identity_remains_valid_and_detaches(self) -> None:
        source = parse_games(PGN)[0]
        shared = Comment("shared annotation")
        source.line.moves[0].comments_before = [shared]
        source.line.moves[0].comments_after = [shared]
        self.assertIn("shared annotation", serialize_game(source))

        resolved = resolve_book_game(Game(game_id=20), lookup=_Lookup(source))

        before = resolved.game.line.moves[0].comments_before[0]
        after = resolved.game.line.moves[0].comments_after[0]
        self.assertEqual(before.text, "shared annotation")
        self.assertEqual(after.text, "shared annotation")
        self.assertIsNot(before, shared)
        self.assertIsNot(after, shared)
        self.assertIsNot(before, after)

    def test_detach_preserves_valid_absent_result_structure(self) -> None:
        # serialize -> parse would materialize the serializer's effective Result
        # into both the header and movetext. Detachment must preserve the valid
        # in-memory canonical structure instead of silently normalizing it.
        source = PgnGame(
            tags={"Event": "No explicit result"},
            line=VariationLine(
                moves=[MoveNode(san="e4", move_number="1.")],
                result=None,
            ),
            source_index=5,
            warnings=["provider warning"],
        )
        self.assertNotIn("Result", source.tags)
        self.assertIsNone(source.line.result)
        self.assertIn("e4", serialize_game(source))

        resolved = resolve_book_game(Game(game_id=23), lookup=_Lookup(source))

        self.assertNotIn("Result", resolved.game.tags)
        self.assertIsNone(resolved.game.line.result)
        self.assertEqual(resolved.game.source_index, 5)
        self.assertEqual(resolved.game.warnings, ["provider warning"])
        self.assertEqual(resolved.warnings, ("provider warning",))
        self.assertIn("e4", serialize_game(resolved.game))


if __name__ == "__main__":
    unittest.main()