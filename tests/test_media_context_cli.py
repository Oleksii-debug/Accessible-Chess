from contextlib import redirect_stdout, redirect_stderr
from io import StringIO
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from acs.media_context_cli import main


class ContextCliTests(unittest.TestCase):
    def test_unicode_path_default_runs_without_network_or_model(self):
        with TemporaryDirectory(prefix='Шахи ') as directory:
            path = Path(directory) / 'Мій урок.srt'
            raw = '1\n00:00:01,000 --> 00:00:03,000\nГраємо e4.\n'.encode()
            path.write_bytes(raw)
            output = StringIO()
            with redirect_stdout(output), patch('socket.create_connection', side_effect=AssertionError('offline only')):
                result = main([str(path), '--at-ms', '1500', '--json'])
            self.assertEqual(result, 0)
            report = json.loads(output.getvalue())
            self.assertEqual(report['segments'][0]['text'], 'Граємо e4.')
            self.assertNotIn(directory, output.getvalue())
            self.assertEqual(path.read_bytes(), raw)

    def test_missing_file_has_ukrainian_path_free_error(self):
        output = StringIO()
        with redirect_stderr(output):
            result = main(['/private/missing.srt', '--at-ms', '0'])
        self.assertEqual(result, 2)
        self.assertIn('Не вдалося', output.getvalue())
        self.assertNotIn('/private', output.getvalue())


if __name__ == '__main__':
    unittest.main()
