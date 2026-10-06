from hashlib import sha256
from pathlib import Path
import tempfile
import threading
import unittest
from unittest.mock import patch

from acs.acsdb import AcsDatabase
from acs.book_library_import import open_book_library_source
from acs.book_library_game_lookup import AcsdbBookGameLookup
from acs.import_contract import read_source_snapshot, SourceReadCancelledError
from acs.library_import_service import LibraryImportService, LibraryImportCancelledError
from acs.library_export_service import LibraryExportService, LibraryExportRequest
from acs.pgn_service import open_pgn
from acs.version2_windows_file_workflows import (
    FileWorkflowEventKind, Version2ImportWorkerServices, Version2WindowsFileActionDelegate,
)
from test_book_html_pgn_loss_accounting import html_book, epub_book


PGN = '[Event "Книга"]\n[White "Олексій"]\n[Black "Émile"]\n1. e4 {Main} (1. d4 $1) e5 *\n\n[Event "Second"]\n1. Nf3 *'


class BookLibraryImportJourneyTests(unittest.TestCase):
    def test_html_and_epub_import_into_real_library_without_source_mutation(self):
        with tempfile.TemporaryDirectory() as directory:
            for suffix, raw in (('.html', html_book(PGN).encode()), ('.epub', epub_book(html_book(PGN)))):
                with self.subTest(suffix=suffix):
                    source = Path(directory) / ('book' + suffix)
                    source.write_bytes(raw)
                    opened = open_book_library_source(source)
                    self.assertEqual(opened.source.sha256, sha256(raw).hexdigest())
                    self.assertEqual([game.source_index for game in opened.games], [0, 1])
                    self.assertTrue(any('games only' in warning for warning in opened.warnings))
                    with AcsDatabase() as database:
                        service = LibraryImportService(database)
                        kwargs = dict(source_name=source.name, source_format=suffix[1:],
                                      source_sha256=opened.source.sha256,
                                      source_warning_count=len(opened.warnings))
                        first = service.import_games(opened.games, **kwargs)
                        self.assertEqual(first.game_count, 2)
                        self.assertGreater(first.warning_count, 0)
                        found = database.search_games(player='Олексій')
                        self.assertEqual(len(found), 1)
                        self.assertEqual(AcsdbBookGameLookup(database).load_book_game(first.first_game_id).line.moves[0].variations[0].moves[0].san, 'd4')
                        second = service.import_games(opened.games, **kwargs)
                        self.assertTrue(second.reused)
                        self.assertEqual(second.source_id, first.source_id)
                        exported_path = Path(directory) / ('export-' + suffix[1:] + '.pgn')
                        exported = LibraryExportService(database).export_to(
                            exported_path, LibraryExportRequest.selected([first.first_game_id, first.last_game_id]),
                        )
                        self.assertEqual(exported.game_count, 2)
                        reopened = open_pgn(exported_path)
                        self.assertEqual(len(reopened.games), 2)
                        self.assertEqual(reopened.games[0].tags['White'], 'Олексій')
                        self.assertEqual(reopened.games[0].line.moves[0].comments_after[0].text, 'Main')
                        self.assertEqual(reopened.games[0].line.moves[0].variations[0].moves[0].nags, ['$1'])
                    self.assertEqual(source.read_bytes(), raw)

    def test_cancelled_atomic_library_import_publishes_no_games(self):
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / 'book.html'
            source.write_text(html_book(PGN), encoding='utf-8')
            opened = open_book_library_source(source)
            with AcsDatabase() as database:
                cancelled = threading.Event()
                with self.assertRaises(LibraryImportCancelledError):
                    LibraryImportService(database).import_games(
                        opened.games, source_name=source.name, source_format='html',
                        source_sha256=opened.source.sha256,
                        cancel_check=cancelled.is_set,
                        progress_callback=lambda progress: cancelled.set() if progress.processed_games == 1 else None,
                    )
                self.assertEqual(database.search_games(), [])

    def test_native_library_command_reaches_book_import_on_background_worker(self):
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / 'book.epub'
            source.write_bytes(epub_book(html_book(PGN)))
            database_path = Path(directory) / 'library.acsdb'
            terminal = threading.Event()
            events = []
            worker_thread_ids = []

            class Dialogs:
                def open_pgn(self): return None
                def save_pgn_as(self, *args): return None
                def select_library_import(self): return source

            def services():
                worker_thread_ids.append(threading.get_ident())
                db = AcsDatabase(database_path)
                return Version2ImportWorkerServices(LibraryImportService(db), None, db.close)

            def observe(event):
                events.append(event)
                if event.kind in {FileWorkflowEventKind.IMPORT_COMPLETED, FileWorkflowEventKind.FAILED}:
                    terminal.set()

            delegate = Version2WindowsFileActionDelegate(
                dialogs=Dialogs(), get_pgn_session=lambda: None, set_pgn_session=lambda session: None,
                import_services_factory=services, event_sink=observe,
                next_delegate=lambda action, payload: self.fail('book import must use Library command'),
            )
            delegate('library.import', {})
            self.assertTrue(terminal.wait(5), 'background import did not finish')
            self.assertTrue(delegate.wait_for_import(5), 'background cleanup did not finish')
            self.assertNotEqual(worker_thread_ids, [threading.get_ident()])
            completed = [event for event in events if event.kind is FileWorkflowEventKind.IMPORT_COMPLETED]
            self.assertEqual(len(completed), 1)
            self.assertEqual(completed[0].game_count, 2)
            self.assertGreater(completed[0].warning_count, 0)
            with AcsDatabase(database_path) as database:
                self.assertEqual(len(database.search_games()), 2)

    def test_book_without_games_returns_empty_with_reading_content_warning(self):
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / 'prose.html'
            source.write_text('<html><body><p>Read me.</p></body></html>', encoding='utf-8')
            opened = open_book_library_source(source)
            self.assertEqual(opened.games, ())
            self.assertTrue(any('Open Book' in warning for warning in opened.warnings))

    def test_source_snapshot_bounds_and_cancel_before_open(self):
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / 'source.bin'
            source.write_bytes(b'12345')
            self.assertEqual(read_source_snapshot(source, max_bytes=5)[1], b'12345')
            with self.assertRaises(ValueError):
                read_source_snapshot(source, max_bytes=4)
            with patch('acs.import_contract._open_readonly_no_reparse', side_effect=AssertionError('must not open')):
                with self.assertRaises(SourceReadCancelledError):
                    read_source_snapshot(source, max_bytes=5, cancel_check=lambda: True)

    def test_same_size_source_mutation_cannot_publish_mixed_snapshot(self):
        import os
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / 'source.bin'
            source.write_bytes(b'12345')
            original_read = os.read
            touched = False

            def racing_read(descriptor, limit):
                nonlocal touched
                result = original_read(descriptor, limit)
                if result and not touched:
                    touched = True
                    source.write_bytes(b'54321')
                return result

            with patch('acs.import_contract.os.read', side_effect=racing_read):
                with self.assertRaisesRegex(ValueError, 'changed'):
                    read_source_snapshot(source, max_bytes=5)

    def test_read_cancellation_is_polled_after_open_and_closes_handle(self):
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / 'source.bin'
            source.write_bytes(b'12345')
            checks = 0

            def cancel():
                nonlocal checks
                checks += 1
                return checks >= 3

            with self.assertRaises(SourceReadCancelledError):
                read_source_snapshot(source, max_bytes=5, cancel_check=cancel)
            source.unlink()  # Windows also verifies no lingering read handle.

    def test_malformed_book_never_creates_durable_library_rows(self):
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / 'invalid.html'
            source.write_text('<html><body><p>Text</p><div data-acs-fen="bad"></div></body></html>', encoding='utf-8')
            with AcsDatabase() as database:
                with self.assertRaises(ValueError):
                    open_book_library_source(source)
                self.assertEqual(database.search_games(), [])


if __name__ == '__main__':
    unittest.main()
