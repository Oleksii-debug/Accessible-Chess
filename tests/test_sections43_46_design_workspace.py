from __future__ import annotations

import json
from pathlib import Path
import unittest

from acs.design_studio import (
    AppTheme,
    Density,
    DesignPreferences,
    WorkspaceLayout,
    decode_preferences,
    encode_preferences,
    exported_profile,
    preset_profile,
    preset_profiles,
    safe_preferences_or_default,
)


ROOT = Path(__file__).resolve().parents[1]
WEB = ROOT / "web"
API = ROOT / "acs" / "version2_release_ui.py"


class Sections4346DesignWorkspaceTests(unittest.TestCase):
    def test_required_premium_profiles_are_real_and_roundtrip(self) -> None:
        required = {
            "classic", "tournament", "coach", "classroom_presentation",
            "low_vision", "high_contrast",
        }
        self.assertEqual(required, set(preset_profiles()))
        for profile_id in sorted(required):
            value = preset_profile(profile_id)
            self.assertEqual(value, decode_preferences(encode_preferences(value)))
            self.assertGreaterEqual(len(value.layouts), 7)
            self.assertIn("chess", {layout.workspace for layout in value.layouts})

    def test_low_vision_and_high_contrast_are_not_cosmetic_aliases(self) -> None:
        low = preset_profile("low_vision")
        high = preset_profile("high_contrast")
        self.assertIs(low.theme, AppTheme.HIGH_CONTRAST)
        self.assertIs(high.theme, AppTheme.HIGH_CONTRAST)
        self.assertGreaterEqual(low.text_scale_percent, 150)
        self.assertGreaterEqual(low.board.board_scale_percent, 140)
        self.assertTrue(low.board.reduced_motion)
        self.assertTrue(high.board.reduced_motion)

    def test_corrupt_profile_fails_safe_to_classic_without_private_data(self) -> None:
        fallback = safe_preferences_or_default('{"schema_version":999}')
        self.assertEqual("Classic", fallback.profile_name)
        payload = exported_profile(fallback)
        text = json.dumps(payload, ensure_ascii=False).casefold()
        for forbidden in ("api_key", "password", "token", "c:\\", "/home/", "/users/"):
            self.assertNotIn(forbidden, text)

    def test_workspace_layout_is_bounded_and_versioned(self) -> None:
        layout = WorkspaceLayout(
            "media", ("player", "timeline", "board", "analysis"),
            ("analysis",), 58,
        )
        value = DesignPreferences(
            "Owner profile", AppTheme.DARK, Density.COMPACT,
            120, 125, 130, layouts=(layout,),
        )
        decoded = decode_preferences(encode_preferences(value))
        self.assertEqual(1, decoded.schema_version)
        self.assertEqual(("analysis",), decoded.layouts[0].collapsed)
        with self.assertRaises(ValueError):
            WorkspaceLayout("media", ("player", "player"), (), 58)

    def test_index_loads_offline_design_assets(self) -> None:
        html = (WEB / "index.html").read_text(encoding="utf-8")
        self.assertIn('href="accessible_chess_design.css"', html)
        self.assertIn('src="accessible_chess_workspaces.js"', html)
        self.assertNotIn("cdn.jsdelivr", html)
        self.assertNotIn("unpkg.com", html)

    def test_workspace_projection_preserves_semantics_and_focus(self) -> None:
        js = (WEB / "accessible_chess_workspaces.js").read_text(encoding="utf-8")
        for token in (
            "Chess", "Library", "Books", "Training", "Teacher", "Student", "Media",
            "aria-current", "aria-expanded", "MutationObserver",
            "heading.tabIndex=-1", "heading.focus({preventScroll:true})",
            "design_update_layout", "design_preview_preset", "design_apply",
            "design_cancel", "design_reset",
        ):
            with self.subTest(token=token):
                self.assertIn(token, js)
        self.assertNotIn("document.onkeydown", js)
        self.assertNotIn("onclick=", js)

    def test_design_css_has_forced_colors_reduced_motion_and_responsive_layout(self) -> None:
        css = (WEB / "accessible_chess_design.css").read_text(encoding="utf-8")
        for token in (
            "@media(forced-colors:active)",
            "@media(prefers-reduced-motion:reduce)",
            "@media(max-width:65rem)",
            ":focus-visible",
            ".ac-workspace",
            ".ac-panel",
            "#ac-workspace-toolbar",
        ):
            with self.subTest(token=token):
                self.assertIn(token, css)
        self.assertNotIn("@import url(", css)
        self.assertNotIn("http://", css)
        self.assertNotIn("https://", css)

    def test_v2_api_is_the_single_persistence_bridge(self) -> None:
        source = API.read_text(encoding="utf-8")
        for token in (
            "def design_snapshot(",
            "def design_preview_preset(",
            "def design_preview_fields(",
            "def design_apply(",
            "def design_cancel(",
            "def design_reset(",
            "def design_update_layout(",
            "def set_visual_preference(",
            'settings.set("design_profile_json", encode_preferences(value))',
            'state["design"] = exported_profile(design)',
            'state["visualBoard"] = visual',
        ):
            with self.subTest(token=token):
                self.assertIn(token, source)

    def test_existing_domain_surfaces_remain_present(self) -> None:
        # Styling/workspaces must be a projection over canonical modules, not demo pages.
        required = (
            "full_product_library.js", "full_product_books_training.js",
            "full_product_teacher.js", "full_product_classroom.js",
            "recorded_media_accessible_player.js", "youtube_iframe_playback_adapter.js",
        )
        for name in required:
            with self.subTest(name=name):
                self.assertTrue((WEB / name).is_file(), name)


if __name__ == "__main__":
    unittest.main()
