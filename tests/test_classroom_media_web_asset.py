from __future__ import annotations

from pathlib import Path
import unittest


class ClassroomMediaWebAssetTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.source = (
            Path(__file__).parents[1] / "web" / "full_product_classroom_media.js"
        ).read_text(encoding="utf-8")

    def test_important_media_state_is_real_selectable_dom_text(self) -> None:
        source = self.source
        self.assertIn("textContent", source)
        self.assertIn('node("p", item && item.summary || "")', source)
        self.assertIn('node("p", snapshot.connection_text || "")', source)
        self.assertNotIn("innerHTML", source)
        self.assertNotIn("outerHTML", source)
        self.assertNotIn("insertAdjacentHTML", source)
        self.assertNotIn("document.write", source)

    def test_controls_are_native_buttons_without_global_keyboard_takeover(self) -> None:
        source = self.source
        self.assertIn('node("button"', source)
        self.assertIn('button.type = "button"', source)
        self.assertNotIn('document.addEventListener("keydown"', source)
        self.assertNotIn('window.addEventListener("keydown"', source)
        self.assertNotIn('setAttribute("role", "button")', source)

    def test_unavailable_provider_is_truthfully_visible_without_fake_controls(self) -> None:
        source = self.source
        self.assertIn("Realtime media is not configured for this build yet.", source)
        self.assertIn("The chess board and lesson data remain available without video.", source)
        self.assertIn('if (!snapshot || typeof snapshot !== "object")', source)

    def test_surface_accepts_only_media_commands_from_snapshot(self) -> None:
        source = self.source
        self.assertIn("/^media\\.[a-z_]+$/", source)
        self.assertIn("action.payload || {}", source)
        lowered = source.casefold()
        self.assertNotIn("roomadmin", lowered)
        self.assertNotIn("api_secret", lowered)
        self.assertNotIn("join token", lowered)
        self.assertNotIn("fen", lowered)
        self.assertNotIn("make_move", lowered)

    def test_action_updates_replace_only_media_section_and_restore_explicit_focus(self) -> None:
        source = self.source
        self.assertIn('root.querySelector("#classroom-media-section")', source)
        self.assertIn("current.replaceWith(renderSection", source)
        self.assertIn('focusById(root, payload.focus_target || "")', source)
        self.assertNotIn("root.replaceChildren", source)

    def test_connection_text_is_not_a_competing_live_region(self) -> None:
        source = self.source
        self.assertIn('connection.setAttribute("aria-live", "off")', source)
        self.assertNotIn('aria-live", "polite"', source)
        self.assertNotIn('setAttribute("role", "status")', source)


if __name__ == "__main__":
    unittest.main()
