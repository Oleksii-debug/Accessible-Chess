from __future__ import annotations

import tempfile
from pathlib import Path
import unittest

from acs.chessbase_library_import import (
    ChessBaseLibraryImportReport,
    ChessBaseLibraryImportStatus,
)
from acs.library_import_service import LibraryImportProgress, LibraryImportResult
from acs.version2_windows_file_workflows import (
    FileWorkflowEventKind,
    Version2ImportWorkerServices,
    Version2WindowsFileActionDelegate,
)


PGN_TWO = """[Event "Trace 1"]
[Site "?"]
[Date "2026.10.06"]
[Round "1"]
[White "White"]
[Black "Black"]
[Result "*"]

1. e4 e5 *

[Event "Trace 2"]
[Site "?"]
[Date "2026.10.06"]
[Round "2"]
[White "White"]
[Black "Black"]
[Result "*"]

1. d4 d5 *
"""


class _Dialogs:
    def __init__(self, import_path: Path) -> None:
        self.import_path = import_path

    def open_pgn(self):
        return None

    def save_pgn_as(self, suggested_filename: str = "game.pgn"):
        return None

    def select_library_import(self):
        return self.import_path


class _UnusedLibrary:
    def import_games(self, *args, **kwargs):
        raise AssertionError("unexpected PGN Library import")


class Version2WindowsImportProgressCoherenceTests(unittest.TestCase):
    def _controller(self, path: Path, services_factory):
        events = []
        controller = Version2WindowsFileActionDelegate(
            dialogs=_Dialogs(path),
            get_pgn_session=lambda: None,
            set_pgn_session=lambda value: None,
            import_services_factory=services_factory,
            event_sink=events.append,
            next_delegate=lambda action_id, payload: None,
        )
        return controller, events

    def _run_pgn_library(self, library) -> list:
        with tempfile.TemporaryDirectory() as tmp:
            source = Path(tmp) / "trace.pgn"
            source.write_text(PGN_TWO, encoding="utf-8")
            controller, events = self._controller(
                source,
                lambda: Version2ImportWorkerServices(
                    library,
                    None,
                    lambda: None,
                ),
            )
            controller("library.import", {})
            self.assertTrue(controller.wait_for_import(5.0))
            self.assertFalse(controller.import_running)
            return events

    def test_valid_new_import_trace_completes(self) -> None:
        class Library:
            def import_games(self, *_args, **kwargs):
                progress = kwargs["progress_callback"]
                progress(LibraryImportProgress(11, 0, 2))
                progress(LibraryImportProgress(11, 1, 2))
                progress(LibraryImportProgress(11, 2, 2))
                return LibraryImportResult(11, 7, 2, 0, 101, 102)

        events = self._run_pgn_library(Library())

        self.assertEqual(events[-1].kind, FileWorkflowEventKind.IMPORT_COMPLETED)
        self.assertEqual(events[-1].game_count, 2)
        self.assertEqual(events[-1].processed_games, 2)
        self.assertEqual(events[-1].total_games, 2)

    def test_valid_reused_import_trace_completes_from_zero_progress(self) -> None:
        class Library:
            def import_games(self, *_args, **kwargs):
                kwargs["progress_callback"](LibraryImportProgress(12, 0, 2))
                return LibraryImportResult(12, 8, 2, 0, 201, 202, reused=True)

        events = self._run_pgn_library(Library())

        self.assertEqual(events[-1].kind, FileWorkflowEventKind.IMPORT_COMPLETED)
        self.assertEqual(events[-1].game_count, 2)

    def test_progress_must_start_at_zero(self) -> None:
        class Library:
            def import_games(self, *_args, **kwargs):
                kwargs["progress_callback"](LibraryImportProgress(21, 1, 2))
                return LibraryImportResult(21, 9, 2, 0, 301, 302)

        events = self._run_pgn_library(Library())

        self.assertEqual(events[-1].kind, FileWorkflowEventKind.FAILED)
        self.assertEqual(events[-1].error_code, "library_import_failed")
        self.assertNotIn(FileWorkflowEventKind.IMPORT_COMPLETED, [e.kind for e in events])

    def test_progress_attempt_id_cannot_change(self) -> None:
        class Library:
            def import_games(self, *_args, **kwargs):
                progress = kwargs["progress_callback"]
                progress(LibraryImportProgress(31, 0, 2))
                progress(LibraryImportProgress(32, 1, 2))
                return LibraryImportResult(31, 10, 2, 0, 401, 402)

        events = self._run_pgn_library(Library())

        self.assertEqual(events[-1].kind, FileWorkflowEventKind.FAILED)
        self.assertEqual(events[-1].error_code, "library_import_failed")

    def test_progress_total_cannot_change(self) -> None:
        class Library:
            def import_games(self, *_args, **kwargs):
                progress = kwargs["progress_callback"]
                progress(LibraryImportProgress(41, 0, 2))
                progress(LibraryImportProgress(41, 1, 3))
                return LibraryImportResult(41, 11, 2, 0, 501, 502)

        events = self._run_pgn_library(Library())

        self.assertEqual(events[-1].kind, FileWorkflowEventKind.FAILED)
        self.assertEqual(events[-1].error_code, "library_import_failed")

    def test_progress_must_be_strictly_increasing(self) -> None:
        class Library:
            def import_games(self, *_args, **kwargs):
                progress = kwargs["progress_callback"]
                progress(LibraryImportProgress(51, 0, 2))
                progress(LibraryImportProgress(51, 1, 2))
                progress(LibraryImportProgress(51, 1, 2))
                return LibraryImportResult(51, 12, 2, 0, 601, 602)

        events = self._run_pgn_library(Library())

        self.assertEqual(events[-1].kind, FileWorkflowEventKind.FAILED)
        self.assertEqual(events[-1].error_code, "library_import_failed")

    def test_result_attempt_must_match_progress_trace(self) -> None:
        class Library:
            def import_games(self, *_args, **kwargs):
                progress = kwargs["progress_callback"]
                progress(LibraryImportProgress(61, 0, 2))
                progress(LibraryImportProgress(61, 1, 2))
                progress(LibraryImportProgress(61, 2, 2))
                return LibraryImportResult(62, 13, 2, 0, 701, 702)

        events = self._run_pgn_library(Library())

        self.assertEqual(events[-1].kind, FileWorkflowEventKind.FAILED)
        self.assertEqual(events[-1].error_code, "library_import_failed")

    def test_result_game_count_must_match_progress_total(self) -> None:
        class Library:
            def import_games(self, *_args, **kwargs):
                progress = kwargs["progress_callback"]
                progress(LibraryImportProgress(71, 0, 2))
                progress(LibraryImportProgress(71, 1, 2))
                progress(LibraryImportProgress(71, 2, 2))
                return LibraryImportResult(71, 14, 1, 0, 801, 801)

        events = self._run_pgn_library(Library())

        self.assertEqual(events[-1].kind, FileWorkflowEventKind.FAILED)
        self.assertEqual(events[-1].error_code, "library_import_failed")

    def test_non_reused_result_requires_completed_progress(self) -> None:
        class Library:
            def import_games(self, *_args, **kwargs):
                progress = kwargs["progress_callback"]
                progress(LibraryImportProgress(81, 0, 2))
                progress(LibraryImportProgress(81, 1, 2))
                return LibraryImportResult(81, 15, 2, 0, 901, 902)

        events = self._run_pgn_library(Library())

        self.assertEqual(events[-1].kind, FileWorkflowEventKind.FAILED)
        self.assertEqual(events[-1].error_code, "library_import_failed")

    def test_reused_result_rejects_staged_progress(self) -> None:
        class Library:
            def import_games(self, *_args, **kwargs):
                progress = kwargs["progress_callback"]
                progress(LibraryImportProgress(91, 0, 2))
                progress(LibraryImportProgress(91, 1, 2))
                progress(LibraryImportProgress(91, 2, 2))
                return LibraryImportResult(91, 16, 2, 0, 1001, 1002, reused=True)

        events = self._run_pgn_library(Library())

        self.assertEqual(events[-1].kind, FileWorkflowEventKind.FAILED)
        self.assertEqual(events[-1].error_code, "library_import_failed")

    def test_result_without_progress_trace_fails_closed(self) -> None:
        class Library:
            def import_games(self, *_args, **_kwargs):
                return LibraryImportResult(101, 17, 2, 0, 1101, 1102)

        events = self._run_pgn_library(Library())

        self.assertEqual(events[-1].kind, FileWorkflowEventKind.FAILED)
        self.assertEqual(events[-1].error_code, "library_import_failed")

    def test_active_progress_scalar_is_rejected_without_hooks(self) -> None:
        touched = []

        class ActiveInt(int):
            def __lt__(self, other):
                touched.append("lt")
                raise AssertionError("active progress scalar hook executed")

            def __gt__(self, other):
                touched.append("gt")
                raise AssertionError("active progress scalar hook executed")

        hostile = LibraryImportProgress(111, 0, 2)
        object.__setattr__(hostile, "total_games", ActiveInt(2))

        class Library:
            def import_games(self, *_args, **kwargs):
                kwargs["progress_callback"](hostile)
                return LibraryImportResult(111, 18, 2, 0, 1201, 1202)

        events = self._run_pgn_library(Library())

        self.assertEqual(touched, [])
        self.assertEqual(events[-1].kind, FileWorkflowEventKind.FAILED)
        self.assertEqual(events[-1].error_code, "library_import_failed")

    def test_chessbase_valid_trace_completes(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            source = Path(tmp) / "trace.cbh"
            source.write_bytes(b"fixture")
            events = []

            class ChessBase:
                def import_database(self, _path, **kwargs):
                    progress = kwargs["progress_callback"]
                    progress(LibraryImportProgress(121, 0, 2))
                    progress(LibraryImportProgress(121, 1, 2))
                    progress(LibraryImportProgress(121, 2, 2))
                    return ChessBaseLibraryImportReport(
                        status=ChessBaseLibraryImportStatus.IMPORTED,
                        source_name="trace.cbh",
                        source_sha256="a" * 64,
                        backend_name="test-backend",
                        backend_commit="b" * 40,
                        decoded_game_count=2,
                        warnings=(),
                        library_result=LibraryImportResult(
                            121, 19, 2, 0, 1301, 1302
                        ),
                    )

            controller, events = self._controller(
                source,
                lambda: Version2ImportWorkerServices(
                    _UnusedLibrary(),
                    ChessBase(),
                    lambda: None,
                ),
            )
            controller("library.import", {})
            self.assertTrue(controller.wait_for_import(5.0))

            self.assertEqual(events[-1].kind, FileWorkflowEventKind.IMPORT_COMPLETED)
            self.assertEqual(events[-1].game_count, 2)

    def test_chessbase_result_attempt_mismatch_fails_path_free(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            source = Path(tmp) / "private-trace.cbh"
            source.write_bytes(b"fixture")

            class ChessBase:
                def import_database(self, _path, **kwargs):
                    progress = kwargs["progress_callback"]
                    progress(LibraryImportProgress(131, 0, 2))
                    progress(LibraryImportProgress(131, 1, 2))
                    progress(LibraryImportProgress(131, 2, 2))
                    return ChessBaseLibraryImportReport(
                        status=ChessBaseLibraryImportStatus.IMPORTED,
                        source_name="private-trace.cbh",
                        source_sha256="c" * 64,
                        backend_name="test-backend",
                        backend_commit="d" * 40,
                        decoded_game_count=2,
                        warnings=(),
                        library_result=LibraryImportResult(
                            132, 20, 2, 0, 1401, 1402
                        ),
                    )

            controller, events = self._controller(
                source,
                lambda: Version2ImportWorkerServices(
                    _UnusedLibrary(),
                    ChessBase(),
                    lambda: None,
                ),
            )
            controller("library.import", {})
            self.assertTrue(controller.wait_for_import(5.0))

            self.assertEqual(events[-1].kind, FileWorkflowEventKind.FAILED)
            self.assertEqual(events[-1].error_code, "chessbase_import_failed")
            self.assertNotIn(str(source), repr(events[-1]))

    def test_chessbase_no_games_needs_no_progress_trace(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            source = Path(tmp) / "empty.cbh"
            source.write_bytes(b"fixture")

            class ChessBase:
                def import_database(self, _path, **_kwargs):
                    return ChessBaseLibraryImportReport(
                        status=ChessBaseLibraryImportStatus.NO_GAMES,
                        source_name="empty.cbh",
                        source_sha256="e" * 64,
                        backend_name="test-backend",
                        backend_commit="f" * 40,
                        decoded_game_count=0,
                        warnings=(),
                        library_result=None,
                    )

            controller, events = self._controller(
                source,
                lambda: Version2ImportWorkerServices(
                    _UnusedLibrary(),
                    ChessBase(),
                    lambda: None,
                ),
            )
            controller("library.import", {})
            self.assertTrue(controller.wait_for_import(5.0))

            self.assertEqual(events[-1].kind, FileWorkflowEventKind.IMPORT_EMPTY)
            self.assertNotIn(FileWorkflowEventKind.FAILED, [e.kind for e in events])


if __name__ == "__main__":
    unittest.main()
