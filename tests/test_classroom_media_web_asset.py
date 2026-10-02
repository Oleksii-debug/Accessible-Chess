from __future__ import annotations

from pathlib import Path
import unittest


class ClassroomMediaWebAssetTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.source = (
            Path(__file__).parents[1] / "web" / "full_product_classroom_media.js"
        ).read_text(encoding="utf-8")
        cls.bootstrap = (
            Path(__file__).parents[1] / "web" / "version2_final_product_bootstrap.js"
        ).read_text(encoding="utf-8")
        cls.workflow = (
            Path(__file__).parents[1] / ".github" / "workflows" / "classroom-media-webview.yml"
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
        self.assertIn("Media controls are temporarily unavailable.", source)
        self.assertIn("The chess board and lesson data remain available without video.", source)
        self.assertIn("availability.recovery_required === true", source)
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

    def test_media_section_stays_inside_existing_classes_main_landmark(self) -> None:
        source = self.source
        self.assertIn('const main = root.querySelector("main")', source)
        self.assertIn("(main || root).appendChild(section)", source)

    def test_participant_rows_are_programmatic_recovery_targets_not_tab_stops(self) -> None:
        source = self.source
        self.assertIn("row.tabIndex = -1", source)
        self.assertNotIn("row.tabIndex = 0", source)

    def test_action_updates_replace_only_media_section_and_restore_explicit_focus(self) -> None:
        source = self.source
        self.assertIn('root.querySelector("#classroom-media-section")', source)
        self.assertIn("current.replaceWith(renderSection", source)
        self.assertIn('focusById(root, payload.focus_target || "")', source)
        self.assertNotIn("root.replaceChildren", source)

    def test_media_workflow_expected_scope_is_c_sorted(self) -> None:
        source = self.workflow
        expected_block = source.split("expected=(", 1)[1].split(")", 1)[0]
        expected = [
            line.strip().strip("'")
            for line in expected_block.splitlines()
            if line.strip().startswith("'")
        ]
        self.assertEqual(expected, sorted(expected))

    def test_media_workflow_binds_live_pull_request_base_fail_closed(self) -> None:
        source = self.workflow
        self.assertIn("EVENT_BASE_SHA: ${{ github.event.pull_request.base.sha }}", source)
        self.assertIn('git merge-base --is-ancestor "$EVENT_BASE_SHA" HEAD', source)
        self.assertIn('git fetch --no-tags origin "$PR_BASE_REF"', source)
        self.assertIn('base="$(git rev-parse "refs/remotes/origin/$PR_BASE_REF")"', source)
        self.assertIn('git merge-base --is-ancestor "$base" HEAD', source)
        self.assertIn('git diff --name-only "$base...HEAD"', source)
        self.assertNotIn('base="$EVENT_BASE_SHA"', source)

    def test_classes_media_remains_reachable_when_education_is_unavailable(self) -> None:
        source = self.bootstrap
        start = source.index('} else if (routeId === "classes") {')
        end = source.index("if (restoreFocus)", start)
        block = source[start:end]
        unavailable = block.index("renderEmptyProduct(routeId, heading);")
        media_mount = block.index("AccessibleChessClassroomMediaSurface.mount")
        self.assertLess(unavailable, media_mount)
        self.assertIn("snapshot.media || null", block)

    def test_connection_text_is_not_a_competing_live_region(self) -> None:
        source = self.source
        self.assertIn('connection.setAttribute("aria-live", "off")', source)
        self.assertNotIn('aria-live", "polite"', source)
        self.assertNotIn('setAttribute("role", "status")', source)


if __name__ == "__main__":
    unittest.main()
