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
from acs.keybindings import BindingContext
from acs.library_webview_projection import LibraryWebViewEvent
from acs.pgn_document import PgnDocumentSession
from acs.version2_application import Version2Application


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
