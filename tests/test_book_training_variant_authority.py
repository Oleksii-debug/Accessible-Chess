import unittest

from acs.book_training import (
    BookTrainingError, BookTrainingErrorCode, build_current_book_training_material,
    restore_book_training_material, return_reader_to_book_training_origin,
)
from acs.bookdocument import BookDocument, Exercise, Paragraph
from acs.bookreader import BookReader
from acs.chesscore import Board
from acs.training import ExerciseSession


class BookTrainingVariantAuthorityTests(unittest.TestCase):
    def reader(self, variant):
        tags = '' if variant is None else f'[Variant "{variant}"]\n'
        return BookReader(BookDocument('Variant authority', blocks=[
            Exercise(fen=Board.START, prompt='Play the line',
                     solution_pgn=tags + '1. e4 e5 *', block_id='exercise'),
            Paragraph(text='Continue reading', block_id='after'),
        ]))

    def test_nonstandard_solution_cannot_enter_training_or_move_reader(self):
        for variant in ('Chess960', 'FischerRandom', 'Atomic', 'Unknown', ''):
            with self.subTest(variant=variant):
                reader = self.reader(variant)
                before = reader.snapshot()
                with self.assertRaises(BookTrainingError) as caught:
                    build_current_book_training_material(reader)
                self.assertEqual(caught.exception.code, BookTrainingErrorCode.UNSUPPORTED_SOLUTION)
                self.assertEqual(reader.snapshot(), before)

    def test_standard_solution_completes_restores_material_and_returns_exact_origin(self):
        for variant in (None, 'Standard', 'Chess', ' standard '):
            with self.subTest(variant=variant):
                reader = self.reader(variant)
                origin = reader.snapshot()
                material = build_current_book_training_material(reader)
                restored = restore_book_training_material(reader.document_snapshot(), material.as_dict())
                session = ExerciseSession(restored.definition)
                self.assertTrue(session.submit('e2e4').accepted)
                self.assertTrue(session.submit('e7e5').completed)
                reader.go_to(1)
                return_reader_to_book_training_origin(reader, restored.origin)
                self.assertEqual(reader.snapshot(), origin)

    def test_changed_variant_cannot_restore_previously_exported_training(self):
        reader = self.reader('Standard')
        material = build_current_book_training_material(reader)
        changed = reader.document_snapshot()
        changed.blocks[0].solution_pgn = '[Variant "Chess960"]\n1. e4 e5 *'
        with self.assertRaises(BookTrainingError):
            restore_book_training_material(changed, material.as_dict())


if __name__ == '__main__':
    unittest.main()
