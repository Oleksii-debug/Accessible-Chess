from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
import tempfile
import unittest

from acs.gametree_navigation import GameTreeCursor
from acs.gametree_resume import GameTreeResumeCode, GameTreeResumeError, GameTreeResumeStore
from acs.pgn_document import PgnDocumentSession
from acs.pgn_roundtrip import parse_pgn_text
from acs.pgn_workspace import PgnWorkspace
from acs.version2_gametree_resume import Version2GameTreeResumeCoordinator
from acs.version2_release_app import _install_unsaved_pgn_close_guard


PGN = '''[Event "D06 V2 release resume"]
[White "Alpha"]
[Black "Beta"]
[Result "*"]

1. e4 e5 2. Nf3 Nc6 *
'''


class _Application:
    def __init__(self) -> None:
        self.session = None
        self.installed = []

    def set_document(self, session) -> None:
        self.session = session
        self.installed.append(session)


class _EventHook:
    def __init__(self) -> None:
        self.handler = None

    def __iadd__(self, handler):
        self.handler = handler
        return self

    def fire(self, event) -> None:
        if self.handler is None:
            raise AssertionError("FormClosing handler was not installed")
        self.handler(None, event)


class _Owner:
    def __init__(self) -> None:
        self.FormClosing = _EventHook()


class D06V2GameTreeResumeReachabilityTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.resume_path = self.root / "gametree-resume.json"
        self.game = parse_pgn_text(PGN, strict=True)[0]

    def _clean_session(self, cursor: GameTreeCursor) -> PgnDocumentSession:
        workspace = PgnWorkspace((self.game,))
        workspace.set_cursor(cursor)
        return PgnDocumentSession(workspace, saved_digest=workspace.content_digest)

    def test_clean_close_then_new_application_restores_exact_selected_game_and_cursor(self):
        first = _Application()
        first.session = self._clean_session(GameTreeCursor((), 2))
        writer = Version2GameTreeResumeCoordinator(self.resume_path)

        writer.prepare_shutdown(first)
        self.assertTrue(self.resume_path.is_file())
        self.assertIsNotNone(writer.token)

        second = _Application()
        reader = Version2GameTreeResumeCoordinator(self.resume_path)
        self.assertTrue(reader.restore(second))
        self.assertEqual(len(second.installed), 1)
        self.assertFalse(second.session.dirty)
        self.assertEqual(second.session.workspace.cursor, GameTreeCursor((), 2))
        self.assertEqual(second.session.workspace.current_game(), self.game)
        self.assertEqual(reader.token, GameTreeResumeStore(self.resume_path).load().token)

    def test_confirmed_dirty_discard_removes_previous_resume_instead_of_resurrecting_it(self):
        app = _Application()
        coordinator = Version2GameTreeResumeCoordinator(self.resume_path)
        app.session = self._clean_session(GameTreeCursor((), 1))
        coordinator.prepare_shutdown(app)
        self.assertTrue(self.resume_path.exists())

        app.session = PgnDocumentSession.from_text(PGN)
        self.assertTrue(app.session.dirty)
        coordinator.prepare_shutdown(app)

        self.assertFalse(self.resume_path.exists())
        self.assertIsNone(coordinator.token)
        self.assertFalse(Version2GameTreeResumeCoordinator(self.resume_path).restore(_Application()))

    def test_dirty_discard_rejects_stale_token_and_preserves_newer_writer(self):
        app = _Application()
        coordinator = Version2GameTreeResumeCoordinator(self.resume_path)
        app.session = self._clean_session(GameTreeCursor((), 1))
        coordinator.prepare_shutdown(app)
        observed = coordinator.token
        self.assertIsNotNone(observed)

        newer = GameTreeResumeStore(self.resume_path).save(
            self.game,
            GameTreeCursor((), 3),
            expected_token=observed,
        )
        app.session = PgnDocumentSession.from_text(PGN)

        with self.assertRaises(GameTreeResumeError) as caught:
            coordinator.prepare_shutdown(app)
        self.assertEqual(caught.exception.code, GameTreeResumeCode.STALE_WRITER)
        authoritative = GameTreeResumeStore(self.resume_path).load()
        self.assertEqual(authoritative.token, newer.token)
        self.assertEqual(authoritative.cursor, GameTreeCursor((), 3))

    def test_corrupt_resume_is_preserved_and_disables_resume_without_blocking_application(self):
        original = b'{"schema_version":1'
        self.resume_path.write_bytes(original)
        app = _Application()
        coordinator = Version2GameTreeResumeCoordinator(self.resume_path)

        self.assertFalse(coordinator.restore(app))
        self.assertTrue(coordinator.disabled)
        self.assertIsInstance(coordinator.error, GameTreeResumeError)
        self.assertIs(getattr(app, "_gametree_resume_error"), coordinator.error)
        self.assertEqual(self.resume_path.read_bytes(), original)

        app.session = PgnDocumentSession.from_text(PGN)
        coordinator.prepare_shutdown(app)
        self.assertEqual(self.resume_path.read_bytes(), original)

    def test_native_close_runs_resume_gate_only_after_dirty_discard_is_confirmed(self):
        order = []
        owner = _Owner()
        application = SimpleNamespace(
            session=SimpleNamespace(dirty=True),
            shutdown=lambda: order.append("shutdown") or True,
        )
        dialogs = SimpleNamespace(
            confirm_discard_unsaved_pgn_on_exit=lambda: order.append("confirm") or True
        )

        _install_unsaved_pgn_close_guard(
            application,
            owner,
            dialogs,
            before_shutdown=lambda app: order.append("resume"),
        )
        event = SimpleNamespace(Cancel=False)
        owner.FormClosing.fire(event)

        self.assertFalse(event.Cancel)
        self.assertEqual(order, ["confirm", "resume", "shutdown"])
        self.assertTrue(application._native_close_shutdown_complete)

    def test_native_close_cancel_does_not_touch_resume_or_shutdown(self):
        order = []
        owner = _Owner()
        application = SimpleNamespace(
            session=SimpleNamespace(dirty=True),
            shutdown=lambda: order.append("shutdown") or True,
        )
        dialogs = SimpleNamespace(
            confirm_discard_unsaved_pgn_on_exit=lambda: order.append("confirm") or False
        )

        _install_unsaved_pgn_close_guard(
            application,
            owner,
            dialogs,
            before_shutdown=lambda app: order.append("resume"),
        )
        event = SimpleNamespace(Cancel=False)
        owner.FormClosing.fire(event)

        self.assertTrue(event.Cancel)
        self.assertEqual(order, ["confirm"])


if __name__ == "__main__":
    unittest.main()
