import unittest
from pathlib import Path

from acs.webapp import AccessibleChessAPI


class AccessibleWebUiTests(unittest.TestCase):
    def setUp(self):
        self.api = AccessibleChessAPI('uk')

    def test_board_has_64_cells(self):
        self.assertEqual(len(self.api.get_state()['board']), 64)

    def test_empty_square_is_coordinate_only(self):
        self.assertEqual(self.api.square_label('e4'), 'e 4')

    def test_occupied_square_has_piece(self):
        self.assertEqual(self.api.square_label('e2'), 'e 2, білий пішак')

    def test_move_entry_and_board_move_share_same_core(self):
        r = self.api.make_move('e4')
        self.assertTrue(r['ok'])
        self.assertIn('e 4', r['lastMove'])
        self.api.undo()
        self.api.activate_square('e2')
        r = self.api.activate_square('e4')
        self.assertTrue(r['ok'])
        self.assertIn('e 4', r['lastMove'])

    def test_locked_single_letter_commands(self):
        self.assertTrue(self.api.make_move('d')['ok'])
        self.assertEqual(self.api.board.turn, 'b')
        self.assertTrue(self.api.make_move('w')['ok'])
        self.assertEqual(self.api.board.turn, 'w')
        self.assertTrue(self.api.make_move('e')['ok'])
        self.assertTrue(self.api.engine_enabled)
        self.assertTrue(self.api.make_move('x')['ok'])
        self.assertFalse(self.api.get_state()['positionComplete'])
        self.assertTrue(self.api.make_move('s')['ok'])
        self.assertTrue(self.api.get_state()['positionComplete'])

    def test_text_position_editor_round_trip(self):
        text = 'W: K g1 Q d1 R a1 R f1 B c4 N f3 P e4 B: K g8 Q d8 N f6'
        r = self.api.set_position_text(text, 'b')
        self.assertTrue(r['ok'])
        self.assertEqual(self.api.board.turn, 'b')
        self.assertEqual(self.api.square_label('g1'), 'g 1, білий король')
        self.assertEqual(self.api.square_label('g8'), 'g 8, чорний король')
        self.assertTrue(r['positionComplete'])

    def test_clear_board_is_safe_in_accessible_state(self):
        r = self.api.clear_board()
        self.assertTrue(r['ok'])
        self.assertEqual(len(r['board']), 64)
        self.assertEqual(r['whitePieces'], 'фігур немає')
        self.assertIn('Редактор позиції', r['gameStatus'])
        self.assertFalse(r['positionComplete'])
        illegal = self.api.make_move('e4')
        self.assertFalse(illegal['ok'])
        self.assertIn('королю', illegal['announcement'])

    def test_semantic_html_contract(self):
        html = (Path(__file__).resolve().parents[1] / 'web' / 'index.html').read_text(encoding='utf-8')
        for heading in [
            'Інформація про гру', 'Список ходів', 'Білі фігури', 'Чорні фігури',
            'Стан гри / позиції', 'Останній хід', 'Введення ходу', 'Аналіз Stockfish',
            'Дошка', 'Дії'
        ]:
            self.assertIn(f'>{heading}<', html)
        self.assertIn('class="skip-link" href="#main-content"', html)
        self.assertIn('<main id="main-content">', html)
        self.assertIn('id="move-input" type="text"', html)
        self.assertIn('id="position-input"', html)
        self.assertIn('id="position-load" type="button"', html)
        self.assertIn('id="empty-board" type="button"', html)
        self.assertIn('id="board-launcher" type="button"', html)
        self.assertIn('role="application" aria-label="Шахова дошка" aria-describedby="board-help"', html)
        self.assertIn('role="grid" aria-label="64 поля шахової дошки" aria-rowcount="8" aria-colcount="8"', html)
        self.assertIn("node.setAttribute('aria-rowindex'", html)
        self.assertIn("node.setAttribute('aria-colindex'", html)

    def test_board_has_direct_coordinate_navigation_contract(self):
        html = (Path(__file__).resolve().parents[1] / 'web' / 'index.html').read_text(encoding='utf-8')
        self.assertIn("/^[a-hA-H]$/.test(key)", html)
        self.assertIn("jumpBoardFocus(key.toLowerCase()+sq[1])", html)
        self.assertIn("/^[1-8]$/.test(key)", html)
        self.assertIn("jumpBoardFocus(sq[0]+key)", html)
        self.assertIn("key==='Home'", html)
        self.assertIn("jumpBoardFocus('a1')", html)
        self.assertIn("key==='End'", html)
        self.assertIn("jumpBoardFocus('h8')", html)
        self.assertIn('Літери a–h — перейти на відповідну вертикаль', html)

    def test_live_region_contract_avoids_background_speech_spam(self):
        html = (Path(__file__).resolve().parents[1] / 'web' / 'index.html').read_text(encoding='utf-8')
        self.assertIn('role="status" aria-live="polite" aria-atomic="true" aria-relevant="text"', html)
        self.assertIn('id="game-info" class="block" aria-live="off"', html)
        self.assertIn('id="moves" class="block" aria-live="off"', html)
        self.assertIn('id="engine-status" class="block" aria-live="off"', html)
        self.assertIn('message===lastAnnouncement&&now-lastAnnouncementAt<500', html)
        self.assertIn("live.setAttribute('aria-busy','true')", html)
        self.assertIn("live.setAttribute('aria-busy','false')", html)


if __name__ == '__main__':
    unittest.main()