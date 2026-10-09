from pathlib import Path
import tempfile
import unittest

from acs.settings import Settings
from acs.webapp import AccessibleChessAPI


ROOT = Path(__file__).resolve().parents[1]


class VisualProfileTests(unittest.TestCase):
    def test_profiles_have_apply_cancel_reset_and_accessible_controls(self):
        html = (ROOT / "web" / "index.html").read_text(encoding="utf-8")
        css = (ROOT / "web" / "design_system.css").read_text(encoding="utf-8")
        for control in ("visual-profile", "visual-theme", "visual-board-theme", "visual-density", "visual-apply", "visual-cancel", "visual-reset"):
            self.assertIn(f'id="{control}"', html)
        self.assertIn('data-visual-profile', css)
        self.assertIn('[data-density="compact"]', css)
        self.assertIn('[data-density="spacious"]', css)

    def test_visual_profile_persists_as_one_atomic_settings_value(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "settings.json"
            api = AccessibleChessAPI("en")
            api._settings = Settings(path)
            result = api.visual_profile_apply("low-vision", "contrast", "high-contrast", "spacious")
            self.assertTrue(result["ok"])

            restarted = AccessibleChessAPI("en")
            restarted._settings = Settings(path)
            loaded = restarted.visual_profile_get()
            self.assertEqual(loaded["profile"], "low-vision")
            self.assertEqual(loaded["theme"], "contrast")
            self.assertEqual(loaded["board_theme"], "high-contrast")
            self.assertEqual(loaded["density"], "spacious")


if __name__ == "__main__":
    unittest.main()
