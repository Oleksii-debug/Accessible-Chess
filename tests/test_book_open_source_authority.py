from pathlib import Path
from types import SimpleNamespace
import os
import tempfile
import unittest
from unittest.mock import patch

from acs.acsdb import AcsDatabase
from acs.analysis_service import AnalysisService
from acs.book_progress_store import BookProgressStore
from acs.chesscore import Board
from acs.engine_assisted_workflows import EngineAssistedWorkflowService
from acs.import_contract import read_source_snapshot
from acs.version2_application import Version2Application
from test_book_html_pgn_loss_accounting import html_book, epub_book


class BookOpenSourceAuthorityTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.database = AcsDatabase(self.root / 'library.acsdb')
        self.addCleanup(self.database.close)
        self.analysis = AnalysisService(lambda: None)
        self.addCleanup(self.analysis.close)
        self.progress = BookProgressStore(self.root / 'progress.json')
        self.app = self.application()

    def application(self):
        return Version2Application(self.database, progress_store=self.progress,
            engine_assistance=EngineAssistedWorkflowService(self.analysis),
            board_dispatch=lambda *_: None, board_position_projector=lambda fen: {'ok': True})

    def source(self, name, raw):
        path = self.root / name
        path.write_bytes(raw)
        return path

    def stable_book(self):
        self.app.open_book(self.source('stable.txt', b'Stable source.\n\nSecond paragraph.'))
        self.app.reader.go_to(1)
        self.app.save_book_progress()
        return (self.app.reader, self.app.reader.snapshot(), self.app.book_key,
                self.app.shell.current_route.route_id, (self.root / 'progress.json').read_bytes())

    def assert_unchanged(self, before):
        reader, snapshot, key, route, durable = before
        self.assertIs(self.app.reader, reader)
        self.assertEqual(self.app.reader.snapshot(), snapshot)
        self.assertEqual(self.app.book_key, key)
        self.assertEqual(self.app.shell.current_route.route_id, route)
        self.assertEqual((self.root / 'progress.json').read_bytes(), durable)

    def test_supported_books_use_stable_bytes_and_resume_after_restart(self):
        markup = html_book('1. e4 e5 *')
        for suffix, raw in (('.epub', epub_book(markup)), ('.HTML', markup.encode()),
                            ('.txt', b'First paragraph.\n\nSecond paragraph.'),
                            ('.md', b'# Lesson\n\nReading text.\n\n```pgn\n1. e4 e5 *\n```')):
            with self.subTest(suffix=suffix):
                source = self.source('study' + suffix, raw)
                with patch('acs.version2_application.read_source_snapshot', wraps=read_source_snapshot) as reader:
                    self.app.open_book(source)
                reader.assert_called_once()
                self.app.reader.go_to(len(self.app.reader.document.blocks) - 1)
                self.app.save_book_progress()
                origin = self.app.reader.snapshot()
                restarted = self.application()
                restarted.open_book(source)
                self.assertEqual(restarted.reader.snapshot(), origin)
                self.assertEqual(source.read_bytes(), raw)

    def test_same_size_mutation_cannot_publish_a_mixed_book_or_progress(self):
        before = self.stable_book()
        raw = html_book('1. e4 *').encode()
        source = self.source('changing.html', raw)
        original_read = os.read
        original_stat = source.stat()
        changed = False

        def mutate(descriptor, size):
            nonlocal changed
            chunk = original_read(descriptor, size)
            if chunk and not changed:
                changed = True
                source.write_bytes(raw.replace(b'Before', b'After!'))
                os.utime(source, ns=(original_stat.st_atime_ns, original_stat.st_mtime_ns))
            return chunk

        with patch('acs.import_contract.os.read', side_effect=mutate):
            with self.assertRaisesRegex(ValueError, 'source changed'):
                self.app.open_book(source)
        self.assertTrue(changed)
        self.assert_unchanged(before)
        source.unlink()  # held Windows source handle was released on rejection

    def test_reparse_source_is_rejected_before_read_and_keeps_active_book(self):
        before = self.stable_book()
        source = self.source('redirect.txt', b'Redirected source')
        original_lstat = Path.lstat

        def marked(path, *args, **kwargs):
            value = original_lstat(path, *args, **kwargs)
            if path == source:
                return SimpleNamespace(st_mode=value.st_mode, st_file_attributes=0x400)
            return value

        with patch.object(Path, 'lstat', marked), patch('acs.import_contract._open_readonly_no_reparse') as opened:
            with self.assertRaises(ValueError):
                self.app.open_book(source)
        opened.assert_not_called()
        self.assert_unchanged(before)

    def test_oversized_source_is_rejected_before_read_and_keeps_active_book(self):
        before = self.stable_book()
        source = self.source('large.txt', b'x' * 17)
        with patch('acs.version2_application.MAX_TEXT_SOURCE_BYTES', 16), patch('acs.import_contract._open_readonly_no_reparse') as opened:
            with self.assertRaises(ValueError):
                self.app.open_book(source)
        opened.assert_not_called()
        self.assert_unchanged(before)

    def test_markdown_game_uses_board_authority_and_returns_to_exact_book_location(self):
        source = self.source('board.md', b'# Lesson\n\nBefore.\n\n```pgn\n1. e4 (1. d4 d5 (1... Nf6)) e5 *\n```\n\nAfter.')
        self.app.open_book(source)
        token = self.app.snapshot()['books']['presentation_token']
        selected = self.app.browser_command('books', 'book.next_game', {'presentation_token': token})
        self.assertEqual(selected['kind'], 'render')
        self.app.save_book_progress()
        origin = self.app.reader.snapshot()
        projected = []
        self.app._board_position_projector = lambda fen: projected.append(fen) or {'ok': True}
        token = self.app.snapshot()['books']['presentation_token']
        self.assertEqual(self.app.browser_command('books', 'book.open_game', {'presentation_token': token})['kind'], 'delegated')
        self.assertEqual(projected[-1], Board.START)
        moved = self.app.browser_command('review', 'book.board_next_move')
        self.assertEqual(moved['kind'], 'review', moved)
        board = Board(Board.START)
        board.push(board.parse_move('e4'))
        self.assertEqual(projected[-1], board.fen())
        self.assertEqual(self.app.browser_command('review', 'book.board_enter_variation')['kind'], 'review')
        self.assertEqual(projected[-1], Board.START)
        self.assertEqual(self.app.browser_command('review', 'book.board_next_move')['kind'], 'review')
        side = Board(Board.START)
        side.push(side.parse_move('d4'))
        self.assertEqual(projected[-1], side.fen())
        self.assertEqual(self.app.browser_command('review', 'book.board_leave_variation')['kind'], 'review')
        self.assertEqual(projected[-1], board.fen())
        token = self.app.snapshot()['books']['presentation_token']
        self.assertEqual(self.app.browser_command('books', 'book.return_from_board', {'presentation_token': token})['kind'], 'render')
        self.assertEqual(self.app.reader.snapshot(), origin)

    def test_hidden_review_return_cannot_unwind_book_board_owner(self):
        for route in ('books', 'library', 'settings'):
            with self.subTest(route=route):
                source = self.source('review-' + route + '.md', b'```pgn\n1. e4 *\n```')
                self.app.open_book(source)
                self.assertEqual(self.app.browser_command('books', 'book.open_game')['kind'], 'delegated')
                self.assertTrue(self.app.book_workflow.active)
                self.app.browser_command('shell', 'screen.' + route)
                origin = self.app.reader.snapshot()
                rejected = self.app.browser_command('review', 'book.return')
                self.assertEqual(rejected['kind'], 'error')
                self.assertTrue(self.app.book_workflow.active)
                self.assertEqual(self.app.reader.snapshot(), origin)
                self.assertEqual(self.app.shell.current_route.route_id, route)
                self.app.browser_command('shell', 'screen.board')
                self.assertEqual(self.app.browser_command('review', 'book.return')['kind'], 'review')
                self.assertFalse(self.app.book_workflow.active)
                self.assertEqual(self.app.shell.current_route.route_id, 'books')


if __name__ == '__main__':
    unittest.main()
