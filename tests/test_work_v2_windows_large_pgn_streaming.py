from __future__ import annotations

from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from acs.acsdb import AcsDatabase
from acs.library_import_service import LibraryImportService
import acs.version2_windows_file_workflows as workflows
from acs.version2_windows_file_workflows import (
    FileWorkflowEventKind,
    Version2ImportWorkerServices,
    Version2WindowsFileActionDelegate,
)


PGN = '''[Event "One"]
[White "Alpha"]
[Black "Beta"]
[Result "*"]

1. e4 e5 *

[Event "Two"]
[White "Gamma"]
[Black "Delta"]
[Result "*"]

1. d4 d5 *
'''


class _Dialogs:
    def __init__(self, source: Path) -> None:
        self.source = source

    def open_pgn(self):
        return None

    def save_pgn_as(self, *_args):
        return None

    def select_library_import(self):
        return self.source


class Version2WindowsLargePgnStreamingEvidenceTests(unittest.TestCase):
    def test_library_pgn_import_does_not_reenter_whole_document_open_pgn(self) -> None:
        """The real Windows Library path must consume canonical streaming ingress.

        ``open_pgn`` is the bounded whole-document document-editor ingress. Large
        Library import has a separate canonical ``StreamingPgnLibraryImporter``
        so the host must not materialize the complete source before publication.
        This test deliberately poisons the whole-document call while leaving the
        real canonical Library service and worker-thread database composition in
        place. A correct host-streaming integration still imports both games.
        """

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "two-games.pgn"
            database_path = root / "library.acsdb"
            source.write_text(PGN, encoding="utf-8", newline="")
            events = []

            def services_factory() -> Version2ImportWorkerServices:
                database = AcsDatabase(database_path)
                return Version2ImportWorkerServices(
                    LibraryImportService(database),
                    None,
                    database.close,
                )

            delegate = Version2WindowsFileActionDelegate(
                dialogs=_Dialogs(source),
                get_pgn_session=lambda: None,
                set_pgn_session=lambda _session: None,
                import_services_factory=services_factory,
                event_sink=events.append,
                next_delegate=lambda *_args: None,
            )

            def forbidden_whole_document_ingress(*_args, **_kwargs):
                raise AssertionError(
                    "Library PGN import re-entered whole-document open_pgn instead of streaming ingress"
                )

            with patch.object(workflows, "open_pgn", side_effect=forbidden_whole_document_ingress):
                started = delegate("library.import", {})
                self.assertEqual(started.kind, FileWorkflowEventKind.IMPORT_STARTED)
                self.assertTrue(delegate.wait_for_import(10))

            self.assertTrue(events)
            self.assertEqual(
                events[-1].kind,
                FileWorkflowEventKind.IMPORT_COMPLETED,
                msg=f"terminal Library import event was {events[-1]!r}",
            )
            self.assertEqual(events[-1].game_count, 2)

            with AcsDatabase(database_path) as database:
                rows = database.search_games(limit=10)
                self.assertEqual(len(rows), 2)
                self.assertEqual({row["white"] for row in rows}, {"Alpha", "Gamma"})


if __name__ == "__main__":
    unittest.main()
