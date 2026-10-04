from __future__ import annotations

import unittest
from unittest.mock import patch

from acs.full_product_presenters import PgnTreePresenter
from acs.full_product_ui_shell import UILanguage
from acs.gametree import (
    MAX_VARIATION_DEPTH,
    GameTreeContractError,
    GameTreeErrorCode,
    MoveNode,
    PgnGame,
    VariationLine,
)
from acs import pgn_presenter_graph_guard


class _ExplodingList(list):
    touched = False

    def __iter__(self):
        type(self).touched = True
        raise AssertionError("hostile list iteration must not execute")


class PgnPresenterGraphSafetyTests(unittest.TestCase):
    def setUp(self) -> None:
        _ExplodingList.touched = False

    @staticmethod
    def _game_with_move(san: str = "e4") -> tuple[PgnGame, VariationLine, MoveNode]:
        move = MoveNode(san)
        line = VariationLine(moves=[move])
        return PgnGame(tags={"White": "A", "Black": "B"}, line=line), line, move

    def assert_code(self, expected: GameTreeErrorCode, callback) -> None:
        with self.assertRaises(GameTreeContractError) as captured:
            callback()
        self.assertIs(expected, captured.exception.code)

    def test_top_level_collection_subclass_is_rejected_before_iteration(self) -> None:
        game, _, _ = self._game_with_move()
        games = _ExplodingList([game])
        with self.assertRaisesRegex(TypeError, "built-in list or tuple"):
            PgnTreePresenter(games)
        self.assertFalse(_ExplodingList.touched)

    def test_nested_hostile_move_container_is_rejected_before_iteration(self) -> None:
        game, line, move = self._game_with_move()
        line.moves = _ExplodingList([move])
        self.assert_code(
            GameTreeErrorCode.INVALID_CONTAINER,
            lambda: PgnTreePresenter([game]),
        )
        self.assertFalse(_ExplodingList.touched)

    def test_cycle_is_rejected_before_recursive_materialization(self) -> None:
        game, line, move = self._game_with_move()
        move.variations.append(line)
        self.assert_code(
            GameTreeErrorCode.GRAPH_CYCLE,
            lambda: PgnTreePresenter([game]),
        )

    def test_shared_variation_alias_is_rejected_as_graph_reuse(self) -> None:
        game, _, move = self._game_with_move()
        child = VariationLine(moves=[MoveNode("c5")])
        move.variations.extend([child, child])
        self.assert_code(
            GameTreeErrorCode.GRAPH_REUSE,
            lambda: PgnTreePresenter([game]),
        )

    def test_depth_limit_is_checked_iteratively_before_presenter_recursion(self) -> None:
        root = VariationLine()
        current = root
        for _ in range(MAX_VARIATION_DEPTH + 1):
            child = VariationLine()
            current.moves.append(MoveNode("e4", variations=[child]))
            current = child
        game = PgnGame(line=root)
        self.assert_code(
            GameTreeErrorCode.GRAPH_DEPTH_LIMIT,
            lambda: PgnTreePresenter([game]),
        )

    def test_node_limit_uses_canonical_guard_before_materialization(self) -> None:
        game = PgnGame(line=VariationLine(moves=[MoveNode("e4"), MoveNode("e5")]))
        with patch.object(pgn_presenter_graph_guard, "MAX_TREE_NODES", 2):
            self.assert_code(
                GameTreeErrorCode.GRAPH_NODE_LIMIT,
                lambda: PgnTreePresenter([game]),
            )

    def test_each_rebuild_revalidates_mutable_graph(self) -> None:
        game, line, move = self._game_with_move()
        presenter = PgnTreePresenter([game], language=UILanguage.UA)
        move.variations.append(line)
        self.assert_code(
            GameTreeErrorCode.GRAPH_CYCLE,
            lambda: presenter.set_language(UILanguage.EN),
        )

    def test_recovery_surface_does_not_turn_guard_into_san_rules_engine(self) -> None:
        game, _, _ = self._game_with_move("not-a-chess-move")
        game.warnings.append("Recovered historical movetext")
        presenter = PgnTreePresenter([game], language=UILanguage.EN)
        view = presenter.view()
        self.assertEqual("A — B", view.title)
        self.assertEqual(("Recovered historical movetext",), view.warnings)
        self.assertEqual("not-a-chess-move", presenter.items()[0].san)


if __name__ == "__main__":
    unittest.main()
