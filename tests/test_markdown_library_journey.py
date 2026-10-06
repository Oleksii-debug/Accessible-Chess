from hashlib import sha256
from pathlib import Path
import tempfile
import threading
import unittest

from acs.acsdb import AcsDatabase
from acs.book_library_import import open_book_library_source
from acs.book_library_game_lookup import AcsdbBookGameLookup
from acs.book_text_import import import_text_book, BookTextFormat, BookTextImportError
from acs.bookdocument import Game, Heading, ListBlock, Note, Position
from acs.chesscore import Board
from acs.gametree_legality import validate_game_legality
from acs.library_import_service import LibraryImportService
from acs.library_export_service import LibraryExportService, LibraryExportRequest
from acs.pgn_service import open_pgn
from acs.version2_windows_file_workflows import (
    FileWorkflowEventKind, Version2ImportWorkerServices, Version2WindowsFileActionDelegate,
)


BLACK_FEN = Board.START.replace(' w ', ' b ').replace('0 1', '0 17')
MARKDOWN = ('# Навчання\n\nПрочитайте пояснення.\n\n- Center\n- Development\n\n'
    '```fen\n' + Board.START + '\n```\n\n'
    '```pgn\n[Event "Урок"]\n[Date "2026.10.05"]\n[White "Олексій"]\n'
    '1. e4 {Main comment} (1. d4 $1 d5 (1... Nf6)) e5 *\n```\n\n'
    'Narrative between games.\n\n```pgn\n[Event "Black start"]\n[SetUp "1"]\n'
    '[FEN "' + BLACK_FEN + '"]\n17... d5 *\n```\n\nAfter the games.')


class MarkdownLibraryJourneyTests(unittest.TestCase):
    def test_book_structure_import_search_lookup_export_and_idempotent_reimport(self):
        with tempfile.TemporaryDirectory() as directory:
            for suffix in ('.md', '.MARKDOWN'):
                with self.subTest(suffix=suffix):
                    source = Path(directory) / ('lesson' + suffix)
                    raw = MARKDOWN.encode('utf-8')
                    source.write_bytes(raw)
                    book = import_text_book(raw, source_name=source.name, source_format=BookTextFormat.MARKDOWN)
                    self.assertTrue(any(type(block) is Heading for block in book.document.blocks))
                    self.assertTrue(any(type(block) is ListBlock for block in book.document.blocks))
                    self.assertTrue(any(type(block) is Position for block in book.document.blocks))
                    self.assertEqual(sum(type(block) is Game for block in book.document.blocks), 2)
                    opened = open_book_library_source(source)
                    self.assertEqual(opened.source.sha256, sha256(raw).hexdigest())
                    self.assertEqual([game.source_index for game in opened.games], [0, 1])
                    self.assertTrue(any('games only' in warning for warning in opened.warnings))
                    self.assertEqual(validate_game_legality(opened.games[1]).start_fen, BLACK_FEN)
                    with AcsDatabase() as database:
                        service = LibraryImportService(database)
                        kwargs = dict(source_name=source.name, source_format=suffix[1:].lower(), source_sha256=opened.source.sha256)
                        imported = service.import_games(opened.games, **kwargs)
                        rows = database.search_games(player='Олексій', event='Урок', date_from='2026.10.05', date_to='2026.10.05')
                        self.assertEqual(len(rows), 1)
                        selected = AcsdbBookGameLookup(database).load_book_game(imported.first_game_id)
                        self.assertEqual(selected.line.moves[0].comments_after[0].text, 'Main comment')
                        self.assertEqual(selected.line.moves[0].variations[0].moves[1].variations[0].moves[0].san, 'Nf6')
                        repeated = service.import_games(opened.games, **kwargs)
                        self.assertTrue(repeated.reused)
                        destination = Path(directory) / ('selected' + suffix + '.pgn')
                        LibraryExportService(database).export_to(destination, LibraryExportRequest.selected([imported.first_game_id, imported.last_game_id]))
                        restored = open_pgn(destination)
                        self.assertEqual(len(restored.games), 2)
                        self.assertEqual(restored.games[1].tags['FEN'], BLACK_FEN)
                        self.assertNotIn('Narrative between games', destination.read_text(encoding='utf-8'))
                    self.assertEqual(source.read_bytes(), raw)

    def test_unmarked_moves_remain_prose_and_malformed_explicit_fen_fails_closed(self):
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / 'lesson.md'
            source.write_text('# Prose\n\n1. e4 e5 2. Nf3 *', encoding='utf-8')
            opened = open_book_library_source(source)
            self.assertEqual(opened.games, ())
            self.assertTrue(any('Open Book' in warning for warning in opened.warnings))
            source.write_text('```fen\ninvalid\n```\n\n```pgn\n1. e4 *\n```', encoding='utf-8')
            with self.assertRaises(BookTextImportError):
                open_book_library_source(source)



    def test_fence_opener_keeps_marker_specific_info_rules(self):
        from acs.book_text_import import _match_fence_opener

        self.assertEqual(
            _match_fence_opener("~~~code`meta"),
            ("~~~", "code`meta"),
        )
        self.assertIsNone(_match_fence_opener("```code`meta"))
        self.assertIsNone(_match_fence_opener("    ~~~code"))

    def test_valid_tilde_fence_with_backtick_info_stays_code_not_semantic_markdown(self):
        source = (
            "~~~code`meta\n"
            "# not a heading\n"
            "![not a semantic image](https://example.invalid/board.png)\n"
            "```fen\n"
            + Board.START
            + "\n```\n"
            "~~~\n\n"
            "After fence."
        )
        book = import_text_book(
            source,
            source_name="tilde.md",
            source_format=BookTextFormat.MARKDOWN,
        )

        self.assertFalse(any(type(block) is Heading for block in book.document.blocks))
        self.assertFalse(any(type(block) is Position for block in book.document.blocks))
        self.assertFalse(any(type(block) is Game for block in book.document.blocks))
        notes = [block for block in book.document.blocks if type(block) is Note]
        self.assertEqual(len(notes), 1)
        self.assertEqual(notes[0].note_type, "code:code`meta")
        self.assertIn("# not a heading", notes[0].text)
        self.assertIn("![not a semantic image]", notes[0].text)
        self.assertIn(Board.START, notes[0].text)
        self.assertFalse(any("image reference" in warning for warning in book.warnings))

    def test_fence_close_requires_same_marker_family_minimum_length_and_no_payload(self):
        from acs.book_text_import import _is_fence_close

        self.assertTrue(_is_fence_close("~~~", "~~~"))
        self.assertTrue(_is_fence_close("  ~~~~~", "~~~~"))
        self.assertFalse(_is_fence_close("~~~", "~~~~"))
        self.assertFalse(_is_fence_close("```", "~~~"))
        self.assertFalse(_is_fence_close("~~~~ trailing", "~~~"))
        self.assertFalse(_is_fence_close("    ~~~~", "~~~"))

    def test_invalid_tilde_closers_stay_opaque_until_matching_close(self):
        source = (
            "~~~~code`meta\n"
            "~~~\n"
            "```\n"
            "~~~~ trailing\n"
            "# still not a heading\n"
            "![still not an image](https://example.invalid/board.png)\n"
            "```fen\n"
            + Board.START
            + "\n```\n"
            "~~~~\n\n"
            "# Real heading"
        )
        book = import_text_book(
            source,
            source_name="tilde-close.md",
            source_format=BookTextFormat.MARKDOWN,
        )

        headings = [block for block in book.document.blocks if type(block) is Heading]
        self.assertEqual([block.text for block in headings], ["Real heading"])
        self.assertFalse(any(type(block) is Position for block in book.document.blocks))
        self.assertFalse(any(type(block) is Game for block in book.document.blocks))
        notes = [block for block in book.document.blocks if type(block) is Note]
        self.assertEqual(len(notes), 1)
        self.assertIn("~~~", notes[0].text)
        self.assertIn("```", notes[0].text)
        self.assertIn("~~~~ trailing", notes[0].text)
        self.assertIn("# still not a heading", notes[0].text)
        self.assertIn(Board.START, notes[0].text)
        self.assertFalse(any("image reference" in warning for warning in book.warnings))

    def test_native_import_action_accepts_markdown_on_worker_and_reopens_database(self):
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / 'lesson.MD'
            source.write_text(MARKDOWN, encoding='utf-8')
            database_path = Path(directory) / 'library.acsdb'
            events, workers = [], []
            terminal = threading.Event()

            class Dialogs:
                def open_pgn(self): return None
                def save_pgn_as(self, *args): return None
                def select_library_import(self): return source

            def services():
                workers.append(threading.get_ident())
                database = AcsDatabase(database_path)
                return Version2ImportWorkerServices(LibraryImportService(database), None, database.close)

            def observe(event):
                events.append(event)
                if event.kind in {FileWorkflowEventKind.IMPORT_COMPLETED, FileWorkflowEventKind.FAILED}:
                    terminal.set()

            delegate = Version2WindowsFileActionDelegate(dialogs=Dialogs(), get_pgn_session=lambda: None,
                set_pgn_session=lambda _: None, import_services_factory=services, event_sink=observe,
                next_delegate=lambda *_: self.fail('Markdown must use canonical Library import'))
            delegate('library.import', {})
            self.assertTrue(terminal.wait(5))
            self.assertTrue(delegate.wait_for_import(5))
            self.assertNotEqual(workers, [threading.get_ident()])
            completed = [event for event in events if event.kind is FileWorkflowEventKind.IMPORT_COMPLETED]
            self.assertEqual(len(completed), 1)
            self.assertEqual(completed[0].game_count, 2)
            self.assertGreater(completed[0].warning_count, 0)
            with AcsDatabase(database_path) as database:
                self.assertEqual(len(database.search_games()), 2)


if __name__ == '__main__':
    unittest.main()
