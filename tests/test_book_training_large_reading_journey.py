import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from acs.bookdocument import BookDocument, Exercise, Paragraph
from acs.bookreader import BookReader
from acs.chesscore import Board
from acs.version2_training_workspace import Version2BookTrainingWorkspace
import acs.version2_training_workspace as training


class BookTrainingLargeReadingJourneyTests(unittest.TestCase):
    def workspace(self, prose_count, *, successor=True, invalid=False):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        blocks = [Exercise(fen=Board.START, prompt='First', answer_text='e4', block_id='first')]
        blocks.extend(Paragraph(text=f'Lesson prose {index}', block_id=f'prose-{index}') for index in range(prose_count))
        if invalid:
            blocks.append(Exercise(fen=Board.START, prompt='Unusable source', answer_text='e5', block_id='invalid'))
        if successor:
            blocks.append(Exercise(fen=Board.START, prompt='Second', answer_text='d4', block_id='second'))
        reader = BookReader(BookDocument(title='Long lesson', blocks=blocks))
        workspace = Version2BookTrainingWorkspace(reader, progress_root=Path(temporary.name))
        workspace.start_current()
        return reader, workspace

    def test_next_availability_revision_work_does_not_grow_with_intervening_prose(self):
        checks = []
        for count in (100, 1000):
            reader, workspace = self.workspace(count, invalid=True)
            with patch.object(reader, '_require_indexed_revision', wraps=reader._require_indexed_revision) as validate:
                self.assertTrue(workspace.has_next())
                checks.append(validate.call_count)
            self.assertEqual(reader.index, 0)
            self.assertEqual(workspace.material.definition.title, 'First')
        self.assertEqual(checks[0], checks[1])
        self.assertLess(checks[1], 15)

    def test_long_lesson_continuation_preserves_origin_and_progress(self):
        reader, workspace = self.workspace(500, invalid=True)
        event = workspace.dispatch('training.submit', {'answer': 'e4'})
        self.assertNotEqual(event.kind, 'error')
        self.assertTrue(workspace.session.completed)
        first_path = workspace._store.path
        first_progress = first_path.read_bytes()
        continued = workspace.dispatch('training.continue')
        self.assertNotEqual(continued.kind, 'error')
        self.assertEqual(reader.index, 502)
        self.assertEqual(workspace.material.definition.title, 'Second')
        self.assertEqual(first_path.read_bytes(), first_progress)
        restarted = Version2BookTrainingWorkspace(reader, progress_root=workspace.progress_root)
        restarted.start_current()
        self.assertEqual(restarted.material.origin, workspace.material.origin)
        self.assertEqual(restarted.session.snapshot(), workspace.session.snapshot())

    def test_source_drift_during_successor_derivation_is_rejected(self):
        reader, workspace = self.workspace(100, invalid=True)
        original = training.build_book_training_material
        before = workspace.material
        def mutate(document, index):
            result = original(document, index)
            reader.document.blocks[50].text = 'Changed source'
            return result
        with patch.object(training, 'build_book_training_material', side_effect=mutate):
            with self.assertRaises(RuntimeError):
                workspace._next_exercise_material()
        self.assertIs(workspace.material, before)
        self.assertEqual(reader.index, 0)

    def test_exhausted_long_lesson_revalidates_after_detached_scan(self):
        reader, workspace = self.workspace(100, successor=False, invalid=True)
        original = training.build_book_training_material
        def mutate(document, index):
            reader.document.blocks[50].text = 'Changed source'
            return original(document, index)
        with patch.object(training, 'build_book_training_material', side_effect=mutate):
            with self.assertRaises(RuntimeError):
                workspace._next_exercise_material()
        self.assertEqual(reader.index, 0)
