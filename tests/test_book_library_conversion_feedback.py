import unittest
import threading
from unittest.mock import patch
import test_version2_application as application_fixture

from acs.chesscore import Board
from acs.full_product_ui_shell import UILanguage
from acs.version2_windows_file_workflows import FileWorkflowEvent, FileWorkflowEventKind


class BookLibraryConversionFeedbackTests(unittest.TestCase):
    setUp = application_fixture.Version2ApplicationTests.setUp

    def import_source(self, suffix, text):
        self.source = self.root / ('private-study' + suffix)
        self.source.write_text(text, encoding='utf-8')
        original = self.source.read_bytes()
        self.assertNotEqual(self.app.browser_command('library', 'library.import')['kind'], 'error')
        self.assertTrue(self.files.wait_for_import(5))
        self.app.import_ui_ready(self.mailbox)
        self.assertEqual(self.source.read_bytes(), original)
        return self.app.snapshot()['library']['import']

    def test_markdown_game_only_conversion_reports_retained_semantic_blocks(self):
        snapshot = self.import_source('.md', '# Lesson\n\nNarrative prose.\n\n```fen\n' + Board.START + '\n```\n\n```pgn\n[Event "Study"]\n[Result "*"]\n\n1. e4 e5 *\n```\n')
        self.assertEqual(snapshot['phase'], 'completed')
        self.assertEqual(snapshot['processed_games'], 1)
        self.assertIn('Джерело: MD', snapshot['progress_label'])
        self.assertIn('блоків книги: 3', snapshot['progress_label'])
        self.assertIn('«Відкрити книгу»', snapshot['progress_label'])
        self.assertNotIn(str(self.root), snapshot['progress_label'])
        self.assertNotIn('private-study', snapshot['progress_label'])

    def test_empty_book_reports_source_warnings_and_preserves_retry(self):
        snapshot = self.import_source('.md', '# Lesson\n\nNarrative only.\n')
        self.assertEqual(snapshot['phase'], 'empty')
        self.assertEqual(snapshot['processed_games'], 0)
        self.assertIn('Попереджень: 1', snapshot['progress_label'])
        self.assertIn('блоків книги: 2', snapshot['progress_label'])
        self.source = self.root / 'next.pgn'
        self.source.write_text('[Result "*"]\n\n1. e4 *', encoding='utf-8')
        self.app.browser_command('library', 'library.import')
        self.assertTrue(self.files.wait_for_import(5))
        self.app.import_ui_ready(self.mailbox)
        retried = self.app.snapshot()['library']['import']
        self.assertEqual(retried['phase'], 'completed')
        self.assertNotIn('блоків книги', retried['progress_label'])

    def test_html_conversion_report_uses_english_ui_labels(self):
        self.app.library.projection.set_language(UILanguage.EN)
        snapshot = self.import_source('.html', '<html><body><h1>Lesson</h1><p>Prose</p><pre>{PGN 1}\n[Event "Study"]\n[Result "*"]\n\n1. e4 *</pre></body></html>')
        self.assertEqual(snapshot['phase'], 'completed')
        self.assertIn('Source: HTML', snapshot['progress_label'])
        self.assertIn('Other book blocks: 2', snapshot['progress_label'])
        self.assertIn('Open Book', snapshot['progress_label'])

    def test_report_fields_reject_paths_and_non_integer_counts(self):
        for kwargs in ({'source_format': 'C:/private/source.epub'}, {'retained_book_blocks': True}, {'retained_book_blocks': -1}):
            with self.assertRaises((TypeError, ValueError)):
                FileWorkflowEvent(FileWorkflowEventKind.IMPORT_COMPLETED, 'library.import', **kwargs)

    def test_report_precedes_observed_commit_when_terminal_host_event_is_late(self):
        self.source = self.root / 'book.md'
        self.source.write_text('# Lesson\n\nProse.\n\n```pgn\n1. e4 *\n```', encoding='utf-8')
        held = threading.Event()
        release = threading.Event()
        emit = self.files._emit_if_current
        def delay_completion(generation, event):
            if event.kind is FileWorkflowEventKind.IMPORT_COMPLETED:
                held.set()
                if not release.wait(5):
                    raise RuntimeError('test terminal event release timed out')
            return emit(generation, event)
        with patch.object(self.files, '_emit_if_current', side_effect=delay_completion):
            try:
                self.app.browser_command('library', 'library.import')
                self.assertTrue(held.wait(5))
                self.app.import_ui_ready(self.mailbox)
                completed = self.app.snapshot()['library']['import']
                self.assertEqual(completed['phase'], 'completed')
                self.assertIn('блоків книги: 2', completed['progress_label'])
            finally:
                release.set()
                self.assertTrue(self.files.wait_for_import(5))
        self.app.import_ui_ready(self.mailbox)
        self.assertEqual(self.app.snapshot()['library']['import'], completed)
