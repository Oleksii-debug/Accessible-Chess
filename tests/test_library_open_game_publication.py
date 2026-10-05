from __future__ import annotations

from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from acs.acsdb import AcsDatabase
from acs.analysis_service import AnalysisService
from acs.book_progress_store import BookProgressStore
from acs.engine_assisted_workflows import EngineAssistedWorkflowService
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
