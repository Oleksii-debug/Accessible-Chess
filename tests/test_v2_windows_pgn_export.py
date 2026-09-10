from __future__ import annotations

from pathlib import Path
import tempfile
import unittest

from acs.full_product_actions import FullProductActionRouter, build_full_product_action_registry
from acs.full_product_ui_shell import AccessibleShellState
from acs.pgn_service import open_pgn, save_pgn_atomic
from acs.pgn_workspace import PgnWorkspace
from acs.pgn_workspace_webview_adapter import PgnWorkspaceWebViewProjection
from acs.version2_windows_pgn_export import (
    PgnSelectionExportEventKind,
    PgnSelectionExportRequest,
    Version2WindowsPgnExportDelegate,
)


_SAMPLE_PGN = """[Event "Host export"]
[Site "Local"]
[Date "2026.08.28"]
[Round "1"]
[White "Alpha"]
[Black "Beta"]
[Result "*"]

1. e4 e5 2. Nf3 (2. Bc4 Nf6) *
"""


class _ExportDialogs:
    def __init__(self, destination: Path | None) -> None:
        self.destination = destination
        self.calls: list[str] = []

    def export_selection(self, suggested_filename: str) -> Path | None:
        self.calls.append(suggested_filename)
        return self.destination


class Version2WindowsPgnExportTests(unittest.TestCase):
    @staticmethod
    def _valid_payload() -> dict[str, object]:
        return {
            "game_index": 0,
            "line_path": (),
            "move_index": 0,
            "expected_record_digest": "a" * 64,
            "content_revision": 0,
        }

    def test_request_rejects_browser_path_or_unknown_authority_fields(self) -> None:
        payload = self._valid_payload()
        payload["destination"] = r"C:\\Users\\person\\private.pgn"
        with self.assertRaises(ValueError):
            PgnSelectionExportRequest.from_payload(payload)

    def test_request_requires_an_actual_selected_tree_item(self) -> None:
        payload = self._valid_payload()
        payload["move_index"] = None
        with self.assertRaises(ValueError):
            PgnSelectionExportRequest.from_payload(payload)

        payload["line_path"] = ((1, 0),)
        request = PgnSelectionExportRequest.from_payload(payload)
        self.assertIsNone(request.move_index)
        self.assertEqual(request.line_path, ((1, 0),))

    def test_dialog_cancel_restores_prior_focus_without_exporting(self) -> None:
        exported: list[object] = []
        events = []
        delegate = Version2WindowsPgnExportDelegate(
            dialogs=_ExportDialogs(None),
            export_selected=lambda request, destination: exported.append((request, destination)),
            event_sink=events.append,
            next_delegate=lambda action_id, payload: None,
            current_focus_provider=lambda: "pgn-node-current",
        )

        event = delegate("pgn.export_selection", self._valid_payload())

        self.assertEqual(event.kind, PgnSelectionExportEventKind.DIALOG_CANCELLED)
        self.assertEqual(event.focus_target, "pgn-node-current")
        self.assertEqual(exported, [])
        self.assertEqual(events, [event])

    def test_invalid_target_fails_before_native_dialog(self) -> None:
        dialogs = _ExportDialogs(Path("ignored.pgn"))
        exported: list[object] = []
        payload = self._valid_payload()
        payload["path"] = "/home/person/private.pgn"
        delegate = Version2WindowsPgnExportDelegate(
            dialogs=dialogs,
            export_selected=lambda request, destination: exported.append((request, destination)),
            event_sink=lambda event: None,
            next_delegate=lambda action_id, action_payload: None,
        )

        event = delegate("pgn.export_selection", payload)

        self.assertEqual(event.kind, PgnSelectionExportEventKind.FAILED)
        self.assertEqual(event.error_code, "invalid_export_target")
        self.assertEqual(dialogs.calls, [])
        self.assertEqual(exported, [])
        self.assertNotIn("private.pgn", repr(event))

    def test_exporter_failure_is_sanitized_and_does_not_project_destination(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            destination = Path(directory) / "private-name.pgn"
            events = []

            def fail_export(request: PgnSelectionExportRequest, path: Path) -> None:
                raise RuntimeError(f"backend failed at {path}")

            delegate = Version2WindowsPgnExportDelegate(
                dialogs=_ExportDialogs(destination),
                export_selected=fail_export,
                event_sink=events.append,
                next_delegate=lambda action_id, payload: None,
                current_focus_provider=lambda: "pgn-toolbar-export",
            )
            event = delegate("pgn.export_selection", self._valid_payload())

            self.assertEqual(event.kind, PgnSelectionExportEventKind.FAILED)
            self.assertEqual(event.error_code, "pgn_export_failed")
            self.assertEqual(event.focus_target, "pgn-toolbar-export")
            self.assertNotIn(str(destination), repr(event))
            self.assertEqual(events, [event])

    def test_unowned_action_passes_through_without_dialog(self) -> None:
        dialogs = _ExportDialogs(Path("unused.pgn"))
        seen = []
        delegate = Version2WindowsPgnExportDelegate(
            dialogs=dialogs,
            export_selected=lambda request, destination: None,
            event_sink=lambda event: None,
            next_delegate=lambda action_id, payload: seen.append((action_id, payload)) or "next",
        )

        result = delegate("library.search", {"player": "Kasparov"})

        self.assertEqual(result, "next")
        self.assertEqual(seen, [("library.search", {"player": "Kasparov"})])
        self.assertEqual(dialogs.calls, [])

    def test_real_pgn_projection_enriches_target_then_host_exports_and_reopens(self) -> None:
        workspace = PgnWorkspace.from_text(_SAMPLE_PGN)
        workspace.next_move()
        events = []

        with tempfile.TemporaryDirectory() as directory:
            destination = Path(directory) / "selected.pgn"
            dialogs = _ExportDialogs(destination)
            owner_requests: list[PgnSelectionExportRequest] = []

            def canonical_owner(
                request: PgnSelectionExportRequest,
                host_destination: Path,
            ) -> dict[str, str]:
                view = workspace.view()
                self.assertEqual(request.game_index, view.selected_game_index)
                self.assertEqual(request.content_revision, view.content_revision)
                self.assertEqual(request.expected_record_digest, view.current_record_digest)
                self.assertEqual(request.line_path, ())
                self.assertEqual(request.move_index, 0)
                self.assertEqual(host_destination, destination)
                owner_requests.append(request)
                save_pgn_atomic(host_destination, (workspace.games()[request.game_index],))
                # Trusted backend returns are deliberately not projected by the host.
                return {"private_path": str(host_destination)}

            delegate = Version2WindowsPgnExportDelegate(
                dialogs=dialogs,
                export_selected=canonical_owner,
                event_sink=events.append,
                next_delegate=lambda action_id, payload: (_ for _ in ()).throw(
                    AssertionError(f"unexpected delegated action: {action_id}")
                ),
                current_focus_provider=lambda: "pgn-node-current",
            )
            shell = AccessibleShellState(initial_route="pgn")
            router = FullProductActionRouter(
                shell,
                delegate,
                registry=build_full_product_action_registry(),
            )
            projection = PgnWorkspaceWebViewProjection(workspace, router)

            render_event = projection.export_selection()

            self.assertEqual(render_event.kind, "selection")
            self.assertEqual(len(owner_requests), 1)
            self.assertEqual(dialogs.calls, ["selection.pgn"])
            self.assertEqual(events[-1].kind, PgnSelectionExportEventKind.EXPORTED)
            self.assertEqual(events[-1].focus_target, "pgn-node-current")
            self.assertNotIn(str(destination), repr(events[-1]))
            reopened = open_pgn(destination)
            self.assertEqual(reopened.total_games, 1)
            self.assertEqual(reopened.games[0], workspace.games()[0])


if __name__ == "__main__":
    unittest.main()
