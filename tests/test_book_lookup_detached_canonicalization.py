from __future__ import annotations

import unittest

from acs.book_game_content import (
    BookGameContentError,
    BookGameContentErrorCode,
    BookGameSource,
    resolve_book_game,
)
from acs.bookdocument import Game
from acs.gametree import (
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
