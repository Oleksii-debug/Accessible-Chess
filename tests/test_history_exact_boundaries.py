import unittest

from acs.history import HistoryError, HistoryErrorCode, PositionSnapshot, ReviewHistory


class HistoryExactBoundaryTests(unittest.TestCase):
    def make_history(self):
        history = ReviewHistory('fen-0')
        for ply in range(1, 5):
            history.append(f'fen-{ply}', san=f'm{ply}')
        return history

    def test_jump_rejects_coercible_non_text_non_integer_targets(self):
        history = self.make_history()
        before = history.current()
        for target in (True, 1.0, b'1', ['1'], None):
            with self.subTest(target=target):
                with self.assertRaises(HistoryError) as caught:
                    history.jump(target)
                self.assertEqual(caught.exception.code, HistoryErrorCode.INVALID_COMMAND)
                self.assertEqual(history.current(), before)

    def test_node_and_variation_targets_require_exact_integer(self):
        history = self.make_history()
        history.previous()
        history.append('branch', san='branch')
        history.previous()
        before = history.current()

        for target in (True, 1.0, '1'):
            with self.subTest(api='select_node', target=target):
                with self.assertRaises(HistoryError):
                    history.select_node(target)
                self.assertEqual(history.current(), before)
            with self.subTest(api='select_variation', target=target):
                with self.assertRaises(HistoryError):
                    history.select_variation(target)
                self.assertEqual(history.current(), before)

    def test_nested_context_is_detached_and_deeply_read_only(self):
        source = {
            'meta': {
                'labels': ['critical', {'score': 7}],
                'flags': {'a', 'b'},
            }
        }
        snapshot = PositionSnapshot('fen', context=source)
        source['meta']['labels'][1]['score'] = 99
        source['meta']['labels'].append('late')
        source['meta']['flags'].add('c')

        self.assertEqual(snapshot.context['meta']['labels'][1]['score'], 7)
        self.assertEqual(len(snapshot.context['meta']['labels']), 2)
        self.assertEqual(snapshot.context['meta']['flags'], frozenset({'a', 'b'}))

        with self.assertRaises(TypeError):
            snapshot.context['meta']['labels'][1]['score'] = 8
        with self.assertRaises(AttributeError):
            snapshot.context['meta']['labels'].append('x')
        with self.assertRaises(AttributeError):
            snapshot.context['meta']['flags'].add('x')

    def test_exported_context_does_not_share_nested_mutable_state(self):
        source = {'nested': {'items': [1, 2]}}
        history = ReviewHistory('fen', context=source)
        exported = history.export_tree().nodes[0].snapshot
        source['nested']['items'].append(3)

        self.assertEqual(exported.context['nested']['items'], (1, 2))
        self.assertIsNot(exported.context, history.current().snapshot.context)
        self.assertIsNot(
            exported.context['nested'],
            history.current().snapshot.context['nested'],
        )

    def test_context_rejects_non_text_keys_and_opaque_mutable_objects(self):
        for context in ({1: 'value'}, {'opaque': object()}):
            with self.subTest(context=context):
                with self.assertRaises(HistoryError) as caught:
                    PositionSnapshot('fen', context=context)
                self.assertEqual(caught.exception.code, HistoryErrorCode.INVALID_SNAPSHOT)


if __name__ == '__main__':
    unittest.main()
