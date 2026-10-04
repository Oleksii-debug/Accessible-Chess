from __future__ import annotations

import unittest
from unittest.mock import patch

import acs.book_training as book_training
from acs.book_training import (
    BookTrainingOrigin,
    build_book_training_material,
    build_current_book_training_material,
    resolve_book_training_origin,
    restore_book_training_material,
    return_reader_to_book_training_origin,
)
from acs.bookdocument import BookDocument, Exercise
from acs.bookreader import BookReader


KING_FEN = "8/8/8/8/8/8/4K3/7k w - - 0 1"


class BookTrainingPassiveRootsTests(unittest.TestCase):
    @staticmethod
    def _book() -> BookDocument:
        return BookDocument(
            "Passive provenance",
            language="en",
            author="Author",
            source_name="passive.md",
            blocks=[
                Exercise(
                    fen=KING_FEN,
                    prompt="Move the king.",
                    answer_text="Kf3",
                    block_id="exercise",
                    source_anchor="chapter:1:exercise",
                )
            ],
        )

    def test_build_rejects_document_subclass_before_metadata_hook(self) -> None:
        class HostileDocument(BookDocument):
            armed = False
            touched = False

            def __getattribute__(self, name):
                if type(self).armed and name in {
                    "title",
                    "language",
                    "author",
                    "source_name",
                    "blocks",
                    "as_dict",
                }:
                    type(self).touched = True
                    raise AssertionError(f"document hook must not execute: {name}")
                return super().__getattribute__(name)

        hostile = HostileDocument(
            "Hostile",
            blocks=[
                Exercise(
                    fen=KING_FEN,
                    prompt="Move.",
                    answer_text="Kf3",
                    block_id="exercise",
                )
            ],
        )
        HostileDocument.armed = True

        with self.assertRaisesRegex(TypeError, "^document must be a BookDocument$"):
            build_book_training_material(hostile, "block:exercise")

        self.assertFalse(HostileDocument.touched)

    def test_reader_subclass_rejected_before_navigation_or_document_hook(self) -> None:
        class HostileReader(BookReader):
            armed = False
            touched = False

            def location(self):
                if type(self).armed:
                    type(self).touched = True
                    raise AssertionError("reader location hook must not execute")
                return super().location()

            def __getattribute__(self, name):
                if type(self).armed and name == "document":
                    type(self).touched = True
                    raise AssertionError("reader document hook must not execute")
                return super().__getattribute__(name)

        hostile = HostileReader(self._book())
        HostileReader.armed = True

        with self.assertRaisesRegex(TypeError, "^reader must be a BookReader$"):
            build_current_book_training_material(hostile)
        self.assertFalse(HostileReader.touched)

        canonical = self._book()
        material = build_book_training_material(canonical, "block:exercise")
        with self.assertRaisesRegex(TypeError, "^reader must be a BookReader$"):
            return_reader_to_book_training_origin(hostile, material.origin)
        self.assertFalse(HostileReader.touched)

    def test_origin_subclass_rejected_before_identity_hook(self) -> None:
        material = build_book_training_material(self._book(), "block:exercise")

        class HostileOrigin(BookTrainingOrigin):
            armed = False
            touched = False

            def __getattribute__(self, name):
                if type(self).armed and name not in {
                    "armed",
                    "touched",
                    "__class__",
                }:
                    type(self).touched = True
                    raise AssertionError(f"origin hook must not execute: {name}")
                return super().__getattribute__(name)

        origin = HostileOrigin(
            target_key=material.origin.target_key,
            block_digest=material.origin.block_digest,
            index_at_export=material.origin.index_at_export,
            block_id=material.origin.block_id,
            source_anchor=material.origin.source_anchor,
            heading_path=material.origin.heading_path,
            book_fingerprint=material.origin.book_fingerprint,
        )
        HostileOrigin.armed = True

        with self.assertRaisesRegex(TypeError, "^origin must be a BookTrainingOrigin$"):
            resolve_book_training_origin(self._book(), origin)
        self.assertFalse(HostileOrigin.touched)

        reader = BookReader(self._book())
        with self.assertRaisesRegex(TypeError, "^origin must be a BookTrainingOrigin$"):
            return_reader_to_book_training_origin(reader, origin)
        self.assertFalse(HostileOrigin.touched)

    def test_block_digest_rejects_exercise_subclass_before_as_dict_hook(self) -> None:
        class HostileExercise(Exercise):
            armed = False
            touched = False

            def as_dict(self):
                if type(self).armed:
                    type(self).touched = True
                    raise AssertionError("Exercise subclass as_dict hook must not execute")
                return super().as_dict()

        hostile = HostileExercise(
            fen=KING_FEN,
            prompt="Move.",
            answer_text="Kf3",
        )
        HostileExercise.armed = True

        with self.assertRaisesRegex(
            TypeError,
            "^book training block must be an exact Exercise$",
        ):
            book_training._block_digest(hostile)

        self.assertFalse(HostileExercise.touched)

    def test_restore_rejects_document_subclass_before_payload_hook(self) -> None:
        book = self._book()
        material = build_book_training_material(book, "block:exercise")

        class HostileDocument(BookDocument):
            pass

        hostile_document = HostileDocument(
            book.title,
            language=book.language,
            author=book.author,
            source_name=book.source_name,
            blocks=list(book.blocks),
        )

        class HostilePayload(dict):
            touched = False

            def __len__(self):
                type(self).touched = True
                raise AssertionError("payload hook must not execute")

        payload = HostilePayload(material.as_dict())

        with self.assertRaisesRegex(TypeError, "^document must be a BookDocument$"):
            restore_book_training_material(hostile_document, payload)

        self.assertFalse(HostilePayload.touched)

    def test_current_material_uses_indexed_document_and_rechecks_live_revision(self) -> None:
        book = self._book()
        reader = BookReader(book)
        real_build = book_training.build_book_training_material

        class HostileBlocks(list):
            armed = False
            touched = False

            def __iter__(self):
                if type(self).armed:
                    type(self).touched = True
                    raise AssertionError("live Book blocks hook must not execute")
                return super().__iter__()

        def mutate_live_then_build(document, target):
            self.assertIsNot(document, book)
            hostile = HostileBlocks(book.blocks)
            book.blocks = hostile
            HostileBlocks.armed = True
            return real_build(document, target)

        with patch.object(
            book_training,
            "build_book_training_material",
            side_effect=mutate_live_then_build,
        ):
            with self.assertRaisesRegex(RuntimeError, "changed after BookReader creation"):
                build_current_book_training_material(reader)

        self.assertFalse(HostileBlocks.touched)
    def test_exact_book_training_provenance_round_trip_is_unchanged(self) -> None:
        book = self._book()
        material = build_book_training_material(book, "block:exercise")
        reader = BookReader(book)
        current = build_current_book_training_material(reader)
        restored = restore_book_training_material(book, material.as_dict())
        location = resolve_book_training_origin(book, material.origin)
        returned = return_reader_to_book_training_origin(reader, material.origin)

        self.assertEqual(current.as_dict(), material.as_dict())
        self.assertEqual(restored.as_dict(), material.as_dict())
        self.assertEqual(location.block_id, "exercise")
        self.assertEqual(returned.block_id, "exercise")
        self.assertEqual(reader.index, 0)


if __name__ == "__main__":
    unittest.main()
