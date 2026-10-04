from __future__ import annotations

from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from acs.acsdb import AcsDatabase
from acs.analysis_service import AnalysisService
from acs.book_progress_store import BookProgressStore
from acs.engine_assisted_workflows import EngineAssistedWorkflowService
from acs.pgn_document import PgnDocumentSession
from acs.version2_application import Version2Application


DOCUMENT = '''[Event "One"]
[Result "*"]

1. e4 e5 *

[Event "Two"]
[Result "*"]

1. d4 d5 *
'''

REPLACEMENT_DOCUMENT = '''[Event "One"]
[Result "*"]

1. e4 e5 *

[Event "Different Tail"]
[Result "*"]

1. Nf3 Nf6 *
'''


class PgnBrowserPresentationLeaseRequiredTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        root = Path(self.temp.name)
        self.database = AcsDatabase(root / "library.acsdb")
        self.addCleanup(self.database.close)
        self.analysis = AnalysisService(lambda: None)
        self.addCleanup(self.analysis.close)
        self.app = Version2Application(
            self.database,
            progress_store=BookProgressStore(root / "progress.json"),
            engine_assistance=EngineAssistedWorkflowService(self.analysis),
            board_dispatch=lambda *_: None,
        )
        self.app.set_document(PgnDocumentSession.from_text(DOCUMENT))

    def test_legacy_bootstrap_before_browser_render_remains_compatible(self) -> None:
        accepted = self.app.browser_command("pgn", "pgn.next_game", {})
        self.assertEqual("selection", accepted["kind"])
        self.assertEqual(1, self.app.session.workspace.selected_game_index)

    def test_replacing_document_before_browser_render_remains_unleased(self) -> None:
        self.app.set_document(PgnDocumentSession.from_text(DOCUMENT))
        accepted = self.app.browser_command("pgn", "pgn.next_game", {})
        self.assertEqual("selection", accepted["kind"])
        self.assertEqual(1, self.app.session.workspace.selected_game_index)

    def test_missing_lease_after_browser_snapshot_rejects_navigation_and_recovers(self) -> None:
        visible = self.app.snapshot()["pgn"]
        rejected = self.app.browser_command("pgn", "pgn.next_game", {})
        self.assertEqual("selection", rejected["kind"])
        self.assertEqual(0, self.app.session.workspace.selected_game_index)
        recovered = rejected["payload"]["snapshot"]
        self.assertEqual(0, recovered["game"]["index"])
        self.assertRegex(recovered["presentation_token"], r"^[0-9a-f]{64}$")
        self.assertEqual(visible["presentation_token"], recovered["presentation_token"])

    def test_hidden_host_snapshot_cannot_make_tokenless_stale_intent_authoritative(self) -> None:
        visible = self.app.snapshot()["pgn"]
        old_token = visible["presentation_token"]
        self.app.session.workspace.next_game()
        hidden = self.app.snapshot()["pgn"]
        self.assertEqual(1, hidden["game"]["index"])
        self.assertNotEqual(old_token, hidden["presentation_token"])
        rejected = self.app.browser_command("pgn", "pgn.previous_game", {})
        self.assertEqual("selection", rejected["kind"])
        self.assertEqual(1, self.app.session.workspace.selected_game_index)
        self.assertEqual(1, rejected["payload"]["snapshot"]["game"]["index"])

    def test_matching_rendered_lease_allows_navigation(self) -> None:
        visible = self.app.snapshot()["pgn"]
        accepted = self.app.browser_command(
            "pgn",
            "pgn.next_game",
            {"presentation_token": visible["presentation_token"]},
        )
        self.assertEqual("selection", accepted["kind"])
        self.assertEqual(1, self.app.session.workspace.selected_game_index)
        self.assertEqual(1, accepted["payload"]["snapshot"]["game"]["index"])

    def test_document_replacement_during_item_dispatch_is_rejected_by_full_digest_cas(self) -> None:
        visible = self.app.snapshot()["pgn"]
        assert visible is not None
        original_session = self.app.session
        original_view = original_session.workspace.view()
        replacement = PgnDocumentSession.from_text(REPLACEMENT_DOCUMENT)
        replacement_view = replacement.workspace.view()
        self.assertEqual(
            original_view.current_record_digest,
            replacement_view.current_record_digest,
        )
        self.assertEqual(
            original_view.content_revision,
            replacement_view.content_revision,
        )
        self.assertNotEqual(original_view.content_digest, replacement_view.content_digest)

        original_dispatch = self.app.router.dispatch
        swapped = False

        def replace_then_dispatch(action_id, payload=None, **kwargs):
            nonlocal swapped
            if not swapped:
                swapped = True
                self.app.set_document(replacement)
            return original_dispatch(action_id, payload, **kwargs)

        with patch.object(
            self.app.router,
            "dispatch",
            side_effect=replace_then_dispatch,
        ):
            rejected = self.app.browser_command(
                "pgn",
                "pgn.move",
                {
                    "delta": 1,
                    "presentation_token": visible["presentation_token"],
                },
            )

        self.assertTrue(swapped)
        self.assertEqual("error", rejected["kind"])
        self.assertIs(self.app.session, replacement)
        self.assertEqual(0, replacement.workspace.cursor.next_move_index)
        self.assertEqual(replacement.workspace.view(), replacement_view)

    def test_document_replacement_during_game_navigation_is_rejected_by_full_digest_cas(self) -> None:
        visible = self.app.snapshot()["pgn"]
        assert visible is not None
        original_session = self.app.session
        original_view = original_session.workspace.view()
        replacement = PgnDocumentSession.from_text(REPLACEMENT_DOCUMENT)
        replacement_view = replacement.workspace.view()
        self.assertEqual(
            original_view.current_record_digest,
            replacement_view.current_record_digest,
        )
        self.assertEqual(
            original_view.content_revision,
            replacement_view.content_revision,
        )
        self.assertNotEqual(original_view.content_digest, replacement_view.content_digest)

        original_dispatch = self.app.router.dispatch
        swapped = False

        def replace_then_dispatch(action_id, payload=None, **kwargs):
            nonlocal swapped
            if not swapped:
                swapped = True
                self.app.set_document(replacement)
            return original_dispatch(action_id, payload, **kwargs)

        with patch.object(
            self.app.router,
            "dispatch",
            side_effect=replace_then_dispatch,
        ):
            rejected = self.app.browser_command(
                "pgn",
                "pgn.next_game",
                {"presentation_token": visible["presentation_token"]},
            )

        self.assertTrue(swapped)
        self.assertEqual("error", rejected["kind"])
        self.assertIs(self.app.session, replacement)
        self.assertEqual(0, replacement.workspace.selected_game_index)
        self.assertEqual(replacement.workspace.view(), replacement_view)

    def test_refresh_remains_token_free_recovery_path(self) -> None:
        self.app.snapshot()
        refreshed = self.app.browser_command("pgn", "pgn.refresh", {})
        self.assertEqual("selection", refreshed["kind"])
        self.assertEqual("ready", refreshed["payload"]["snapshot"]["status"])
        self.assertRegex(
            refreshed["payload"]["snapshot"]["presentation_token"],
            r"^[0-9a-f]{64}$",
        )

    def test_replacing_document_does_not_drop_issued_lease_requirement(self) -> None:
        self.app.snapshot()
        self.app.set_document(PgnDocumentSession.from_text(DOCUMENT))
        rejected = self.app.browser_command("pgn", "pgn.next_game", {})
        self.assertEqual("selection", rejected["kind"])
        self.assertEqual(0, self.app.session.workspace.selected_game_index)
        self.assertRegex(
            rejected["payload"]["snapshot"]["presentation_token"],
            r"^[0-9a-f]{64}$",
        )


if __name__ == "__main__":
    unittest.main()
