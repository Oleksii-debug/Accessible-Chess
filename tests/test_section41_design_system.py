from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]


class Section41DesignSystemTests(unittest.TestCase):
    def test_local_design_system_is_offline_and_accessible(self):
        html = (ROOT / "web/index.html").read_text(encoding="utf-8")
        css = (ROOT / "web/design_system.css").read_text(encoding="utf-8")
        self.assertIn('<link rel="stylesheet" href="design_system.css">', html)
        self.assertIn("--ac-accent", css)
        self.assertIn('[data-theme="dark"]', css)
        self.assertIn('[data-theme="contrast"]', css)
        self.assertIn('[data-theme="system"]', css)
        self.assertIn("forced-colors: active", css)
        self.assertIn("prefers-reduced-motion: reduce", css)
        self.assertIn(":focus-visible", css)
        self.assertNotIn("https://", css)


if __name__ == "__main__":
    unittest.main()
