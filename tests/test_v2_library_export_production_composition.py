from __future__ import annotations

from pathlib import Path
import tempfile
import unittest

from acs.acsdb import AcsDatabase
from acs.library_export_service import LibraryExportRequest, LibraryExportService
from acs.pgn_service import open_pgn
from acs.version2_windows_library_export import (
    LibraryExportHostEventKind,
    build_version2_windows_library_file_runtime,
)


_PGN = """[Event "Native Library export"]
[White "Олексій"]
[Black "Test"]
[Result "*"]

1. e4 e5 *
"""


class _DialogResult:
    OK = "ok"


class _OpenDialog:
    def __init__(self) -> None:
        self.FileName = ""

    def ShowDialog(self, owner):  # noqa: N802
        return _DialogResult.OK

    def Dispose(self):  # noqa: N802
        return None


class _SaveDialog:
    destination: Path | None = None
    owners: list[object] = []

    def __init__(self) -> None:
        self.FileName = ""

    def ShowDialog(self, owner):  # noqa: N802
        type(self).owners.append(owner)
        if type(self).destination is not None:
            self.FileName = str(type(self).destination)
        return _DialogResult.OK

    def Dispose(self):  # noqa: N802
        return None


def _forms_loader():
    return _DialogResult, _OpenDialog, _SaveDialog


class _Owner:
    def __init__(self) -> None:
        self.IsDisposed = False
        self.Disposing = False
        self.InvokeRequired = False
        self.posted: list[object] = []

    def BeginInvoke(self, delegate):  # noqa: N802
        self.posted.append(delegate)
        return len(self.posted)


class LibraryExportProductionCompositionTests(unittest.TestCase):
    def setUp(self) -> None:
        _SaveDialog.destination = None
        _SaveDialog.owners.clear()

    def test_current_builder_routes_canonical_request_to_owner_bound_native_destination(self) -> None:
        database = AcsDatabase()
        self.addCleanup(database.close)
        report = database.import_pgn_text(_PGN, source_name="lawful-library.pgn")
        game_id = report.game_ids[0]
        service = LibraryExportService(database)
        owner = _Owner()
        events: list[object] = []
        fallbacks: list[object] = []

        with tempfile.TemporaryDirectory() as directory:
            destination = Path(directory) / "експорт ♞.pgn"
            _SaveDialog.destination = destination
            runtime = build_version2_windows_library_file_runtime(
                owner_control=owner,
                library_service=service,
                library_export_event_sink=events.append,
                get_pgn_session=lambda: None,
                set_pgn_session=lambda _session: None,
                import_services_factory=lambda: None,
                export_selected=lambda _request, _destination: None,
                import_ui_ready=lambda _mailbox: None,
                pgn_export_event_sink=lambda _event: None,
                next_delegate=lambda action_id, payload: fallbacks.append(
                    (action_id, dict(payload))
                ),
                current_focus_provider=lambda: "library-results",
                ui_delegate_factory=lambda callback: callback,
                file_forms_loader=_forms_loader,
                export_forms_loader=_forms_loader,
            )
            try:
                event = runtime(
                    "library.export",
                    LibraryExportRequest.selected([game_id]).browser_payload(),
                )
            finally:
                self.assertTrue(runtime.shutdown())

            reopened = open_pgn(destination)

        self.assertEqual(event.kind, LibraryExportHostEventKind.EXPORTED)
        self.assertEqual(event.game_count, 1)
        self.assertEqual(event.focus_target, "library-results")
        self.assertEqual(events, [event])
        self.assertEqual(fallbacks, [])
        self.assertEqual(_SaveDialog.owners, [owner])
        self.assertEqual(reopened.games[0].tags["Event"], "Native Library export")
        self.assertNotIn(str(destination), repr(event))


if __name__ == "__main__":
    unittest.main()
