import sqlite3
import tempfile
import unittest
from pathlib import Path

from acs.acsdb import ACSDB_SCHEMA_VERSION, AcsDatabase
from acs.bookdocument import BookDocument, Heading, Paragraph, Position
from acs.bookreader import BookReader
from acs.training import ExerciseDefinition, ExerciseSession, ExerciseStep


BOOK_FEN = "8/8/8/8/8/8/4K3/7k w - - 0 1"
TRAINING_FEN = "7k/8/8/8/8/8/6R1/6K1 w - - 0 1"


def make_book(*, paragraph: str = "Exact source paragraph") -> BookDocument:
    return BookDocument(
        "Durable book",
        book_id="book:durable-one",
        author="Author",
        language="uk",
        source_name="source.docx",
        blocks=[
            Heading(text="Chapter", block_id="chapter", source_anchor="p1"),
            Paragraph(text=paragraph, block_id="paragraph", source_anchor="p2"),
            Position(fen=BOOK_FEN, caption="Position", block_id="position"),
        ],
    )


def make_definition(*, title: str = "Rook line") -> ExerciseDefinition:
    return ExerciseDefinition(
        "training:rook-line",
        TRAINING_FEN,
        (
            ExerciseStep(frozenset({"Rh2+"}), hint="Use the file"),
            ExerciseStep(frozenset({"Kg8"}), hint="Leave the file"),
        ),
        title=title,
        tags=("calculation",),
        source_id="book:durable-one#position",
    )


class AcsDatabaseBooksTrainingTests(unittest.TestCase):
    def test_schema_v4_owns_books_bookmarks_definitions_and_progress(self):
        with AcsDatabase() as database:
            self.assertEqual(database.schema_version, ACSDB_SCHEMA_VERSION)
            self.assertEqual(ACSDB_SCHEMA_VERSION, 4)
            counts = database.catalog_counts()
            for table in (
                "books",
                "book_bookmarks",
                "training_definitions",
                "training_progress",
            ):
                self.assertEqual(counts[table], 0)

    def test_book_and_exact_source_bookmark_survive_reopen(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "library.acsdb"
            with AcsDatabase(path) as database:
                book_id = database.save_book(make_book())
                reader = BookReader(database.get_book(book_id))
                reader.go_to(1, reading_offset=6)
                database.save_bookmark(book_id, "resume", reader.location())

            with AcsDatabase(path) as database:
                restored_book = database.get_book("book:durable-one")
                self.assertEqual(restored_book.as_dict(), make_book().as_dict())
                location = database.load_bookmark("book:durable-one", "resume")
                self.assertEqual(location.block_id, "paragraph")
                self.assertEqual(location.source_anchor, "p2")
                self.assertEqual(location.chapter_block_id, "chapter")
                self.assertEqual(location.reading_offset, 6)

    def test_changed_book_snapshot_invalidates_obsolete_bookmarks(self):
        with AcsDatabase() as database:
            book_id = database.save_book(make_book())
            reader = BookReader(database.get_book(book_id))
            reader.go_to(1, reading_offset=2)
            database.save_bookmark(book_id, "resume", reader.location())

            same_id = database.save_book(make_book(paragraph="Changed paragraph"))
            self.assertEqual(same_id, book_id)
            with self.assertRaises(LookupError):
                database.load_bookmark(book_id, "resume")

    def test_corrupt_stored_book_fails_closed(self):
        with AcsDatabase() as database:
            book_id = database.save_book(make_book())
            database.conn.execute(
                "UPDATE books SET document_json=? WHERE id=?",
                ('{"schema_version":2,"title":"lost"}', book_id),
            )
            database.conn.commit()
            with self.assertRaises(sqlite3.DatabaseError):
                database.get_book(book_id)

    def test_training_progress_replays_exact_move_history_after_reopen(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "training.acsdb"
            definition = make_definition()
            session = ExerciseSession(definition)
            session.submit("Rh3")
            session.submit("g2h2")
            session.request_hint()

            with AcsDatabase(path) as database:
                database.save_training_progress(session)

            with AcsDatabase(path) as database:
                restored = database.load_training_session(definition.exercise_id)
                self.assertEqual(restored.snapshot(), session.snapshot())
                self.assertEqual(restored.move_history, ("Rh2+",))
                restored.submit("Kg8")
                database.save_training_progress(restored)

            with AcsDatabase(path) as database:
                completed = database.load_training_session(definition.exercise_id)
                self.assertTrue(completed.completed)
                self.assertTrue(completed.analysis_allowed)
                self.assertEqual(completed.move_history, ("Rh2+", "Kg8"))

    def test_changed_definition_discards_incompatible_progress(self):
        with AcsDatabase() as database:
            session = ExerciseSession(make_definition())
            session.submit("Rh2+")
            database.save_training_progress(session)
            self.assertEqual(database.catalog_counts()["training_progress"], 1)

            database.save_training_definition(make_definition(title="Revised line"))
            self.assertEqual(database.catalog_counts()["training_progress"], 0)
            restored = database.load_training_session("training:rook-line")
            self.assertEqual(restored.step_index, 0)
            self.assertEqual(restored.position_fen, TRAINING_FEN)

    def test_corrupt_training_summary_or_payload_fails_closed(self):
        with AcsDatabase() as database:
            session = ExerciseSession(make_definition())
            session.submit("Rh2+")
            database.save_training_progress(session)

            database.conn.execute(
                "UPDATE training_progress SET current_fen=? WHERE exercise_id=?",
                (TRAINING_FEN, session.definition.exercise_id),
            )
            database.conn.commit()
            with self.assertRaises(sqlite3.DatabaseError):
                database.load_training_session(session.definition.exercise_id)


if __name__ == "__main__":
    unittest.main()
