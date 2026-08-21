import unittest

from acs.full_product_ui_shell import (
    AccessibleShellState,
    ROUTES,
    UILanguage,
    concise_user_error,
    is_standard_editing_shortcut,
    should_global_keymap_handle,
    validate_routes,
)
from acs.teacher_presentation import StudentEventKind, TeacherPresentationState


class AccessibleShellTests(unittest.TestCase):
    def test_route_registry_is_unique_localized_and_keyboard_focusable(self):
        validate_routes()
        self.assertEqual(10, len(ROUTES))
        self.assertEqual(len(ROUTES), len({route.open_action_id for route in ROUTES}))

    def test_navigation_exposes_all_major_product_modules(self):
        shell = AccessibleShellState(language=UILanguage.EN)
        ids = [item["route_id"] for item in shell.navigation_items()]
        self.assertEqual(
            [
                "board",
                "analysis",
                "pgn",
                "library",
                "books",
                "training",
                "teacher",
                "classes",
                "settings",
                "help",
            ],
            ids,
        )

    def test_route_focus_restores_without_mouse_dependency(self):
        shell = AccessibleShellState()
        self.assertEqual("move-input", shell.restore_focus_target())
        self.assertEqual("library-search", shell.open_route("library", current_focus_id="board-square-e4"))
        shell.record_focus("library-result-17")
        self.assertEqual("board-square-e4", shell.open_route("board"))
        self.assertEqual("library-result-17", shell.open_route("library"))

    def test_language_switch_changes_labels_not_route_identity(self):
        shell = AccessibleShellState(language=UILanguage.UA)
        before = [(item["route_id"], item["action_id"]) for item in shell.navigation_items()]
        ua = shell.current_route.label(shell.language)
        shell.set_language(UILanguage.EN)
        after = [(item["route_id"], item["action_id"]) for item in shell.navigation_items()]
        self.assertEqual(before, after)
        self.assertNotEqual(ua, shell.current_route.label(shell.language))

    def test_standard_editing_shortcuts_are_reserved_inside_editables(self):
        for key in "acxvzy":
            self.assertTrue(is_standard_editing_shortcut(key, ["Ctrl"]))
            self.assertFalse(should_global_keymap_handle(key=key, modifiers=["Ctrl"], editable=True))
        self.assertTrue(should_global_keymap_handle(key="g", modifiers=["Ctrl"], editable=True))
        self.assertTrue(should_global_keymap_handle(key="c", modifiers=["Ctrl"], editable=False))

    def test_internal_errors_do_not_leak_paths_tracebacks_or_database_noise(self):
        for raw in (
            'Traceback (most recent call last): File "C:\\app\\acs\\x.py", line 2',
            "sqlite OperationalError: database is locked",
            "UCI error: engine executable C:\\stockfish\\stockfish.exe missing",
        ):
            projected = concise_user_error(raw, language=UILanguage.EN)
            self.assertEqual("The action could not be completed.", projected)
        self.assertEqual(
            "Invalid PGN tag.",
            concise_user_error("Invalid PGN tag.", language=UILanguage.EN),
        )


class TeacherPresentationTests(unittest.TestCase):
    def test_pointer_editor_completes_coordinate_immediately_and_auto_clears(self):
        state = TeacherPresentationState()
        self.assertIsNone(state.type_pointer_character("f"))
        self.assertEqual("f", state.pointer_input_buffer)
        self.assertEqual("f3", state.type_pointer_character("3"))
        self.assertEqual("f3", state.pointer_square)
        self.assertEqual("", state.pointer_input_buffer)
        self.assertIsNone(state.type_pointer_character("c"))
        self.assertEqual("c7", state.type_pointer_character("7"))
        self.assertEqual(["f3", "c7"], state.pointer_history)

    def test_pointer_is_distinct_from_move_input_and_contains_no_position(self):
        state = TeacherPresentationState()
        state.set_pointer("a1")
        snapshot = state.presentation_snapshot()
        self.assertEqual("a1", snapshot["pointer"])
        self.assertNotIn("position", snapshot)
        self.assertNotIn("move", snapshot)

    def test_annotations_are_visual_state_only_and_deduplicate_arrows(self):
        state = TeacherPresentationState()
        state.set_highlight("E4", style="legal")
        state.add_arrow("e2", "e4", style="idea")
        state.add_arrow("e2", "e4", style="idea")
        self.assertEqual({"e4": "legal"}, state.highlights)
        self.assertEqual(1, len(state.arrows))
        state.clear_annotations()
        self.assertFalse(state.highlights)
        self.assertFalse(state.arrows)

    def test_hover_selection_and_move_request_remain_distinct_events(self):
        state = TeacherPresentationState()
        hover = state.record_student_event(StudentEventKind.HOVER, "d4", piece_name="knight")
        selected = state.record_student_event(StudentEventKind.SELECT, "d4", piece_name="knight")
        requested = state.record_student_event(StudentEventKind.MOVE_REQUEST, "f5")
        self.assertNotEqual(hover.kind, selected.kind)
        self.assertNotEqual(selected.kind, requested.kind)
        self.assertEqual("Hover d4, knight", state.concise_student_event(hover, language="en"))

    def test_invalid_pointer_input_fails_closed_and_resets_buffer(self):
        state = TeacherPresentationState()
        with self.assertRaises(ValueError):
            state.type_pointer_character("9")
        self.assertEqual("", state.pointer_input_buffer)
        state.type_pointer_character("a")
        with self.assertRaises(ValueError):
            state.type_pointer_character("9")
        self.assertEqual("", state.pointer_input_buffer)


if __name__ == "__main__":
    unittest.main()
