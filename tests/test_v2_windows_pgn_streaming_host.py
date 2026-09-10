from __future__ import annotations

from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from acs.library_import_service import LibraryImportProgress, LibraryImportResult
from acs.version2_windows_file_workflows import (
    FileWorkflowEventKind,
    Version2ImportWorkerServices,
)
from acs.version2_windows_pgn_streaming_host import (
    Version2WindowsStreamingFileActionDelegate,
)


PGN_ONE = '''[Event "First"]
[Site "?"]
[Date "2026.09.07"]
[Round "1"]
[White "White"]
[Black "Black"]
[Result "*"]

1. e4 e5 *
'''

PGN_TWO = PGN_ONE + "\n" + PGN_ONE.replace('"First"', '"Second"')

GOOD_PREFIX_THEN_TRUNCATED = '''[Event "Accepted"]
[Result "*"]

1. e4 e5 *

[Event "Broken"]
[Result "*"]

1. d4 {unterminated
'''


class _Dialogs:
    def __init__(self, source: Path) -> None:
        self.source = source

    def open_pgn(self):
        raise AssertionError("PGN document open is not part of Library import")

    def save_pgn_as(self, suggested_filename="game.pgn"):
        raise AssertionError("PGN save is not part of Library import")

    def select_library_import(self):
        return self.source


class _StructuralLibraryPort:
    """Observer-compatible Library port; deliberately not LibraryImportService."""

    def __init__(self) -> None:
        self.calls = 0
        self.game_counts: list[int] = []
        self.source_names: list[str] = []

    def import_games(self, games, **kwargs):
        self.calls += 1
        count = len(games)
        self.game_counts.append(count)
        self.source_names.append(kwargs["source_name"])
        progress = kwargs["progress_callback"]
        progress(LibraryImportProgress(31, 0, count))
        progress(LibraryImportProgress(31, count, count))
        return LibraryImportResult(31, 41, count, kwargs["source_warning_count"], 1, count)


class Version2WindowsPgnStreamingHostTests(unittest.TestCase):
    def _controller(self, source: Path, library: object):
        events = []
        closed = []

        def factory():
            return Version2ImportWorkerServices(
                library,
                None,
                lambda: closed.append(True),
            )

        controller = Version2WindowsStreamingFileActionDelegate(
            dialogs=_Dialogs(source),
            get_pgn_session=lambda: None,
            set_pgn_session=lambda session: None,
            import_services_factory=factory,
            event_sink=events.append,
            next_delegate=lambda action, payload: None,
            current_focus_provider=lambda: "library-search-player",
        )
        return controller, events, closed

    def test_windows_library_import_uses_streaming_path_not_whole_document_open(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "private-large-source.pgn"
            source.write_text(PGN_TWO, encoding="utf-8", newline="")
            library = _StructuralLibraryPort()
            controller, events, closed = self._controller(source, library)

            # The historical host called open_pgn() before Library publication.
            # The current large-PGN journey must remain successful even when that
            # whole-document entry point is impossible to call.
            with patch(
                "acs.version2_windows_file_workflows.open_pgn",
                side_effect=AssertionError("whole-document PGN path must not run"),
            ):
                started = controller("library.import", {})
                self.assertEqual(started.kind, FileWorkflowEventKind.IMPORT_STARTED)
                self.assertTrue(controller.wait_for_import(10.0))

            self.assertEqual(library.calls, 1)
            self.assertEqual(library.game_counts, [2])
            self.assertEqual(closed, [True])
            kinds = [event.kind for event in events]
            self.assertIn(FileWorkflowEventKind.IMPORT_PROGRESS, kinds)
            self.assertEqual(kinds[-1], FileWorkflowEventKind.IMPORT_COMPLETED)
            self.assertEqual(events[-1].game_count, 2)
            self.assertEqual(events[-1].total_games, 2)
            self.assertEqual(events[-1].focus_target, "library-import-file")
            for event in events:
                rendered = repr(event)
                self.assertNotIn(str(source), rendered)
                self.assertNotIn("private-large-source", rendered)

    def test_later_truncated_game_is_source_atomic_in_real_host(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "private-truncated-source.pgn"
            source.write_text(GOOD_PREFIX_THEN_TRUNCATED, encoding="utf-8", newline="")
            library = _StructuralLibraryPort()
            controller, events, closed = self._controller(source, library)

            controller("library.import", {})
            self.assertTrue(controller.wait_for_import(10.0))

            self.assertEqual(library.calls, 0)
            self.assertEqual(closed, [True])
            self.assertEqual(events[-1].kind, FileWorkflowEventKind.FAILED)
            self.assertEqual(events[-1].error_code, "pgn_import_failed")
            self.assertEqual(events[-1].focus_target, "library-import-file")
            self.assertNotIn(FileWorkflowEventKind.IMPORT_COMPLETED, [event.kind for event in events])
            self.assertNotIn(str(source), repr(events[-1]))
            self.assertNotIn("private-truncated-source", repr(events[-1]))

    def test_zero_byte_pgn_preserves_empty_source_terminal_state(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "private-empty-source.pgn"
            source.write_bytes(b"")
            library = _StructuralLibraryPort()
            controller, events, closed = self._controller(source, library)

            controller("library.import", {})
            self.assertTrue(controller.wait_for_import(5.0))

            self.assertEqual(library.calls, 0)
            self.assertEqual(closed, [True])
            self.assertEqual(events[-1].kind, FileWorkflowEventKind.IMPORT_EMPTY)
            self.assertEqual(events[-1].focus_target, "library-import-file")


if __name__ == "__main__":
    unittest.main()
