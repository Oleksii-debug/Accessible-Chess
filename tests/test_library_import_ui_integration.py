from __future__ import annotations

import hashlib
import unittest

from acs.acsdb import AcsDatabase
from acs.full_product_presenters import LibraryPresenter
from acs.full_product_ui_shell import UILanguage
from acs.gametree import parse_games
from acs.library_import_service import (
    LibraryImportCancelledError,
    LibraryImportProgress,
    LibraryImportResult,
    LibraryImportService,
)
from acs.library_webview_bridge import LibraryWebViewBridge
from acs.library_webview_projection import (
    LibraryImportPhase,
    LibraryWebViewProjection,
)
from acs.search_service import GameSearchService


PGN = """[Event "Київ Open"]
[White "Олексій"]
[Black "Анна"]
[Result "1-0"]

1. e4 e5 1-0

[Event "Львів Open"]
[White "Богдан"]
[Black "ОЛЕКСІЙ"]
[Result "0-1"]

1. d4 d5 0-1

[Event "Одеса Open"]
[White "Олексій"]
[Black "Віра"]
[Result "1/2-1/2"]

1. c4 e5 1/2-1/2

[Event "Дніпро Open"]
[White "Ганна"]
[Black "Олексій"]
[Result "*"]

1. Nf3 d5 *
"""


class LibraryImportUiIntegrationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.database = AcsDatabase()
        self.import_service = LibraryImportService(self.database)
        self.cancel_requested = False
        self.dispatch_calls: list[tuple[str, dict[str, object]]] = []

        def dispatch(action_id: str, payload: dict[str, object]):
            self.dispatch_calls.append((action_id, dict(payload)))
            if action_id == "library.import":
                self.cancel_requested = False
            elif action_id == "library.cancel_import":
                self.cancel_requested = True
            return {"private": "backend return must not reach browser"}

        presenter = LibraryPresenter(
            GameSearchService(self.database),
            language=UILanguage.UA,
        )
        self.projection = LibraryWebViewProjection(
            presenter,
            dispatch,
            language=UILanguage.UA,
        )
        self.bridge = LibraryWebViewBridge(self.projection)
        self.games = tuple(parse_games(PGN))

    def tearDown(self) -> None:
        self.database.close()

    @staticmethod
    def digest(text: str) -> str:
        return hashlib.sha256(text.encode("utf-8")).hexdigest()

    def test_real_import_progress_completion_and_unicode_search_share_one_acsdb(self) -> None:
        requested = self.bridge.dispatch("library.import", {})
        self.assertEqual("delegated", requested.kind)
        self.assertEqual({"action": "library.import"}, dict(requested.payload))
        self.assertEqual([("library.import", {})], self.dispatch_calls)

        import_ui = self.projection.import_projection
        started = import_ui.begin(len(self.games))
        self.assertEqual("running", started.payload["import"]["phase"])
        seen: list[tuple[int, int, str]] = []

        def progress(item: LibraryImportProgress) -> None:
            event = import_ui.progress(item)
            state = event.payload["import"]
            seen.append(
                (
                    int(state["processed_games"]),
                    int(state["total_games"]),
                    str(event.payload["announcement"]),
                )
            )

        result = self.import_service.import_games(
            self.games,
            source_name=r"C:\Users\private\large-library.pgn",
            source_format="PGN",
            source_sha256=self.digest(PGN),
            progress_callback=progress,
        )
        completed = import_ui.complete(result)
        state = completed.payload["import"]
        self.assertEqual("completed", state["phase"])
        self.assertEqual(len(self.games), state["processed_games"])
        self.assertEqual("", seen[-1][2])
        self.assertNotIn("C:\\", repr(state))
        self.assertNotIn("private", repr(state).casefold())
        self.assertNotIn("source_id", repr(state))
        self.assertNotIn("attempt_id", repr(state))

        searched = self.bridge.dispatch(
            "library.search",
            {"player": "олексій", "limit": "25"},
        ).payload["snapshot"]
        self.assertEqual(4, len(searched["rows"]))
        self.assertEqual("completed", searched["import"]["phase"])

    def test_cancel_rolls_back_partial_data_and_retry_commits_complete_batch(self) -> None:
        import_ui = self.projection.import_projection
        self.bridge.dispatch("library.import", {})
        import_ui.begin(len(self.games))

        def progress_then_cancel(item: LibraryImportProgress) -> None:
            import_ui.progress(item)
            if item.processed_games == 1:
                event = self.bridge.dispatch("library.cancel_import", {})
                self.assertEqual("render-import", event.kind)
                self.assertEqual("cancelling", event.payload["import"]["phase"])

        with self.assertRaises(LibraryImportCancelledError):
            self.import_service.import_games(
                self.games,
                source_name="cancelled.pgn",
                source_format="pgn",
                source_sha256="a" * 64,
                cancel_check=lambda: self.cancel_requested,
                progress_callback=progress_then_cancel,
            )
        cancelled = import_ui.cancelled().payload["import"]
        self.assertEqual("cancelled", cancelled["phase"])
        self.assertEqual(0, self.database.conn.execute("SELECT COUNT(*) FROM games").fetchone()[0])
        self.assertEqual(0, self.database.conn.execute("SELECT COUNT(*) FROM sources").fetchone()[0])

        retry = self.bridge.dispatch("library.import", {})
        self.assertEqual("delegated", retry.kind)
        import_ui.begin(len(self.games))
        result = self.import_service.import_games(
            self.games,
            source_name="retry.pgn",
            source_format="pgn",
            source_sha256="b" * 64,
            cancel_check=lambda: self.cancel_requested,
            progress_callback=import_ui.progress,
        )
        final_state = import_ui.complete(result).payload["import"]
        self.assertEqual("completed", final_state["phase"])
        self.assertEqual(len(self.games), self.database.conn.execute("SELECT COUNT(*) FROM games").fetchone()[0])
        attempts = self.database.list_import_attempts()
        self.assertEqual(["full", "failed"], [item["status"] for item in attempts])

    def test_stale_or_malformed_progress_is_atomic_and_browser_errors_are_bounded(self) -> None:
        import_ui = self.projection.import_projection
        import_ui.begin(2)
        import_ui.progress(LibraryImportProgress(7, 1, 2))
        before = import_ui.snapshot()
        for invalid in (
            LibraryImportProgress(8, 2, 2),
            LibraryImportProgress(7, 0, 2),
            LibraryImportProgress(7, 2, 3),
        ):
            with self.subTest(invalid=invalid):
                with self.assertRaises((ValueError, RuntimeError)):
                    import_ui.progress(invalid)
                self.assertEqual(before, import_ui.snapshot())

        with self.assertRaises(ValueError):
            import_ui.complete(LibraryImportResult(7, 1, 3, 0, 1, 3))
        self.assertEqual(before, import_ui.snapshot())

        failed = import_ui.fail(RuntimeError(r"sqlite failed at C:\Users\private\library.acsdb"))
        visible = repr(failed.payload).casefold()
        self.assertEqual(LibraryImportPhase.ERROR, import_ui.phase)
        self.assertNotIn("sqlite", visible)
        self.assertNotIn("private", visible)
        self.assertNotIn("c:\\", visible)

    def test_cancel_command_is_rejected_without_mutating_idle_state(self) -> None:
        before = self.projection.import_projection.snapshot()
        event = self.bridge.dispatch("library.cancel_import", {})
        self.assertEqual("error", event.kind)
        self.assertEqual(before, self.projection.import_projection.snapshot())


if __name__ == "__main__":
    unittest.main()
