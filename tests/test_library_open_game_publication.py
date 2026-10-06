from __future__ import annotations

from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from acs.acsdb import AcsDatabase
from acs.analysis_service import AnalysisService
from acs.book_progress_store import BookProgressStore
from acs.engine_assisted_workflows import EngineAssistedWorkflowService
from acs.full_product_actions import build_full_product_action_registry
from acs.full_product_ui_shell import UILanguage
from acs.keybindings import BindingContext
from acs.library_webview_projection import LibraryWebViewEvent
from acs.pgn_document import PgnDocumentSession
from acs.search_service import GameSearchQuery
from acs.version2_application import Version2Application
from acs.version2_windows_library_export import (
    LibraryExportHostEvent,
    LibraryExportHostEventKind,
)


PGN_TEMPLATE = """[Event "{event}"]
[Site "?"]
[Date "2026.10.05"]
[Round "1"]
[White "White"]
[Black "Black"]
[Result "*"]

1. e4 e5 *
"""


class LibraryOpenGamePublicationTests(unittest.TestCase):
    def test_library_export_failures_are_actionable_path_free_and_library_localized(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            database = AcsDatabase(root / "library.acsdb")
            analysis = AnalysisService(lambda: None)
            try:
                app = Version2Application(
                    database,
                    progress_store=BookProgressStore(root / "book-progress.json"),
                    engine_assistance=EngineAssistedWorkflowService(analysis),
                    board_dispatch=lambda *_args: None,
                    copy_text=lambda _text: None,
                )
                cases = (
                    ("invalid_export_request", "вибір ігор або фільтр"),
                    ("library_export_busy", "ще завершується"),
                    ("library_export_unavailable", "зараз недоступний"),
                    ("file_dialog_failed", "вікно вибору файла"),
                    ("library_export_worker_failed", "фоновий експорт"),
                    ("library_export_failed", "завершити експорт"),
                    ("no_library_export_running", "вже завершився"),
                )
                for error_code, fragment in cases:
                    with self.subTest(error_code=error_code):
                        event = LibraryExportHostEvent(
                            LibraryExportHostEventKind.FAILED,
                            focus_target="library-search-player",
                            error_code=error_code,
                        )
                        app._file_event(event)
                        emitted = app.drain_events()
                        self.assertEqual(emitted[-1]["kind"], "error")
                        message = emitted[-1]["payload"]["message"]
                        self.assertIn(fragment, message)
                        self.assertNotEqual(message, "Не вдалося виконати дію.")
                        self.assertNotIn(str(root), message)

                # Library owns this surface's locale. Keep the shell in Ukrainian
                # while switching only the Library projection to English.
                self.assertIs(app.shell.language, UILanguage.UA)
                app.library.projection.set_language(UILanguage.EN)
                event = LibraryExportHostEvent(
                    LibraryExportHostEventKind.FAILED,
                    focus_target="library-search-player",
                    error_code="library_export_failed",
                )
                app._file_event(event)
                english = app.drain_events()[-1]["payload"]["message"]
                self.assertIn("Library export could not be completed", english)
                self.assertNotEqual(english, "The action could not be completed.")
                self.assertIs(app.shell.language, UILanguage.UA)
            finally:
                analysis.close()
                database.close()

    def test_library_file_error_message_rejects_active_event_subclass_before_field_access(self) -> None:
        class ActiveLibraryExportHostEvent(LibraryExportHostEvent):
            armed = False

            def __getattribute__(self, name):
                if name in {"action_id", "error_code"} and object.__getattribute__(
                    self, "armed"
                ):
                    raise AssertionError("active event field accessor executed")
                return super().__getattribute__(name)

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            database = AcsDatabase(root / "library.acsdb")
            analysis = AnalysisService(lambda: None)
            try:
                app = Version2Application(
                    database,
                    progress_store=BookProgressStore(root / "book-progress.json"),
                    engine_assistance=EngineAssistedWorkflowService(analysis),
                    board_dispatch=lambda *_args: None,
                    copy_text=lambda _text: None,
                )
                event = ActiveLibraryExportHostEvent(
                    LibraryExportHostEventKind.FAILED,
                    focus_target="library-search-player",
                    error_code="library_export_failed",
                )
                object.__setattr__(event, "armed", True)

                self.assertEqual(
                    "Не вдалося виконати дію.",
                    app._native_file_error_message(event),
                )
                app._file_event(event)
                self.assertEqual(
                    [
                        {
                            "kind": "error",
                            "payload": {"message": "Не вдалося виконати дію."},
                        }
                    ],
                    app.drain_events(),
                )
            finally:
                analysis.close()
                database.close()

    def test_library_home_end_are_central_remappable_actions(self) -> None:
        registry = build_full_product_action_registry()

        self.assertEqual(
            registry.resolve_binding(BindingContext.LIBRARY_RESULTS, "Home").action_id,
            "library.first_result",
        )
        self.assertEqual(
            registry.resolve_binding(BindingContext.LIBRARY_RESULTS, "End").action_id,
            "library.last_result",
        )

        registry.set_binding("library.first_result", "Ctrl+Home")
        registry.set_binding("library.last_result", "Ctrl+End")
        self.assertIsNone(
            registry.resolve_binding(BindingContext.LIBRARY_RESULTS, "Home")
        )
        self.assertIsNone(
            registry.resolve_binding(BindingContext.LIBRARY_RESULTS, "End")
        )
        self.assertEqual(
            registry.resolve_binding(BindingContext.LIBRARY_RESULTS, "Ctrl+Home").action_id,
            "library.first_result",
        )
        self.assertEqual(
            registry.resolve_binding(BindingContext.LIBRARY_RESULTS, "Ctrl+End").action_id,
            "library.last_result",
        )

    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.database = AcsDatabase(self.root / "library.acsdb")
        self.addCleanup(self.database.close)
        self.analysis = AnalysisService(lambda: None)
        self.addCleanup(self.analysis.close)
        self.app = Version2Application(
            self.database,
            progress_store=BookProgressStore(self.root / "book-progress.json"),
            engine_assistance=EngineAssistedWorkflowService(self.analysis),
            board_dispatch=lambda *_args: None,
            copy_text=lambda _text: None,
        )

    def _session(self, filename: str, event: str) -> PgnDocumentSession:
        source = self.root / filename
        source.write_text(PGN_TEMPLATE.format(event=event), encoding="utf-8")
        return PgnDocumentSession.open(source)

    def _prior_library_state(self) -> tuple[PgnDocumentSession, object, str]:
        session = self._session("prior.pgn", "Prior")
        self.app.set_document(session)
        prior_pgn = self.app.pgn
        self.app._focus = self.app.shell.open_route("library")
        prior_focus = self.app._focus
        self.app._pgn_browser_lease_required = True
        return session, prior_pgn, prior_focus

    def _staged_dispatch(self, replacement: PgnDocumentSession, calls: list[tuple[object, object]]):
        def dispatch(command, payload):
            calls.append((command, payload))
            self.app.set_document(replacement)
            return LibraryWebViewEvent(
                "delegated",
                {"action": "library.open_game"},
            )

        return dispatch

    def test_exact_request_replay_and_rollback_restore_prior_pgn_owner(self) -> None:
        prior_session, prior_pgn, prior_focus = self._prior_library_state()
        replacement = self._session("replacement.pgn", "Replacement")
        calls: list[tuple[object, object]] = []
        request = {"publication_protocol": "ack-v1", "request_id": 71}

        with patch.object(
            self.app.library,
            "dispatch",
            side_effect=self._staged_dispatch(replacement, calls),
        ):
            started = self.app.browser_command("library", "library.open_game", request)
            replayed = self.app.browser_command("library", "library.open_game", request)

        self.assertEqual(started, replayed)
        self.assertEqual(calls, [("library.open_game", {})])
        self.assertEqual(started["kind"], "delegated")
        token = started["payload"]["publication_token"]
        self.assertGreater(token, 0)
        self.assertIs(self.app.session, replacement)
        self.assertEqual(self.app.shell.current_route.route_id, "pgn")
        self.assertTrue(self.app.shell._publication_hold_active)
        self.assertEqual(self.app.snapshot()["shell_publication_token"], token)

        stale_surface = self.app.browser_command("library", "library.search", {})
        self.assertEqual(stale_surface["kind"], "error")
        self.assertIs(self.app.session, replacement)

        rolled_back = self.app.browser_command(
            "shell",
            "shell.presentation_rollback",
            {"token": token},
        )
        self.assertEqual(rolled_back["kind"], "presentation-rollback")
        self.assertEqual(rolled_back["payload"]["route_id"], "library")
        self.assertEqual(rolled_back["payload"]["focus_target"], prior_focus)
        self.assertIs(self.app.session, prior_session)
        self.assertIs(self.app.pgn, prior_pgn)
        self.assertTrue(self.app._pgn_browser_lease_required)
        self.assertEqual(self.app.shell.current_route.route_id, "library")
        self.assertFalse(self.app.shell._publication_hold_active)
        self.assertIsNone(self.app._pending_shell_publication)
        self.assertIsNone(self.app._pending_shell_publication_restore)

        duplicate = self.app.browser_command(
            "shell",
            "shell.presentation_rollback",
            {"token": token},
        )
        self.assertEqual(duplicate["kind"], "presentation-rollback")
        self.assertIs(self.app.session, prior_session)
        self.assertIs(self.app.pgn, prior_pgn)

    def test_library_open_rollback_failure_retains_exact_retry_authority(self) -> None:
        prior_session, prior_pgn, prior_focus = self._prior_library_state()
        replacement = self._session("rollback-retry.pgn", "Rollback Retry")
        calls: list[tuple[object, object]] = []

        with patch.object(
            self.app.library,
            "dispatch",
            side_effect=self._staged_dispatch(replacement, calls),
        ):
            started = self.app.browser_command(
                "library",
                "library.open_game",
                {"publication_protocol": "ack-v1", "request_id": 711},
            )

        token = started["payload"]["publication_token"]
        with patch.object(
            self.app.shell,
            "_restore_presentation_state",
            side_effect=RuntimeError("simulated rollback restore failure"),
        ):
            failed = self.app.browser_command(
                "shell",
                "shell.presentation_rollback",
                {"token": token},
            )

        self.assertEqual(failed["kind"], "error")
        self.assertIsNotNone(self.app._pending_shell_publication)
        self.assertIsNotNone(self.app._pending_shell_publication_restore)
        self.assertEqual(self.app.snapshot()["shell_publication_token"], token)
        self.assertTrue(self.app.shell._publication_hold_active)
        self.assertIs(self.app.session, prior_session)
        self.assertIs(self.app.pgn, prior_pgn)
        self.assertEqual(self.app._focus, prior_focus)
        self.assertTrue(self.app._pgn_browser_lease_required)

        recovered = self.app.browser_command(
            "shell",
            "shell.presentation_rollback",
            {"token": token},
        )
        self.assertEqual(recovered["kind"], "presentation-rollback")
        self.assertEqual(recovered["payload"]["route_id"], "library")
        self.assertEqual(recovered["payload"]["focus_target"], prior_focus)
        self.assertIs(self.app.session, prior_session)
        self.assertIs(self.app.pgn, prior_pgn)
        self.assertFalse(self.app.shell._publication_hold_active)
        self.assertIsNone(self.app._pending_shell_publication)
        self.assertIsNone(self.app._pending_shell_publication_restore)

    def test_library_open_commit_release_failure_retains_exact_retry_authority(self) -> None:
        self._prior_library_state()
        replacement = self._session("commit-retry.pgn", "Commit Retry")
        calls: list[tuple[object, object]] = []

        with patch.object(
            self.app.library,
            "dispatch",
            side_effect=self._staged_dispatch(replacement, calls),
        ):
            started = self.app.browser_command(
                "library",
                "library.open_game",
                {"publication_protocol": "ack-v1", "request_id": 712},
            )

        token = started["payload"]["publication_token"]
        original_end = self.app.shell._end_publication_hold
        attempts = 0

        def fail_once() -> None:
            nonlocal attempts
            attempts += 1
            if attempts == 1:
                raise RuntimeError("simulated publication release failure")
            original_end()

        with patch.object(self.app.shell, "_end_publication_hold", side_effect=fail_once):
            failed = self.app.browser_command(
                "shell",
                "shell.presentation_commit",
                {"token": token},
            )
            self.assertEqual(failed["kind"], "error")
            self.assertEqual(self.app.snapshot()["shell_publication_token"], token)
            self.assertIsNotNone(self.app._pending_shell_publication)
            self.assertTrue(self.app.shell._publication_hold_active)

            committed = self.app.browser_command(
                "shell",
                "shell.presentation_commit",
                {"token": token},
            )

        self.assertEqual(committed["kind"], "presentation-commit")
        self.assertEqual(attempts, 2)
        self.assertIs(self.app.session, replacement)
        self.assertFalse(self.app.shell._publication_hold_active)
        self.assertIsNone(self.app._pending_shell_publication)
        self.assertIsNone(self.app._pending_shell_publication_restore)

    def test_commit_keeps_replacement_owner_and_is_idempotent(self) -> None:
        prior_session, _prior_pgn, _prior_focus = self._prior_library_state()
        replacement = self._session("committed.pgn", "Committed")
        calls: list[tuple[object, object]] = []

        with patch.object(
            self.app.library,
            "dispatch",
            side_effect=self._staged_dispatch(replacement, calls),
        ):
            started = self.app.browser_command(
                "library",
                "library.open_game",
                {"publication_protocol": "ack-v1", "request_id": 72},
            )

        token = started["payload"]["publication_token"]
        committed = self.app.browser_command(
            "shell",
            "shell.presentation_commit",
            {"token": token},
        )
        duplicate = self.app.browser_command(
            "shell",
            "shell.presentation_commit",
            {"token": token},
        )

        self.assertEqual(calls, [("library.open_game", {})])
        self.assertEqual(committed["kind"], "presentation-commit")
        self.assertEqual(duplicate, committed)
        self.assertIsNot(self.app.session, prior_session)
        self.assertIs(self.app.session, replacement)
        self.assertEqual(self.app.shell.current_route.route_id, "pgn")
        self.assertFalse(self.app.shell._publication_hold_active)
        self.assertIsNone(self.app._pending_shell_publication)
        self.assertIsNone(self.app._pending_shell_publication_restore)

    def test_malformed_success_envelope_restores_prior_owner_before_error(self) -> None:
        prior_session, prior_pgn, prior_focus = self._prior_library_state()
        replacement = self._session("malformed-success.pgn", "Replacement")
        calls: list[tuple[object, object]] = []

        def malformed_dispatch(command, payload):
            calls.append((command, payload))
            self.app.set_document(replacement)
            return LibraryWebViewEvent(
                "delegated",
                {"action": "library.import"},
            )

        with patch.object(self.app.library, "dispatch", side_effect=malformed_dispatch):
            rejected = self.app.browser_command(
                "library",
                "library.open_game",
                {"publication_protocol": "ack-v1", "request_id": 75},
            )

        self.assertEqual(rejected["kind"], "error")
        self.assertEqual(calls, [("library.open_game", {})])
        self.assertIs(self.app.session, prior_session)
        self.assertIs(self.app.pgn, prior_pgn)
        self.assertEqual(self.app.shell.current_route.route_id, "library")
        self.assertEqual(self.app._focus, prior_focus)
        self.assertTrue(self.app._pgn_browser_lease_required)
        self.assertFalse(self.app.shell._publication_hold_active)
        self.assertIsNone(self.app._pending_shell_publication)
        self.assertIsNone(self.app._pending_shell_publication_restore)

    def test_malformed_success_restore_failure_still_restores_prior_domain(self) -> None:
        prior_session, prior_pgn, prior_focus = self._prior_library_state()
        replacement = self._session("malformed-restore-failure.pgn", "Replacement")
        calls: list[tuple[object, object]] = []

        def malformed_dispatch(command, payload):
            calls.append((command, payload))
            self.app.set_document(replacement)
            return LibraryWebViewEvent(
                "delegated",
                {"action": "library.import"},
            )

        with (
            patch.object(self.app.library, "dispatch", side_effect=malformed_dispatch),
            patch.object(
                self.app.shell,
                "_restore_presentation_state",
                side_effect=RuntimeError("simulated pre-publication restore failure"),
            ),
        ):
            rejected = self.app.browser_command(
                "library",
                "library.open_game",
                {"publication_protocol": "ack-v1", "request_id": 751},
            )

        self.assertEqual(rejected["kind"], "error")
        self.assertEqual(calls, [("library.open_game", {})])
        self.assertIs(self.app.session, prior_session)
        self.assertIs(self.app.pgn, prior_pgn)
        self.assertEqual(self.app._focus, prior_focus)
        self.assertTrue(self.app._pgn_browser_lease_required)
        self.assertFalse(self.app.shell._publication_hold_active)
        self.assertIsNone(self.app._pending_shell_publication)
        self.assertIsNone(self.app._pending_shell_publication_restore)

    def test_dirty_prior_pgn_is_restored_after_accepted_open_rolls_back(self) -> None:
        prior_session, prior_pgn, _prior_focus = self._prior_library_state()
        prior_session.edit_tag("Event", "Unsaved prior owner")
        self.assertTrue(prior_session.dirty)
        replacement = self._session("dirty-replacement.pgn", "Replacement")
        confirmations: list[str] = []
        dispatch_calls: list[tuple[object, object]] = []

        def accept() -> bool:
            confirmations.append("confirm")
            return True

        self.app.confirm_document_replace = accept
        request = {"publication_protocol": "ack-v1", "request_id": 73}
        with patch.object(
            self.app.library,
            "dispatch",
            side_effect=self._staged_dispatch(replacement, dispatch_calls),
        ):
            started = self.app.browser_command("library", "library.open_game", request)
            replayed = self.app.browser_command("library", "library.open_game", request)

        self.assertEqual(started, replayed)
        self.assertEqual(confirmations, ["confirm"])
        self.assertEqual(dispatch_calls, [("library.open_game", {})])
        token = started["payload"]["publication_token"]

        rolled_back = self.app.browser_command(
            "shell",
            "shell.presentation_rollback",
            {"token": token},
        )

        self.assertEqual(rolled_back["kind"], "presentation-rollback")
        self.assertIs(self.app.session, prior_session)
        self.assertIs(self.app.pgn, prior_pgn)
        self.assertTrue(prior_session.dirty)
        self.assertEqual(
            prior_session.workspace.current_game().tags["Event"],
            "Unsaved prior owner",
        )
        self.assertEqual(self.app.shell.current_route.route_id, "library")

    def test_new_library_publication_requires_visible_unblocked_library(self) -> None:
        prior_session = self._session("non-library.pgn", "Prior")
        self.app.set_document(prior_session)
        replacement = self._session("stale-library.pgn", "Replacement")
        calls: list[tuple[object, object]] = []

        with patch.object(
            self.app.library,
            "dispatch",
            side_effect=self._staged_dispatch(replacement, calls),
        ):
            rejected = self.app.browser_command(
                "library",
                "library.open_game",
                {"publication_protocol": "ack-v1", "request_id": 74},
            )

        self.assertEqual(rejected["kind"], "error")
        self.assertEqual(calls, [])
        self.assertIs(self.app.session, prior_session)
        self.assertEqual(self.app.shell.current_route.route_id, "pgn")
        self.assertIsNone(self.app._pending_shell_publication)

    def test_library_browser_commands_fail_closed_while_modal_owns_focus(self) -> None:
        _prior_session, _prior_pgn, prior_focus = self._prior_library_state()
        before = self.app.library.projection.snapshot()
        self.app.shell.open_dialog(
            "library-test-dialog",
            opener_focus_id=prior_focus,
            initial_focus_id="library-dialog-confirm",
        )

        rejected = self.app.browser_command("library", "library.search", {})

        self.assertEqual(rejected["kind"], "error")
        self.assertEqual(self.app.library.projection.snapshot(), before)
        self.assertEqual(self.app.shell.current_route.route_id, "library")
        self.assertEqual(self.app.shell.active_dialog_id, "library-test-dialog")

    def test_committed_library_open_rejects_stale_library_surface_commands(self) -> None:
        _prior_session, _prior_pgn, _prior_focus = self._prior_library_state()
        replacement = self._session("route-fence.pgn", "Replacement")
        calls: list[tuple[object, object]] = []

        with patch.object(
            self.app.library,
            "dispatch",
            side_effect=self._staged_dispatch(replacement, calls),
        ):
            started = self.app.browser_command(
                "library",
                "library.open_game",
                {"publication_protocol": "ack-v1", "request_id": 76},
            )

        token = started["payload"]["publication_token"]
        committed = self.app.browser_command(
            "shell",
            "shell.presentation_commit",
            {"token": token},
        )
        self.assertEqual(committed["kind"], "presentation-commit")
        self.assertEqual(self.app.shell.current_route.route_id, "pgn")

        before = self.app.library.projection.snapshot()
        stale_search = self.app.browser_command("library", "library.search", {})
        stale_move = self.app.browser_command(
            "library",
            "library.move",
            {"delta": 1},
        )

        self.assertEqual(stale_search["kind"], "error")
        self.assertEqual(stale_move["kind"], "error")
        self.assertEqual(self.app.library.projection.snapshot(), before)
        self.assertIs(self.app.session, replacement)
        self.assertEqual(self.app.shell.current_route.route_id, "pgn")

    def test_pending_route_publication_blocks_direct_pgn_owner_replacement(self) -> None:
        prior = self._session("publication-prior.pgn", "Prior")
        self.app.set_document(prior)
        self.app._focus = self.app.shell.open_route("board")
        started = self.app.browser_command(
            "shell",
            "screen.library",
            {"publication_protocol": "ack-v1", "request_id": 81},
        )
        token = started["payload"]["publication_token"]
        replacement = self._session("publication-replacement.pgn", "Replacement")

        with self.assertRaisesRegex(RuntimeError, "publication is pending"):
            self.app.set_document(replacement)

        self.assertIs(self.app.session, prior)
        self.assertTrue(self.app.shell._publication_hold_active)
        self.app.browser_command(
            "shell",
            "shell.presentation_rollback",
            {"token": token},
        )
        self.assertIs(self.app.session, prior)

    def test_pending_route_publication_blocks_background_book_owner_commit(self) -> None:
        source = self.root / "publication-book.txt"
        source.write_text(
            "Accessible Chess\n\nPublication fence paragraph.",
            encoding="utf-8",
        )
        prepared = self.app.prepare_book_open(source)
        started = self.app.browser_command(
            "shell",
            "screen.library",
            {"publication_protocol": "ack-v1", "request_id": 82},
        )
        token = started["payload"]["publication_token"]

        with self.assertRaisesRegex(RuntimeError, "publication is pending"):
            self.app.commit_prepared_book_open(prepared)

        self.assertIsNone(self.app.reader)
        self.assertIsNone(self.app.books)
        self.assertTrue(self.app.shell._publication_hold_active)
        self.app.browser_command(
            "shell",
            "shell.presentation_rollback",
            {"token": token},
        )
        self.assertIsNone(self.app.reader)
        self.assertIsNone(self.app.books)

    def test_native_library_modal_preflight_rejects_before_state_or_file_work(self) -> None:
        self.app._focus = self.app.shell.open_route("library")
        self.app.shell.open_dialog(
            "test-dialog",
            opener_focus_id=self.app._focus,
            initial_focus_id="dialog-primary",
        )
        touched: list[str] = []

        def touched_projection(*_args, **_kwargs):
            touched.append("projection")
            raise AssertionError("projection must not run behind modal focus")

        self.app._files = lambda action, payload: touched.append(f"files:{action}")

        with patch.object(
            self.app.library.projection,
            "search",
            side_effect=touched_projection,
        ), patch.object(
            self.app.library.projection,
            "open_selected",
            side_effect=touched_projection,
        ), patch.object(
            self.app.library.projection,
            "request_export_selected",
            side_effect=touched_projection,
        ):
            for action in (
                "library.search",
                "library.open_game",
                "library.import",
                "library.export",
            ):
                with self.subTest(action=action):
                    with self.assertRaisesRegex(ValueError, "close the active dialog"):
                        self.app._delegate(action, {})

        self.assertEqual(touched, [])
        self.assertEqual(self.app.shell.current_route.route_id, "library")
        self.assertEqual(self.app.shell.active_dialog_id, "test-dialog")

    def test_native_library_open_rejects_noncanonical_identity_before_database_lookup(self) -> None:
        class IntSubclass(int):
            pass

        class HostileDict(dict):
            def __bool__(self):
                raise AssertionError("payload truthiness must not run")

            def __iter__(self):
                raise AssertionError("payload iteration must not run")

        malformed = (
            HostileDict(game_id=1, source_id=1, source_index=0),
            {"game_id": True, "source_id": 1, "source_index": 0},
            {"game_id": IntSubclass(1), "source_id": 1, "source_index": 0},
            {"game_id": 0, "source_id": 1, "source_index": 0},
            {"game_id": 1 << 63, "source_id": 1, "source_index": 0},
            {"game_id": 1, "source_id": False, "source_index": 0},
            {"game_id": 1, "source_id": IntSubclass(1), "source_index": 0},
            {"game_id": 1, "source_id": 0, "source_index": 0},
            {"game_id": 1, "source_id": 1 << 63, "source_index": 0},
            {"game_id": 1, "source_id": 1, "source_index": False},
            {"game_id": 1, "source_id": 1, "source_index": IntSubclass(0)},
            {"game_id": 1, "source_id": 1, "source_index": -1},
            {"game_id": 1, "source_id": 1, "source_index": 1 << 63},
        )

        with patch.object(
            self.database,
            "get_game",
            side_effect=AssertionError("database lookup must not run"),
        ):
            for payload in malformed:
                with self.subTest(payload=repr(payload)):
                    with self.assertRaisesRegex(ValueError, "invalid Library game request"):
                        self.app._delegate("library.open_game", payload)

    def test_native_library_open_accepts_exact_persisted_identity(self) -> None:
        self.database.import_pgn_text(
            PGN_TEMPLATE.format(event="Exact Native Open"),
            source_name="exact-native-open.pgn",
        )
        row = self.database.search_games(limit=1)[0]
        payload = {
            "game_id": row["id"],
            "source_id": row["source_id"],
            "source_index": row["source_index"],
        }

        result = self.app._delegate("library.open_game", payload)

        self.assertIsNone(result)
        self.assertIsNotNone(self.app.session)
        self.assertIsNotNone(self.app.pgn)
        self.assertEqual(self.app.shell.current_route.route_id, "pgn")

    def test_native_library_open_rejects_malformed_persisted_provenance_before_load(self) -> None:
        payload = {"game_id": 1, "source_id": 1, "source_index": 0}
        malformed_rows = (
            {"source_id": True, "source_index": 0},
            {"source_id": 1, "source_index": False},
            {"source_id": 1},
            {"source_index": 0},
        )
        for row in malformed_rows:
            with self.subTest(row=row):
                with patch.object(self.database, "get_game", return_value=row), patch(
                    "acs.version2_application.AcsdbBookGameLookup.load_book_game",
                    side_effect=AssertionError("game load must not run"),
                ):
                    with self.assertRaisesRegex(ValueError, "Library selection is stale"):
                        self.app._delegate("library.open_game", payload)

    def test_native_library_navigation_rejects_payload_before_projection_mutation(self) -> None:
        class HostileDict(dict):
            def __bool__(self):
                raise AssertionError("payload truthiness must not run")

        projection = self.app.library.projection
        with patch.object(
            projection,
            "_capture_native_navigation_state",
            side_effect=AssertionError("Library state capture must not run"),
        ):
            for action in (
                "library.search",
                "library.reset_filters",
                "library.next_page",
                "library.previous_page",
            ):
                for payload in ({"unexpected": 1}, HostileDict(unexpected=1), 1):
                    with self.subTest(action=action, payload=repr(payload)):
                        with self.assertRaisesRegex(
                            ValueError,
                            "Library navigation accepts no payload",
                        ):
                            self.app._delegate(action, payload)

    def test_native_library_navigation_requires_exact_passive_render_envelope(self) -> None:
        class EventLookalike:
            kind = "render"
            payload = {"snapshot": {"status": "ready"}}

        class DictSubclass(dict):
            pass

        class StrSubclass(str):
            pass

        candidates = (
            EventLookalike(),
            LibraryWebViewEvent(
                "render",
                DictSubclass(snapshot={"status": "ready"}),
            ),
            LibraryWebViewEvent(
                "render",
                {"snapshot": DictSubclass(status="ready")},
            ),
            LibraryWebViewEvent(
                "render",
                {"snapshot": {"status": StrSubclass("ready")}},
            ),
        )

        origin_focus = self.app.shell.open_route("board")
        self.app._focus = origin_focus
        for candidate in candidates:
            with self.subTest(candidate=type(candidate).__name__):
                with patch.object(
                    self.app.library.projection,
                    "next_page",
                    return_value=candidate,
                ):
                    with self.assertRaises(ValueError):
                        self.app._delegate("library.next_page", {})
                self.assertEqual(self.app.shell.current_route.route_id, "board")
                self.assertEqual(self.app._focus, origin_focus)

    def test_native_library_failed_or_malformed_pagination_preserves_route_and_focus(self) -> None:
        origin_focus = self.app.shell.open_route("board")
        self.app._focus = origin_focus
        error_result = LibraryWebViewEvent(
            "render",
            {
                "snapshot": {
                    "status": "error",
                    "message": "Library page could not be loaded.",
                }
            },
        )
        with patch.object(
            self.app.library.projection,
            "next_page",
            return_value=error_result,
        ):
            with self.assertRaisesRegex(RuntimeError, "could not be loaded"):
                self.app._delegate("library.next_page", {})

        self.assertEqual(self.app.shell.current_route.route_id, "board")
        self.assertEqual(self.app._focus, origin_focus)

        malformed = LibraryWebViewEvent(
            "delegated",
            {"action": "library.import"},
        )
        with patch.object(
            self.app.library.projection,
            "previous_page",
            return_value=malformed,
        ):
            with self.assertRaisesRegex(ValueError, "invalid Library projection result"):
                self.app._delegate("library.previous_page", {})

        self.assertEqual(self.app.shell.current_route.route_id, "board")
        self.assertEqual(self.app._focus, origin_focus)

    def test_native_library_secondary_projection_rollback_failure_still_restores_shell(self) -> None:
        origin_focus = self.app.shell.open_route("board")
        self.app._focus = origin_focus
        projection = self.app.library.projection
        with patch.object(
            projection,
            "next_page",
            side_effect=RuntimeError("primary pagination failure"),
        ), patch.object(
            projection,
            "_restore_native_navigation_state",
            side_effect=RuntimeError("secondary projection rollback failure"),
        ):
            with self.assertRaisesRegex(RuntimeError, "Library navigation rollback failed") as raised:
                self.app._delegate("library.next_page", {})

        self.assertIsInstance(raised.exception.__cause__, RuntimeError)
        self.assertIn("primary pagination failure", str(raised.exception.__cause__))
        self.assertEqual(self.app.shell.current_route.route_id, "board")
        self.assertEqual(self.app._focus, origin_focus)

    def test_native_library_valid_pagination_commits_route_and_focus_after_render(self) -> None:
        self.app._focus = self.app.shell.open_route("board")
        ready = LibraryWebViewEvent(
            "render",
            {"snapshot": {"status": "ready"}},
        )
        with patch.object(
            self.app.library.projection,
            "next_page",
            return_value=ready,
        ):
            result = self.app._delegate("library.next_page", {})

        self.assertIs(result, ready)
        self.assertEqual(self.app.shell.current_route.route_id, "library")
        self.assertEqual(self.app._focus, self.app.shell.restore_focus_target())

    def test_native_library_search_error_render_rolls_back_presenter_state(self) -> None:
        self.database.import_pgn_text(
            PGN_TEMPLATE.format(event="Stable Search"),
            source_name="search-error-rollback.pgn",
        )
        projection = self.app.library.projection
        projection.search(GameSearchQuery(event="Stable Search"))
        before = projection.snapshot()

        self.app._focus = self.app.shell.open_route("board")
        prior_focus = self.app._focus
        with patch.object(
            projection._presenter._service,
            "search",
            side_effect=RuntimeError("simulated backend search failure"),
        ):
            with self.assertRaises(RuntimeError):
                self.app._delegate("library.search", {})

        self.assertEqual(projection.snapshot(), before)
        self.assertEqual(self.app.shell.current_route.route_id, "board")
        self.assertEqual(self.app._focus, prior_focus)

    def test_native_library_route_failure_rolls_back_real_keyset_page(self) -> None:
        self.database.import_pgn_text(
            PGN_TEMPLATE.format(event="Page One") + "\n" + PGN_TEMPLATE.format(event="Page Two"),
            source_name="route-rollback.pgn",
        )
        projection = self.app.library.projection
        projection.search(GameSearchQuery(limit=1))
        before = projection.snapshot()
        self.assertTrue(before["actions"][1]["enabled"])

        self.app._focus = self.app.shell.open_route("board")
        prior_focus = self.app._focus
        open_route = self.app.shell.open_route

        def partially_fail(route_id):
            if route_id == "library":
                open_route(route_id)
                raise RuntimeError("simulated Library route publication failure")
            return open_route(route_id)

        with patch.object(self.app.shell, "open_route", side_effect=partially_fail):
            with self.assertRaisesRegex(RuntimeError, "route publication failure"):
                self.app._delegate("library.next_page", {})

        self.assertEqual(projection.snapshot(), before)
        self.assertEqual(self.app.shell.current_route.route_id, "board")
        self.assertEqual(self.app._focus, prior_focus)

    def test_native_library_route_failure_restores_query_and_export_selection(self) -> None:
        self.database.import_pgn_text(
            PGN_TEMPLATE.format(event="Keep Filter"),
            source_name="selection-rollback.pgn",
        )
        projection = self.app.library.projection
        searched = projection.search(GameSearchQuery(event="Keep Filter"))
        row = searched.payload["snapshot"]["rows"][0]
        projection.toggle_export_selection(row["game_id"])
        before = projection.snapshot()
        before_ids = projection.export_game_ids
        before_query = projection.query

        self.app._focus = self.app.shell.open_route("board")
        prior_focus = self.app._focus
        open_route = self.app.shell.open_route

        def partially_fail(route_id):
            if route_id == "library":
                open_route(route_id)
                raise RuntimeError("simulated Library route publication failure")
            return open_route(route_id)

        with patch.object(self.app.shell, "open_route", side_effect=partially_fail):
            with self.assertRaisesRegex(RuntimeError, "route publication failure"):
                self.app._delegate("library.reset_filters", {})

        self.assertEqual(projection.query, before_query)
        self.assertEqual(projection.export_game_ids, before_ids)
        self.assertEqual(projection.snapshot(), before)
        self.assertEqual(self.app.shell.current_route.route_id, "board")
        self.assertEqual(self.app._focus, prior_focus)

    def test_full_native_event_queue_without_eviction_preserves_exact_order(self) -> None:
        expected = tuple(
            {
                "kind": "status",
                "payload": {"announcement": f"exact-{index}"},
            }
            for index in range(64)
        )
        for event in expected:
            self.app._events.append(event)

        self.assertFalse(self.app._events.overflowed)
        self.assertEqual(self.app.drain_events(), expected)
        self.assertFalse(self.app._events.overflowed)

    def test_saturated_native_event_queue_recovers_with_canonical_route_refresh(self) -> None:
        self.app._focus = self.app.shell.open_route("library")
        for index in range(65):
            self.app._events.append(
                {
                    "kind": "status",
                    "payload": {"announcement": f"queued-{index}"},
                }
            )

        drained = self.app.drain_events()

        self.assertEqual(
            drained,
            ({"kind": "route", "payload": {"route_id": "library"}},),
        )
        self.assertEqual(self.app.drain_events(), ())

    def test_saturated_event_recovery_stays_deferred_until_publication_resolves(self) -> None:
        _prior_session, _prior_pgn, _prior_focus = self._prior_library_state()
        replacement = self._session("overflow-replacement.pgn", "Replacement")
        calls: list[tuple[object, object]] = []

        with patch.object(
            self.app.library,
            "dispatch",
            side_effect=self._staged_dispatch(replacement, calls),
        ):
            started = self.app.browser_command(
                "library",
                "library.open_game",
                {"publication_protocol": "ack-v1", "request_id": 77},
            )

        token = started["payload"]["publication_token"]
        for index in range(65):
            self.app._events.append(
                {
                    "kind": "status",
                    "payload": {"announcement": f"pending-{index}"},
                }
            )

        self.assertEqual(self.app.drain_events(), ())
        rolled_back = self.app.browser_command(
            "shell",
            "shell.presentation_rollback",
            {"token": token},
        )
        self.assertEqual(rolled_back["kind"], "presentation-rollback")
        self.assertEqual(
            self.app.drain_events(),
            ({"kind": "route", "payload": {"route_id": "library"}},),
        )

    def test_browser_library_open_fails_closed_without_ack_protocol(self) -> None:
        prior_session, prior_pgn, _prior_focus = self._prior_library_state()
        replacement = self._session("legacy.pgn", "Legacy")
        calls: list[tuple[object, object]] = []

        with patch.object(
            self.app.library,
            "dispatch",
            side_effect=self._staged_dispatch(replacement, calls),
        ):
            rejected = self.app.browser_command("library", "library.open_game", {})

        self.assertEqual(rejected["kind"], "error")
        self.assertEqual(calls, [])
        self.assertIs(self.app.session, prior_session)
        self.assertIs(self.app.pgn, prior_pgn)
        self.assertEqual(self.app.shell.current_route.route_id, "library")
        self.assertIsNone(self.app._pending_shell_publication)


if __name__ == "__main__":
    unittest.main()
