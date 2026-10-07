from __future__ import annotations

import unittest

from acs.gametree import MoveNode, PgnGame, VariationLine
from acs.gametree_navigation import GameTreeCursor, VariationStep
from acs.position_editor import PositionState, standard_position
from acs.tactile_graphics import (
    TACTILE_BOARD_ORDER,
    TactileDisplayPort,
    TactileGraphicsController,
    TactileGraphicsError,
    TactileSceneSource,
    TactileSimulator,
    position_for_gametree_cursor,
    project_tactile_scene,
)


class _FailingDisplay:
    def present(self, scene):
        raise RuntimeError("simulated adapter failure")


class Section8TactileGraphicsCoreTests(unittest.TestCase):
    def test_scene_is_vendor_neutral_full_board_plus_focus_view(self):
        position = standard_position()
        scene = project_tactile_scene(position, focus_square="e4", sequence=7)

        self.assertEqual(scene.position_fen, position.to_fen())
        self.assertEqual(scene.sequence, 7)
        self.assertEqual(scene.source, TactileSceneSource.POSITION_NAVIGATION)
        self.assertEqual(len(scene.full_board), 64)
        self.assertEqual(
            tuple(cell.square for cell in scene.full_board),
            TACTILE_BOARD_ORDER,
        )
        self.assertEqual(scene.full_board[0].square, "a8")
        self.assertEqual(scene.full_board[-1].square, "h1")
        self.assertEqual(
            {cell.square: cell.piece for cell in scene.full_board}["e1"],
            "K",
        )
        self.assertEqual(
            tuple(cell.square for cell in scene.focus_view),
            ("d5", "e5", "f5", "d4", "e4", "f4", "d3", "e3", "f3"),
        )
        self.assertEqual(
            [cell.square for cell in scene.full_board if cell.focused],
            ["e4"],
        )

    def test_simulator_is_display_port_and_records_refreshes(self):
        simulator = TactileSimulator()
        self.assertIsInstance(simulator, TactileDisplayPort)
        controller = TactileGraphicsController(simulator)

        first = controller.refresh_position(standard_position())
        second = controller.on_position_navigation(
            standard_position(),
            focus_square="a1",
        )

        self.assertEqual((first.sequence, second.sequence), (1, 2))
        self.assertEqual(simulator.history, (first, second))
        self.assertIs(simulator.current_scene, second)
        self.assertIs(controller.current_scene, second)

    def test_exploration_is_detached_and_cannot_mutate_position(self):
        position = standard_position()
        original_fen = position.to_fen()
        simulator = TactileSimulator()
        controller = TactileGraphicsController(simulator)
        first = controller.refresh_position(position, focus_square="e4")

        # Low-level corruption of the original object after projection cannot
        # make tactile exploration publish a different Position.
        object.__setattr__(position, "turn", "b")
        explored = controller.explore("h8")

        self.assertEqual(first.position_fen, original_fen)
        self.assertEqual(explored.position_fen, original_fen)
        self.assertEqual(explored.source, TactileSceneSource.EXPLORATION)
        self.assertEqual(explored.focus_square, "h8")
        self.assertEqual(
            tuple(cell.square for cell in explored.focus_view),
            ("g8", "h8", "g7", "h7"),
        )

    def test_invalid_exploration_fails_without_advancing_display(self):
        simulator = TactileSimulator()
        controller = TactileGraphicsController(simulator)
        before = controller.refresh_position(
            standard_position(),
            focus_square="e4",
        )

        with self.assertRaises(TactileGraphicsError):
            controller.explore("E4")

        self.assertIs(controller.current_scene, before)
        self.assertEqual(simulator.history, (before,))

    def test_display_failure_does_not_advance_controller_state(self):
        controller = TactileGraphicsController(_FailingDisplay())

        with self.assertRaisesRegex(RuntimeError, "simulated adapter failure"):
            controller.refresh_position(standard_position())

        self.assertIsNone(controller.current_scene)

    def test_gametree_cursor_uses_canonical_legality_projection(self):
        game = PgnGame(
            tags={"Result": "*"},
            line=VariationLine(
                moves=[
                    MoveNode("e4"),
                    MoveNode("e5"),
                    MoveNode("Nf3"),
                ]
            ),
        )
        simulator = TactileSimulator()
        controller = TactileGraphicsController(simulator)

        root = controller.on_gametree_navigation(
            game,
            GameTreeCursor(next_move_index=0),
        )
        after_e4 = controller.on_gametree_navigation(
            game,
            GameTreeCursor(next_move_index=1),
            focus_square="e4",
        )

        self.assertEqual(root.position_fen, standard_position().to_fen())
        self.assertNotEqual(after_e4.position_fen, root.position_fen)
        self.assertEqual(
            PositionState.from_fen(after_e4.position_fen).piece_at("e4"),
            "P",
        )
        self.assertEqual(
            after_e4.source,
            TactileSceneSource.GAMETREE_NAVIGATION,
        )
        self.assertEqual((root.sequence, after_e4.sequence), (1, 2))

    def test_variation_navigation_refreshes_from_branch_position(self):
        game = PgnGame(
            tags={"Result": "*"},
            line=VariationLine(
                moves=[
                    MoveNode(
                        "e4",
                        variations=[
                            VariationLine(moves=[MoveNode("d4")])
                        ],
                    ),
                    MoveNode("e5"),
                ]
            ),
        )
        path = (VariationStep(0, 0),)

        at_branch_start = position_for_gametree_cursor(
            game,
            GameTreeCursor(path, 0),
        )
        after_d4 = position_for_gametree_cursor(
            game,
            GameTreeCursor(path, 1),
        )

        self.assertEqual(at_branch_start.to_fen(), standard_position().to_fen())
        self.assertEqual(after_d4.piece_at("d4"), "P")
        self.assertIsNone(after_d4.piece_at("e4"))

    def test_unprovable_gametree_position_fails_closed(self):
        game = PgnGame(
            tags={"Result": "*"},
            line=VariationLine(moves=[MoveNode("not-a-legal-move")]),
        )

        with self.assertRaisesRegex(
            TactileGraphicsError,
            "position is not provable",
        ):
            position_for_gametree_cursor(
                game,
                GameTreeCursor(next_move_index=1),
            )


if __name__ == "__main__":
    unittest.main()
