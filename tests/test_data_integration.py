import unittest

from acs.acsdb import AcsDatabase
from acs.bookdocument import BookDocument, Heading, Game
from acs.chessbase_adapter import probe_chessbase_source
from acs.history import ReviewHistory


class DataIntegrationTests(unittest.TestCase):
    def test_pgn_to_acsdb_search_and_book_reference(self):
        pgn = '''[Event "Integration"]
[White "Alpha"]
[Black "Beta"]
[Result "1-0"]
[ECO "C20"]
[Opening "King's Pawn Game"]

1. e4 e5 2. Nf3 Nc6 1-0
'''
        with AcsDatabase(':memory:') as db:
            report = db.import_pgn_text(pgn, 'integration.pgn')
            self.assertEqual(report.full, 1)
            game_id = report.game_ids[0]
            self.assertEqual(len(db.search_games(player='alpha', opening='pawn', source_name='integration')), 1)
            doc = BookDocument(title='Integrated book', source_name='integration.pgn')
            doc.append(Heading(text='Game one', level=1))
            doc.append(Game(game_id=game_id, title='Alpha–Beta'))
            roundtrip = BookDocument.from_dict(doc.as_dict())
            self.assertEqual(roundtrip.blocks[1].game_id, game_id)

    def test_history_review_is_non_destructive_and_direct_jump_works(self):
        history = ReviewHistory('start-fen')
        history.append('after-e4', san='e4', side='b', last_move='e2e4')
        history.append('after-e5', san='e5', side='w', last_move='e7e5')
        history.append('after-nf3', san='Nf3', side='b', last_move='g1f3')
        history.append('after-nc6', san='Nc6', side='w', last_move='b8c6')
        end = history.current()
        self.assertEqual(end.ply, 4)
        self.assertEqual(history.jump('1w').snapshot.fen, 'after-e4')
        self.assertEqual(history.jump('1').snapshot.fen, 'after-e5')
        self.assertEqual(history.jump('start').snapshot.fen, 'start-fen')
        self.assertEqual(history.jump('end').snapshot.fen, 'after-nc6')
        self.assertEqual(history.node_count, 5)

    def test_chessbase_probe_never_claims_decoder_from_extension(self):
        probe = probe_chessbase_source('sample.CBH')
        self.assertTrue(probe.recognized)
        self.assertTrue(probe.read_only)
        self.assertFalse(probe.decoder_available)
        self.assertFalse(probe.safe_to_import)


if __name__ == '__main__':
    unittest.main()
