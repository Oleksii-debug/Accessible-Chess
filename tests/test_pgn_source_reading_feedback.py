import unittest
from types import SimpleNamespace

from acs.full_product_ui_shell import UILanguage
from acs.library_import_service import LibraryImportProgress
from acs.library_webview_projection import LibraryImportWebViewProjection
from acs.version2_application import Version2Application
from acs.version2_windows_file_workflows import FileWorkflowEvent, FileWorkflowEventKind
import test_version2_application as application_fixture


class SourceReadingProjectionTests(unittest.TestCase):
    def test_reading_is_not_published_games_and_announces_only_phase_entry(self):
        for language, phrase in ((UILanguage.EN, 'Reading PGN'), (UILanguage.UA, 'Читання PGN')):
            ui = LibraryImportWebViewProjection(lambda *_: None, language=language)
            ui.prepare()
            first = ui.source_reading(20, 100, 2)
            self.assertIn(phrase, first.payload['announcement'])
            self.assertEqual(ui.snapshot()['processed_games'], 0)
            self.assertEqual(ui.snapshot()['total_games'], 0)
            later = ui.source_reading(90, 100, 8)
            self.assertEqual(later.payload['announcement'], '')
            self.assertEqual(later.payload['focus_target'], '')
            ui.source_reading(0, 100, 0)  # qualified encoding retry
            ui.begin(8)
            ui.progress(LibraryImportProgress(1, 3, 8))
            self.assertNotIn(phrase, ui.snapshot()['progress_label'])
            self.assertEqual(ui.snapshot()['processed_games'], 3)

    def test_cancel_and_invalid_counters_do_not_replace_reading_state(self):
        ui = LibraryImportWebViewProjection(lambda *_: None)
        ui.prepare()
        ui.source_reading(20, 100, 2)
        before = ui.snapshot()
        for values in ((True, 100, 2), (101, 100, 2), (20, 101, 2), (20, 100, 2**53)):
            with self.assertRaises(ValueError):
                ui.source_reading(*values)
            self.assertEqual(before, ui.snapshot())
        ui.host_cancelling()
        with self.assertRaises(RuntimeError):
            ui.source_reading(30, 100, 3)
        self.assertEqual(ui.snapshot()['phase'], 'cancelling')


class ApplicationSourceReadingTests(unittest.TestCase):
    setUp = application_fixture.Version2ApplicationTests.setUp
    def test_mailbox_reading_progress_reaches_real_application_without_fake_import(self):
        ui = self.app.library.projection.import_projection
        ui.prepare()
        event = FileWorkflowEvent(FileWorkflowEventKind.IMPORT_PROGRESS, 'library.import',
                                  processed_games=4, source_parsing=True,
                                  source_bytes_read=500, source_total_bytes=1000)
        self.app.import_ui_ready(SimpleNamespace(drain=lambda: (event,)))
        snapshot = self.app.snapshot()['library']['import']
        self.assertIn('500', snapshot['progress_label'])
        self.assertIn('1000', snapshot['progress_label'])
        self.assertEqual(snapshot['processed_games'], 0)
        self.assertEqual(snapshot['total_games'], 0)
        ui.host_cancelling()
        before = ui.snapshot()
        self.app.import_ui_ready(SimpleNamespace(drain=lambda: (event,)))
        self.assertEqual(ui.snapshot(), before)
