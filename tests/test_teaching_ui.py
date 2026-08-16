from __future__ import annotations

import unittest
from pathlib import Path

from acs.sound_profiles import SoundEventPreference, SoundProfile
from acs.teaching_ui import TeachingUiState
from acs.visual_preferences import VisualPackKind, VisualPackManifest


ROOT = Path(__file__).resolve().parents[1]
HTML = ROOT / "web" / "teaching.html"
TEACHING_APP = ROOT / "acs" / "teaching_webapp.py"


def piece_assets() -> dict[str, str]:
    return {
        f"{side}_{piece}": f"pieces/{side}_{piece}.svg"
        for side in ("white", "black")
        for piece in ("king", "queen", "rook", "bishop", "knight", "pawn")
    }


class TeachingUiStateTests(unittest.TestCase):
    def make_state(self) -> TeachingUiState:
        return TeachingUiState(
            visual_packs=(
                VisualPackManifest(
                    pack_id="blue-green",
                    version="1",
                    title="Blue Green",
                    kind=VisualPackKind.BOARD,
                    license_id="CC0-1.0",
                    assets={"light": "board/light.png", "dark": "board/dark.png"},
                ),
                VisualPackManifest(
                    pack_id="large-classic",
                    version="1",
                    title="Large Classic",
                    kind=VisualPackKind.PIECES,
                    license_id="CC0-1.0",
                    assets=piece_assets(),
                ),
            )
        )

    def test_visual_preferences_are_independent_and_pack_kind_checked(self) -> None:
        state = self.make_state()
        view = state.set_visual_preferences(
            {
                "board_theme_id": "blue-green",
                "piece_theme_id": "large-classic",
                "coordinate_mode": "every_square",
                "board_scale_percent": 140,
                "piece_scale_percent": 120,
            }
        )
        self.assertEqual(view["visual"]["board_theme_id"], "blue-green")
        self.assertEqual(view["visual"]["piece_theme_id"], "large-classic")
        self.assertEqual(view["visual"]["coordinate_mode"], "every_square")
        self.assertEqual(view["visual"]["board_scale_percent"], 140)
        self.assertEqual(view["visual"]["piece_scale_percent"], 120)
        with self.assertRaises(ValueError):
            state.set_visual_preferences({"board_theme_id": "large-classic"})

    def test_coordinate_modes_do_not_change_semantic_square_identity(self) -> None:
        state = self.make_state()
        state.set_visual_preferences({"coordinate_mode": "off"})
        self.assertEqual(
            state.coordinate_labels_for("f3"),
            {"showFile": False, "showRank": False, "showEverySquare": False},
        )
        state.set_visual_preferences({"coordinate_mode": "edges"})
        self.assertEqual(
            state.coordinate_labels_for("a4"),
            {"showFile": False, "showRank": True, "showEverySquare": False},
        )
        state.set_visual_preferences({"coordinate_mode": "every_square"})
        self.assertEqual(
            state.coordinate_labels_for("f3"),
            {"showFile": True, "showRank": True, "showEverySquare": True},
        )

    def test_pointer_commit_is_semantic_immediate_clear_and_refocus_contract(self) -> None:
        state = self.make_state()
        result = state.commit_pointer(" F 3 ")
        self.assertTrue(result["ok"])
        self.assertEqual(result["square"], "f3")
        self.assertTrue(result["clearInput"])
        self.assertTrue(result["keepFocus"])
        self.assertEqual(state.snapshot()["pointer"]["square"], "f3")
        with self.assertRaises(ValueError):
            state.commit_pointer("f9")

    def test_student_pointer_history_is_concise_and_timestamp_free(self) -> None:
        state = self.make_state()
        result = state.record_student_pointer("student-1", "Марко", "e4", "click")
        self.assertEqual(result["accessibleText"], "Марко: e 4.")
        self.assertNotIn(":00", result["history"])
        self.assertEqual(state.snapshot()["studentPointerHistory"][0]["action"], "click")

    def test_square_and_arrow_annotations_are_overlay_state_only(self) -> None:
        state = self.make_state()
        state.add_square_annotation("s1", "c7")
        state.add_arrow_annotation("a1", "f3", "c6")
        rows = state.snapshot()["annotations"]
        self.assertEqual(rows[0]["kind"], "square")
        self.assertEqual(rows[1]["kind"], "arrow")
        self.assertEqual(rows[1]["source"], "f3")
        self.assertEqual(rows[1]["target"], "c6")

    def test_sound_profile_is_per_event_and_preview_never_fakes_disabled_playback(self) -> None:
        state = TeachingUiState(
            sound=SoundProfile(
                master_enabled=True,
                master_volume_percent=80,
                events={"check": SoundEventPreference(enabled=True, volume_percent=50, sound_id="soft.check")},
            )
        )
        preview = state.preview_sound_event("check")
        self.assertTrue(preview["ok"])
        self.assertEqual(preview["soundId"], "soft.check")
        self.assertEqual(preview["volumePercent"], 40)
        state.set_sound_event("check", enabled=False)
        preview = state.preview_sound_event("check")
        self.assertFalse(preview["ok"])
        self.assertEqual(preview["volumePercent"], 0)
        self.assertIn("вимкнено", preview["accessibleText"])


class TeachingWebSemanticTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.html = HTML.read_text(encoding="utf-8")
        cls.app_source = TEACHING_APP.read_text(encoding="utf-8")

    def test_teaching_surface_has_semantic_controls_and_one_live_region(self) -> None:
        self.assertIn('id="pointer-input"', self.html)
        self.assertIn('id="coordinate-mode"', self.html)
        self.assertIn('value="every_square"', self.html)
        self.assertIn('id="student-history"', self.html)
        self.assertIn('id="sound-events"', self.html)
        self.assertEqual(self.html.count('role="status"'), 1)

    def test_pointer_input_commits_two_character_square_then_clears_and_refocuses(self) -> None:
        self.assertIn("/^[a-h][1-8]$/", self.html)
        self.assertIn("teaching_pointer_commit", self.html)
        self.assertIn("e.target.value=''", self.html)
        self.assertIn("e.target.focus()", self.html)

    def test_visual_theme_does_not_rewrite_accessible_square_name(self) -> None:
        self.assertIn("n.setAttribute('aria-label',squareName(s))", self.html)
        self.assertIn("snapshot.visual.board_scale_percent", self.html)
        self.assertNotIn("aria-label=\"theme", self.html)

    def test_no_os_mouse_is_source_of_truth(self) -> None:
        lowered = self.html.lower()
        self.assertNotIn("setcursorpos", lowered)
        self.assertNotIn("mousemove", lowered)
        self.assertIn("snapshot.pointer.square", self.html)

    def test_teaching_launcher_is_isolated_from_frozen_release_app(self) -> None:
        self.assertNotIn("from . import webapp", self.app_source)
        self.assertNotIn("from .webapp", self.app_source)
        self.assertNotIn("chesscore", self.app_source.lower())
        self.assertIn("TeachingAccessibleChessAPI", self.app_source)
        self.assertIn('"web" / "teaching.html"', self.app_source)


if __name__ == "__main__":
    unittest.main()
