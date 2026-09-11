"""Real canonical state across launcher, native owner and WebView worker threads."""
from concurrent.futures import Future, ThreadPoolExecutor
import inspect
from pathlib import Path
from queue import Queue
import tempfile
import threading
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from acs.acsdb import AcsDatabase
from acs.analysis_service import AnalysisService
from acs.book_progress_store import BookProgressStore
from acs.engine_assisted_workflows import EngineAssistedWorkflowService
from acs.pgn_document import PgnDocumentSession
from acs.stage1_release_ui import Stage1ReleaseAccessibleChessAPI
from acs.version2_application import Version2Application
from acs.version2_release_app import create_version2_release_application
from acs.version2_release_ui import Version2ReleaseAccessibleChessAPI


class _OwnerLoop:
    """Deterministic Form.Invoke transport, with a genuinely separate owner thread."""
    def __init__(self):
        self.tasks = Queue()
        self.ready = threading.Event()
        self.IsDisposed = False
        self.thread = threading.Thread(target=self._run, name="test-native-owner")
        self.thread.start()
        if not self.ready.wait(5):
            raise RuntimeError("owner did not start")

    def _run(self):
        self.thread_id = threading.get_ident()
        self.ready.set()
        while True:
            entry = self.tasks.get()
            if entry is None:
                return
            callback, future = entry
            try:
                future.set_result(callback())
            except BaseException as error:
                future.set_exception(error)

    @property
    def InvokeRequired(self):
        return threading.get_ident() != self.thread_id

    def Invoke(self, callback):
        if not self.InvokeRequired:
            return callback()
        future = Future()
        self.tasks.put((callback, future))
        return future.result(5)

    def close(self):
        self.IsDisposed = True
        self.tasks.put(None)
        self.thread.join(5)
        if self.thread.is_alive():
            raise RuntimeError("owner did not stop")


class Version2ApiThreadDispatchTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.owner = _OwnerLoop()
        self.addCleanup(self.owner.close)
        self.api = Version2ReleaseAccessibleChessAPI(keymap_path=self.root / "keys.json")
        self.analysis = AnalysisService(lambda: None)
        self.addCleanup(self.analysis.close)

        def construct():
            self.api._bind_ui_owner(self.owner, action_factory=lambda callback: callback)
            database = AcsDatabase(self.root / "library.acsdb")
            app = Version2Application(database,
                progress_store=BookProgressStore(self.root / "books.json"),
                engine_assistance=EngineAssistedWorkflowService(self.analysis),
                board_dispatch=self.api.v2_board_dispatch)
            self.api.bind_version2_application(app)
            return app

        self.app = self.owner.Invoke(construct)
        self.addCleanup(lambda: self.owner.Invoke(self.app.shutdown))
        self.addCleanup(lambda: Stage1ReleaseAccessibleChessAPI.close_analysis(self.api))

    def test_worker_snapshot_library_query_and_pgn_edit_share_native_owner(self):
        self.owner.Invoke(lambda: self.app.set_document(
            PgnDocumentSession.from_text('1. e4 {old} (1. d4 d5) e5 *')))
        with ThreadPoolExecutor(max_workers=4) as workers:
            snapshots = [workers.submit(self.api.v2_snapshot) for _ in range(8)]
            self.assertTrue(all(item.result(5)["pgn"] for item in snapshots))
            result = workers.submit(self.api.v2_browser_command,
                "library", "library.search", {"player": "Петренко"}).result(5)
            self.assertEqual(result["kind"], "render")
            selected = workers.submit(self.api.v2_browser_command,
                "pgn", "pgn.select", {"node_id": "g0:main/m0"}).result(5)
            self.assertEqual(selected["kind"], "selection")
            edited = workers.submit(self.api.v2_browser_command,
                "pgn", "pgn.comment_edit", {"text": "Збережений зміст"}).result(5)
            self.assertEqual(edited["kind"], "selection")
            workers.submit(self.api.v2_record_focus, "pgn-comment").result(5)
            workers.submit(self.api.v2_drain_events).result(5)
        self.assertTrue(self.owner.Invoke(lambda: self.app.session.dirty))
        self.assertEqual(self.owner.Invoke(lambda: self.app._focus), "pgn-comment")
        # The canonical affinity guards remain strict when bypassing the host API.
        with self.assertRaisesRegex(RuntimeError, "native UI thread"):
            self.app.snapshot()
        with self.assertRaises(Exception) as error:
            self.app.database.conn.execute("SELECT 1")
        self.assertIn("thread", str(error.exception).lower())

    def test_inherited_board_commands_and_nested_v2_dispatch_use_same_state(self):
        with ThreadPoolExecutor(max_workers=2) as workers:
            moved = workers.submit(self.api.make_move, "e4").result(5)
            self.assertTrue(moved["ok"])
            state = workers.submit(self.api.get_state).result(5)
            current = workers.submit(self.api.v2_board_dispatch,
                "board.current", {"square": "e4"}).result(5)
        self.assertEqual(state["fen"], current["fen"])
        self.assertEqual(current["focusSquare"], "e4")
        self.assertEqual(inspect.signature(self.api.make_move),
                         inspect.signature(Stage1ReleaseAccessibleChessAPI.make_move).replace(
                             parameters=list(inspect.signature(Stage1ReleaseAccessibleChessAPI.make_move).parameters.values())[1:]))

    def test_errors_propagate_and_disposed_owner_never_falls_back_to_worker(self):
        with self.assertRaisesRegex(ValueError, "payload"):
            self.api.v2_board_dispatch("board.current", {"path": "not-a-square"})
        self.owner.IsDisposed = True
        try:
            with self.assertRaisesRegex(RuntimeError, "unavailable"):
                self.api.v2_snapshot()
        finally:
            self.owner.IsDisposed = False
        self.assertEqual(self.owner.Invoke(lambda: self.app.database.schema_version), 6)

    def test_production_factory_defers_sqlite_until_native_owner_exists(self):
        runtime = SimpleNamespace(provider=lambda: None, close=lambda: None)
        data_root = self.root / "deferred"
        with patch("acs.version2_release_app.AcsDatabase", wraps=AcsDatabase) as create_database:
            api, factory, engine, files = create_version2_release_application(
                data_root=data_root, runtime_factory=lambda _: runtime,
                sound_playback=SimpleNamespace(play=lambda *_: None), defer_ui=True)
            self.assertTrue(callable(factory))
            create_database.assert_not_called()
            self.assertIs(engine, runtime)
            def construct():
                api._bind_ui_owner(self.owner, action_factory=lambda callback: callback)
                return factory()
            app = self.owner.Invoke(construct)
            try:
                self.assertEqual(api.v2_snapshot()["screen"]["route_id"], "board")
                self.assertEqual(self.owner.Invoke(lambda: app.database.schema_version), 6)
                with self.assertRaisesRegex(RuntimeError, "already constructed"):
                    self.owner.Invoke(factory)
            finally:
                self.owner.Invoke(app.shutdown)
                Stage1ReleaseAccessibleChessAPI.close_analysis(api)


if __name__ == "__main__":
    unittest.main()
