from pathlib import Path
import subprocess
import os
import sys
import tempfile
import threading
import unittest
from unittest.mock import patch
from hashlib import sha256

from acs.acsdb import AcsDatabase
from acs.cbv_extractor import ExternalCbvExtractorConfig
from acs.chessbase_decoder import ExternalChessBaseDecoderConfig
from acs.chessbase_library_import import ChessBaseLibraryImportService
from acs.library_import_service import LibraryImportCancelledError, LibraryImportControlError
from acs.library_import_service import LibraryImportService
from acs.version2_windows_file_workflows import (
    FileWorkflowEventKind, Version2ImportWorkerServices, Version2WindowsFileActionDelegate,
)


class ActiveChessBaseImportCancellationTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.database = AcsDatabase(self.root / 'library.acsdb')
        self.addCleanup(self.database.close)
        self.source = self.root / 'Fixture.cbh'
        self.source.write_bytes(b'immutable header')
        self.companion = self.source.with_suffix('.cbg')
        self.companion.write_bytes(b'immutable moves')
        self.decoder = ExternalChessBaseDecoderConfig(Path(sys.executable), timeout_seconds=30)
        self.processes = []
        self.directories = []
        self.popen = subprocess.Popen

    def spawn(self, command, **kwargs):
        # Run a real bounded child through the actual pipe reader/wait/kill code.
        # This harness is control-path evidence, not a proprietary decoder oracle.
        self.directories.append(Path(kwargs['cwd']))
        if os.name == 'nt':
            self.assertTrue(kwargs['creationflags'] & subprocess.CREATE_NO_WINDOW)
        child = self.popen([sys.executable, '-c', 'import time; time.sleep(30)'], **kwargs)
        self.processes.append(child)
        self.addCleanup(self.reap, child)
        return child

    @staticmethod
    def reap(child):
        if child.poll() is None:
            child.kill()
        child.wait(timeout=5)

    def counts(self):
        return tuple(self.database.conn.execute('SELECT COUNT(*) FROM ' + table).fetchone()[0]
                     for table in ('sources', 'games', 'import_attempts'))

    def assert_preserved(self):
        self.assertEqual((0, 0, 0), self.counts())
        self.assertEqual(b'immutable header', self.source.read_bytes())
        self.assertEqual(b'immutable moves', self.companion.read_bytes())
        for child in self.processes:
            self.assertIsNotNone(child.poll())

    def test_native_cancel_command_interrupts_real_active_backend_and_closes_worker(self):
        ready = threading.Event()
        closed = threading.Event()
        events = []
        source = self.source
        class Dialogs:
            def open_pgn(self): return None
            def save_pgn_as(self, *args): return None
            def select_library_import(self): return source
        def services():
            database = AcsDatabase(self.root / 'library.acsdb')
            def close():
                database.close()
                closed.set()
            return Version2ImportWorkerServices(
                LibraryImportService(database), ChessBaseLibraryImportService(database, self.decoder), close,
            )
        def spawn_notify(command, **kwargs):
            child = self.spawn(command, **kwargs)
            ready.set()
            return child
        delegate = Version2WindowsFileActionDelegate(
            dialogs=Dialogs(), get_pgn_session=lambda: None, set_pgn_session=lambda _: None,
            import_services_factory=services, event_sink=events.append, next_delegate=lambda *_: None,
        )
        with patch('acs.chessbase_decoder.subprocess.Popen', side_effect=spawn_notify):
            delegate('library.import', {})
            self.assertTrue(ready.wait(5))
            delegate('library.cancel_import', {})
            self.assertTrue(delegate.wait_for_import(5))
        self.assertTrue(closed.is_set())
        self.assertEqual(1, sum(event.kind is FileWorkflowEventKind.IMPORT_CANCELLED for event in events))
        self.assertFalse(any(event.kind in {FileWorkflowEventKind.FAILED, FileWorkflowEventKind.IMPORT_COMPLETED} for event in events))
        self.assert_preserved()

    def test_cancel_running_cbh_decoder_reaps_child_before_library_staging(self):
        service = ChessBaseLibraryImportService(self.database, self.decoder)
        with patch('acs.chessbase_decoder.subprocess.Popen', side_effect=self.spawn):
            with self.assertRaises(LibraryImportCancelledError):
                service.import_database(self.source, cancel_check=lambda: bool(self.processes))
        self.assertEqual(1, len(self.processes))
        self.assert_preserved()

    def test_cancel_control_failure_reaps_running_decoder_without_publication(self):
        service = ChessBaseLibraryImportService(self.database, self.decoder)
        def broken_control():
            if self.processes:
                raise OSError('private control failure')
            return False
        with patch('acs.chessbase_decoder.subprocess.Popen', side_effect=self.spawn):
            with self.assertRaises(LibraryImportControlError) as caught:
                service.import_database(self.source, cancel_check=broken_control)
        self.assertNotIn('private', str(caught.exception))
        self.assert_preserved()

    def test_initial_cancel_never_launches_backend(self):
        service = ChessBaseLibraryImportService(self.database, self.decoder)
        with patch('acs.chessbase_decoder.subprocess.Popen') as launch:
            with self.assertRaises(LibraryImportCancelledError):
                service.import_database(self.source, cancel_check=lambda: True)
            launch.assert_not_called()
        self.assert_preserved()

    def test_cancel_cbv_listing_cleans_owned_directory_and_keeps_source(self):
        self.cbv_cancel_journey(cancel_at=1)

    def test_cancel_cbv_extraction_cleans_owned_directory_and_keeps_source(self):
        self.cbv_cancel_journey(cancel_at=2)

    def cbv_cancel_journey(self, *, cancel_at):
        archive = self.root / 'Fixture.cbv'
        archive.write_bytes(b'immutable archive')
        executable = Path(sys.executable)
        extractor = ExternalCbvExtractorConfig(executable, expected_backend_sha256=sha256(executable.read_bytes()).hexdigest(), timeout_seconds=30)
        service = ChessBaseLibraryImportService(self.database, self.decoder, extractor)
        def extract_spawn(command, **kwargs):
            if command[1] == 'list' and cancel_at == 2:
                self.directories.append(Path(kwargs['cwd']))
                child = self.popen([sys.executable, '-c', "print('Fixture.cbh\\nFixture.cbg')"], **kwargs)
                self.processes.append(child)
                self.addCleanup(self.reap, child)
                return child
            return self.spawn(command, **kwargs)
        with patch('acs.cbv_extractor.subprocess.Popen', side_effect=extract_spawn):
            with self.assertRaises(LibraryImportCancelledError):
                service.import_database(archive, cancel_check=lambda: len(self.processes) >= cancel_at)
        self.assertEqual(cancel_at, len(self.processes))
        self.assertTrue(self.directories)
        self.assertTrue(all(not directory.exists() for directory in self.directories))
        self.assertEqual(b'immutable archive', archive.read_bytes())
        self.assert_preserved()


if __name__ == '__main__':
    unittest.main()
