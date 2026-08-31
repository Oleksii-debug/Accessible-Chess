from __future__ import annotations

from pathlib import Path
import tempfile
import unittest

from acs.acsdb import AcsDatabase
from acs.full_product_ui_shell import UILanguage
from acs.library_export_service import LibraryExportRequest, LibraryExportService
from acs.library_export_workspace import build_library_export_webview
from acs.pgn_service import open_pgn
from acs.search_service import GameSearchQuery, GameSearchService
from acs.version2_windows_library_export import (
    LibraryExportHostEventKind,
    Version2WindowsLibraryExportDelegate,
)


_PGN = '''[Event "Reachability"]
[Site "Ужгород"]
[Date "2026.08.31"]
[Round "1"]
[White "Альфа"]
[Black "Beta"]
[Result "1-0"]
[ECO "C20"]

1. e4 $1 {main comment} e5 (1... c5 {RAV}) 2. Nf3 Nc6 1-0

[Event "Reachability"]
[Site "Košice"]
[Date "2026.08.31"]
[Round "2"]
[White "Gamma"]
[Black "Éva"]
[Result "*"]
[SetUp "1"]
[FEN "8/8/8/8/8/8/4K3/6k1 w - - 0 1"]

1. Kf3 *

[Event "Other"]
[Site "Kyiv"]
[Date "2026.08.31"]
[Round "3"]
[White "Delta"]
[Black "Epsilon"]
[Result "*"]

1. d4 d5 *
'''


class _Dialog:
    def __init__(self, destination: Path) -> None:
        self.destination = destination
        self.calls: list[str] = []

    def export_selection(self, suggested_filename: str) -> Path:
        self.calls.append(suggested_filename)
        return self.destination


class LibraryExportReachabilityTests(unittest.TestCase):
    def test_search_selection_to_trusted_dialog_atomic_file_and_reopen(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            db = AcsDatabase()
            try:
                db.import_pgn_text(_PGN, source_name="lawful-fixture.pgn")
                search = GameSearchService(db)
                all_ids = tuple(item.game_id for item in search.search(GameSearchQuery(limit=20)).items)
                service = LibraryExportService(db, search_service=search)
                selected_path = Path(directory) / "native-selected.pgn"
                dialogs = _Dialog(selected_path)
                events: list[object] = []
                fallback: list[object] = []
                delegate = Version2WindowsLibraryExportDelegate(
                    dialogs=dialogs,
                    service=service,
                    event_sink=events.append,
                    next_delegate=lambda action, payload: fallback.append((action, dict(payload))),
                    current_focus_provider=lambda: "library-game-focus",
                )
                bridge = build_library_export_webview(
                    db,
                    delegate,
                    language=UILanguage.EN,
                )

                searched = bridge.dispatch("library.search", {"event": "Reachability", "limit": 25})
                rows = searched.payload["snapshot"]["rows"]
                self.assertEqual(len(rows), 2)
                # Select in reverse click order; service still writes canonical id order.
                bridge.dispatch("library.toggle_export_selection", {"game_id": rows[1]["game_id"]})
                bridge.dispatch("library.toggle_export_selection", {"game_id": rows[0]["game_id"]})
                delegated = bridge.dispatch("library.export_selected", {})

                self.assertEqual(delegated.kind, "delegated")
                self.assertTrue(selected_path.is_file())
                self.assertEqual(dialogs.calls, ["library-export.pgn"])
                self.assertEqual(events[-1].kind, LibraryExportHostEventKind.EXPORTED)
                self.assertEqual(events[-1].game_count, 2)
                self.assertEqual(events[-1].focus_target, "library-game-focus")
                expected = service.resolve_games(
                    LibraryExportRequest.selected([rows[1]["game_id"], rows[0]["game_id"]])
                )
                self.assertEqual(open_pgn(selected_path).games, expected)
                self.assertEqual(expected[0].line.moves[0].nags, ["$1"])
                self.assertTrue(expected[0].line.moves[0].variations)
                self.assertEqual(expected[1].tags["SetUp"], "1")
                self.assertEqual(fallback, [])

                filtered_path = Path(directory) / "native-filtered.pgn"
                dialogs.destination = filtered_path
                bridge.dispatch("library.export_filtered", {})
                filtered = open_pgn(filtered_path)
                self.assertEqual(len(filtered.games), 2)
                self.assertEqual(
                    filtered.games,
                    service.resolve_games(
                        LibraryExportRequest.filtered(GameSearchQuery(event="Reachability"))
                    ),
                )
                self.assertEqual(dialogs.calls, ["library-export.pgn", "library-export.pgn"])
                self.assertNotIn(str(selected_path), repr(events))
                self.assertNotIn(str(filtered_path), repr(events))
                self.assertEqual(all_ids[:2], tuple(row["game_id"] for row in rows))
            finally:
                db.close()


if __name__ == "__main__":
    unittest.main()
