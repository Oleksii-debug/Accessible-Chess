from types import SimpleNamespace
import unittest
from unittest.mock import patch
import test_version2_application as application_fixture

from acs.full_product_ui_shell import UILanguage
from acs.version2_windows_file_workflows import FileWorkflowEvent, FileWorkflowEventKind


class NativeFormatFailureFeedbackTests(unittest.TestCase):
    setUp = application_fixture.Version2ApplicationTests.setUp

    def test_blocked_extensions_report_supported_operations_without_launching_decoder(self):
        for suffix in ('.cbf', '.cbi', '.2cbh', '.cbone'):
            self.source = self.root / ('private-file' + suffix)
            self.source.write_bytes(b'unverified source')
            before = self.database.conn.total_changes
            self.app.drain_events()
            with patch.object(self.files, '_import_services_factory', side_effect=AssertionError('unsupported source must not create a worker')):
                self.app.browser_command('library', 'library.import')
            errors = [event['payload']['message'] for event in self.app.drain_events() if event['kind'] == 'error']
            self.assertEqual(len(errors), 1)
            self.assertIn('Інші формати не можна імпортувати', errors[0])
            self.assertIn('PGN', errors[0])
            self.assertNotIn('private-file', errors[0])
            self.assertEqual(self.database.conn.total_changes, before)

    def test_async_decoder_failure_is_localized_and_retryable(self):
        self.app.library.projection.set_language(UILanguage.EN)
        self.app.library.projection.import_projection.prepare()
        event = FileWorkflowEvent(FileWorkflowEventKind.FAILED, 'library.import', error_code='chessbase_backend_unavailable')
        self.app.import_ui_ready(SimpleNamespace(drain=lambda: (event,)))
        snapshot = self.app.snapshot()['library']['import']
        self.assertEqual(snapshot['phase'], 'error')
        self.assertIn('configured supported decoder', snapshot['progress_label'])
        self.assertTrue(snapshot['actions'][0]['enabled'])

    def test_unknown_or_private_error_codes_never_reach_user_messages(self):
        for code in ('C:/private/source.pgn', 'secret provider failure', 'x' * 10000):
            event = FileWorkflowEvent(FileWorkflowEventKind.FAILED, 'library.import', error_code=code)
            message = self.app._native_file_error_message(event)
            self.assertEqual(message, 'Не вдалося виконати дію.')

    def test_unavailable_book_source_does_not_report_a_pgn_failure(self):
        self.source = self.root / 'missing-private-book.md'
        self.app.browser_command('library', 'library.import')
        self.assertTrue(self.files.wait_for_import(5))
        self.app.import_ui_ready(self.mailbox)
        snapshot = self.app.snapshot()['library']['import']
        self.assertEqual(snapshot['phase'], 'error')
        self.assertIn('джерело книги', snapshot['progress_label'])
        self.assertNotIn('PGN', snapshot['progress_label'])
        self.assertNotIn('missing-private-book', snapshot['progress_label'])
        self.assertIsNone(self.database.get_game(1))
