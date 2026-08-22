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


class FakeTeacherBackend:
    def __init__(self):
        self.calls = []
        self.state = {
            "pointer_square": None,
            "highlights": [],
            "arrows": [],
            "coordinate_labels_visible": True,
            "student_pointer_history": [],
            "active_student_id": None,
            "engine_visibility": "hidden",
            "board_permission": "locked",
            "version": 1,
        }

    def dispatch(self, action_id, payload):
        payload = dict(payload)
        self.calls.append((action_id, payload))
        if action_id == "teacher.pointer_input":
            self.state["pointer_square"] = payload["square"]
        elif action_id == "teacher.pointer_clear":
            self.state["pointer_square"] = None
        elif action_id == "teacher.highlight":
            self.state["highlights"].append(
                {"square": payload["square"], "purpose": payload["purpose"]}
            )
        elif action_id == "teacher.arrow":
            self.state["arrows"].append(dict(payload))
        elif action_id == "teacher.clear_annotations":
            self.state["highlights"] = []
            self.state["arrows"] = []
        elif action_id == "teacher.board_permission":
            self.state["board_permission"] = payload["permission"]
        elif action_id == "teacher.engine_visibility":
            self.state["engine_visibility"] = payload["visibility"]
        return {"ok": True}

    def snapshot(self):
        return {
            key: tuple(value) if isinstance(value, list) else value
            for key, value in self.state.items()
        }


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
    def setUp(self):
        self.backend = FakeTeacherBackend()
        self.state = TeacherPresentationState(
            self.backend.dispatch,
            self.backend.snapshot,
        )

    def test_pointer_editor_dispatches_coordinate_immediately_and_auto_clears(self):
        self.assertIsNone(self.state.type_pointer_character("f"))
        self.assertEqual("f", self.state.pointer_input_buffer)
        self.assertEqual("f3", self.state.type_pointer_character("3"))
        self.assertEqual("", self.state.pointer_input_buffer)
        self.assertEqual(
            ("teacher.pointer_input", {"square": "f3"}),
            self.backend.calls[-1],
        )
        self.assertEqual("f3", self.state.pointer_square)

    def test_pointer_is_distinct_from_move_input_and_controller_owns_no_position(self):
        self.state.type_pointer_character("a")
        self.state.type_pointer_character("1")
        snapshot = self.state.presentation_snapshot()
        self.assertEqual("a1", snapshot["pointer_square"])
        self.assertNotIn("position", snapshot)
        self.assertNotIn("fen", snapshot)
        self.assertNotEqual("board.input", self.backend.calls[-1][0])

    def test_annotations_dispatch_only_and_summary_reads_provider_state(self):
        self.state.set_highlight("E4", purpose="legal")
        self.state.add_arrow("e2", "e4", purpose="idea")
        self.assertEqual("teacher.highlight", self.backend.calls[-2][0])
        self.assertEqual("teacher.arrow", self.backend.calls[-1][0])
        summary = self.state.accessible_annotation_summary(language="en")
        self.assertIn("e4 legal", summary)
        self.assertIn("e2–e4 idea", summary)
        self.state.clear_annotations()
        self.assertFalse(self.backend.state["highlights"])
        self.assertFalse(self.backend.state["arrows"])

    def test_hover_and_selection_remain_distinct_feedback_events(self):
        hover = self.state.record_student_event(StudentEventKind.HOVER, "d4", piece_name="knight")
        selected = self.state.record_student_event(StudentEventKind.SELECT, "d4", piece_name="knight")
        self.assertNotEqual(hover.kind, selected.kind)
        self.assertEqual("Hover d4, knight", self.state.concise_student_event(hover, language="en"))

    def test_invalid_pointer_input_fails_closed_and_resets_buffer_without_dispatch(self):
        before = list(self.backend.calls)
        with self.assertRaises(ValueError):
            self.state.type_pointer_character("9")
        self.assertEqual("", self.state.pointer_input_buffer)
        self.assertEqual(before, self.backend.calls)
        self.state.type_pointer_character("a")
        with self.assertRaises(ValueError):
            self.state.type_pointer_character("9")
        self.assertEqual("", self.state.pointer_input_buffer)
        self.assertEqual(before, self.backend.calls)

    def test_provider_that_leaks_chess_state_is_rejected(self):
        bad = TeacherPresentationState(
            self.backend.dispatch,
            lambda: {"pointer_square": "e4", "fen": "secret"},
        )
        with self.assertRaises(ValueError):
            bad.snapshot()


if __name__ == "__main__":
    unittest.main()
