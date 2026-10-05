import json
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from acs.acsdb import AcsDatabase
from acs.analysis_service import AnalysisService
from acs.book_progress_store import (
    BookProgressStore,
    BookProgressStoreError,
    BookProgressStoreErrorCode,
)
from acs.book_text_import import BookTextFormat, import_text_book
from acs.bookdocument import BookDocument, Exercise
from acs.bookreader import BookReader
from acs.chesscore import Board
from acs.engine_assisted_workflows import EngineAssistedWorkflowService
from acs.pgn_service import open_pgn
from acs.report_paths import report_safe_name
from acs.version2_application import Version2Application
from acs.version2_windows_file_workflows import FileWorkflowEvent, FileWorkflowEventKind, Version2WindowsFileActionDelegate
from acs.version2_windows_import_event_mailbox import Version2ImportUiEventMailbox


PGN = '[Event "Україна"]\n[White "Петренко"]\n[Black "Smith"]\n[Result "*"]\n\n1. e4 {before} (1. d4 $1 d5) e5 *\n'


class Version2ApplicationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.source = self.root / "input.pgn"
        self.source.write_text(PGN, encoding="utf-8")
        self.database = AcsDatabase(self.root / "library.acsdb")
        self.addCleanup(self.database.close)
        self.analysis = AnalysisService(lambda: None)
        self.addCleanup(self.analysis.close)
        self.copied = []
        self.projected_positions = []

        def project_position(fen):
            self.projected_positions.append(fen)
            return {"ok": True}

        self.app = Version2Application(self.database, progress_store=BookProgressStore(self.root / "progress.json"),
            engine_assistance=EngineAssistedWorkflowService(self.analysis), board_dispatch=lambda *_: None,
            board_position_projector=project_position, copy_text=self.copied.append)
        self.mailbox = Version2ImportUiEventMailbox()
        self.dialogs = SimpleNamespace(open_pgn=lambda: self.source, save_pgn_as=lambda *_: self.root / "saved.pgn", select_library_import=lambda: self.source)
        self.files = Version2WindowsFileActionDelegate(dialogs=self.dialogs, get_pgn_session=lambda: self.app.session,
            set_pgn_session=self.app.set_document, import_services_factory=self.app.worker_factory(self.root / "library.acsdb"),
            event_sink=self.mailbox, next_delegate=lambda *_: None)
        self.app.bind_files(self.files)
        self.addCleanup(lambda: self.files.shutdown(timeout=5))

    def test_record_focus_uses_one_exact_shell_dom_id_authority(self):
        self.app.record_focus("board-square-e4")
        self.assertEqual("board-square-e4", self.app._focus)
        self.assertEqual("board-square-e4", self.app.shell.restore_focus_target())

        # Empty/non-text notifications are not focus transitions and must not
        # erase the last valid token consumed by the native menu.
        self.app.record_focus("")
        self.app.record_focus(None)
        self.assertEqual("board-square-e4", self.app._focus)
        self.assertEqual("board-square-e4", self.app.shell.restore_focus_target())

        for token in (" board-square-e4", "board-square-e4 ", "кнопка", "bad.focus"):
            with self.subTest(token=token):
                with self.assertRaises(ValueError):
                    self.app.record_focus(token)
                self.assertEqual("board-square-e4", self.app._focus)
                self.assertEqual("board-square-e4", self.app.shell.restore_focus_target())

    def test_native_file_open_browser_edit_save_and_reopen(self):
        self.app.browser_command("shell", "pgn.open")
        self.assertEqual(self.app.shell.current_route.route_id, "pgn")
        selected = self.app.browser_command("pgn", "pgn.select", {"node_id": "g0:main/m0"})
        self.assertEqual(selected["kind"], "selection")
        edited = self.app.browser_command("pgn", "pgn.comment_edit", {"text": "новий коментар"})
        self.assertEqual(edited["kind"], "selection")
        self.assertTrue(self.app.session.dirty)
        self.app.browser_command("shell", "pgn.save")
        self.assertFalse(self.app.session.dirty)
        reopened = open_pgn(self.source)
        self.assertEqual(reopened.games[0].line.moves[0].comments_after[0].text, "новий коментар")
        self.assertEqual(len(reopened.games[0].line.moves[0].variations), 1)

    def test_native_cancel_pgn_open_reaches_bound_file_runtime(self):
        calls = []
        cancelling = FileWorkflowEvent(
            kind=FileWorkflowEventKind.PGN_OPEN_CANCELLING,
            action_id="pgn.cancel_open",
            focus_target="pgn-open-cancel",
        )

        def files(action, payload):
            calls.append((action, dict(payload)))
            return cancelling

        self.app.bind_files(files)
        result = self.app._delegate("pgn.cancel_open", {})

        self.assertIs(result, cancelling)
        self.assertEqual(calls, [("pgn.cancel_open", {})])
        events = self.app.drain_events()
        self.assertEqual(events[-1]["kind"], "status")
        self.assertIn("Скасовую", events[-1]["payload"]["announcement"])

    def test_native_cancel_pgn_save_reaches_bound_file_runtime(self):
        calls = []
        cancelling = FileWorkflowEvent(
            kind=FileWorkflowEventKind.PGN_SAVE_CANCELLING,
            action_id="pgn.cancel_save",
            focus_target="pgn-save-cancel",
        )

        def files(action, payload):
            calls.append((action, dict(payload)))
            return cancelling

        self.app.bind_files(files)
        result = self.app._delegate("pgn.cancel_save", {})

        self.assertIs(result, cancelling)
        self.assertEqual(calls, [("pgn.cancel_save", {})])
        events = self.app.drain_events()
        self.assertEqual(events[-1]["kind"], "status")
        announcement = events[-1]["payload"]["announcement"]
        self.assertIn("Запит на скасування", announcement)
        self.assertIn("ще не опубліковано", announcement)
        self.assertNotIn("Скасовую", announcement)

    def test_pgn_save_preflight_and_postpublication_stale_messages_are_truthful(self):
        preflight = FileWorkflowEvent(
            kind=FileWorkflowEventKind.FAILED,
            action_id="pgn.save_as",
            error_code="pgn_save_preflight_stale",
        )
        durable = FileWorkflowEvent(
            kind=FileWorkflowEventKind.FAILED,
            action_id="pgn.save",
            error_code="pgn_save_stale",
        )

        preflight_message = self.app._native_file_error_message(preflight)
        durable_message = self.app._native_file_error_message(durable)

        self.assertIn("не розпочато", preflight_message)
        self.assertNotIn("уже записано", preflight_message)
        self.assertIn("уже записано", durable_message)

    def test_pgn_save_conflict_announces_no_clobber_truth(self):
        conflict = FileWorkflowEvent(
            kind=FileWorkflowEventKind.FAILED,
            action_id="pgn.save",
            focus_target="pgn-game-list",
            error_code="pgn_save_conflict",
        )

        self.app._file_event(conflict)

        events = self.app.drain_events()
        self.assertEqual(events[-1]["kind"], "error")
        message = events[-1]["payload"]["message"]
        self.assertIn("не перезаписано", message)
        self.assertNotIn(str(self.root), message)

    def test_async_pgn_save_completion_announces_without_route_replacement(self):
        saved = FileWorkflowEvent(
            kind=FileWorkflowEventKind.PGN_SAVED,
            action_id="pgn.save",
            focus_target="pgn-game-list",
            game_count=1,
        )

        self.app.import_ui_ready(SimpleNamespace(drain=lambda: (saved,)))

        events = self.app.drain_events()
        self.assertFalse(any(event["kind"] == "route" for event in events))
        self.assertEqual(events[-1]["kind"], "status")
        self.assertIn("збережено", events[-1]["payload"]["announcement"])

    def test_async_pgn_open_completion_refreshes_route_and_announces(self):
        self.app.set_document(PgnDocumentSession.open(self.source))
        self.app.drain_events()
        opened = FileWorkflowEvent(
            kind=FileWorkflowEventKind.PGN_OPENED,
            action_id="pgn.open",
            focus_target="pgn-game-list",
            game_count=1,
        )

        self.app.import_ui_ready(SimpleNamespace(drain=lambda: (opened,)))

        events = self.app.drain_events()
        self.assertEqual(events[0]["kind"], "route")
        self.assertEqual(events[0]["payload"]["route_id"], "pgn")
        self.assertEqual(events[0]["payload"]["focus_target"], "pgn-game-list")
        self.assertEqual(events[1]["kind"], "status")
        self.assertEqual(events[1]["payload"]["announcement"], "PGN відкрито.")

    def test_real_import_observer_search_open_detached_game(self):
        self.app.browser_command("library", "library.import")
        self.assertTrue(self.files.wait_for_import(5))
        self.app.import_ui_ready(self.mailbox)
        snapshot = self.app.snapshot()
        self.assertEqual(snapshot["library"]["import"]["phase"], "completed")
        self.assertEqual(snapshot["library"]["import"]["processed_games"], 1)
        searched = self.app.browser_command("library", "library.search", {"player": "петренко"})
        self.assertEqual(searched["kind"], "render")
        before = self.database.get_game(1)["pgn_text"]
        self.assertEqual(self.app.browser_command("library", "library.open_game")["kind"], "delegated")
        self.app.browser_command("pgn", "pgn.select", {"node_id": "g0:main/m0"})
        self.app.browser_command("pgn", "pgn.comment_edit", {"text": "detached edit"})
        self.assertEqual(self.database.get_game(1)["pgn_text"], before)
        serialized = json.dumps(self.app.snapshot(), ensure_ascii=False)
        self.assertNotIn(str(self.root), serialized)
        self.assertNotIn("attempt_id", serialized)

    def test_late_native_cancel_cannot_regress_completed_import_ui(self):
        self.app.browser_command("library", "library.import")
        self.assertTrue(self.files.wait_for_import(5))
        self.app.import_ui_ready(self.mailbox)
        before = self.app.snapshot()["library"]["import"]
        self.assertEqual(before["phase"], "completed")
        self.app.drain_events()

        late_cancel = FileWorkflowEvent(
            kind=FileWorkflowEventKind.IMPORT_CANCELLING,
            action_id="library.cancel_import",
        )
        self.app.bind_files(lambda action, payload: late_cancel)

        result = self.app._delegate("library.cancel_import", {})

        self.assertIs(result, late_cancel)
        self.assertEqual(self.app.snapshot()["library"]["import"], before)
        self.assertEqual(self.app.drain_events(), ())

    def test_empty_source_has_terminal_ui_and_can_retry(self):
        self.source.write_text("", encoding="utf-8")
        self.app.browser_command("library", "library.import")
        self.assertTrue(self.files.wait_for_import(5))
        self.app.import_ui_ready(self.mailbox)
        self.assertEqual(self.app.snapshot()["library"]["import"]["phase"], "empty")
        self.source.write_text(PGN, encoding="utf-8")
        self.app.browser_command("library", "library.import")
        self.assertTrue(self.files.wait_for_import(5))
        self.app.import_ui_ready(self.mailbox)
        self.assertEqual(self.app.snapshot()["library"]["import"]["phase"], "completed")

    def _open_book_game(self):
        book = self.root / "study.md"
        book_pgn = (
            '[Event "Україна"]\n'
            '[White "Петренко"]\n'
            '[Black "Smith"]\n'
            '[Result "*"]\n\n'
            '{Intro C:\\\\private\\\\root.txt} '
            '1. e4 {before} (1. d4 $1 d5 *) e5 * '
            '{Outro /home/private/tail.txt}\n'
        )
        book.write_text(
            "# Навчання\n\nТекст\n\n```pgn\n" + book_pgn + "```\n\nПісля\n",
            encoding="utf-8",
        )
        self.app.open_book_dialog = lambda: book
        self.assertEqual(self.app.browser_command("shell", "book.open")["kind"], "delegated")
        self.app.browser_command("books", "book.next_game")
        return book, self.app.reader.location()

    def test_browser_ingress_rejects_string_subclasses_before_custom_hooks(self):
        class HostileText(str):
            touched = False

            def __eq__(self, _other):
                type(self).touched = True
                raise AssertionError("browser ingress equality hook must never execute")

            def __hash__(self):
                type(self).touched = True
                raise AssertionError("browser ingress hash hook must never execute")

            def startswith(self, *_args, **_kwargs):
                type(self).touched = True
                raise AssertionError("browser ingress startswith hook must never execute")

            def strip(self, *_args, **_kwargs):
                type(self).touched = True
                raise AssertionError("browser ingress strip hook must never execute")

        result = self.app.browser_command(HostileText("books"), "book.next")
        self.assertEqual("error", result["kind"])
        self.assertFalse(HostileText.touched)

        result = self.app.browser_command("books", HostileText("book.next"))
        self.assertEqual("error", result["kind"])
        self.assertFalse(HostileText.touched)


    def test_direct_book_dispatch_rejects_command_subclass_without_strip_hook(self):
        self._open_book_game()

        class StripBomb(str):
            touched = False

            def strip(self, *_args, **_kwargs):
                type(self).touched = True
                raise AssertionError("application preflight must not strip subclass")

        event = self.app._dispatch_book_surface_command(StripBomb("book.next"))
        self.assertEqual("error", event.kind)
        self.assertFalse(StripBomb.touched)


    def test_board_projection_rejects_hostile_or_oversized_position_before_projector(self):
        class StripBomb(str):
            touched = False

            def strip(self, *_args, **_kwargs):
                type(self).touched = True
                raise AssertionError("board boundary must not strip subclass")

        before = list(self.projected_positions)
        with self.assertRaisesRegex(RuntimeError, "canonical board position"):
            self.app._project_board_position(StripBomb("8/8/8/8/8/8/8/8 w - - 0 1"))
        self.assertFalse(StripBomb.touched)

        with self.assertRaisesRegex(RuntimeError, "canonical board position"):
            self.app._project_board_position("x" * 4097)
        with self.assertRaisesRegex(RuntimeError, "canonical board position"):
            self.app._project_board_position("8/8/8/8/8/8/8/8 w - - 0 1\x00")
        self.assertEqual(before, self.projected_positions)


    def test_whole_app_book_snapshot_exposes_semantic_game_reading_without_board_activation(self):
        _book, origin = self._open_book_game()

        snapshot = self.app.snapshot()
        book = snapshot["books"]
        tree = book.get("semantic_tree")

        self.assertIsInstance(tree, dict)
        self.assertEqual(tree["players"], "Петренко — Smith")
        self.assertIn(
            {"kind": "event", "label": "Подія", "value": "Україна"},
            tree["details"],
        )
        self.assertEqual(len(tree["intro_comments"]), 1)
        self.assertIn("Intro", tree["intro_comments"][0])
        self.assertEqual(len(tree["outro_comments"]), 1)
        self.assertIn("Outro", tree["outro_comments"][0])
        self.assertGreaterEqual(len(tree["items"]), 5)
        self.assertIn("e4", tree["items"][0]["label"])
        self.assertIsNone(tree["items"][0]["parent_index"])
        self.assertEqual(tree["items"][1]["kind"], "variation")
        self.assertEqual(tree["items"][1]["depth"], 1)
        self.assertEqual(tree["items"][1]["parent_index"], 0)
        self.assertEqual(tree["items"][1]["result"], "*")
        self.assertEqual(tree["items"][0]["result"], "")
        self.assertIn("d4", tree["items"][2]["label"])
        self.assertEqual(tree["items"][2]["parent_index"], 1)
        self.assertIn("$1", tree["items"][2]["label"])
        serialized = json.dumps(book, ensure_ascii=False)
        self.assertNotIn("[Event", serialized)
        self.assertNotIn("C:\\\\private", serialized)
        self.assertNotIn("/home/private", serialized)
        self.assertNotIn(str(self.root), serialized)
        self.assertEqual(self.app.reader.location(), origin)
        self.assertFalse(self.app.book_workflow.active)
        self.assertFalse(snapshot["book_board_active"])

    def test_book_registry_linear_actions_reach_canonical_reader(self):
        book = self.root / "linear-reading.md"
        book.write_text("# Розділ\n\nПерший абзац.\n\nДругий абзац.\n", encoding="utf-8")
        self.app.open_book_dialog = lambda: book
        self.assertEqual(self.app.browser_command("shell", "book.open")["kind"], "delegated")
        self.assertEqual(self.app.shell.current_route.route_id, "books")

        origin = self.app.reader.location()
        forward = self.app.router.dispatch("book.next_block")
        self.assertFalse(forward.handled_by_shell)
        self.assertEqual(forward.value.kind, "render")
        self.assertEqual(self.app.reader.index, origin.index + 1)

        backward = self.app.router.dispatch("book.previous_block")
        self.assertFalse(backward.handled_by_shell)
        self.assertEqual(backward.value.kind, "render")
        self.assertEqual(self.app.reader.location(), origin)

    def test_book_stale_write_rebinds_external_canonical_progress(self):
        book = self.root / "stale-write.md"
        book.write_text(
            "# Chapter\n\nFirst paragraph.\n\nSecond paragraph.\n",
            encoding="utf-8",
        )
        self.app.open_book_dialog = lambda: book
        self.assertEqual(
            self.app.browser_command("shell", "book.open")["kind"],
            "delegated",
        )
        store = self.app.progress_store
        key = self.app.book_key
        document = self.app.reader.document
        before = self.app.reader.snapshot()

        external_reader = BookReader(document)
        external_reader.go_to(2)
        external_store = BookProgressStore(store.path)
        injected = False

        def external_generation_wins(_book_key, _reader):
            nonlocal injected
            if not injected:
                external_store.save(key, external_reader)
                injected = True
            raise BookProgressStoreError(
                "external Book progress generation won",
                code=BookProgressStoreErrorCode.STALE_WRITE,
            )

        with patch.object(
            store,
            "save",
            side_effect=external_generation_wins,
        ):
            result = self.app.browser_command("books", "book.next")

        self.assertTrue(injected)
        self.assertEqual("error", result["kind"])
        self.assertIsNotNone(self.app.reader)
        self.assertNotEqual(before, self.app.reader.snapshot())
        self.assertEqual(
            external_reader.snapshot(),
            self.app.reader.snapshot(),
            "STALE_WRITE rollback overwrote the canonical external Book progress",
        )
        persisted = external_store.restore_primary(key, document)
        self.assertEqual(persisted.snapshot(), self.app.reader.snapshot())
        self.assertEqual("books", self.app.shell.current_route.route_id)

    def test_book_durability_unknown_reloads_visible_canonical_progress(self):
        book = self.root / "durability-unknown.md"
        book.write_text(
            "# Розділ\n\nПерший абзац.\n\nДругий абзац.\n",
            encoding="utf-8",
        )
        self.app.open_book_dialog = lambda: book
        self.assertEqual(
            self.app.browser_command("shell", "book.open")["kind"],
            "delegated",
        )
        store = self.app.progress_store
        key = self.app.book_key
        before = self.app.reader.snapshot()

        def fail_primary_sync(path):
            if Path(path) == store.path:
                raise OSError("post-replace durability probe failed")

        with patch(
            "acs.book_progress_store._sync_published_path",
            side_effect=fail_primary_sync,
        ):
            result = self.app.browser_command("books", "book.next")

        self.assertEqual(result["kind"], "error")
        self.assertIsNotNone(self.app.reader)
        self.assertIsNotNone(self.app.books)
        self.assertNotEqual(self.app.reader.snapshot(), before)
        self.assertEqual(self.app.reader.index, 1)
        persisted = store.restore(key, self.app.reader.document)
        self.assertEqual(persisted.snapshot(), self.app.reader.snapshot())
        self.assertEqual(self.app.shell.current_route.route_id, "books")

    def test_book_post_replace_change_reloads_actual_canonical_progress(self):
        book = self.root / "post-replace-change.md"
        book.write_text(
            "# Розділ\n\nПерший абзац.\n\nДругий абзац.\n",
            encoding="utf-8",
        )
        self.app.open_book_dialog = lambda: book
        self.assertEqual(
            self.app.browser_command("shell", "book.open")["kind"],
            "delegated",
        )
        store = self.app.progress_store
        key = self.app.book_key
        before = self.app.reader.snapshot()
        canonical_before = store.path.read_bytes()

        def replace_after_sync(path):
            if Path(path) == store.path:
                store.path.write_bytes(canonical_before)

        with patch(
            "acs.book_progress_store._sync_published_path",
            side_effect=replace_after_sync,
        ):
            result = self.app.browser_command("books", "book.next")

        self.assertEqual(result["kind"], "error")
        self.assertIsNotNone(self.app.reader)
        self.assertEqual(self.app.reader.snapshot(), before)
        persisted = store.restore(key, self.app.reader.document)
        self.assertEqual(persisted.snapshot(), before)
        self.assertEqual(self.app.shell.current_route.route_id, "books")

    def test_book_open_binds_native_focus_to_rendered_current_block(self):
        book = self.root / "initial-book-focus.md"
        book.write_text(
            "# Розділ\n\nПерший абзац.\n",
            encoding="utf-8",
        )

        self.app.open_book(book)

        self.assertEqual(self.app.reader.index, 0)
        self.assertEqual(self.app.shell.current_route.route_id, "books")
        self.assertEqual(self.app.shell.restore_focus_target(), "book-block-0")
        self.assertEqual(self.app._focus, "book-block-0")
        self.assertEqual(
            self.app.snapshot()["screen"]["focus_target"],
            "book-block-0",
        )

    def test_native_books_route_replaces_legacy_placeholder_before_event_publish(self):
        book = self.root / "native-book-focus.md"
        book.write_text(
            "# Розділ\n\nПерший абзац.\n",
            encoding="utf-8",
        )
        self.app.open_book(book)
        self.app.record_focus("book-reader")
        library = self.app.browser_command("shell", "screen.library")
        self.assertEqual(library["kind"], "route")

        route = self.app.adapter.activate_action(
            "screen.books",
            current_focus_id=self.app._focus,
        )
        self.assertEqual(route.kind, "route")
        self.assertEqual(route.payload["focus_target"], "book-reader")

        self.assertTrue(self.app.native_command(route))

        self.assertEqual(self.app.shell.restore_focus_target(), "book-block-0")
        self.assertEqual(self.app._focus, "book-block-0")
        route_events = [
            event for event in self.app.drain_events()
            if event.get("kind") == "route"
        ]
        self.assertEqual(len(route_events), 1)
        self.assertEqual(
            route_events[0]["payload"]["focus_target"],
            "book-block-0",
        )
        self.assertEqual(
            route_events[0]["payload"]["snapshot"]["screen"]["focus_target"],
            "book-block-0",
        )

    def test_browser_books_route_projects_repaired_focus_in_route_snapshot(self):
        book = self.root / "browser-book-focus.md"
        book.write_text(
            "# Розділ\n\nПерший абзац.\n",
            encoding="utf-8",
        )
        self.app.open_book(book)
        self.app.record_focus("book-reader")
        library = self.app.browser_command("shell", "screen.library")
        self.assertEqual(library["kind"], "route")

        books = self.app.browser_command("shell", "screen.books")

        self.assertEqual(books["kind"], "route")
        self.assertEqual(books["payload"]["focus_target"], "book-block-0")
        self.assertEqual(
            books["payload"]["snapshot"]["screen"]["focus_target"],
            "book-block-0",
        )
        self.assertEqual(self.app.shell.restore_focus_target(), "book-block-0")
        self.assertEqual(self.app._focus, "book-block-0")

    def test_book_recovery_render_preflight_preserves_published_owners_on_failure(self):
        book = self.root / "recovery-render-preflight.md"
        book.write_text(
            "# Chapter\n\nFirst paragraph.\n\nSecond paragraph.\n",
            encoding="utf-8",
        )
        self.app.open_book(book)
        self.app.record_focus("book-bookmark-name")

        before_reader = self.app.reader
        before_workflow = self.app.book_workflow
        before_delegate = self.app.book_delegate
        before_books = self.app.books
        before_training_workspace = self.app.training_workspace
        before_training = self.app.training
        before_route = self.app.shell.current_route.route_id
        before_focus = self.app.shell.restore_focus_target()
        snapshot = before_reader.snapshot()
        language = before_books.projection.language
        bookmark_name = before_books.projection.bookmark_name

        class FailingProjection:
            def restore_bookmark_name(self, _name):
                return None

            def snapshot(self):
                raise ValueError("simulated recovery render preflight failure")

        failing_bridge = SimpleNamespace(projection=FailingProjection())

        with patch(
            "acs.version2_application.build_version2_book_webview",
            return_value=failing_bridge,
        ):
            with self.assertRaisesRegex(ValueError, "render preflight"):
                self.app._restore_book_progress(
                    snapshot,
                    language=language,
                    bookmark_name=bookmark_name,
                )

        self.assertIs(self.app.reader, before_reader)
        self.assertIs(self.app.book_workflow, before_workflow)
        self.assertIs(self.app.book_delegate, before_delegate)
        self.assertIs(self.app.books, before_books)
        self.assertIs(self.app.training_workspace, before_training_workspace)
        self.assertIs(self.app.training, before_training)
        self.assertEqual(self.app.shell.current_route.route_id, before_route)
        self.assertEqual(self.app.shell.restore_focus_target(), before_focus)
        self.assertEqual(self.app._focus, before_focus)
        self.assertEqual(self.app.reader.snapshot(), snapshot)

    def test_book_durability_rebind_repairs_stale_book_block_focus(self):
        book = self.root / "durability-rebind-focus.md"
        book.write_text(
            "# Розділ\n\nПерший абзац.\n\nДругий абзац.\n",
            encoding="utf-8",
        )
        self.app.open_book(book)
        key = self.app.book_key
        document = self.app.reader.document
        self.app.record_focus("book-block-0")

        external = BookReader(document)
        external.go_to(2)
        self.app.progress_store.save(key, external)

        self.app._reload_book_progress_after_durability_ambiguity()

        self.assertEqual(self.app.reader.index, 2)
        self.assertEqual(self.app.shell.current_route.route_id, "books")
        self.assertEqual(self.app.shell.restore_focus_target(), "book-block-2")
        self.assertEqual(self.app._focus, "book-block-2")
        self.assertEqual(
            self.app.snapshot()["screen"]["focus_target"],
            "book-block-2",
        )

    def test_book_durability_rebind_preserves_stable_book_control_focus(self):
        book = self.root / "durability-rebind-control-focus.md"
        book.write_text(
            "# Розділ\n\nПерший абзац.\n\nДругий абзац.\n",
            encoding="utf-8",
        )
        self.app.open_book(book)
        key = self.app.book_key
        document = self.app.reader.document
        self.app.record_focus("book-bookmark-name")

        external = BookReader(document)
        external.go_to(2)
        self.app.progress_store.save(key, external)

        self.app._reload_book_progress_after_durability_ambiguity()

        self.assertEqual(self.app.reader.index, 2)
        self.assertEqual(
            self.app.shell.restore_focus_target(),
            "book-bookmark-name",
        )
        self.assertEqual(self.app._focus, "book-bookmark-name")

    def test_book_durability_unknown_with_unreadable_primary_fails_surface_closed(self):
        book = self.root / "durability-unknown-unreadable.md"
        book.write_text(
            "# Розділ\n\nПерший абзац.\n\nДругий абзац.\n",
            encoding="utf-8",
        )
        self.app.open_book_dialog = lambda: book
        self.assertEqual(
            self.app.browser_command("shell", "book.open")["kind"],
            "delegated",
        )
        store = self.app.progress_store
        key = self.app.book_key
        document = self.app.reader.document

        def fail_primary_sync(path):
            if Path(path) == store.path:
                raise OSError("post-replace durability probe failed")

        with (
            patch(
                "acs.book_progress_store._sync_published_path",
                side_effect=fail_primary_sync,
            ),
            patch.object(
                store,
                "restore_primary",
                side_effect=BookProgressStoreError(
                    "canonical progress cannot be re-read",
                    code=BookProgressStoreErrorCode.IO_FAILURE,
                ),
            ),
        ):
            result = self.app.browser_command("books", "book.next")

        self.assertEqual(result["kind"], "error")
        self.assertIsNone(self.app.reader)
        self.assertIsNone(self.app.book_key)
        self.assertIsNone(self.app.book_workflow)
        self.assertIsNone(self.app.book_delegate)
        self.assertIsNone(self.app.books)
        self.assertIsNone(self.app.training_workspace)
        self.assertIsNone(self.app.training)
        self.assertEqual(self.app.shell.current_route.route_id, "library")
        persisted = store.restore(key, document)
        self.assertEqual(persisted.index, 1)

    def test_book_durability_unknown_with_corrupt_primary_fails_surface_closed(self):
        book = self.root / "durability-unknown-corrupt-primary.md"
        book.write_text(
            "# Розділ\n\nПерший абзац.\n\nДругий абзац.\n",
            encoding="utf-8",
        )
        self.app.open_book_dialog = lambda: book
        self.assertEqual(
            self.app.browser_command("shell", "book.open")["kind"],
            "delegated",
        )
        store = self.app.progress_store
        key = self.app.book_key
        document = self.app.reader.document

        def corrupt_after_primary_sync(path):
            if Path(path) == store.path:
                store.path.write_bytes(b'{"schema_version":2,"generation":')

        with patch(
            "acs.book_progress_store._sync_published_path",
            side_effect=corrupt_after_primary_sync,
        ):
            result = self.app.browser_command("books", "book.next")

        self.assertEqual(result["kind"], "error")
        self.assertIsNone(self.app.reader)
        self.assertIsNone(self.app.book_key)
        self.assertIsNone(self.app.book_workflow)
        self.assertIsNone(self.app.book_delegate)
        self.assertIsNone(self.app.books)
        self.assertIsNone(self.app.training_workspace)
        self.assertIsNone(self.app.training)
        self.assertEqual(self.app.shell.current_route.route_id, "library")
        with self.assertRaises(BookProgressStoreError) as caught:
            store.restore_primary(key, document)
        self.assertEqual(
            caught.exception.code,
            BookProgressStoreErrorCode.CORRUPT_STORE,
        )

    def test_book_open_can_explicitly_recover_missing_primary_from_valid_backup(self):
        book, origin = self._open_book_game()
        store = self.app.progress_store
        key = self.app.book_key

        # Create a previous-valid generation at the exact current semantic cursor,
        # then simulate loss of only the primary file.
        store.save(key, self.app.reader)
        backup_before = store.backup_path.read_bytes()
        store.path.unlink()

        restarted = self._restarted_application(store)
        confirmations = []
        restarted.confirm_book_progress_recovery = lambda: confirmations.append(True) or True

        restarted.open_book(book)

        self.assertEqual(confirmations, [True])
        self.assertEqual(restarted.shell.current_route.route_id, "books")
        self.assertEqual(restarted.reader.location(), origin)
        self.assertEqual(store.restore(key, restarted.reader.document).location(), origin)
        self.assertTrue(store.path.exists())
        self.assertTrue(store.backup_path.exists())
        self.assertEqual(store.backup_path.read_bytes(), backup_before)

    def test_book_open_declined_missing_primary_recovery_is_atomic_and_non_destructive(self):
        book, origin = self._open_book_game()
        store = self.app.progress_store
        key = self.app.book_key
        store.save(key, self.app.reader)
        backup_before = store.backup_path.read_bytes()
        store.path.unlink()

        restarted = self._restarted_application(store)
        route_before = restarted.shell.current_route.route_id
        confirmations = []
        restarted.confirm_book_progress_recovery = lambda: confirmations.append(True) or False

        with self.assertRaises(BookProgressStoreError) as caught:
            restarted.open_book(book)

        self.assertEqual(caught.exception.code, BookProgressStoreErrorCode.CORRUPT_STORE)
        self.assertEqual(confirmations, [True])
        self.assertIsNone(restarted.reader)
        self.assertIsNone(restarted.books)
        self.assertIsNone(restarted.book_workflow)
        self.assertEqual(restarted.shell.current_route.route_id, route_before)
        self.assertFalse(store.path.exists())
        self.assertEqual(store.backup_path.read_bytes(), backup_before)
        restored = store.restore(key, self.app.reader.document)
        self.assertEqual(restored.location(), origin)

    def test_book_open_missing_primary_recovery_rejects_backup_swap_after_confirmation(self):
        book, _origin = self._open_book_game()
        store = self.app.progress_store
        key = self.app.book_key
        store.save(key, self.app.reader)
        store.path.unlink()

        swapped_backup = b'{"entries":{},"generation":7,"schema_version":2}'
        restarted = self._restarted_application(store)
        route_before = restarted.shell.current_route.route_id
        confirmations = []

        def confirm_and_swap_backup():
            confirmations.append(True)
            store.backup_path.write_bytes(swapped_backup)
            return True

        restarted.confirm_book_progress_recovery = confirm_and_swap_backup
        with self.assertRaises(BookProgressStoreError) as caught:
            restarted.open_book(book)

        self.assertEqual(caught.exception.code, BookProgressStoreErrorCode.STALE_WRITE)
        self.assertEqual(confirmations, [True])
        self.assertIsNone(restarted.reader)
        self.assertIsNone(restarted.books)
        self.assertIsNone(restarted.book_workflow)
        self.assertEqual(restarted.shell.current_route.route_id, route_before)
        self.assertFalse(store.path.exists())
        self.assertEqual(store.backup_path.read_bytes(), swapped_backup)

    def test_book_open_missing_primary_future_backup_never_offers_rollback(self):
        book, _origin = self._open_book_game()
        store = self.app.progress_store
        key = self.app.book_key
        store.save(key, self.app.reader)
        future_backup = b'{"entries":{},"generation":9,"schema_version":999}'
        store.backup_path.write_bytes(future_backup)
        store.path.unlink()

        restarted = self._restarted_application(store)
        route_before = restarted.shell.current_route.route_id
        confirmations = []
        restarted.confirm_book_progress_recovery = lambda: confirmations.append(True) or True

        with self.assertRaises(BookProgressStoreError) as caught:
            restarted.open_book(book)

        self.assertEqual(caught.exception.code, BookProgressStoreErrorCode.UNSUPPORTED_SCHEMA)
        self.assertEqual(confirmations, [])
        self.assertIsNone(restarted.reader)
        self.assertIsNone(restarted.books)
        self.assertEqual(restarted.shell.current_route.route_id, route_before)
        self.assertFalse(store.path.exists())
        self.assertEqual(store.backup_path.read_bytes(), future_backup)

    def test_book_open_missing_primary_unrelated_backup_never_offers_cross_book_recovery(self):
        book, _origin = self._open_book_game()
        store = self.app.progress_store
        store.path.unlink()
        unrelated_backup = b'{"entries":{},"generation":7,"schema_version":2}'
        store.backup_path.write_bytes(unrelated_backup)

        restarted = self._restarted_application(store)
        route_before = restarted.shell.current_route.route_id
        confirmations = []
        restarted.confirm_book_progress_recovery = lambda: confirmations.append(True) or True

        with self.assertRaises(BookProgressStoreError) as caught:
            restarted.open_book(book)

        self.assertEqual(caught.exception.code, BookProgressStoreErrorCode.CORRUPT_STORE)
        self.assertEqual(confirmations, [])
        self.assertIsNone(restarted.reader)
        self.assertIsNone(restarted.books)
        self.assertEqual(restarted.shell.current_route.route_id, route_before)
        self.assertFalse(store.path.exists())
        self.assertEqual(store.backup_path.read_bytes(), unrelated_backup)

    def test_training_continue_stale_write_rebinds_external_canonical_progress(self):
        after_e4 = Board()
        after_e4.push_text("e4")
        after_e4_e5 = Board()
        after_e4_e5.push_text("e4")
        after_e4_e5.push_text("e5")
        document = BookDocument(
            title="Training stale progress",
            language="uk",
            blocks=[
                Exercise(
                    fen=Board.START,
                    prompt="Find the first move.",
                    answer_text="e4",
                    block_id="training-one",
                ),
                Exercise(
                    fen=after_e4.fen(),
                    prompt="Find the reply.",
                    answer_text="e5",
                    block_id="training-two",
                ),
                Exercise(
                    fen=after_e4_e5.fen(),
                    prompt="Find the developing move.",
                    answer_text="Nf3",
                    block_id="training-three",
                ),
            ],
        )
        reader = BookReader(document)
        self.app.reader = reader
        self.app.book_key = "book:training-stale"
        self.app._restore_book_progress(
            reader.snapshot(),
            language=self.app.shell.language,
            bookmark_name="default",
        )
        store = self.app.progress_store
        store.save(self.app.book_key, self.app.reader)
        self.app.shell.open_route("books")
        self.assertTrue(self.app._start_training_from_current_book())
        self.app.shell.open_route("training")

        submitted = self.app.browser_command(
            "training",
            "training.submit",
            {"answer": "e4"},
        )
        self.assertNotEqual("error", submitted["kind"])
        self.assertTrue(self.app.training_workspace.session.completed)

        external_reader = BookReader(document)
        external_reader.go_to(2)
        external_store = BookProgressStore(store.path)
        injected = False

        def external_generation_wins(_book_key, _reader):
            nonlocal injected
            if not injected:
                external_store.save(self.app.book_key, external_reader)
                injected = True
            raise BookProgressStoreError(
                "external Training progress generation won",
                code=BookProgressStoreErrorCode.STALE_WRITE,
            )

        with patch.object(
            store,
            "save",
            side_effect=external_generation_wins,
        ):
            result = self.app.browser_command(
                "training",
                "training.continue",
            )

        self.assertTrue(injected)
        self.assertEqual("error", result["kind"])
        self.assertIsNotNone(self.app.reader)
        self.assertEqual(2, self.app.reader.index)
        self.assertEqual("training-three", self.app.reader.location().block_id)
        self.assertIsNotNone(self.app.training_workspace)
        self.assertIs(self.app.training_workspace.reader, self.app.reader)
        persisted = external_store.restore_primary(self.app.book_key, document)
        self.assertEqual(persisted.snapshot(), self.app.reader.snapshot())
        self.assertEqual("training", self.app.shell.current_route.route_id)

    def test_training_continue_durability_unknown_rebinds_to_canonical_successor(self):
        board = Board()
        board.push_text("e4")
        document = BookDocument(
            title="Training durability",
            language="uk",
            blocks=[
                Exercise(
                    fen=Board.START,
                    prompt="Знайдіть перший хід.",
                    answer_text="e4",
                    block_id="training-one",
                ),
                Exercise(
                    fen=board.fen(),
                    prompt="Знайдіть відповідь.",
                    answer_text="e5",
                    block_id="training-two",
                ),
            ],
        )
        reader = BookReader(document)
        self.app.reader = reader
        self.app.book_key = "book:training-durability"
        self.app._restore_book_progress(
            reader.snapshot(),
            language=self.app.shell.language,
            bookmark_name="default",
        )
        self.app.progress_store.save(self.app.book_key, self.app.reader)
        self.app.shell.open_route("books")
        self.assertTrue(self.app._start_training_from_current_book())
        self.app.shell.open_route("training")

        language = self.app.browser_command(
            "training",
            "training.language",
            {"language": "en"},
        )
        self.assertNotEqual("error", language["kind"])
        submitted = self.app.browser_command(
            "training",
            "training.submit",
            {"answer": "e4"},
        )
        self.assertNotEqual("error", submitted["kind"])
        self.assertTrue(self.app.training_workspace.session.completed)

        store = self.app.progress_store

        def fail_primary_sync(path):
            if Path(path) == store.path:
                raise OSError("post-replace durability probe failed")

        with patch(
            "acs.book_progress_store._sync_published_path",
            side_effect=fail_primary_sync,
        ):
            result = self.app.browser_command("training", "training.continue")

        self.assertEqual("error", result["kind"])
        self.assertIsNotNone(self.app.reader)
        self.assertIsNotNone(self.app.books)
        self.assertIsNotNone(self.app.training_workspace)
        self.assertIs(self.app.training_workspace.reader, self.app.reader)
        self.assertEqual(1, self.app.reader.index)
        self.assertEqual("training-two", self.app.reader.location().block_id)
        self.assertEqual("en", self.app.training_workspace.language.value)
        persisted = store.restore_primary(self.app.book_key, document)
        self.assertEqual(self.app.reader.snapshot(), persisted.snapshot())
        self.assertEqual("training", self.app.shell.current_route.route_id)

    def test_book_render_failure_rolls_back_reader_and_durable_progress(self):
        book = self.root / "render-failure.md"
        book.write_text("Коротко\n\n12345678901\n", encoding="utf-8")
        self.app.open_book_dialog = lambda: book
        self.assertEqual(
            self.app.browser_command("shell", "book.open")["kind"],
            "delegated",
        )
        before = self.app.reader.snapshot()
        key = self.app.book_key

        with patch(
            "acs.book_webview_projection._MAX_BOOK_BLOCK_VISIBLE_CHARS",
            10,
        ):
            result = self.app.browser_command("books", "book.next")

        self.assertEqual(result["kind"], "error")
        self.assertEqual(self.app.reader.snapshot(), before)
        self.assertEqual(self.app.reader.index, 0)
        restored = self.app.progress_store.restore(key, self.app.reader.document)
        self.assertEqual(restored.snapshot(), before)

    def test_external_book_open_projection_failure_is_atomic_and_does_not_persist_candidate(self):
        accepted = self.root / "accepted.md"
        accepted.write_text(
            "# Accepted\n\nFirst paragraph.\n\nSecond paragraph.\n",
            encoding="utf-8",
        )
        self.app.open_book(accepted)
        self.assertEqual(self.app.browser_command("books", "book.next")["kind"], "render")

        reader_before = self.app.reader
        books_before = self.app.books
        workflow_before = self.app.book_workflow
        delegate_before = self.app.book_delegate
        key_before = self.app.book_key
        snapshot_before = reader_before.snapshot()
        # Book Open is globally reachable from the native menu. A failed
        # candidate must not steal the user's current non-Books surface.
        self.app.shell.open_route("library")
        route_before = self.app.shell.current_route.route_id

        candidate = self.root / "candidate.md"
        candidate.write_text(
            "# Candidate\n\nThis source must never publish if its initial projection fails.\n",
            encoding="utf-8",
        )
        candidate_import = import_text_book(
            candidate.read_bytes(),
            source_name=report_safe_name(candidate),
            source_format=BookTextFormat.MARKDOWN,
        )
        self.assertNotEqual(candidate_import.book_key, key_before)
        self.assertFalse(self.app.progress_store.has(candidate_import.book_key))
        self.app.open_book_dialog = lambda: candidate

        with patch(
            "acs.version2_book_workspace.Version2BookWebViewProjection.snapshot",
            side_effect=ValueError("candidate projection rejected"),
        ):
            result = self.app.browser_command("shell", "book.open")

        self.assertEqual(result["kind"], "error")
        self.assertIs(self.app.reader, reader_before)
        self.assertIs(self.app.books, books_before)
        self.assertIs(self.app.book_workflow, workflow_before)
        self.assertIs(self.app.book_delegate, delegate_before)
        self.assertEqual(self.app.book_key, key_before)
        self.assertEqual(self.app.reader.snapshot(), snapshot_before)
        self.assertEqual(self.app.shell.current_route.route_id, route_before)
        self.assertFalse(self.app.progress_store.has(candidate_import.book_key))
        restored = self.app.progress_store.restore(key_before, reader_before.document)
        self.assertEqual(restored.snapshot(), snapshot_before)

    def test_external_book_open_announces_only_bounded_import_warning_count(self):
        book = self.root / "warning-book.md"
        book.write_text(
            "# Warning book\n\n> Quoted advice\n\nReadable text.\n",
            encoding="utf-8",
        )
        imported = import_text_book(
            book.read_bytes(),
            source_name=report_safe_name(book),
            source_format=BookTextFormat.MARKDOWN,
        )
        self.assertGreater(len(imported.warnings), 0)
        self.app.open_book_dialog = lambda: book

        command = self.app.adapter.activate_action(
            "book.open",
            current_focus_id="board-launcher",
        )
        self.assertEqual(command.kind, "delegated")
        self.app.native_command(command)
        events = self.app.drain_events()

        status = [
            event
            for event in events
            if event.get("kind") == "status"
            and isinstance(event.get("payload"), dict)
            and event["payload"].get("announcement")
        ]
        delegated = [
            event
            for event in events
            if event.get("kind") == "delegated"
            and isinstance(event.get("payload"), dict)
            and event["payload"].get("action_id") == "book.open"
        ]
        self.assertEqual(len(status), 1)
        self.assertEqual(len(delegated), 1)
        self.assertLess(events.index(status[0]), events.index(delegated[0]))
        announcement = status[0]["payload"]["announcement"]
        self.assertEqual(
            announcement,
            f"Книгу відкрито з попередженнями імпорту: {len(imported.warnings)}.",
        )
        serialized = json.dumps(status, ensure_ascii=False)
        self.assertNotIn(str(self.root), serialized)
        for warning in imported.warnings:
            self.assertNotIn(warning, serialized)

    def test_book_webview_game_handoff_uses_canonical_board_and_exact_return(self):
        book, origin = self._open_book_game()
        self.projected_positions.clear()

        actions = {
            action["command"]: action["enabled"]
            for action in self.app.books.projection.snapshot()["actions"]
        }
        self.assertFalse(actions["book.open_position"])
        self.assertTrue(actions["book.open_game"])
        self.assertFalse(actions["book.return_from_board"])

        opened = self.app.browser_command("books", "book.open_game")
        self.assertEqual(opened["kind"], "delegated")
        self.assertEqual(opened["payload"]["action"], "book.open_game")
        self.assertEqual(opened["payload"]["announcement"], "Партію відкрито на дошці.")
        self.assertTrue(self.app.book_workflow.active)
        self.assertEqual(self.app.shell.current_route.route_id, "board")
        self.assertEqual(self.projected_positions[-1], Board.START)

        returned = self.app.browser_command("books", "book.return_from_board")
        self.assertEqual(returned["kind"], "render")
        self.assertEqual(returned["payload"]["announcement"], "Повернуто до місця читання.")
        self.assertFalse(self.app.book_workflow.active)
        self.assertEqual(self.app.shell.current_route.route_id, "books")
        self.assertEqual(self.app.reader.location(), origin)

        self.app.open_book(book)
        self.assertEqual(self.app.reader.location(), origin)

    def test_book_native_open_board_exact_return_and_persistent_resume(self):
        book, origin = self._open_book_game()
        self.projected_positions.clear()
        opened = self.app.browser_command("books", "book.open_position")
        self.assertEqual(opened["kind"], "delegated")
        self.assertEqual(opened["payload"]["announcement"], "Позицію відкрито на дошці.")
        self.assertTrue(self.app.book_workflow.active)
        self.assertEqual(self.projected_positions[-1], Board.START)

        self.app.router.dispatch("book.board_next_move")
        expected = Board()
        expected.push_text("e4")
        self.assertEqual(self.projected_positions[-1], expected.fen())
        self.assertEqual(self.app.book_delegate.board_snapshot().fen(), expected.fen())

        returned = self.app.browser_command("books", "book.return_from_board")
        self.assertEqual(returned["kind"], "render")
        self.assertEqual(returned["payload"]["announcement"], "Повернуто до місця читання.")
        self.assertEqual(self.app.reader.location(), origin)
        self.app.open_book(book)
        self.assertEqual(self.app.reader.location(), origin)

    def test_browser_route_chain_never_reuses_previous_route_focus_token(self):
        _book, _origin = self._open_book_game()
        book_focus = f"book-block-{self.app.reader.index}"
        self.app.record_focus(book_focus)

        library = self.app.browser_command("shell", "screen.library")
        self.assertEqual(library["kind"], "route")
        self.assertEqual(
            library["payload"]["focus_target"],
            "library-search-player",
        )

        books = self.app.browser_command("shell", "screen.books")
        self.assertEqual(books["kind"], "route")
        self.assertEqual(books["payload"]["focus_target"], book_focus)

        library_again = self.app.browser_command("shell", "screen.library")
        self.assertEqual(library_again["kind"], "route")
        self.assertEqual(
            library_again["payload"]["focus_target"],
            "library-search-player",
            "stale Books focus polluted Library route-local focus history",
        )

    def test_native_route_event_rebinds_application_focus_before_next_command(self):
        _book, _origin = self._open_book_game()
        book_focus = f"book-block-{self.app.reader.index}"
        self.app.record_focus(book_focus)

        routed = self.app.adapter.activate_action(
            "screen.library",
            current_focus_id=book_focus,
        )
        self.assertEqual(routed.kind, "route")
        self.assertTrue(self.app.native_command(routed))
        self.assertEqual(self.app._focus, "library-search-player")

        books = self.app.browser_command("shell", "screen.books")
        self.assertEqual(books["kind"], "route")
        self.assertEqual(books["payload"]["focus_target"], book_focus)

        library_again = self.app.browser_command("shell", "screen.library")
        self.assertEqual(
            library_again["payload"]["focus_target"],
            "library-search-player",
        )

    def test_book_board_transition_focus_is_bound_before_webview_focusin(self):
        _book, origin = self._open_book_game()
        book_focus = f"book-block-{self.app.reader.index}"
        self.app.record_focus(book_focus)

        opened = self.app.browser_command("books", "book.open_position")
        self.assertEqual(opened["kind"], "delegated")
        self.assertTrue(self.app.book_workflow.active)
        self.assertEqual(self.app.shell.current_route.route_id, "board")
        self.assertEqual(self.app._focus, "board-launcher")
        self.assertEqual(
            self.app.shell.restore_focus_target(),
            "board-launcher",
        )

        # Exercise the race window before any browser focusin callback: an
        # immediate route away/back must retain Board-local focus rather than
        # recording the old Book block under the Board route.
        library = self.app.browser_command("shell", "screen.library")
        self.assertEqual(library["kind"], "route")
        board = self.app.browser_command("shell", "screen.board")
        self.assertEqual(board["kind"], "route")
        self.assertEqual(board["payload"]["focus_target"], "board-launcher")

        returned = self.app.browser_command(
            "books",
            "book.return_from_board",
        )
        self.assertEqual(returned["kind"], "render")
        self.assertFalse(self.app.book_workflow.active)
        self.assertEqual(self.app.shell.current_route.route_id, "books")
        self.assertEqual(self.app.reader.location(), origin)
        self.assertEqual(self.app._focus, book_focus)
        self.assertEqual(self.app.shell.restore_focus_target(), book_focus)

    def test_book_board_open_durability_unknown_keeps_canonical_reload_authority(self):
        _book, _origin = self._open_book_game()
        store = self.app.progress_store
        key = self.app.book_key
        self.projected_positions.clear()

        def fail_primary_sync(path):
            if Path(path) == store.path:
                raise OSError("post-replace durability probe failed")

        with (
            patch.object(
                self.app,
                "_restore_book_progress",
                wraps=self.app._restore_book_progress,
            ) as rollback,
            patch(
                "acs.book_progress_store._sync_published_path",
                side_effect=fail_primary_sync,
            ),
        ):
            result = self.app.browser_command("books", "book.open_position")

        self.assertEqual(result["kind"], "error")
        rollback.assert_called_once()
        self.assertIsNotNone(self.app.reader)
        self.assertIsNotNone(self.app.books)
        self.assertIsNotNone(self.app.book_workflow)
        self.assertFalse(self.app.book_workflow.active)
        self.assertEqual(self.app.shell.current_route.route_id, "books")
        self.assertEqual(self.projected_positions, [])
        persisted = store.restore(key, self.app.reader.document)
        self.assertEqual(persisted.snapshot(), self.app.reader.snapshot())

    def test_book_board_durability_unknown_rebind_returns_to_books_route(self):
        _book, _origin = self._open_book_game()
        expected_focus = f"book-block-{self.app.reader.index}"
        self.app.record_focus(expected_focus)
        opened = self.app.browser_command("books", "book.open_position")
        self.assertEqual(opened["kind"], "delegated")
        self.assertTrue(self.app.book_workflow.active)
        self.assertEqual(self.app.shell.current_route.route_id, "board")
        self.app.drain_events()
        store = self.app.progress_store
        key = self.app.book_key

        def fail_primary_sync(path):
            if Path(path) == store.path:
                raise OSError("post-replace durability probe failed")

        with patch(
            "acs.book_progress_store._sync_published_path",
            side_effect=fail_primary_sync,
        ):
            with self.assertRaises(BookProgressStoreError) as caught:
                self.app.save_book_progress()

        self.assertEqual(
            caught.exception.code,
            BookProgressStoreErrorCode.DURABILITY_UNKNOWN,
        )
        self.assertIsNotNone(self.app.reader)
        self.assertIsNotNone(self.app.books)
        self.assertIsNotNone(self.app.book_workflow)
        self.assertFalse(self.app.book_workflow.active)
        self.assertEqual(self.app.shell.current_route.route_id, "books")
        self.assertEqual(self.app.shell.restore_focus_target(), expected_focus)
        route_events = [
            event for event in self.app.drain_events()
            if event.get("kind") == "route"
        ]
        self.assertEqual(
            route_events,
            [{"kind": "route", "payload": {"route_id": "books"}}],
        )
        persisted = store.restore(key, self.app.reader.document)
        self.assertEqual(persisted.snapshot(), self.app.reader.snapshot())

    def test_book_board_durability_unknown_unreadable_primary_routes_library(self):
        _book, _origin = self._open_book_game()
        opened = self.app.browser_command("books", "book.open_position")
        self.assertEqual(opened["kind"], "delegated")
        self.assertTrue(self.app.book_workflow.active)
        self.assertEqual(self.app.shell.current_route.route_id, "board")
        self.app.drain_events()
        store = self.app.progress_store

        def fail_primary_sync(path):
            if Path(path) == store.path:
                raise OSError("post-replace durability probe failed")

        with (
            patch(
                "acs.book_progress_store._sync_published_path",
                side_effect=fail_primary_sync,
            ),
            patch.object(
                store,
                "restore_primary",
                side_effect=BookProgressStoreError(
                    "canonical progress cannot be re-read",
                    code=BookProgressStoreErrorCode.IO_FAILURE,
                ),
            ),
        ):
            with self.assertRaises(BookProgressStoreError) as caught:
                self.app.save_book_progress()

        self.assertEqual(
            caught.exception.code,
            BookProgressStoreErrorCode.DURABILITY_UNKNOWN,
        )
        self.assertIsNone(self.app.reader)
        self.assertIsNone(self.app.book_key)
        self.assertIsNone(self.app.book_workflow)
        self.assertIsNone(self.app.book_delegate)
        self.assertIsNone(self.app.books)
        self.assertIsNone(self.app.training_workspace)
        self.assertIsNone(self.app.training)
        self.assertEqual(self.app.shell.current_route.route_id, "library")
        route_events = [
            event for event in self.app.drain_events()
            if event.get("kind") == "route"
        ]
        self.assertEqual(
            route_events,
            [{"kind": "route", "payload": {"route_id": "library"}}],
        )

    def test_browser_book_return_durability_unknown_keeps_exact_safe_return(self):
        _book, origin = self._open_book_game()
        opened = self.app.browser_command("books", "book.open_position")
        self.assertEqual(opened["kind"], "delegated")
        self.assertTrue(self.app.book_workflow.active)
        self.app.drain_events()
        store = self.app.progress_store
        key = self.app.book_key

        def fail_primary_sync(path):
            if Path(path) == store.path:
                raise OSError("post-return durability probe failed")

        with patch(
            "acs.book_progress_store._sync_published_path",
            side_effect=fail_primary_sync,
        ):
            result = self.app.browser_command("books", "book.return_from_board")

        self.assertEqual(result["kind"], "error")
        self.assertFalse(self.app.book_workflow.active)
        self.assertEqual(self.app.shell.current_route.route_id, "books")
        self.assertEqual(self.app.reader.location(), origin)
        self.assertEqual(
            [
                event
                for event in self.app.drain_events()
                if event.get("kind") == "route"
            ],
            [{"kind": "route", "payload": {"route_id": "books"}}],
        )
        persisted = store.restore(key, self.app.reader.document)
        self.assertEqual(persisted.snapshot(), self.app.reader.snapshot())

    def test_native_book_return_durability_unknown_is_sanitized_after_safe_return(self):
        _book, origin = self._open_book_game()
        opened = self.app.adapter.activate_action(
            "book.open_position",
            current_focus_id="book-block-2",
        )
        self.assertEqual(opened.kind, "delegated")
        self.assertTrue(self.app.book_workflow.active)
        self.app.drain_events()
        store = self.app.progress_store

        def fail_primary_sync(path):
            if Path(path) == store.path:
                raise OSError("private post-return durability probe failed")

        with patch(
            "acs.book_progress_store._sync_published_path",
            side_effect=fail_primary_sync,
        ):
            result = self.app.adapter.activate_action(
                "book.return",
                current_focus_id="board-launcher",
            )

        self.assertEqual(result.kind, "error")
        self.assertNotIn("private", str(result.payload.get("message", "")).casefold())
        self.assertFalse(self.app.book_workflow.active)
        self.assertEqual(self.app.shell.current_route.route_id, "books")
        self.assertEqual(self.app.reader.location(), origin)
        self.assertEqual(
            [
                event
                for event in self.app.drain_events()
                if event.get("kind") == "route"
            ],
            [{"kind": "route", "payload": {"route_id": "books"}}],
        )

    def test_native_game_handoff_feedback_falls_back_if_semantic_probe_breaks(self):
        _book, _origin = self._open_book_game()
        self.app.drain_events()

        opened = self.app.adapter.activate_action(
            "book.open_position",
            current_focus_id=f"book-block-{self.app.reader.index}",
        )
        self.assertEqual(opened.kind, "delegated")
        self.assertTrue(self.app.book_workflow.active)

        with patch.object(
            self.app.reader,
            "location",
            side_effect=RuntimeError("synthetic read-only semantic probe failure"),
        ):
            self.assertTrue(self.app.native_command(opened))

        result = next(
            event
            for event in self.app.drain_events()
            if event["kind"] == "delegated"
            and event["payload"].get("action_id") == "book.open_position"
        )
        self.assertEqual(
            result["payload"]["announcement"],
            "Позицію відкрито на дошці.",
        )

    def test_book_keymap_native_ingress_queues_accessible_open_and_return_results(self):
        _book, origin = self._open_book_game()
        self.app.drain_events()

        opened = self.app.adapter.activate_action(
            "book.open_position",
            current_focus_id="book-block-2",
        )
        self.assertEqual(opened.kind, "delegated")
        self.app.native_command(opened)
        open_events = self.app.drain_events()
        open_result = next(
            event
            for event in open_events
            if event["kind"] == "delegated"
            and event["payload"].get("action_id") == "book.open_position"
        )
        self.assertEqual(
            open_result["payload"]["announcement"],
            "Партію відкрито на дошці.",
        )
        self.assertTrue(self.app.book_workflow.active)
        self.assertEqual(self.app.shell.current_route.route_id, "board")

        returned = self.app.adapter.activate_action(
            "book.return",
            current_focus_id="board-launcher",
        )
        self.assertEqual(returned.kind, "delegated")
        self.app.native_command(returned)
        return_events = self.app.drain_events()
        self.assertIn(
            {"kind": "route", "payload": {"route_id": "books"}},
            return_events,
        )
        return_result = next(
            event
            for event in return_events
            if event["kind"] == "delegated"
            and event["payload"].get("action_id") == "book.return"
        )
        self.assertEqual(
            return_result["payload"]["announcement"],
            "Повернуто до місця читання.",
        )
        self.assertFalse(self.app.book_workflow.active)
        self.assertEqual(self.app.shell.current_route.route_id, "books")
        self.assertEqual(self.app.reader.location(), origin)
        self.assertEqual(
            self.app.shell.restore_focus_target(),
            "book-block-2",
        )

    def _restarted_application(self, store):
        restarted = Version2Application(
            self.database,
            progress_store=store,
            engine_assistance=self.app.engine_assistance,
            board_dispatch=lambda *_: None,
            board_position_projector=lambda fen: {"ok": True},
            copy_text=self.copied.append,
        )
        return restarted

    def test_book_open_can_explicitly_recover_corrupt_progress_from_valid_backup(self):
        book, origin = self._open_book_game()
        store = self.app.progress_store
        key = self.app.book_key

        # Pin a previous-valid backup to the exact current semantic cursor, then
        # simulate a crash/torn primary. The restarted app has no in-memory Book
        # state that could hide the persistence failure.
        store.save(key, self.app.reader)
        backup_before = store.backup_path.read_bytes()
        store.path.write_bytes(b'{"schema_version":2,"generation":')
        corrupt_primary = store.path.read_bytes()

        restarted = self._restarted_application(store)
        confirmations = []
        restarted.confirm_book_progress_recovery = lambda: confirmations.append(True) or True

        restarted.open_book(book)

        self.assertEqual(confirmations, [True])
        self.assertEqual(restarted.shell.current_route.route_id, "books")
        self.assertEqual(restarted.reader.location(), origin)
        self.assertEqual(store.restore(key, restarted.reader.document).location(), origin)
        self.assertNotEqual(store.path.read_bytes(), corrupt_primary)
        self.assertTrue(store.backup_path.exists())
        self.assertNotEqual(backup_before, b"")

    def test_book_open_declined_progress_recovery_is_atomic_and_non_destructive(self):
        book, _origin = self._open_book_game()
        store = self.app.progress_store
        key = self.app.book_key
        store.save(key, self.app.reader)
        backup_before = store.backup_path.read_bytes()
        corrupt_primary = b'{"schema_version":2,"generation":'
        store.path.write_bytes(corrupt_primary)

        restarted = self._restarted_application(store)
        route_before = restarted.shell.current_route.route_id
        confirmations = []
        restarted.confirm_book_progress_recovery = lambda: confirmations.append(True) or False

        with self.assertRaises(BookProgressStoreError) as caught:
            restarted.open_book(book)

        self.assertEqual(caught.exception.code, BookProgressStoreErrorCode.CORRUPT_STORE)
        self.assertEqual(confirmations, [True])
        self.assertIsNone(restarted.reader)
        self.assertIsNone(restarted.books)
        self.assertIsNone(restarted.book_workflow)
        self.assertEqual(restarted.shell.current_route.route_id, route_before)
        self.assertEqual(store.path.read_bytes(), corrupt_primary)
        self.assertEqual(store.backup_path.read_bytes(), backup_before)

    def test_book_open_future_progress_schema_never_offers_backup_rollback(self):
        book, _origin = self._open_book_game()
        store = self.app.progress_store
        key = self.app.book_key
        store.save(key, self.app.reader)
        backup_before = store.backup_path.read_bytes()
        future_primary = b'{"schema_version":999,"entries":{}}'
        store.path.write_bytes(future_primary)

        restarted = self._restarted_application(store)
        confirmations = []
        restarted.confirm_book_progress_recovery = lambda: confirmations.append(True) or True

        with self.assertRaises(BookProgressStoreError) as caught:
            restarted.open_book(book)

        self.assertEqual(caught.exception.code, BookProgressStoreErrorCode.UNSUPPORTED_SCHEMA)
        self.assertEqual(confirmations, [])
        self.assertIsNone(restarted.reader)
        self.assertIsNone(restarted.books)
        self.assertEqual(store.path.read_bytes(), future_primary)
        self.assertEqual(store.backup_path.read_bytes(), backup_before)

    def test_book_open_recovery_confirmation_failure_preserves_all_progress_bytes(self):
        book, _origin = self._open_book_game()
        store = self.app.progress_store
        key = self.app.book_key
        store.save(key, self.app.reader)
        backup_before = store.backup_path.read_bytes()
        corrupt_primary = b'{"schema_version":2,"generation":'
        store.path.write_bytes(corrupt_primary)

        restarted = self._restarted_application(store)

        def broken_confirmation():
            raise RuntimeError("private dialog failure")

        restarted.confirm_book_progress_recovery = broken_confirmation
        with self.assertRaises(BookProgressStoreError) as caught:
            restarted.open_book(book)

        self.assertEqual(caught.exception.code, BookProgressStoreErrorCode.CORRUPT_STORE)
        self.assertIsNone(restarted.reader)
        self.assertIsNone(restarted.books)
        self.assertEqual(store.path.read_bytes(), corrupt_primary)
        self.assertEqual(store.backup_path.read_bytes(), backup_before)
        self.assertNotIn("private dialog failure", str(caught.exception))


    def test_runtime_book_save_does_not_offer_recovery_without_backup(self):
        self._open_book_game()
        store = self.app.progress_store
        store.backup_path.unlink(missing_ok=True)
        corrupt_primary = b'{"schema_version":2,"generation":'
        store.path.write_bytes(corrupt_primary)
        confirmations = []
        self.app.confirm_book_progress_recovery = (
            lambda: confirmations.append(True) or True
        )

        with self.assertRaises(BookProgressStoreError) as caught:
            self.app.save_book_progress()

        self.assertEqual(caught.exception.code, BookProgressStoreErrorCode.CORRUPT_STORE)
        self.assertEqual(confirmations, [])
        self.assertEqual(store.path.read_bytes(), corrupt_primary)
        self.assertFalse(store.backup_path.exists())

    def test_runtime_book_save_does_not_offer_recovery_from_corrupt_backup(self):
        self._open_book_game()
        store = self.app.progress_store
        corrupt_primary = b'{"schema_version":2,"generation":'
        corrupt_backup = b'{"schema_version":2,"entries":'
        store.path.write_bytes(corrupt_primary)
        store.backup_path.write_bytes(corrupt_backup)
        confirmations = []
        self.app.confirm_book_progress_recovery = (
            lambda: confirmations.append(True) or True
        )

        with self.assertRaises(BookProgressStoreError) as caught:
            self.app.save_book_progress()

        self.assertEqual(caught.exception.code, BookProgressStoreErrorCode.CORRUPT_STORE)
        self.assertEqual(confirmations, [])
        self.assertEqual(store.path.read_bytes(), corrupt_primary)
        self.assertEqual(store.backup_path.read_bytes(), corrupt_backup)



    def test_runtime_book_save_does_not_offer_recovery_from_unrelated_valid_backup(self):
        self._open_book_game()
        store = self.app.progress_store
        corrupt_primary = b'{"schema_version":2,"generation":'
        unrelated_backup = b'{"entries":{},"generation":1,"schema_version":2}'
        store.path.write_bytes(corrupt_primary)
        store.backup_path.write_bytes(unrelated_backup)
        confirmations = []
        self.app.confirm_book_progress_recovery = (
            lambda: confirmations.append(True) or True
        )

        with self.assertRaises(BookProgressStoreError) as caught:
            self.app.save_book_progress()

        self.assertEqual(caught.exception.code, BookProgressStoreErrorCode.CORRUPT_STORE)
        self.assertEqual(confirmations, [])
        self.assertEqual(store.path.read_bytes(), corrupt_primary)
        self.assertEqual(store.backup_path.read_bytes(), unrelated_backup)



    def test_runtime_book_save_recovers_only_after_usable_backup_confirmation(self):
        self._open_book_game()
        store = self.app.progress_store
        key = self.app.book_key
        # A second successful write pins a valid previous generation as backup.
        store.save(key, self.app.reader)
        self.assertTrue(store.backup_path.exists())
        corrupt_primary = b'{"schema_version":2,"generation":'
        store.path.write_bytes(corrupt_primary)
        confirmations = []
        self.app.confirm_book_progress_recovery = (
            lambda: confirmations.append(True) or True
        )
        expected = self.app.reader.snapshot()

        self.app.save_book_progress()

        self.assertEqual(confirmations, [True])
        self.assertNotEqual(store.path.read_bytes(), corrupt_primary)
        restored = store.restore(key, self.app.reader.document)
        self.assertEqual(restored.snapshot(), expected)


    def test_book_recovery_validation_rebinds_without_prompt_if_primary_wins(self):
        self._open_book_game()
        store = self.app.progress_store
        key = self.app.book_key
        document = self.app.reader.document
        store.save(key, self.app.reader)

        external_path = self.root / "validation-race-winner.json"
        external_store = BookProgressStore(external_path)
        external_reader = BookReader(document)
        external_reader.go_to(2)
        external_store.save(key, external_reader)
        external_primary = external_path.read_bytes()

        store.path.write_bytes(b'{"schema_version":2,"generation":')
        confirmations = []
        self.app.confirm_book_progress_recovery = (
            lambda: confirmations.append(True) or True
        )
        real_read_state = store._read_state_unlocked
        injected = False

        def read_backup_and_publish_winner(path, *, missing_ok):
            nonlocal injected
            result = real_read_state(path, missing_ok=missing_ok)
            if Path(path) == store.backup_path and not injected:
                store.path.write_bytes(external_primary)
                injected = True
            return result

        with patch.object(
            store,
            "_read_state_unlocked",
            side_effect=read_backup_and_publish_winner,
        ):
            with self.assertRaises(BookProgressStoreError) as caught:
                self.app.save_book_progress()

        self.assertTrue(injected)
        self.assertEqual(caught.exception.code, BookProgressStoreErrorCode.STALE_WRITE)
        self.assertEqual(confirmations, [])
        self.assertEqual(store.path.read_bytes(), external_primary)
        self.assertIsNotNone(self.app.reader)
        self.assertEqual(self.app.reader.snapshot(), external_reader.snapshot())
        self.assertEqual(self.app.shell.current_route.route_id, "books")

    def test_book_recovery_confirmation_rebinds_if_valid_primary_wins(self):
        self._open_book_game()
        store = self.app.progress_store
        key = self.app.book_key
        document = self.app.reader.document
        store.save(key, self.app.reader)
        backup_bytes = store.backup_path.read_bytes()

        external_path = self.root / "external-valid-progress.json"
        external_store = BookProgressStore(external_path)
        external_reader = BookReader(document)
        external_reader.go_to(2)
        external_store.save(key, external_reader)
        external_primary = external_path.read_bytes()

        corrupt_primary = b'{"schema_version":2,"generation":'
        store.path.write_bytes(corrupt_primary)
        confirmations = []

        def confirm_and_publish_external_primary():
            confirmations.append(True)
            store.path.write_bytes(external_primary)
            return True

        self.app.confirm_book_progress_recovery = confirm_and_publish_external_primary
        with self.assertRaises(BookProgressStoreError) as caught:
            self.app.save_book_progress()

        self.assertEqual(caught.exception.code, BookProgressStoreErrorCode.STALE_WRITE)
        self.assertEqual(confirmations, [True])
        self.assertEqual(store.path.read_bytes(), external_primary)
        self.assertEqual(store.backup_path.read_bytes(), backup_bytes)
        self.assertIsNotNone(self.app.reader)
        self.assertEqual(self.app.reader.snapshot(), external_reader.snapshot())
        self.assertEqual(self.app.shell.current_route.route_id, "books")

    def test_book_recovery_confirmation_fails_closed_if_corrupt_primary_changes(self):
        self._open_book_game()
        store = self.app.progress_store
        key = self.app.book_key
        store.save(key, self.app.reader)
        backup_bytes = store.backup_path.read_bytes()

        corrupt_primary = b'{"schema_version":2,"generation":'
        changed_corrupt_primary = b'{"schema_version":2,"entries":'
        store.path.write_bytes(corrupt_primary)
        confirmations = []

        def confirm_and_replace_corrupt_primary():
            confirmations.append(True)
            store.path.write_bytes(changed_corrupt_primary)
            return True

        self.app.confirm_book_progress_recovery = confirm_and_replace_corrupt_primary
        with self.assertRaises(BookProgressStoreError) as caught:
            self.app.save_book_progress()

        self.assertEqual(caught.exception.code, BookProgressStoreErrorCode.STALE_WRITE)
        self.assertEqual(confirmations, [True])
        self.assertEqual(store.path.read_bytes(), changed_corrupt_primary)
        self.assertEqual(store.backup_path.read_bytes(), backup_bytes)
        self.assertIsNone(self.app.reader)
        self.assertIsNone(self.app.books)
        self.assertEqual(self.app.shell.current_route.route_id, "library")

    def test_book_recovery_confirmation_rejects_corrupt_backup_drift_as_stale(self):
        self._open_book_game()
        store = self.app.progress_store
        key = self.app.book_key
        store.save(key, self.app.reader)
        corrupt_primary = b'{"schema_version":2,"generation":'
        changed_backup = b'{"schema_version":2,"entries":'
        store.path.write_bytes(corrupt_primary)
        confirmations = []

        def confirm_and_corrupt_backup():
            confirmations.append(True)
            store.backup_path.write_bytes(changed_backup)
            return True

        self.app.confirm_book_progress_recovery = confirm_and_corrupt_backup
        with self.assertRaises(BookProgressStoreError) as caught:
            self.app.save_book_progress()

        self.assertEqual(caught.exception.code, BookProgressStoreErrorCode.STALE_WRITE)
        self.assertEqual(confirmations, [True])
        self.assertEqual(store.path.read_bytes(), corrupt_primary)
        self.assertEqual(store.backup_path.read_bytes(), changed_backup)
        self.assertIsNone(self.app.reader)
        self.assertIsNone(self.app.books)
        self.assertEqual(self.app.shell.current_route.route_id, "library")

    def test_book_recovery_confirmation_rejects_disappeared_backup_as_stale(self):
        self._open_book_game()
        store = self.app.progress_store
        key = self.app.book_key
        store.save(key, self.app.reader)
        corrupt_primary = b'{"schema_version":2,"generation":'
        store.path.write_bytes(corrupt_primary)
        confirmations = []

        def confirm_and_delete_backup():
            confirmations.append(True)
            store.backup_path.unlink()
            return True

        self.app.confirm_book_progress_recovery = confirm_and_delete_backup
        with self.assertRaises(BookProgressStoreError) as caught:
            self.app.save_book_progress()

        self.assertEqual(caught.exception.code, BookProgressStoreErrorCode.STALE_WRITE)
        self.assertEqual(confirmations, [True])
        self.assertEqual(store.path.read_bytes(), corrupt_primary)
        self.assertFalse(store.backup_path.exists())
        self.assertIsNone(self.app.reader)
        self.assertIsNone(self.app.books)
        self.assertEqual(self.app.shell.current_route.route_id, "library")

    def test_book_recovery_publishes_only_the_semantically_validated_backup_revision(self):
        self._open_book_game()
        store = self.app.progress_store
        key = self.app.book_key
        store.save(key, self.app.reader)
        self.assertTrue(store.backup_path.exists())

        corrupt_primary = b'{"schema_version":2,"generation":'
        store.path.write_bytes(corrupt_primary)
        swapped_backup = b'{"entries":{},"generation":1,"schema_version":2}'
        confirmations = []

        def confirm_and_swap_backup():
            confirmations.append(True)
            store.backup_path.write_bytes(swapped_backup)
            return True

        self.app.confirm_book_progress_recovery = confirm_and_swap_backup
        with self.assertRaises(BookProgressStoreError) as caught:
            self.app.save_book_progress()

        self.assertEqual(caught.exception.code, BookProgressStoreErrorCode.STALE_WRITE)
        self.assertEqual(confirmations, [True])
        self.assertEqual(store.path.read_bytes(), corrupt_primary)
        self.assertEqual(store.backup_path.read_bytes(), swapped_backup)

    def test_book_store_expected_backup_revision_is_exact_and_backward_compatible(self):
        self._open_book_game()
        store = self.app.progress_store
        key = self.app.book_key
        store.save(key, self.app.reader)
        revision = store.validated_backup_revision(key, self.app.reader.document)
        self.assertEqual(len(revision), 64)
        self.assertTrue(all(character in "0123456789abcdef" for character in revision))

        corrupt_primary = b'{"schema_version":2,"generation":'
        store.path.write_bytes(corrupt_primary)
        self.assertTrue(store.recover_from_backup(expected_backup_revision=revision))
        self.assertNotEqual(store.path.read_bytes(), corrupt_primary)

        store.path.write_bytes(corrupt_primary)
        with self.assertRaises(BookProgressStoreError) as caught:
            store.recover_from_backup(expected_backup_revision="not-a-revision")
        self.assertEqual(caught.exception.code, BookProgressStoreErrorCode.INVALID_ARGUMENT)
        self.assertEqual(store.path.read_bytes(), corrupt_primary)

    def test_book_board_open_and_return_publish_exact_origin_once_each(self):
        _book, origin = self._open_book_game()
        before = self.app.reader.snapshot()
        real_save = self.app.progress_store.save

        with patch.object(
            self.app.progress_store,
            "save",
            wraps=real_save,
        ) as save:
            opened = self.app.browser_command("books", "book.open_position")

            self.assertEqual("delegated", opened["kind"])
            save.assert_called_once_with(self.app.book_key, self.app.reader)
            self.assertTrue(self.app.book_workflow.active)
            self.assertEqual("board", self.app.shell.current_route.route_id)
            self.assertEqual(origin, self.app.reader.location())
            self.assertEqual(before, self.app.reader.snapshot())

            save.reset_mock()
            returned = self.app.browser_command("books", "book.return_from_board")

            self.assertEqual("render", returned["kind"])
            save.assert_called_once_with(self.app.book_key, self.app.reader)
            self.assertFalse(self.app.book_workflow.active)
            self.assertEqual("books", self.app.shell.current_route.route_id)
            self.assertEqual(origin, self.app.reader.location())
            self.assertEqual(before, self.app.reader.snapshot())

    def test_book_game_open_fails_closed_when_release_board_rejects_position(self):
        _book, origin = self._open_book_game()
        before = self.app.reader.snapshot()
        self.app._board_position_projector = lambda _fen: {"ok": False}

        # The helper leaves the reader on a Game block, so exercise the real
        # Game -> Board handoff. Calling book.open_position here only proves the
        # semantic action guard and never reaches the release board projector.
        result = self.app.browser_command("books", "book.open_game")

        self.assertEqual(result["kind"], "error")
        self.assertNotIn("announcement", result["payload"])
        self.assertFalse(self.app.book_workflow.active)
        self.assertEqual(self.app.reader.location(), origin)
        self.assertEqual(self.app.reader.snapshot(), before)
        self.assertEqual(self.app.shell.current_route.route_id, "books")

    def test_book_navigation_projection_failure_restores_canonical_cursor(self):
        _book, _origin = self._open_book_game()
        self.assertEqual(self.app.browser_command("books", "book.open_position")["kind"], "delegated")
        before = self.app.book_delegate.view()
        projected = []

        def reject_changed_position(fen):
            projected.append(fen)
            return {"ok": fen == before.current_fen}

        self.app._board_position_projector = reject_changed_position
        result = self.app.browser_command("review", "book.board_next_move")

        self.assertEqual(result["kind"], "error")
        after = self.app.book_delegate.view()
        self.assertEqual(after.cursor, before.cursor)
        self.assertEqual(after.current_fen, before.current_fen)
        self.assertTrue(self.app.book_workflow.active)
        self.assertEqual(self.app.shell.current_route.route_id, "board")
        self.assertEqual(projected[-1], before.current_fen)

    def test_book_projection_recovery_return_is_storage_independent(self):
        _book, origin = self._open_book_game()
        self.assertEqual(
            self.app.browser_command("books", "book.open_position")["kind"],
            "delegated",
        )
        self.assertTrue(self.app.book_workflow.active)
        self.assertEqual("board", self.app.shell.current_route.route_id)
        self.app.drain_events()

        self.app._board_position_projector = lambda _fen: {"ok": False}
        with patch.object(
            self.app.progress_store,
            "save",
            side_effect=AssertionError(
                "read-only Board recovery return must not write Book progress"
            ),
        ) as save:
            result = self.app.browser_command("review", "book.board_next_move")

        self.assertEqual("error", result["kind"])
        save.assert_not_called()
        self.assertFalse(self.app.book_workflow.active)
        self.assertEqual("books", self.app.shell.current_route.route_id)
        self.assertEqual(origin, self.app.reader.location())
        self.assertEqual(
            [
                event
                for event in self.app.drain_events()
                if event.get("kind") == "route"
            ],
            [{"kind": "route", "payload": {"route_id": "books"}}],
        )

    def test_browser_path_payload_rejected_before_native_picker(self):
        self.dialogs.open_pgn = lambda: self.fail("must not open dialog")
        result = self.app.browser_command("shell", "pgn.open", {"path": str(self.source)})
        self.assertEqual(result["kind"], "error")
        self.assertIsNone(self.app.session)


    def test_pgn_open_on_board_is_atomic_when_modal_blocks_route_change(self):
        opened = self.app.browser_command("shell", "pgn.open")
        self.assertEqual("delegated", opened["kind"])
        self.assertEqual("pgn", self.app.shell.current_route.route_id)
        self.assertFalse(self.app.pgn_board_active)
        projected_before = tuple(self.projected_positions)

        dialog = self.app.adapter.open_dialog(
            "pgn-open-modal",
            opener_focus_id="pgn-game-list",
            initial_focus_id="pgn-open-modal-confirm",
        )
        self.assertEqual("dialog-open", dialog.kind)

        result = self.app.browser_command("review", "pgn.open_on_board")

        self.assertEqual("error", result["kind"])
        self.assertEqual("pgn", self.app.shell.current_route.route_id)
        self.assertFalse(self.app.pgn_board_active)
        self.assertEqual(projected_before, tuple(self.projected_positions))
        self.assertEqual("pgn-open-modal", self.app.shell.active_dialog_id)

    def test_pgn_return_is_atomic_when_modal_blocks_route_change(self):
        opened = self.app.browser_command("shell", "pgn.open")
        self.assertEqual("delegated", opened["kind"])
        self.assertEqual("pgn", self.app.shell.current_route.route_id)

        opened_board = self.app.browser_command("review", "pgn.open_on_board")
        self.assertEqual("review", opened_board["kind"])
        self.assertEqual("board", self.app.shell.current_route.route_id)
        self.assertTrue(self.app.pgn_board_active)
        projected_before = tuple(self.projected_positions)

        dialog = self.app.adapter.open_dialog(
            "pgn-return-modal",
            opener_focus_id="board-launcher",
            initial_focus_id="pgn-return-modal-confirm",
        )
        self.assertEqual("dialog-open", dialog.kind)

        result = self.app.browser_command("review", "pgn.return")

        self.assertEqual("error", result["kind"])
        self.assertEqual("board", self.app.shell.current_route.route_id)
        self.assertTrue(self.app.pgn_board_active)
        self.assertEqual(projected_before, tuple(self.projected_positions))
        self.assertEqual("pgn-return-modal", self.app.shell.active_dialog_id)

    def test_library_open_game_cannot_replace_pgn_session_behind_modal_dialog(self):
        self.app.browser_command("library", "library.import")
        self.assertTrue(self.files.wait_for_import(5))
        self.app.import_ui_ready(self.mailbox)
        searched = self.app.browser_command("library", "library.search", {"player": "петренко"})
        self.assertEqual("render", searched["kind"])

        session_before = self.app.session
        pgn_before = self.app.pgn
        route_before = self.app.shell.current_route.route_id
        opened_dialog = self.app.adapter.open_dialog(
            "test-library-modal",
            opener_focus_id="library-results",
            initial_focus_id="test-library-modal-confirm",
        )
        self.assertEqual("dialog-open", opened_dialog.kind)

        result = self.app.browser_command("library", "library.open_game")

        self.assertEqual("error", result["kind"])
        self.assertIs(session_before, self.app.session)
        self.assertIs(pgn_before, self.app.pgn)
        self.assertEqual(route_before, self.app.shell.current_route.route_id)
        self.assertEqual("test-library-modal", self.app.shell.active_dialog_id)


if __name__ == "__main__": unittest.main()
