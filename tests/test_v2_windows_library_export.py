from __future__ import annotations

from pathlib import Path
import tempfile
import unittest

from acs.acsdb import AcsDatabase
from acs.library_export_service import LibraryExportRequest, LibraryExportService
from acs.pgn_service import open_pgn
from acs.search_service import GameSearchQuery, GameSearchService
from acs.version2_windows_library_export import (
    LibraryExportHostEventKind,
    Version2WindowsLibraryExportDelegate,
)


_PGN = '''[Event "Windows Library"]
[Site "Uzhhorod UKR"]
[Date "2026.08.31"]
[Round "1"]
[White "Олексій"]
[Black "Test"]
[Result "*"]

1. e4 {comment} e5 (1... c5 $5) *
'''


class _Dialogs:
    def __init__(self, destination: Path | None) -> None:
        self.destination = destination
        self.calls: list[str] = []

    def export_selection(self, suggested_filename: str = "selection.pgn") -> Path | None:
        self.calls.append(suggested_filename)
        return self.destination


class _ExplodingDialogs(_Dialogs):
    def export_selection(self, suggested_filename: str = "selection.pgn") -> Path | None:
        self.calls.append(suggested_filename)
        raise RuntimeError(r"dialog failed at C:\Users\Private\secret.pgn")


class Version2WindowsLibraryExportTests(unittest.TestCase):
    def setUp(self) -> None:
        self.db = AcsDatabase()
        self.db.import_pgn_text(_PGN, source_name="library.pgn")
        self.search = GameSearchService(self.db)
        self.game_id = self.search.search(GameSearchQuery()).items[0].game_id
        self.service = LibraryExportService(self.db, search_service=self.search)

    def tearDown(self) -> None:
        self.db.close()

    def _delegate(self, dialogs, events, fallbacks):
        def fallback(action_id, payload):
            fallbacks.append((action_id, dict(payload)))
            return ("fallback", action_id)

        return Version2WindowsLibraryExportDelegate(
            dialogs=dialogs,
            service=self.service,
            event_sink=events.append,
            next_delegate=fallback,
            current_focus_provider=lambda: "library-results",
        )

    def test_browser_cannot_supply_arbitrary_destination_and_dialog_never_opens(self) -> None:
        dialogs = _Dialogs(Path("should-not-be-used.pgn"))
        events: list[object] = []
        fallbacks: list[object] = []
        delegate = self._delegate(dialogs, events, fallbacks)

        event = delegate(
            "library.export",
            {
                "scope": "selected",
                "game_ids": [self.game_id],
                "path": r"C:\Users\Private\stolen.pgn",
            },
        )

        self.assertEqual(event.kind, LibraryExportHostEventKind.FAILED)
        self.assertEqual(event.error_code, "invalid_export_request")
        self.assertEqual(event.focus_target, "library-results")
        self.assertEqual(dialogs.calls, [])
        self.assertEqual(fallbacks, [])
        self.assertNotIn("path", repr(event).lower())
        self.assertNotIn("users", repr(event).lower())

    def test_native_save_dialog_cancel_restores_focus_and_writes_nothing(self) -> None:
        dialogs = _Dialogs(None)
        events: list[object] = []
        delegate = self._delegate(dialogs, events, [])

        event = delegate(
            "library.export",
            LibraryExportRequest.selected([self.game_id]).browser_payload(),
        )

        self.assertEqual(event.kind, LibraryExportHostEventKind.DIALOG_CANCELLED)
        self.assertEqual(event.focus_target, "library-results")
        self.assertEqual(dialogs.calls, ["library-export.pgn"])
        self.assertEqual(events, [event])

    def test_selected_library_export_uses_host_path_atomic_writer_and_reopens(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            destination = Path(directory) / "chosen-by-native-dialog.pgn"
            dialogs = _Dialogs(destination)
            events: list[object] = []
            delegate = self._delegate(dialogs, events, [])

            event = delegate(
                "library.export",
                LibraryExportRequest.selected([self.game_id]).browser_payload(),
            )
            reopened = open_pgn(destination)

        self.assertEqual(event.kind, LibraryExportHostEventKind.EXPORTED)
        self.assertEqual(event.game_count, 1)
        self.assertEqual(event.focus_target, "library-results")
        self.assertEqual(reopened.games, self.service.resolve_games(LibraryExportRequest.selected([self.game_id])))
        self.assertEqual(dialogs.calls, ["library-export.pgn"])
        self.assertEqual(events, [event])
        self.assertNotIn(str(destination), repr(event))

    def test_dialog_and_writer_failures_are_path_free_and_do_not_mutate_library(self) -> None:
        before = tuple(
            tuple(row)
            for row in self.db.conn.execute("SELECT id, pgn_text FROM games ORDER BY id").fetchall()
        )
        events: list[object] = []
        dialog_event = self._delegate(_ExplodingDialogs(None), events, [])(
            "library.export",
            LibraryExportRequest.selected([self.game_id]).browser_payload(),
        )
        self.assertEqual(dialog_event.error_code, "file_dialog_failed")

        with tempfile.TemporaryDirectory() as directory:
            unwritable = Path(directory) / "parent-is-file"
            unwritable.write_text("occupied", encoding="utf-8")
            writer_event = self._delegate(_Dialogs(unwritable / "out.pgn"), events, [])(
                "library.export",
                LibraryExportRequest.selected([self.game_id]).browser_payload(),
            )
        self.assertEqual(writer_event.kind, LibraryExportHostEventKind.FAILED)
        self.assertEqual(writer_event.error_code, "library_export_failed")
        self.assertNotIn("parent-is-file", repr(writer_event))
        after = tuple(
            tuple(row)
            for row in self.db.conn.execute("SELECT id, pgn_text FROM games ORDER BY id").fetchall()
        )
        self.assertEqual(after, before)

    def test_unrelated_action_chains_exactly_once(self) -> None:
        fallbacks: list[object] = []
        delegate = self._delegate(_Dialogs(None), [], fallbacks)
        result = delegate("analysis.restart", {"source": "library"})
        self.assertEqual(result, ("fallback", "analysis.restart"))
        self.assertEqual(fallbacks, [("analysis.restart", {"source": "library"})])


if __name__ == "__main__":
    unittest.main()
