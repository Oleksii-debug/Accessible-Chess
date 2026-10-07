from __future__ import annotations

import json
from pathlib import Path
import tempfile
import unittest

from acs.version2_release_ui import Version2ReleaseAccessibleChessAPI
from acs.visual_board_contract import (
    VisualBoardConsumer,
    build_visual_board_contract,
)
from acs.visual_board_webview import VisualBoardWebViewError, VisualBoardWebViewState
from acs.visual_pack_store import VisualPackStore, VisualPreferencesStore
from acs.visual_preferences import (
    BoardOrientation,
    BoardVisualPreferences,
    CoordinateMode,
    VISUAL_PREFERENCES_SCHEMA_VERSION,
)


class Section15VisualBoardClosureTests(unittest.TestCase):
    def make_visual(self, root: Path) -> VisualBoardWebViewState:
        return VisualBoardWebViewState(
            VisualPackStore(root / "packs"),
            VisualPreferencesStore(root / "visual-preferences.json"),
        )

    def test_schema_v2_roundtrip_and_v1_migration_preserve_orientation(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            store = VisualPreferencesStore(root / "prefs.json")
            expected = BoardVisualPreferences(
                coordinate_mode=CoordinateMode.EVERY_SQUARE,
                orientation=BoardOrientation.BLACK,
                board_scale_percent=135,
                piece_scale_percent=110,
                show_last_move=False,
                reduced_motion=True,
            )
            store.save(expected)
            saved = json.loads(store.path.read_text(encoding="utf-8"))
            self.assertEqual(VISUAL_PREFERENCES_SCHEMA_VERSION, saved["schema_version"])
            self.assertEqual("black", saved["preferences"]["orientation"])
            self.assertEqual(expected, store.load())

            old = expected.as_dict()
            old.pop("orientation")
            store.path.write_text(
                json.dumps({"schema_version": 1, "preferences": old}),
                encoding="utf-8",
            )
            migrated = store.load()
            self.assertIsNotNone(migrated)
            self.assertEqual(BoardOrientation.WHITE, migrated.orientation)
            self.assertEqual(CoordinateMode.EVERY_SQUARE, migrated.coordinate_mode)

    def test_shared_contract_supports_all_surfaces_and_rejects_chess_truth(self) -> None:
        visual = {
            "preferences": BoardVisualPreferences().as_dict(),
            "effective": {"board_theme_id": "classic", "piece_theme_id": "classic"},
            "themes": {"board": (), "pieces": ()},
            "assets": {"board": {}, "pieces": {}},
        }
        for consumer in VisualBoardConsumer:
            payload = build_visual_board_contract(
                consumer,
                visual,
                selected_square="e2",
                legal_squares=("e3", "e4"),
                last_move=("g1", "f3"),
            )
            self.assertEqual(consumer.value, payload["consumer"])
            self.assertEqual("e2", payload["presentation"]["selected_square"])
            self.assertEqual(["e3", "e4"], payload["presentation"]["legal_squares"])
            self.assertEqual({"from": "g1", "to": "f3"}, payload["presentation"]["last_move"])
            self.assertNotIn("fen", payload["visual"])
            self.assertNotIn("pieces", payload["visual"])

        with self.assertRaises(ValueError):
            build_visual_board_contract("play", {"fen": "forbidden"})
        with self.assertRaises(ValueError):
            build_visual_board_contract("play", {"moves": []})
        with self.assertRaises(ValueError):
            build_visual_board_contract(
                "play",
                visual,
                selected_square="E2",
            )

    def test_visual_state_persists_every_section15_preference_without_chess_state(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            visual = self.make_visual(root)
            changes = {
                "coordinate_mode": "every_square",
                "orientation": "black",
                "board_scale_percent": 150,
                "piece_scale_percent": 120,
                "show_last_move": False,
                "reduced_motion": True,
            }
            for field, value in changes.items():
                visual.update_field(field, value)
            snapshot = visual.snapshot()
            for field, value in changes.items():
                self.assertEqual(value, snapshot["preferences"][field])
            self.assertEqual("classic", snapshot["effective"]["board_theme_id"])
            self.assertEqual("classic", snapshot["effective"]["piece_theme_id"])
            self.assertNotIn("fen", repr(snapshot).lower())
            self.assertNotIn("legal_moves", repr(snapshot).lower())
            with self.assertRaises(VisualBoardWebViewError):
                visual.update_field("position_fen", "secret")

            visual.reset()
            self.assertEqual(BoardVisualPreferences().as_dict(), visual.snapshot()["preferences"])

    def test_ordinary_board_contract_projects_selection_legal_moves_and_last_move(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            visual = self.make_visual(Path(raw))
            api = Version2ReleaseAccessibleChessAPI()
            api.bind_visual_board_state(visual)

            initial = api.get_state()
            contract = initial["visualBoard"]
            self.assertEqual("play", contract["consumer"])
            self.assertIsNone(contract["presentation"]["selected_square"])
            self.assertEqual([], contract["presentation"]["legal_squares"])
            self.assertIsNone(contract["presentation"]["last_move"])

            selected = api.activate_square("e2")
            presentation = selected["visualBoard"]["presentation"]
            self.assertEqual("e2", presentation["selected_square"])
            self.assertEqual({"e3", "e4"}, set(presentation["legal_squares"]))

            moved = api.make_move("e4")
            self.assertEqual(
                {"from": "e2", "to": "e4"},
                moved["visualBoard"]["presentation"]["last_move"],
            )

            changed = api.visual_update_field("orientation", "black")
            self.assertTrue(changed["ok"])
            self.assertEqual(
                "black",
                changed["visualBoard"]["visual"]["preferences"]["orientation"],
            )
            self.assertEqual(
                BoardOrientation.BLACK,
                visual.preference_store.load().orientation,
            )

    def test_visual_update_cannot_mutate_chess_truth(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            visual = self.make_visual(Path(raw))
            api = Version2ReleaseAccessibleChessAPI()
            api.bind_visual_board_state(visual)
            before = api.board.fen()
            rejected = api.visual_update_field("fen", "8/8/8/8/8/8/8/8 w - - 0 1")
            self.assertFalse(rejected["ok"])
            self.assertEqual(before, api.board.fen())
            self.assertNotIn("8/8", rejected["announcement"])

    def test_web_surface_exposes_complete_visual_controls_without_replacing_grid_semantics(self) -> None:
        root = Path(__file__).resolve().parents[1]
        html = (root / "web" / "index.html").read_text(encoding="utf-8")
        teacher = (root / "web" / "full_product_teacher.js").read_text(encoding="utf-8")
        bootstrap = (root / "web" / "stage1_release_bootstrap.js").read_text(encoding="utf-8")

        for token in (
            'id="board-grid" role="grid"',
            'role="gridcell"',
            'visual-board-theme',
            'visual-piece-theme',
            'visual-orientation',
            'visual-coordinate-mode',
            'visual-board-scale',
            'visual-piece-scale',
            'visual-show-last-move',
            'visual-reduced-motion',
            'data-visual-legal',
            'data-visual-last',
            "visual_update_field",
        ):
            self.assertIn(token, html)
        self.assertIn("black=el('board-grid').dataset.orientation==='black'", html)
        self.assertIn("teacher-visual-board-theme", teacher)
        self.assertIn("teacher-visual-piece-theme", teacher)
        self.assertIn("teacher.visual.update", teacher)
        self.assertIn("stage1-visual-piece", bootstrap)
        self.assertIn("activeVisualPieceAssets", bootstrap)
        self.assertIn("grid.dataset.reducedMotion === 'true'", bootstrap)


if __name__ == "__main__":
    unittest.main()
