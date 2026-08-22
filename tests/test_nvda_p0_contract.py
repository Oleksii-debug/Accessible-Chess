import unittest
from html.parser import HTMLParser
from pathlib import Path

from acs.webapp import AccessibleChessAPI


class _SemanticProbe(HTMLParser):
    def __init__(self):
        super().__init__()
        self.tags = []
        self.attrs_by_id = {}

    def handle_starttag(self, tag, attrs):
        data = dict(attrs)
        self.tags.append((tag, data))
        element_id = data.get("id")
        if element_id:
            self.attrs_by_id[element_id] = (tag, data)


class NVDAP0ContractTests(unittest.TestCase):
    """Regression gate for the real NVDA failure captured in issue #2.

    These tests cannot certify NVDA itself. They prevent the WebView2 surface
    from silently regressing back to a visually-only or canvas-first contract
    before a human Windows + NVDA acceptance test.
    """

    @classmethod
    def setUpClass(cls):
        cls.html_path = Path(__file__).resolve().parents[1] / "web" / "index.html"
        cls.html = cls.html_path.read_text(encoding="utf-8")
        cls.probe = _SemanticProbe()
        cls.probe.feed(cls.html)

    def test_main_surface_is_a_real_semantic_document(self):
        main = self.probe.attrs_by_id.get("main-content")
        self.assertIsNotNone(main)
        self.assertEqual(main[0], "main")

        heading_ids = {
            "h-game-info", "h-moves", "h-white", "h-black", "h-status",
            "h-last", "h-input", "h-engine", "h-board", "h-actions",
            "h-settings", "h-help",
        }
        for heading_id in heading_ids:
            with self.subTest(heading=heading_id):
                self.assertEqual(self.probe.attrs_by_id[heading_id][0], "h2")

    def test_native_form_controls_remain_available_to_nvda_quick_navigation(self):
        self.assertEqual(self.probe.attrs_by_id["move-input"][0], "input")
        self.assertEqual(self.probe.attrs_by_id["move-input"][1].get("type"), "text")
        self.assertEqual(self.probe.attrs_by_id["fen-input"][0], "input")
        self.assertEqual(self.probe.attrs_by_id["position-input"][0], "textarea")
        self.assertEqual(self.probe.attrs_by_id["position-turn"][0], "select")

        required_buttons = {
            "move-submit", "fen-load", "position-load", "empty-board",
            "engine-toggle", "board-launcher", "new-game", "undo", "redo",
            "white-turn", "black-turn",
        }
        for button_id in required_buttons:
            with self.subTest(button=button_id):
                tag, attrs = self.probe.attrs_by_id[button_id]
                self.assertEqual(tag, "button")
                self.assertEqual(attrs.get("type"), "button")

    def test_live_region_is_separate_from_reading_blocks(self):
        tag, attrs = self.probe.attrs_by_id["live"]
        self.assertEqual(tag, "div")
        self.assertEqual(attrs.get("role"), "status")
        self.assertEqual(attrs.get("aria-live"), "polite")
        for block_id in ("game-info", "moves", "white-pieces", "black-pieces", "game-status", "last-move", "engine-status"):
            with self.subTest(block=block_id):
                self.assertEqual(self.probe.attrs_by_id[block_id][1].get("aria-live"), "off")

    def test_board_is_dedicated_application_surface_not_canvas(self):
        tag, attrs = self.probe.attrs_by_id["board-application"]
        self.assertEqual(tag, "div")
        self.assertEqual(attrs.get("role"), "application")
        grid_tag, grid_attrs = self.probe.attrs_by_id["board-grid"]
        self.assertEqual(grid_tag, "div")
        self.assertEqual(grid_attrs.get("role"), "grid")
        self.assertEqual(grid_attrs.get("aria-rowcount"), "8")
        self.assertEqual(grid_attrs.get("aria-colcount"), "8")
        self.assertNotIn("<canvas", self.html.lower())

    def test_python_board_contract_has_64_unique_logical_squares(self):
        api = AccessibleChessAPI("uk")
        cells = api.get_state()["board"]
        self.assertEqual(len(cells), 64)
        squares = [cell["square"] for cell in cells]
        self.assertEqual(len(set(squares)), 64)
        self.assertEqual(set(squares), {f"{file}{rank}" for file in "abcdefgh" for rank in "12345678"})

    def test_empty_square_is_coordinate_only_and_occupied_square_names_piece(self):
        api = AccessibleChessAPI("uk")
        self.assertEqual(api.square_label("e4"), "e 4")
        self.assertIn("білий король", api.square_label("e1"))

    def test_locked_move_input_commands_b_and_c_do_not_regress(self):
        api = AccessibleChessAPI("en")
        black = api.make_move("b")
        self.assertTrue(black["ok"])
        self.assertEqual(api.board.turn, "b")

        api.new_game()
        cleared = api.make_move("c")
        self.assertTrue(cleared["ok"])
        self.assertTrue(all(piece is None for piece in api.board.board))

        api.new_game()
        old_black_alias = api.make_move("d")
        old_clear_alias = api.make_move("x")
        self.assertFalse(old_black_alias["ok"])
        self.assertFalse(old_clear_alias["ok"])
        self.assertTrue(any(piece is not None for piece in api.board.board))


if __name__ == "__main__":
    unittest.main()
