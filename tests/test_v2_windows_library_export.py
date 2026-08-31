from __future__ import annotations

from pathlib import Path
import tempfile
import unittest

from acs.acsdb import AcsDatabase
from acs.full_product_actions import FullProductActionRouter, build_full_product_action_registry
from acs.full_product_ui_shell import AccessibleShellState
from acs.library_pgn_export import LibraryPgnExportService
from acs.pgn_service import open_pgn
from acs.version2_windows_library_export import (
    LibraryPgnExportEventKind,
    Version2WindowsLibraryExportDelegate,
)
from acs.version2_windows_save_export_runtime import Version2WindowsSaveExportRuntime


_SAMPLE = """[Event "Library host one"]
[Result "*"]

1. e4 e5 *

[Event "Library host два"]
[Result "*"]

1. d4 d5 *
"""


class _Dialogs:
    def __init__(self, destination: Path | None) -> None:
        self.destination = destination
        self.calls = []

    def export_library(self, suggested_filename: str) -> Path | None:
        self.calls.append(suggested_filename)
        return self.destination


class _DialogResult:
    OK = "ok"


class _OwnedOpenDialog:
    owners = []

    def __init__(self) -> None:
        self.FileName = ""

    def ShowDialog(self, owner):  # noqa: N802
        type(self).owners.append(owner)
        return _DialogResult.OK

    def Dispose(self):  # noqa: N802
        return None


class _OwnedSaveDialog:
    owners = []

    def __init__(self) -> None:
        self.FileName = ""

    def ShowDialog(self, owner):  # noqa: N802
        type(self).owners.append(owner)
        return _DialogResult.OK

    def Dispose(self):  # noqa: N802
        return None


def _forms_loader():
    return _DialogResult, _OwnedOpenDialog, _OwnedSaveDialog


class _Owner:
    def __init__(self) -> None:
        self.IsDisposed = False
        self.Disposing = False
        self.InvokeRequired = False
        self.posted = []

    def BeginInvoke(self, delegate):  # noqa: N802
        self.posted.append(delegate)
        return len(self.posted)


class Version2WindowsLibraryExportTests(unittest.TestCase):
    def _database(self):
        database = AcsDatabase()
        report = database.import_pgn_text(_SAMPLE, source_name="library-host.pgn")
        self.assertEqual(len(report.game_ids), 2)
        return database, tuple(report.game_ids)

    def test_browser_payload_cannot_submit_path_or_game_ids(self) -> None:
        dialogs = _Dialogs(Path("ignored.pgn"))
        exported = []
        events = []
        delegate = Version2WindowsLibraryExportDelegate(
            dialogs=dialogs,
            selection_provider=lambda: (1,),
            export_subset=lambda ids, destination: exported.append((ids, destination)),
            event_sink=events.append,
            next_delegate=lambda action_id, payload: None,
        )

        for payload in (
            {"path": r"C:\Users\person\private.pgn"},
            {"destination": "/home/person/private.pgn"},
            {"game_ids": (1,)},
        ):
            with self.subTest(payload=payload):
                event = delegate("library.export", payload)
                self.assertEqual(event.kind, LibraryPgnExportEventKind.FAILED)
                self.assertEqual(event.error_code, "invalid_export_request")

        self.assertEqual(dialogs.calls, [])
        self.assertEqual(exported, [])
        self.assertNotIn("private.pgn", repr(events))

    def test_cancel_preserves_focus_without_export(self) -> None:
        events = []
        exported = []
        delegate = Version2WindowsLibraryExportDelegate(
            dialogs=_Dialogs(None),
            selection_provider=lambda: (1, 2),
            export_subset=lambda ids, destination: exported.append((ids, destination)),
            event_sink=events.append,
            next_delegate=lambda action_id, payload: None,
            current_focus_provider=lambda: "library-game-current",
        )

        event = delegate("library.export", {})

        self.assertEqual(event.kind, LibraryPgnExportEventKind.DIALOG_CANCELLED)
        self.assertEqual(event.focus_target, "library-game-current")
        self.assertEqual(exported, [])
        self.assertEqual(events, [event])

    def test_canonical_router_to_trusted_host_exports_library_subset_and_reopens(self) -> None:
        database, game_ids = self._database()
        self.addCleanup(database.close)
        service = LibraryPgnExportService(database)
        events = []

        with tempfile.TemporaryDirectory() as raw_dir:
            destination = Path(raw_dir) / "бібліотека ♞.pgn"
            dialogs = _Dialogs(destination)
            delegate = Version2WindowsLibraryExportDelegate(
                dialogs=dialogs,
                selection_provider=lambda: (game_ids[1], game_ids[0]),
                export_subset=service.export_subset,
                event_sink=events.append,
                next_delegate=lambda action_id, payload: (_ for _ in ()).throw(
                    AssertionError(f"unexpected delegated action: {action_id}")
                ),
                current_focus_provider=lambda: "library-game-current",
            )
            router = FullProductActionRouter(
                AccessibleShellState(initial_route="library"),
                delegate,
                registry=build_full_product_action_registry(),
            )

            result = router.dispatch("library.export")
            event = result.value

            self.assertFalse(result.handled_by_shell)
            self.assertEqual(event.kind, LibraryPgnExportEventKind.EXPORTED)
            self.assertEqual(event.game_count, 2)
            self.assertEqual(event.focus_target, "library-game-current")
            self.assertEqual(dialogs.calls, ["library-selection.pgn"])
            self.assertNotIn(str(destination), repr(event))
            reopened = open_pgn(destination)
            self.assertEqual(
                [game.tags["Event"] for game in reopened.games],
                ["Library host два", "Library host one"],
            )

    def test_export_failure_is_path_free_and_focus_stable(self) -> None:
        with tempfile.TemporaryDirectory() as raw_dir:
            destination = Path(raw_dir) / "secret-user-name.pgn"
            events = []

            def fail(ids, path):
                raise RuntimeError(f"backend failed at {path}")

            delegate = Version2WindowsLibraryExportDelegate(
                dialogs=_Dialogs(destination),
                selection_provider=lambda: (1,),
                export_subset=fail,
                event_sink=events.append,
                next_delegate=lambda action_id, payload: None,
                current_focus_provider=lambda: "library-export",
            )
            event = delegate("library.export", {})

            self.assertEqual(event.kind, LibraryPgnExportEventKind.FAILED)
            self.assertEqual(event.error_code, "library_export_failed")
            self.assertEqual(event.focus_target, "library-export")
            self.assertNotIn(str(destination), repr(event))
            self.assertEqual(events, [event])

    def test_composed_windows_runtime_routes_library_export_through_owned_save_dialog(self) -> None:
        _OwnedSaveDialog.owners.clear()
        owner = _Owner()
        export_calls = []
        events = []
        fallbacks = []
        runtime = Version2WindowsSaveExportRuntime(
            owner_control=owner,
            get_pgn_session=lambda: None,
            set_pgn_session=lambda session: None,
            import_services_factory=lambda: None,
            export_selected=lambda request, destination: None,
            import_ui_ready=lambda mailbox: None,
            pgn_export_event_sink=lambda event: None,
            library_selection_provider=lambda: (11, 12),
            library_export_subset=lambda ids, destination: export_calls.append((ids, destination)),
            library_export_event_sink=events.append,
            next_delegate=lambda action_id, payload: fallbacks.append((action_id, dict(payload)))
            or ("fallback", action_id),
            current_focus_provider=lambda: "library-game-current",
            ui_delegate_factory=lambda callback: callback,
            file_forms_loader=_forms_loader,
            export_forms_loader=_forms_loader,
        )
        try:
            event = runtime("library.export", {})
            self.assertEqual(event.kind, LibraryPgnExportEventKind.EXPORTED)
            self.assertEqual(event.focus_target, "library-game-current")
            self.assertEqual(event.game_count, 2)
            self.assertEqual(export_calls, [((11, 12), Path("library-selection.pgn"))])
            self.assertEqual(events, [event])
            self.assertEqual(fallbacks, [])
            self.assertEqual(_OwnedSaveDialog.owners, [owner])
        finally:
            self.assertTrue(runtime.shutdown())

    def test_unowned_actions_chain_without_opening_export_dialog(self) -> None:
        dialogs = _Dialogs(Path("unused.pgn"))
        seen = []
        delegate = Version2WindowsLibraryExportDelegate(
            dialogs=dialogs,
            selection_provider=lambda: (1,),
            export_subset=lambda ids, destination: None,
            event_sink=lambda event: None,
            next_delegate=lambda action_id, payload: seen.append((action_id, payload)) or "next",
        )

        self.assertEqual(delegate("pgn.save", {}), "next")
        self.assertEqual(seen, [("pgn.save", {})])
        self.assertEqual(dialogs.calls, [])


if __name__ == "__main__":
    unittest.main()
