"""Section 42 shipping-route lifecycle, preferences, hostile ingress, recovery."""
import json
from pathlib import Path
import tempfile
import unittest

from acs.settings import Settings, SettingsError
from acs.webapp import AccessibleChessAPI


ROOT = Path(__file__).resolve().parents[1]
VISUAL_FIELDS = {
    "pieceTheme", "orientation", "coordinateMode", "scalePercent",
    "showLastMove", "fitToWindow", "presentationMode",
    "animateMoves", "lowPowerMode",
}


class Section42ShippingRuntimeTests(unittest.TestCase):
    def _options(self, api):
        raw = api.get_state()["visualBoard"]["preferences"]
        return {key: value for key, value in raw.items() if key in VISUAL_FIELDS}

    def test_play_projection_has_exact_board_authority_and_silent_art(self):
        api = AccessibleChessAPI("en")
        board = api.get_state()
        visual = board["visualBoard"]
        self.assertEqual(visual["surface"], "ordinary_play")
        self.assertEqual(len(visual["cells"]), 64)
        self.assertEqual(visual["cells"][0]["square"], "a8")
        self.assertEqual(visual["cells"][0]["piece"], "r")
        self.assertEqual(visual["cells"][63]["square"], "h1")
        self.assertEqual(visual["cells"][63]["piece"], "R")
        self.assertEqual(len({cell["square"] for cell in visual["cells"]}), 64)
        self.assertEqual(visual["preferences"]["boardTheme"], "classic_wood")
        self.assertEqual(board["fen"], api.board.fen())
        self.assertFalse(visual["preferences"]["animateMoves"])

    def test_preferences_survive_restart_without_mutating_game_or_four_key_profile(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "settings.json"
            api = AccessibleChessAPI("en")
            api._settings = Settings(path)
            fen = api.board.fen()
            tree = api.review_history.export_tree()
            self.assertTrue(api.visual_profile_apply(
                "low-vision", "contrast", "high-contrast", "spacious")["ok"])
            original_profile = api.visual_profile_get()
            options = self._options(api)
            options.update({
                "pieceTheme": "rhosgfx", "orientation": "black",
                "coordinateMode": "every_square", "scalePercent": 200,
                "fitToWindow": True, "presentationMode": True,
                "animateMoves": True, "lowPowerMode": True,
            })
            result = api.visual_board_apply(options)
            self.assertTrue(result["ok"])
            self.assertEqual(result["visualBoard"]["preferences"]["pieceTheme"], "rhosgfx")
            self.assertEqual(result["visualBoard"]["preferences"]["boardTheme"], "high_contrast")
            self.assertEqual(api.board.fen(), fen)
            self.assertEqual(api.review_history.export_tree(), tree)
            self.assertEqual(api.visual_profile_get(), original_profile)

            restarted = AccessibleChessAPI("en")
            restarted._settings = Settings(path)
            loaded = restarted.get_state()["visualBoard"]["preferences"]
            for key, value in options.items():
                self.assertEqual(loaded[key], value, key)
            self.assertEqual(loaded["boardTheme"], "high_contrast")
            self.assertEqual(restarted.board.fen(), fen)

            restarted.visual_profile_apply("classic", "system", "wood", "comfortable")
            self.assertEqual(restarted.get_state()["visualBoard"]["preferences"]["boardTheme"],
                             "classic_wood")
            self.assertEqual(restarted.get_state()["visualBoard"]["preferences"]["pieceTheme"],
                             "rhosgfx")

    def test_unsafe_payload_cannot_change_settings_or_fen(self):
        with tempfile.TemporaryDirectory() as directory:
            settings = Settings(Path(directory) / "settings.json")
            api = AccessibleChessAPI("uk")
            api._settings = settings
            good = self._options(api)
            fen = api.board.fen()
            old = settings.get("visual_board_preferences_json")
            for bad in (
                {**good, "pieceTheme": "https://host.invalid/remote.svg"},
                {**good, "scalePercent": "200"},
                {**good, "scalePercent": True},
                {**good, "scalePercent": 201},
                {**good, "animateMoves": "yes"},
                {**good, "orientation": "../bad"},
                {**good, "unknown": 1},
                {key: value for key, value in good.items() if key != "lowPowerMode"},
            ):
                with self.subTest(bad=bad):
                    self.assertFalse(api.visual_board_apply(bad)["ok"])
                    self.assertEqual(settings.get("visual_board_preferences_json"), old)
                    self.assertEqual(api.board.fen(), fen)
            with self.assertRaises(SettingsError):
                settings.set("visual_board_preferences_json",
                             json.dumps({**good, "scalePercent": 10}))
            with self.assertRaises(SettingsError):
                settings.set("visual_board_preferences_json", "not json")

    def test_document_exposes_keyboard_controls_and_safe_fallback(self):
        html = (ROOT / "web/index.html").read_text(encoding="utf-8")
        css = (ROOT / "web/board_themes.css").read_text(encoding="utf-8")
        for target in (
            "section42-piece-style", "section42-board-scale", "section42-board-orientation",
            "section42-board-coordinates", "section42-board-fit",
            "section42-board-presentation", "section42-board-animate",
            "section42-board-low-power", "section42-board-apply",
            "section42-board-cancel",
        ):
            with self.subTest(target=target):
                self.assertIn('id="' + target + '"', html)
        self.assertIn("image.src='assets/pieces/rhosgfx/'+safeName", html)
        self.assertIn("image.addEventListener('error',()=>image.remove())", html)
        self.assertIn("node.setAttribute('aria-label',cell.label)", html)
        self.assertIn("image.setAttribute('aria-hidden','true')", html)
        self.assertIn("overlay.project(grid,ordered,visual)", html)
        self.assertIn('aria-live="off"', html)
        self.assertIn("data-board-shade", css)
        self.assertIn("prefers-reduced-motion:reduce", css)
        self.assertIn("forced-colors:active", css)
        self.assertNotIn("localStorage.setItem", html)


if __name__ == "__main__":
    unittest.main()
