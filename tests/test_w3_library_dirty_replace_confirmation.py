from __future__ import annotations

import inspect
from pathlib import Path
import tempfile
import unittest

from acs.acsdb import AcsDatabase
from acs.analysis_service import AnalysisService
from acs.book_progress_store import BookProgressStore
from acs.engine_assisted_workflows import EngineAssistedWorkflowService
from acs.pgn_document import PgnDocumentSession
from acs.version2_application import Version2Application
from acs.version2_release_app import create_version2_release_application


PGN_TEMPLATE = """[Event \"{event}\"]
[Site \"?\"]
[Date \"2026.09.10\"]
[Round \"1\"]
[White \"White\"]
[Black \"Black\"]
[Result \"*\"]

1. e4 e5 *
"""


class W3LibraryDirtyReplaceConfirmationEvidenceTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.database = AcsDatabase(self.root / "library.acsdb")
        self.addCleanup(self.database.close)
        self.analysis = AnalysisService(lambda: None)
        self.addCleanup(self.analysis.close)
        self.application = Version2Application(
            self.database,
            progress_store=BookProgressStore(self.root / "progress.json"),
            engine_assistance=EngineAssistedWorkflowService(self.analysis),
            board_dispatch=lambda *_: None,
            copy_text=lambda _: None,
        )

    def _session(self, filename: str, event: str) -> PgnDocumentSession:
        path = self.root / filename
        path.write_text(PGN_TEMPLATE.format(event=event), encoding="utf-8")
        return PgnDocumentSession.open(path)

    def _dirty_document(self) -> PgnDocumentSession:
        session = self._session("current.pgn", "Original")
        self.application.set_document(session)
        session.edit_tag("Event", "Unsaved")
        self.assertTrue(session.dirty)
        return session

    def _assert_preserved(self, session: PgnDocumentSession, snapshot: dict) -> None:
        self.assertIs(self.application.session, session)
        self.assertTrue(session.dirty)
        self.assertEqual(session.workspace.current_game().tags["Event"], "Unsaved")
        self.assertEqual(self.application.snapshot(), snapshot)

    def test_production_composition_binds_confirmation_after_close_guard_and_runtime_exist(self) -> None:
        source = inspect.getsource(create_version2_release_application)
        runtime_build = source.index("file_runtime = Version2WindowsFileWorkflowRuntime(")
        close_guard = source.index("file_runtime = _install_close_guard_or_shutdown(", runtime_build)
        binding = source.index(
            "application.confirm_document_replace = file_runtime.file_dialogs.confirm_discard_unsaved_pgn",
            close_guard,
        )
        runtime_return = source.index("return file_runtime", binding)

        self.assertLess(runtime_build, close_guard)
        self.assertLess(close_guard, binding)
        self.assertLess(binding, runtime_return)
        self.assertIn(
            "set_pgn_session=lambda session: _install_host_confirmed_document(application, session)",
            source,
            "native PGN Open must retain the host-confirmed no-double-prompt installation path",
        )

    def test_before_native_owner_dirty_application_replacement_fails_closed(self) -> None:
        current = self._dirty_document()
        replacement = self._session("replacement.pgn", "Replacement")
        before = self.application.snapshot()

        with self.assertRaisesRegex(ValueError, "replacement cancelled"):
            self.application.set_document(replacement)

        self._assert_preserved(current, before)

    def test_owner_cancel_is_requested_once_and_preserves_dirty_document_exactly(self) -> None:
        current = self._dirty_document()
        replacement = self._session("replacement.pgn", "Replacement")
        before = self.application.snapshot()
        calls = []

        def deny() -> bool:
            calls.append("confirm")
            return False

        self.application.confirm_document_replace = deny
        with self.assertRaisesRegex(ValueError, "replacement cancelled"):
            self.application.set_document(replacement)

        self.assertEqual(calls, ["confirm"])
        self._assert_preserved(current, before)

    def test_owner_dialog_failure_preserves_dirty_document_exactly(self) -> None:
        current = self._dirty_document()
        replacement = self._session("replacement.pgn", "Replacement")
        before = self.application.snapshot()
        calls = []

        def fail() -> bool:
            calls.append("confirm")
            raise RuntimeError("synthetic native dialog failure")

        self.application.confirm_document_replace = fail
        with self.assertRaisesRegex(RuntimeError, "synthetic native dialog failure"):
            self.application.set_document(replacement)

        self.assertEqual(calls, ["confirm"])
        self._assert_preserved(current, before)

    def test_owner_accept_replaces_once_without_browser_confirmation_payload(self) -> None:
        current = self._dirty_document()
        replacement = self._session("replacement.pgn", "Replacement")
        calls = []

        def accept() -> bool:
            calls.append("confirm")
            return True

        self.application.confirm_document_replace = accept
        self.application.set_document(replacement)

        self.assertEqual(calls, ["confirm"])
        self.assertIs(self.application.session, replacement)
        self.assertIsNot(self.application.session, current)
        self.assertEqual(replacement.workspace.current_game().tags["Event"], "Replacement")

        replacement.edit_tag("Event", "Unsaved")
        before = self.application.snapshot()
        calls.clear()
        with self.assertRaisesRegex(ValueError, "invalid Library game request"):
            self.application._delegate(
                "library.open_game",
                {"game_id": 1, "source_id": 1, "source_index": 0, "confirm": True},
            )
        self.assertEqual(calls, [])
        self._assert_preserved(replacement, before)

    def test_library_open_game_reuses_application_document_replacement_seam(self) -> None:
        source = inspect.getsource(Version2Application._delegate)
        self.assertIn(
            "self.set_document(PgnDocumentSession(PgnWorkspace((game,))))",
            source,
            "Library -> Open game bypasses the canonical application replacement seam",
        )
        self.assertNotIn("confirm_document_replace(", source)


if __name__ == "__main__":
    unittest.main()
