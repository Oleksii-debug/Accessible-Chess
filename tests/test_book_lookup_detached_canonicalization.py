from __future__ import annotations

import unittest

from acs.book_game_content import BookGameSource, resolve_book_game
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
    def test_nested_move_deepcopy_hook_is_not_executed(self) -> None:
        class HostileMoveNode(MoveNode):
            touched = False

            def __deepcopy__(self, memo):
                type(self).touched = True
                raise RuntimeError(
                    r"C:\Users\Oleksii\private\provider.db nested deepcopy hook"
                )

        source = parse_games(PGN)[0]
        original = source.line.moves[0]
        source.line.moves[0] = HostileMoveNode(
            san=original.san,
            move_number=original.move_number,
            nags=list(original.nags),
            comments_before=list(original.comments_before),
            comments_after=list(original.comments_after),
            variations=list(original.variations),
        )
        source.source_index = 7
        source.warnings = ["recovered source warning"]
        lookup = _Lookup(source)

        # The provider value is structurally canonical for the existing GameTree
        # serializer. The Books boundary must detach it without invoking copy
        # hooks on nested provider-owned subclasses.
        self.assertIn("e4", serialize_game(source))
        self.assertFalse(HostileMoveNode.touched)

        resolved = resolve_book_game(Game(game_id=17), lookup=lookup)

        self.assertEqual(lookup.calls, [17])
        self.assertEqual(resolved.source, BookGameSource.REFERENCE)
        self.assertFalse(HostileMoveNode.touched)
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
