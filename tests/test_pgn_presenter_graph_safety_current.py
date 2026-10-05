from __future__ import annotations

import unittest
from unittest.mock import patch

from acs.full_product_presenters import PgnTreePresenter
from acs.full_product_ui_shell import UILanguage
from acs.gametree import (
    MAX_VARIATION_DEPTH,
    Comment,
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

    def test_game_collection_count_is_bounded_before_snapshot_copy(self) -> None:
        game, _, _ = self._game_with_move()
        with patch.object(
            pgn_presenter_graph_guard,
            "MAX_PGN_PRESENTATION_GAMES",
            1,
        ):
            with self.assertRaisesRegex(
                GameTreeContractError,
                "game collection exceeds the presentation limit",
            ):
                PgnTreePresenter([game, game])

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

    def test_failed_language_rebuild_keeps_previous_locale_and_tree(self) -> None:
        game, line, move = self._game_with_move("not-a-chess-move")
        presenter = PgnTreePresenter([game], language=UILanguage.UA)
        before_items = presenter.items()
        before_selected = presenter.selected_node_id

        move.variations.append(line)
        self.assert_code(
            GameTreeErrorCode.GRAPH_CYCLE,
            lambda: presenter.set_language(UILanguage.EN),
        )

        self.assertEqual(before_items, presenter.items())
        self.assertEqual(before_selected, presenter.selected_node_id)

        # Repair the mutable recovery graph, then force another rebuild without
        # changing language. A failed EN switch must not have leaked its locale.
        move.variations.clear()
        presenter.select_game(0)
        self.assertEqual(
            "Необроблений запис ходу: not-a-chess-move",
            presenter.items()[0].label,
        )

    def test_failed_game_switch_keeps_previous_game_tree_and_selection(self) -> None:
        first, _, _ = self._game_with_move("e4")
        second, second_line, second_move = self._game_with_move("d4")
        presenter = PgnTreePresenter([first, second], language=UILanguage.EN)
        before_items = presenter.items()
        before_selected = presenter.selected_node_id

        second_move.variations.append(second_line)
        self.assert_code(
            GameTreeErrorCode.GRAPH_CYCLE,
            lambda: presenter.select_game(1),
        )

        self.assertEqual(0, presenter.game_index)
        self.assertEqual(before_items, presenter.items())
        self.assertEqual(before_selected, presenter.selected_node_id)

        second_move.variations.clear()
        switched = presenter.next_game()
        self.assertEqual(1, presenter.game_index)
        self.assertEqual("d4", switched.items[0].san)

    def test_presenter_rejects_noncanonical_language_and_game_index_types(self) -> None:
        game, _, _ = self._game_with_move()
        with self.assertRaisesRegex(TypeError, "language must be UILanguage"):
            PgnTreePresenter([game], language="en")  # type: ignore[arg-type]

        presenter = PgnTreePresenter([game], language=UILanguage.EN)
        with self.assertRaisesRegex(TypeError, "language must be UILanguage"):
            presenter.set_language("uk")  # type: ignore[arg-type]
        with self.assertRaisesRegex(TypeError, "exact integer"):
            presenter.select_game(True)  # type: ignore[arg-type]

    def test_valid_san_uses_shared_accessible_move_label(self) -> None:
        game, _, _ = self._game_with_move("Nbd2")
        presenter = PgnTreePresenter([game], language=UILanguage.EN)

        item = presenter.items()[0]
        self.assertEqual("Nbd2", item.san)
        self.assertEqual("N b d 2", item.label)

    def test_recovery_surface_does_not_turn_guard_into_san_rules_engine(self) -> None:
        game, _, _ = self._game_with_move("not-a-chess-move")
        game.warnings.append("Recovered historical movetext")
        presenter = PgnTreePresenter([game], language=UILanguage.EN)
        view = presenter.view()
        self.assertEqual("A — B", view.title)
        self.assertEqual(("Recovered historical movetext",), view.warnings)
        self.assertEqual("not-a-chess-move", presenter.items()[0].san)
        self.assertEqual(
            "Unparsed move text: not-a-chess-move",
            presenter.items()[0].label,
        )

        presenter.set_language(UILanguage.UA)
        self.assertEqual("not-a-chess-move", presenter.items()[0].san)
        self.assertEqual(
            "Необроблений запис ходу: not-a-chess-move",
            presenter.items()[0].label,
        )

    def test_san_text_budget_fails_before_presenter_label_materialization(self) -> None:
        game, _, _ = self._game_with_move("xxxxx")
        with patch.object(pgn_presenter_graph_guard, "MAX_PGN_PRESENTATION_SAN_CHARS", 4):
            with self.assertRaisesRegex(
                GameTreeContractError,
                "PGN SAN text exceeds the presentation text limit",
            ):
                PgnTreePresenter([game])

    def test_comment_cardinality_is_bounded_before_presenter_strip(self) -> None:
        game, _, move = self._game_with_move()
        move.comments_before.extend([Comment("one"), Comment("two")])
        with patch.object(
            pgn_presenter_graph_guard,
            "MAX_PGN_PRESENTATION_COMMENTS_PER_SLOT",
            1,
        ):
            with self.assertRaisesRegex(
                GameTreeContractError,
                "contains too many comments",
            ):
                PgnTreePresenter([game])

    def test_nag_cardinality_is_bounded_before_presenter_join(self) -> None:
        game, _, move = self._game_with_move()
        move.nags.extend(["$1", "$2"])
        with patch.object(
            pgn_presenter_graph_guard,
            "MAX_PGN_PRESENTATION_NAGS_PER_MOVE",
            1,
        ):
            with self.assertRaisesRegex(
                GameTreeContractError,
                "PGN move has too many NAGs",
            ):
                PgnTreePresenter([game])

    def test_comment_text_is_bounded_before_presenter_strip(self) -> None:
        game, _, move = self._game_with_move()
        move.comments_after.append(Comment("xxxxx"))
        with patch.object(
            pgn_presenter_graph_guard,
            "MAX_PGN_PRESENTATION_RAW_TEXT_CHARS",
            4,
        ):
            with self.assertRaisesRegex(
                GameTreeContractError,
                "comments after move text exceeds the presentation text limit",
            ):
                PgnTreePresenter([game])

    def test_aggregate_presentation_text_budget_is_bounded(self) -> None:
        game = PgnGame(line=VariationLine(moves=[MoveNode("e4")]))
        with patch.object(
            pgn_presenter_graph_guard,
            "MAX_PGN_PRESENTATION_TOTAL_TEXT_CHARS",
            1,
        ):
            with self.assertRaisesRegex(
                GameTreeContractError,
                "aggregate resource limit",
            ):
                PgnTreePresenter([game])


if __name__ == "__main__":
    unittest.main()
