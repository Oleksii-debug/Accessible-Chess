from __future__ import annotations

import tempfile
from pathlib import Path
import unittest
from unittest.mock import patch

from acs.acsdb import AcsDatabase
from acs.library_import_service import LibraryImportService
import acs.version2_windows_file_workflows as file_workflows
from acs.version2_windows_file_workflows import (
    FileWorkflowEventKind,
    Version2ImportWorkerServices,
    Version2WindowsFileActionDelegate,
)


PGN_TEXT = """[Event \"Streaming host evidence\"]
[Site \"?\"]
[Date \"2026.09.07\"]
[Round \"1\"]
[White \"White\"]
[Black \"Black\"]
[Result \"*\"]

1. e4 e5 2. Nf3 Nc6 *
"""

PGN_TEXT_TWO = PGN_TEXT + "\n" + PGN_TEXT.replace(
    "Streaming host evidence", "Streaming host evidence 2"
)


class _Dialogs:
    def __init__(self, import_path: Path) -> None:
        self.import_path = import_path

    def open_pgn(self):
        raise AssertionError("unexpected native PGN-open dialog")

    def save_pgn_as(self, suggested_filename: str = "game.pgn"):
        raise AssertionError("unexpected native PGN-save dialog")

    def select_library_import(self) -> Path:
        return self.import_path


class Version2WindowsPgnStreamingHostEvidenceTests(unittest.TestCase):
    """RED-first evidence for the real Windows Library Import composition.

    The D06 streaming importer already exists, while the current V2 Windows
    host still routes Library Import of a PGN through whole-document
    ``open_pgn`` before publishing games to LibraryImportService.  The Windows
    host must consume the bounded streaming ingress for Library Import without
    changing the ordinary user PGN-open workflow.
    """

    def test_library_import_pgn_does_not_use_whole_document_open_pgn(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = root / "private-large-source.pgn"
            database_path = root / "library.acsdb"
            source.write_text(PGN_TEXT_TWO, encoding="utf-8")
            events = []

            def services_factory() -> Version2ImportWorkerServices:
                database = AcsDatabase(database_path)
                return Version2ImportWorkerServices(
                    LibraryImportService(database),
                    None,
                    database.close,
                )

            controller = Version2WindowsFileActionDelegate(
                dialogs=_Dialogs(source),
                get_pgn_session=lambda: None,
                set_pgn_session=lambda value: None,
                import_services_factory=services_factory,
                event_sink=events.append,
                next_delegate=lambda action_id, payload: None,
                current_focus_provider=lambda: "library-import-file",
            )

            # This sentinel is intentionally scoped across the worker lifetime.
            # pgn.open may continue to use open_pgn; library.import must not.
            with patch.object(
                file_workflows,
                "open_pgn",
                side_effect=AssertionError(
                    "Library Import bypassed bounded StreamingPgnLibraryImporter"
                ),
            ):
                started = controller("library.import", {})
                self.assertEqual(started.kind, FileWorkflowEventKind.IMPORT_STARTED)
                self.assertTrue(controller.wait_for_import(10.0))

            self.assertTrue(events, "the background import must publish terminal evidence")
            self.assertEqual(
                events[-1].kind,
                FileWorkflowEventKind.IMPORT_COMPLETED,
                "PGN Library Import must complete without the whole-document open_pgn path",
            )
            self.assertEqual(events[-1].game_count, 2)

            with AcsDatabase(database_path) as database:
                game_count = database.conn.execute(
                    "SELECT COUNT(*) FROM games"
                ).fetchone()[0]
                attempts = database.conn.execute(
                    "SELECT status, game_count FROM import_attempts ORDER BY id"
                ).fetchall()

            self.assertEqual(game_count, 2)
            self.assertEqual(
                [(row[0], row[1]) for row in attempts],
                [("full", 2)],
                "the streaming host path must retain canonical atomic Library publication",
            )

            for event in events:
                rendered = repr(event)
                self.assertNotIn(str(source), rendered)
                self.assertNotIn("private-large-source", rendered)
                self.assertNotIn(str(database_path), rendered)


if __name__ == "__main__":
    unittest.main()
