import importlib.util
import pathlib
import unittest

MODULE_PATH = pathlib.Path(__file__).with_name('stage1_uia_topology_classify.py')
spec = importlib.util.spec_from_file_location('classifier', MODULE_PATH)
classifier = importlib.util.module_from_spec(spec)
spec.loader.exec_module(classifier)


def complete_view(**overrides):
    base = dict(started=True, completed=True, error_count=0, cap_reached=False,
                truncated=False, disconnected_count=0, cycle_or_duplicate_count=0)
    base.update(overrides)
    return base


def root(**overrides):
    base = dict(relevant_provider_root=True, connected_to_app=True, from_handle_success=True,
                provider_subtree_seen=True, raw_view=complete_view(), control_view=complete_view())
    base.update(overrides)
    return base


def move(**overrides):
    base = dict(control_type='ControlType.Edit', name='Хід', connected_to_app=True,
                source_root_connected=True, source_contract_original_possible=True,
                enabled=True, keyboard_focusable=True, offscreen=False,
                is_control_element=True, is_content_element=True, value_pattern=True,
                bounds=[1, 1, 100, 20], runtime_id='1.2.3', process_id=2,
                native_window_handle=3, automation_id='move-input')
    base.update(overrides)
    return base


def base_report():
    return {
        'root_attempts': [root()],
        'provider_chain': {
            'host_found': True, 'native_relationship_proven': True,
            'process_relationship_proven': True, 'provider_entry_proven': True,
            'uia_subtree_proven': True, 'provider_transition_proven': True,
            'unresolved_boundary_count': 0,
        },
        'connected_edits': [],
        'source_contract': {'unique_original_move_edit': True, 'no_qa_proxy_in_product_tree': True},
    }


class ClassificationTests(unittest.TestCase):
    def test_complete_provider_plus_real_move_is_a(self):
        r = base_report(); r['connected_edits'] = [move()]
        self.assertEqual(classifier.classify(r)[0], 'A')

    def test_complete_without_move_is_b(self):
        self.assertEqual(classifier.classify(base_report())[0], 'B')

    def test_traversal_exception_is_c(self):
        r = base_report(); r['root_attempts'][0]['raw_view'] = complete_view(completed=False, error_count=1)
        self.assertEqual(classifier.classify(r)[0], 'C')

    def test_cap_is_c(self):
        r = base_report(); r['root_attempts'][0]['raw_view'] = complete_view(completed=False, cap_reached=True, truncated=True)
        self.assertEqual(classifier.classify(r)[0], 'C')

    def test_disconnected_random_provider_is_c(self):
        r = base_report(); r['root_attempts'][0]['connected_to_app'] = False
        self.assertEqual(classifier.classify(r)[0], 'C')

    def test_incomplete_raw_is_c(self):
        r = base_report(); r['root_attempts'][0]['raw_view'] = complete_view(completed=False)
        self.assertEqual(classifier.classify(r)[0], 'C')

    def test_incomplete_control_is_c(self):
        r = base_report(); r['root_attempts'][0]['control_view'] = complete_view(completed=False)
        self.assertEqual(classifier.classify(r)[0], 'C')

    def test_hidden_edit_not_a(self):
        r = base_report(); r['connected_edits'] = [move(offscreen=True)]
        self.assertEqual(classifier.classify(r)[0], 'C')

    def test_no_value_pattern_not_a(self):
        r = base_report(); r['connected_edits'] = [move(value_pattern=False)]
        self.assertEqual(classifier.classify(r)[0], 'C')

    def test_duplicate_move_is_c(self):
        r = base_report(); r['connected_edits'] = [move(runtime_id='1'), move(runtime_id='2')]
        self.assertEqual(classifier.classify(r)[0], 'C')

    def test_wrong_name_not_a_and_complete_can_be_b(self):
        r = base_report(); r['connected_edits'] = [move(name='FEN')]
        self.assertEqual(classifier.classify(r)[0], 'B')

    def test_real_move_is_a(self):
        r = base_report(); r['connected_edits'] = [move(name='Move')]
        self.assertEqual(classifier.classify(r)[0], 'A')

    def test_cycle_is_c(self):
        r = base_report(); r['root_attempts'][0]['control_view'] = complete_view(completed=False, cycle_or_duplicate_count=1)
        self.assertEqual(classifier.classify(r)[0], 'C')

    def test_missing_provider_transition_is_c(self):
        r = base_report(); r['provider_chain']['provider_transition_proven'] = False
        self.assertEqual(classifier.classify(r)[0], 'C')

    def test_unresolved_boundary_is_c(self):
        r = base_report(); r['provider_chain']['unresolved_boundary_count'] = 1
        self.assertEqual(classifier.classify(r)[0], 'C')

    def test_source_proxy_uncertainty_blocks_b(self):
        r = base_report(); r['source_contract']['no_qa_proxy_in_product_tree'] = False
        self.assertEqual(classifier.classify(r)[0], 'C')


if __name__ == '__main__':
    unittest.main(verbosity=2)
