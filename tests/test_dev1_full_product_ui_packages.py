import unittest

from acs.bookdocument import (
    BookDocument,
    Diagram,
    Exercise as BookExercise,
    Heading,
    Paragraph,
    Position,
)
from acs.bookreader import BookReader
from acs.full_product_actions import (
    FULL_PRODUCT_ACTION_IDS,
    FullProductActionRouter,
    build_full_product_action_registry,
    validate_full_product_actions,
)
from acs.full_product_presenters import (
    BookReaderPresenter,
    LibraryPresenter,
    PgnTreePresenter,
    SurfaceStatus,
    TrainingPresenter,
)
from acs.full_product_ui_shell import AccessibleShellState, ROUTES, UILanguage
from acs.gametree import parse_games, serialize_games
from acs.keybindings import BindingContext
from acs.search_service import GameSearchItem, GameSearchPage, GameSearchQuery
from acs.teacher_presentation import (
    AnnotationStyle,
    BoardOrientation,
    StudentEventKind,
    TeacherPresentationState,
    TeachingMode,
)
from acs.training import ExerciseDefinition, ExerciseSession, ExerciseStep


class FullProductActionTests(unittest.TestCase):
    def test_one_registry_contains_stage1_and_full_product_actions_without_collisions(self):
        validate_full_product_actions()
        registry = build_full_product_action_registry()
        self.assertEqual("board.current", registry.definition("board.current").action_id)
        self.assertEqual("teacher.pointer_input", registry.definition("teacher.pointer_input").action_id)
        self.assertIn("screen.library", FULL_PRODUCT_ACTION_IDS)
        self.assertIn("student.move", FULL_PRODUCT_ACTION_IDS)
        self.assertEqual(
            "teacher.pointer_input",
            registry.resolve_binding(BindingContext.DOCUMENT, "Ctrl+Alt+P").action_id,
        )
        self.assertNotEqual(
            registry.definition("teacher.pointer_input").action_id,
            registry.definition("board.input").action_id,
        )

    def test_screen_action_is_shell_local_but_domain_action_delegates_unchanged(self):
        calls = []

        def delegate(action_id, payload):
            calls.append((action_id, dict(payload)))
            return {"ok": True}

        shell = AccessibleShellState()
        router = FullProductActionRouter(shell, delegate)
        screen = router.dispatch("screen.library", current_focus_id="board-square-e4")
        self.assertTrue(screen.handled_by_shell)
        self.assertEqual("library", screen.route_id)
        self.assertEqual("library-search-player", screen.focus_target)
        self.assertEqual([], calls)
        domain = router.dispatch("library.open_game", {"game_id": 41})
        self.assertFalse(domain.handled_by_shell)
        self.assertEqual({"ok": True}, domain.value)
        self.assertEqual([("library.open_game", {"game_id": 41})], calls)

    def test_every_full_product_route_has_registered_open_action(self):
        registry = build_full_product_action_registry()
        for route in ROUTES:
            self.assertEqual(route.open_action_id, registry.definition(route.open_action_id).action_id)


class ShellDialogFocusTests(unittest.TestCase):
    def test_nested_dialogs_restore_exact_keyboard_focus(self):
        shell = AccessibleShellState(initial_route="library")
        shell.record_focus("library-result-17")
        self.assertEqual(
            "filter-player",
            shell.open_dialog(
                "library-filter-dialog",
                opener_focus_id="library-filter-button",
                initial_focus_id="filter-player",
            ),
        )
        self.assertEqual(
            "confirm-ok",
            shell.open_dialog(
                "confirm-dialog",
                opener_focus_id="filter-apply",
                initial_focus_id="confirm-ok",
            ),
        )
        self.assertEqual("filter-player", shell.close_dialog("confirm-dialog"))
        self.assertEqual("library-filter-button", shell.close_dialog("library-filter-dialog"))
        self.assertEqual("library-filter-button", shell.restore_focus_target())

    def test_route_change_is_blocked_while_dialog_is_active(self):
        shell = AccessibleShellState(initial_route="books")
        shell.open_dialog(
            "bookmark-dialog",
            opener_focus_id="book-bookmark",
            initial_focus_id="bookmark-name",
        )
        with self.assertRaises(RuntimeError):
            shell.open_route("training")
        self.assertEqual("books", shell.current_route.route_id)

    def test_language_changes_semantics_without_route_or_focus_identity_change(self):
        shell = AccessibleShellState(language=UILanguage.UA, initial_route="teacher")
        ua = shell.semantic_snapshot()
        shell.set_language(UILanguage.EN)
        en = shell.semantic_snapshot()
        self.assertEqual(ua["route_id"], en["route_id"])
        self.assertEqual(ua["focus_target"], en["focus_target"])
        self.assertNotEqual(ua["heading"], en["heading"])


class PgnPresenterTests(unittest.TestCase):
    def setUp(self):
        text = """[Event \"Accessible test\"]
[White \"White\"]
[Black \"Black\"]
[Result \"*\"]

1. e4 {main comment} e5 $1 (1... c5 {Sicilian} 2. Nf3 (2. Nc3)) 2. Nf3 *
"""
        self.games = tuple(parse_games(text))

    def test_recursive_variations_comments_and_nags_are_semantically_projected(self):
        presenter = PgnTreePresenter(self.games, language=UILanguage.EN)
        view = presenter.view()
        self.assertEqual("White — Black", view.title)
        self.assertTrue(any("e4" in item.label for item in view.items))
        self.assertTrue(any("$1" in item.label for item in view.items))
        self.assertTrue(any(item.comments and "main comment" in item.comments for item in view.items))
        self.assertTrue(any(item.kind == "variation" and item.label == "Variation 1" for item in view.items))
        self.assertGreaterEqual(max(item.depth for item in view.items), 3)

    def test_keyboard_selection_parent_and_boundaries_are_explicit(self):
        presenter = PgnTreePresenter(self.games, language=UILanguage.EN)
        first = presenter.selected()
        second = presenter.move_selection(1)
        self.assertNotEqual(first.node_id, second.node_id)
        variation = next(item for item in presenter.items() if item.kind == "variation")
        presenter.select(variation.node_id)
        self.assertEqual(variation.parent_id, presenter.select_parent().node_id)
        presenter.select(presenter.items()[0].node_id)
        with self.assertRaises(LookupError):
            presenter.move_selection(-1)

    def test_mutation_intent_dispatch_never_edits_canonical_game_in_presenter(self):
        presenter = PgnTreePresenter(self.games)
        before = serialize_games(self.games)
        calls = []

        def dispatch(action_id, payload):
            calls.append((action_id, dict(payload)))
            return "accepted"

        result = presenter.dispatch_edit(
            "pgn.comment_edit",
            dispatch,
            extra={"text": "new comment"},
        )
        self.assertEqual("accepted", result)
        self.assertEqual(before, serialize_games(self.games))
        self.assertEqual("pgn.comment_edit", calls[0][0])
        self.assertEqual("new comment", calls[0][1]["text"])

    def test_language_switch_changes_label_not_stable_node_identity(self):
        presenter = PgnTreePresenter(self.games, language=UILanguage.UA)
        ua_ids = [item.node_id for item in presenter.items()]
        ua_labels = [item.label for item in presenter.items() if item.kind == "variation"]
        presenter.set_language(UILanguage.EN)
        self.assertEqual(ua_ids, [item.node_id for item in presenter.items()])
        self.assertNotEqual(ua_labels, [item.label for item in presenter.items() if item.kind == "variation"])


class FakeSearchService:
    def __init__(self):
        self.calls = []
        self.pages = {
            None: GameSearchPage(
                items=(
                    GameSearchItem(1, 10, r"C:\\private\\one.pgn", "PGN", 0, "full", "Alpha", "Beta", "Event A", None, "2026.01.01", "1", "1-0", "C20", "King Pawn", None),
                    GameSearchItem(2, 10, r"C:\\private\\one.pgn", "PGN", 1, "full", "Gamma", "Delta", "Event B", None, "2026.01.02", "2", "0-1", "B12", "Caro-Kann", None),
                ),
                next_after_game_id=2,
                has_more=True,
            ),
            2: GameSearchPage(
                items=(
                    GameSearchItem(3, 11, "/home/user/two.pgn", "PGN", 0, "full", "Epsilon", "Zeta", None, None, None, None, "1/2-1/2", None, None, None),
                ),
                next_after_game_id=None,
                has_more=False,
            ),
        }

    def search(self, query):
        normalized = query.normalized()
        self.calls.append(normalized)
        return self.pages[normalized.after_game_id]


class FailingSearchService:
    def search(self, query):
        raise RuntimeError(r"sqlite OperationalError at C:\\private\\library.db")


class LibraryPresenterTests(unittest.TestCase):
    def test_paging_selection_and_cached_previous_page_remain_keyboard_stable(self):
        service = FakeSearchService()
        presenter = LibraryPresenter(service, language=UILanguage.EN)
        first = presenter.search(GameSearchQuery(player="Alpha", limit=2))
        self.assertEqual(SurfaceStatus.READY, first.status)
        self.assertEqual(1, first.selected_game_id)
        presenter.select(2)
        self.assertEqual(3, presenter.next_page().selected_game_id)
        self.assertEqual(1, presenter.previous_page().selected_game_id)
        self.assertEqual(2, len(service.calls))

    def test_source_paths_are_not_projected_into_visible_rows(self):
        presenter = LibraryPresenter(FakeSearchService(), language=UILanguage.EN)
        first = presenter.search(GameSearchQuery(limit=2))
        self.assertEqual("one.pgn", first.rows[0].source_label)
        self.assertNotIn("private", first.rows[0].source_label)
        second = presenter.next_page()
        self.assertEqual("two.pgn", second.rows[0].source_label)
        self.assertNotIn("/home/", second.rows[0].source_label)

    def test_open_selected_dispatches_neutral_ids_not_database_rows(self):
        presenter = LibraryPresenter(FakeSearchService())
        presenter.search(GameSearchQuery(limit=2))
        presenter.select(2)
        calls = []

        def dispatch(action_id, payload):
            calls.append((action_id, dict(payload)))
            return "opened"

        self.assertEqual("opened", presenter.open_selected(dispatch))
        self.assertEqual(
            [("library.open_game", {"game_id": 2, "source_id": 10, "source_index": 1})],
            calls,
        )

    def test_database_path_exception_becomes_concise_accessible_error(self):
        view = LibraryPresenter(FailingSearchService(), language=UILanguage.EN).search(GameSearchQuery())
        self.assertEqual(SurfaceStatus.ERROR, view.status)
        self.assertEqual("The action could not be completed.", view.message)
        self.assertNotIn("sqlite", view.message.lower())
        self.assertNotIn("C:\\", view.message)


class BookReaderPresenterTests(unittest.TestCase):
    def setUp(self):
        self.document = BookDocument(
            title="Accessible book",
            source_name=r"C:\\private\\book.docx",
            blocks=[
                Heading(text="Chapter 1", level=1, source_anchor=r"C:\\private\\book.docx#h1"),
                Paragraph(text="Text paragraph"),
                Diagram(
                    fen="8/8/8/8/8/8/4K3/7k w - - 0 1",
                    caption="Position A",
                    alt_text=None,
                    source_anchor=r"C:\\private\\book.docx#diagram1",
                ),
                Position(fen="8/8/8/8/8/8/3K4/7k b - - 0 1", caption="Position B"),
                BookExercise(
                    fen="8/8/8/8/8/8/2K5/7k w - - 0 1",
                    prompt="Find the square.",
                    answer_text="c3",
                ),
            ],
        )

    def test_semantic_roles_heading_path_warning_and_source_privacy(self):
        presenter = BookReaderPresenter(BookReader(self.document), language=UILanguage.EN)
        heading = presenter.current()
        self.assertEqual("heading", heading.role)
        self.assertEqual(1, heading.heading_level)
        diagram = presenter.next_position()
        self.assertEqual("img", diagram.role)
        self.assertIn("Chapter 1", diagram.heading_path)
        self.assertIn("No separate diagram description", diagram.warning)
        self.assertEqual("book.docx#diagram1", diagram.source_anchor)
        self.assertNotIn("private", diagram.source_anchor)

    def test_open_position_and_return_restore_exact_reading_context(self):
        presenter = BookReaderPresenter(BookReader(self.document))
        diagram = presenter.next_position()
        calls = []

        def dispatch(action_id, payload):
            calls.append((action_id, dict(payload)))
            return "board-opened"

        self.assertEqual("board-opened", presenter.open_current_position(dispatch))
        self.assertEqual(diagram.position_fen, calls[0][1]["fen"])
        presenter.next_block()
        restored = presenter.return_from_board()
        self.assertEqual(diagram.index, restored.index)
        self.assertEqual(diagram.position_fen, restored.position_fen)

    def test_named_bookmark_is_independent_from_board_return_point(self):
        presenter = BookReaderPresenter(BookReader(self.document))
        saved = presenter.bookmark("chapter-start")
        presenter.next_position()
        self.assertEqual(saved.index, presenter.restore_bookmark("chapter-start").index)


class TrainingPresenterTests(unittest.TestCase):
    def setUp(self):
        self.definition = ExerciseDefinition(
            exercise_id="ex-1",
            start_fen="rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w KQkq - 0 1",
            steps=(
                ExerciseStep(frozenset({"e4"}), hint="Move the pawn two squares.", explanation="Good."),
                ExerciseStep(frozenset({"e5"}), hint="Advance again."),
            ),
            title="Pawn practice",
            source_id="book:1",
        )

    def test_hint_reject_accept_and_completion_delegate_to_canonical_session(self):
        presenter = TrainingPresenter(ExerciseSession(self.definition), language=UILanguage.EN)
        hint, view = presenter.request_hint()
        self.assertTrue(hint.available)
        self.assertEqual("Move the pawn two squares.", view.message)
        rejected, view = presenter.submit("e3")
        self.assertFalse(rejected.accepted)
        self.assertEqual("Try again.", view.message)
        accepted, view = presenter.submit("e4")
        self.assertTrue(accepted.accepted)
        self.assertEqual("Good.", view.message)
        completed, view = presenter.submit("e5")
        self.assertTrue(completed.completed)
        self.assertEqual("Exercise completed.", view.message)

    def test_reveal_and_retry_do_not_advance_canonical_progress(self):
        presenter = TrainingPresenter(ExerciseSession(self.definition), language=UILanguage.EN)
        before = presenter.snapshot()
        self.assertEqual(("e4",), presenter.reveal_solution())
        self.assertEqual(before, presenter.snapshot())
        presenter.retry()
        self.assertEqual(before, presenter.snapshot())

    def test_snapshot_restore_preserves_progress_without_ui_side_state(self):
        presenter = TrainingPresenter(ExerciseSession(self.definition))
        presenter.submit("e4")
        snapshot = presenter.snapshot()
        restored = TrainingPresenter.restore(self.definition, snapshot)
        self.assertEqual(snapshot, restored.snapshot())
        self.assertEqual(2, restored.view().step_number)


class CanonicalTeacherBackend:
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
        elif action_id == "teacher.highlight":
            self.state["highlights"].append({"square": payload["square"], "purpose": payload["purpose"]})
        elif action_id == "teacher.arrow":
            self.state["arrows"].append(dict(payload))
        elif action_id == "teacher.board_permission":
            self.state["board_permission"] = payload["permission"]
        elif action_id == "teacher.engine_visibility":
            self.state["engine_visibility"] = payload["visibility"]
        return action_id

    def snapshot(self):
        return {key: tuple(value) if isinstance(value, list) else value for key, value in self.state.items()}


class TeacherControllerTests(unittest.TestCase):
    def setUp(self):
        self.backend = CanonicalTeacherBackend()
        self.controller = TeacherPresentationState(self.backend.dispatch, self.backend.snapshot)

    def test_policy_commands_are_dispatched_to_canonical_owner_not_stored_in_ui(self):
        self.controller.set_board_permission("move_allowed")
        self.controller.set_engine_visibility("visible_to_teacher")
        self.assertEqual("move_allowed", self.backend.state["board_permission"])
        self.assertEqual("visible_to_teacher", self.backend.state["engine_visibility"])
        self.assertEqual("teacher.board_permission", self.backend.calls[-2][0])
        self.assertEqual("teacher.engine_visibility", self.backend.calls[-1][0])

    def test_student_move_is_explicit_action_not_hover_or_selection(self):
        self.controller.record_student_event(StudentEventKind.HOVER, "e4")
        self.controller.record_student_event(StudentEventKind.SELECT, "e4")
        self.controller.request_student_move("e4")
        self.assertEqual("student.move", self.backend.calls[-1][0])
        self.assertEqual({"raw_text": "e4"}, self.backend.calls[-1][1])
        self.assertEqual(2, len(self.controller.feedback_events()))

    def test_hover_duplicate_feedback_is_coalesced_without_hiding_selection(self):
        for sequence in range(5):
            self.controller.record_student_event(
                StudentEventKind.HOVER,
                "d4",
                piece_name="knight",
                student_id="student-1",
                sequence=sequence,
            )
        self.controller.record_student_event(StudentEventKind.SELECT, "d4", piece_name="knight")
        events = self.controller.feedback_events(limit=10)
        self.assertEqual(2, len(events))
        self.assertEqual(StudentEventKind.HOVER, events[0].kind)
        self.assertEqual(StudentEventKind.SELECT, events[1].kind)

    def test_modes_orientation_and_theme_are_ui_only_but_annotations_dispatch(self):
        self.controller.set_teaching_mode(TeachingMode.ATTACK_DEFENCE)
        self.assertEqual(BoardOrientation.BLACK, self.controller.toggle_orientation())
        self.controller.type_pointer_character("f")
        self.controller.type_pointer_character("3")
        self.controller.set_highlight("d5", purpose="attack")
        self.controller.add_arrow("e4", "d5", purpose="idea")
        self.assertEqual("attack_defence", self.controller.teaching_mode.value)
        self.assertEqual("black", self.controller.orientation.value)
        summary = self.controller.accessible_annotation_summary(language="en")
        self.assertIn("Pointer f3", summary)
        self.assertIn("d5 attack", summary)
        self.assertIn("e4–d5 idea", summary)
        self.assertNotIn("position", self.controller.snapshot())

    def test_custom_annotation_color_requires_safe_hex_but_only_purpose_crosses_boundary(self):
        self.controller.register_style(AnnotationStyle("student", "#123ABC"))
        self.controller.set_highlight("a1", purpose="student")
        action, payload = self.backend.calls[-1]
        self.assertEqual("teacher.highlight", action)
        self.assertEqual({"square": "a1", "purpose": "student"}, payload)
        self.assertNotIn("color", payload)
        with self.assertRaises(ValueError):
            AnnotationStyle("bad", "red")

    def test_provider_chess_state_leak_is_rejected(self):
        bad = TeacherPresentationState(self.backend.dispatch, lambda: {"pointer_square": "e4", "fen": "x"})
        with self.assertRaises(ValueError):
            bad.snapshot()


if __name__ == "__main__":
    unittest.main()
