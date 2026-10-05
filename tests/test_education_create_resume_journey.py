from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from acs.acsdb import AcsDatabase
from acs.analysis_service import AnalysisService
from acs.book_progress_store import BookProgressStore
from acs.engine_assisted_workflows import EngineAssistedWorkflowService
from acs.version2_education_mutation_application import Version2EducationMutationApplication


class EducationCreateResumeJourneyTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.database = AcsDatabase(self.root / 'library.acsdb')
        self.addCleanup(self.database.close)
        self.analysis = AnalysisService(lambda: None)
        self.addCleanup(self.analysis.close)
        self.app = self.application()

    def application(self):
        return Version2EducationMutationApplication(
            self.database, progress_store=BookProgressStore(self.root / 'books.json'),
            engine_assistance=EngineAssistedWorkflowService(self.analysis),
            board_dispatch=lambda *_: None, board_position_projector=lambda fen: {'ok': bool(fen)},
            copy_text=lambda _: None, education_workspace_path=self.root / 'education.json',
        )

    def test_create_second_class_keeps_selection_for_open_and_restart(self):
        self.app.shell.open_route('classes')
        first = self.app.browser_command('education', 'education.new_class')
        self.assertEqual('selection', first['kind'])
        second = self.app.browser_command('education', 'education.new_class')
        self.assertEqual('selection', second['kind'])
        selected = [item for item in second['payload']['snapshot']['items'] if item['selected']]
        self.assertEqual(['Новий клас 2'], [item['label'] for item in selected])
        current = self.app.browser_command('education', 'education.snapshot')['payload']['snapshot']
        selected = [item for item in current['sections'][0]['items'] if item['selected']]
        self.assertEqual(['Новий клас 2'], [item['label'] for item in selected])
        opened = self.app.browser_command('education', 'education.open', {'kind': 'class'})
        self.assertEqual('delegated', opened['kind'])
        self.assertEqual('Новий клас 2', opened['payload']['detail']['heading'])
        revision = self.app.education_revision
        reopened = self.application()
        self.assertEqual(revision, reopened.education_revision)
        self.assertEqual(['Новий клас 1', 'Новий клас 2'], [c.title for c in reopened._education_provider().classroom.classes])
        self.assertNotIn('class-', repr(opened['payload']))

    def test_failed_creation_preserves_selected_record_and_durable_bytes(self):
        self.app.shell.open_route('classes')
        self.app.browser_command('education', 'education.new_class')
        before = self.app.browser_command('education', 'education.snapshot')
        bridge = self.app.education
        workspace = self.app._education_provider()
        revision = self.app.education_revision
        durable = (self.root / 'education.json').read_bytes()
        with patch.object(self.app.education_store, 'save', side_effect=OSError('private file failed')):
            failed = self.app.browser_command('education', 'education.new_class')
        self.assertEqual('error', failed['kind'])
        self.assertNotIn('private', repr(failed))
        self.assertIs(bridge, self.app.education)
        self.assertIs(workspace, self.app._education_provider())
        self.assertEqual(revision, self.app.education_revision)
        self.assertEqual(before, self.app.browser_command('education', 'education.snapshot'))
        self.assertEqual(durable, (self.root / 'education.json').read_bytes())

    def test_hidden_and_modal_commands_do_not_create_or_change_selection(self):
        initial = self.app._education_provider()
        commands = (
            ('education.new_class', {}),
            ('education.move', {'kind': 'class', 'direction': 1}),
            ('education.page', {'kind': 'class', 'direction': 1}),
            ('education.open', {'kind': 'class'}),
        )
        with patch.object(self.app.education_store, 'save', side_effect=AssertionError('unexpected write')):
            for route in ('board', 'books', 'training', 'teacher', 'settings'):
                self.app.shell.open_route(route)
                for area in ('education', 'classes'):
                    for command, payload in commands:
                        self.assertEqual('error', self.app.browser_command(area, command, payload)['kind'])
                self.assertEqual('render', self.app.browser_command('education', 'education.snapshot')['kind'])
                self.assertIs(initial, self.app._education_provider())
            self.app.shell.open_route('classes')
            self.app.shell.open_dialog('test-dialog', opener_focus_id='classes-list', initial_focus_id='test-input')
            for command, payload in commands:
                self.assertEqual('error', self.app.browser_command('education', command, payload)['kind'])
            self.assertIs(initial, self.app._education_provider())
        self.app.shell.close_dialog()
        self.assertEqual('selection', self.app.browser_command('classes', 'education.new_class')['kind'])


if __name__ == '__main__':
    unittest.main()
