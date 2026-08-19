import unittest

from acs.bookdocument import (
    BookDocument,
    BookDocumentError,
    BookDocumentErrorCode,
    Exercise,
    Heading,
    Position,
)


FEN = '8/8/8/8/8/8/8/8 w - - 0 1'


class BookDocumentExportValidationTests(unittest.TestCase):
    def assert_invalid_export(self, document):
        with self.assertRaises(BookDocumentError) as caught:
            document.as_dict()
        self.assertEqual(caught.exception.code, BookDocumentErrorCode.INVALID_FIELD)

    def test_mutated_heading_is_revalidated_before_export(self):
        heading = Heading(text='Chapter', level=2)
        document = BookDocument('Book', blocks=[heading])

        heading.level = True
        self.assert_invalid_export(document)

        heading.level = 2
        heading.text = '   '
        self.assert_invalid_export(document)

    def test_mutated_position_fen_is_revalidated_before_export(self):
        position = Position(fen=FEN)
        document = BookDocument('Book', blocks=[position])
        position.fen = 'not a fen'
        self.assert_invalid_export(document)

    def test_mutated_exercise_cannot_lose_all_solution_content(self):
        exercise = Exercise(fen=FEN, prompt='Find a move', answer_text='Answer')
        document = BookDocument('Book', blocks=[exercise])
        exercise.answer_text = None
        exercise.solution_pgn = None
        self.assert_invalid_export(document)

    def test_mutated_document_header_and_collections_fail_closed(self):
        document = BookDocument('Book', blocks=[Heading(text='Chapter')])
        document.title = ''
        self.assert_invalid_export(document)

        document = BookDocument('Book', blocks=[Heading(text='Chapter')])
        document.warnings = ('warning',)
        self.assert_invalid_export(document)

        document = BookDocument('Book', blocks=[Heading(text='Chapter')])
        document.blocks = tuple(document.blocks)
        self.assert_invalid_export(document)

    def test_append_and_extend_reject_already_mutated_blocks_atomically(self):
        document = BookDocument('Book')
        bad = Heading(text='Chapter')
        bad.level = 0
        with self.assertRaises(BookDocumentError):
            document.append(bad)
        self.assertEqual(document.blocks, [])

        good = Heading(text='Good')
        bad = Position(fen=FEN)
        bad.fen = 'bad'
        with self.assertRaises(BookDocumentError):
            document.extend([good, bad])
        self.assertEqual(document.blocks, [])

    def test_valid_document_round_trip_still_uses_schema_v1(self):
        document = BookDocument(
            'Book',
            language='uk',
            blocks=[Heading(text='Chapter'), Position(fen=FEN)],
            warnings=['source warning'],
        )
        payload = document.as_dict()
        restored = BookDocument.from_dict(payload)
        self.assertEqual(restored.as_dict(), payload)
        self.assertEqual(payload['schema_version'], 1)


if __name__ == '__main__':
    unittest.main()
