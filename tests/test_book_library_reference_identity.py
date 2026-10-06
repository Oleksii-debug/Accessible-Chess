import unittest
from acs.acsdb import AcsDatabase
from acs.analysis_service import AnalysisService
from acs.book_board_workflow import BookBoardWorkflow, BookBoardWorkflowError
from acs.book_game_content import BookGameContentError, BookGameContentErrorCode, resolve_book_game
from acs.book_library_game_lookup import AcsdbBookGameLookup
from acs.bookdocument import BookDocument, BookDocumentError, Game
from acs.bookreader import BookReader
from acs.engine_assisted_workflows import EngineAssistedWorkflowService


class BookLibraryReferenceIdentityTests(unittest.TestCase):
    def database(self, pgn):
        db = AcsDatabase()
        self.addCleanup(db.close)
        db.import_pgn_text(pgn, source_name='source.pgn')
        return db

    def test_bound_reference_roundtrips_and_rejects_same_id_in_another_library(self):
        expected = self.database('[Event "Expected"]\n[Result "*"]\n\n1. e4 {comment} (1. d4 d5) e5 *')
        other = self.database('[Event "Other"]\n[Result "*"]\n\n1. d4 d5 *')
        reference = AcsdbBookGameLookup(expected).make_book_reference(1, block_id='bound')
        self.assertEqual(len(reference.game_record_digest), 64)
        restored = BookDocument.from_dict(BookDocument('Study', blocks=[reference]).as_dict()).blocks[0]
        self.assertEqual(restored.game_record_digest, reference.game_record_digest)
        resolved = resolve_book_game(restored, lookup=AcsdbBookGameLookup(expected))
        self.assertEqual(resolved.game.tags['Event'], 'Expected')
        with self.assertRaises(BookGameContentError) as caught:
            resolve_book_game(restored, lookup=AcsdbBookGameLookup(other))
        self.assertEqual(caught.exception.code, BookGameContentErrorCode.REFERENCE_CHANGED)

    def test_changed_record_fails_before_board_open_and_preserves_reader(self):
        db = self.database('[Event "Expected"]\n[Result "*"]\n\n1. e4 *')
        lookup = AcsdbBookGameLookup(db)
        reader = BookReader(BookDocument('Study', blocks=[lookup.make_book_reference(1)]))
        analysis = AnalysisService(lambda: None)
        self.addCleanup(analysis.close)
        workflow = BookBoardWorkflow(reader, EngineAssistedWorkflowService(analysis), game_lookup=lookup)
        before = reader.snapshot()
        db.conn.execute('UPDATE games SET pgn_text = ? WHERE id = 1', ('[Event "Changed"]\n[Result "*"]\n\n1. d4 *',))
        db.conn.commit()
        with self.assertRaises(BookBoardWorkflowError):
            workflow.open_current()
        self.assertFalse(workflow.active)
        self.assertEqual(reader.snapshot(), before)

    def test_missing_reference_and_invalid_digest_fail_closed(self):
        db = self.database('1. e4 *')
        reference = AcsdbBookGameLookup(db).make_book_reference(1)
        empty = AcsDatabase()
        self.addCleanup(empty.close)
        with self.assertRaises(BookGameContentError):
            resolve_book_game(reference, lookup=AcsdbBookGameLookup(empty))
        for digest in ('a' * 63, 'A' * 64, True, 'g' * 64, 'a' * 65):
            with self.assertRaises(BookDocumentError):
                Game(game_id=1, game_record_digest=digest)
        with self.assertRaises(BookDocumentError):
            Game(pgn='1. e4 *', game_record_digest='a' * 64)

    def test_legacy_local_reference_remains_compatible_and_source_read_only(self):
        db = self.database('1. e4 *')
        before = db.conn.total_changes
        resolve_book_game(Game(game_id=1), lookup=AcsdbBookGameLookup(db))
        AcsdbBookGameLookup(db).make_book_reference(1)
        self.assertEqual(db.conn.total_changes, before)
        legacy = Game(game_id=1)
        self.assertNotIn('game_record_digest', legacy.as_dict())
        document = BookDocument('Legacy', blocks=[legacy])
        reader = BookReader(document)
        saved = reader.snapshot()
        self.assertEqual(BookReader.restore_snapshot(document, saved).snapshot(), saved)
