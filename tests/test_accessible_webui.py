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

    def test_semantic_html_contract(self):
        html = (Path(__file__).resolve().parents[1] / 'web' / 'index.html').read_text(encoding='utf-8')
        for heading in [
            'Інформація про гру', 'Список ходів', 'Білі фігури', 'Чорні фігури',
            'Стан гри / позиції', 'Останній хід', 'Введення ходу', 'Аналіз Stockfish',
            'Дошка', 'Дії'
        ]:
            self.assertIn(f'>{heading}<', html)
        self.assertIn('id="move-input" type="text"', html)
        self.assertIn('id="board-launcher" type="button"', html)
        self.assertIn('role="application" aria-label="Шахова дошка"', html)
        self.assertIn('role="status" aria-live="polite"', html)


if __name__ == '__main__':
    unittest.main()
