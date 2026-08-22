import unittest

from acs.bookdocument import BookDocument, Heading, Paragraph
from acs.bookreader import BookReader


class BookReaderLiveMutationGuardTests(unittest.TestCase):
    def make_book(self):
        return BookDocument(
            "Mutable source",
            blocks=[
                Heading(text="Start", level=1, block_id="start"),
                Paragraph(text="Alpha", block_id="alpha"),
                Paragraph(text="Beta", source_anchor="source-beta"),
            ],
        )

    def test_snapshot_fails_closed_after_block_reorder(self):
        document = self.make_book()
        reader = BookReader(document)
        reader.go_to(1)
        reader.save_return_point("resume")

        document.blocks[1], document.blocks[2] = document.blocks[2], document.blocks[1]

        with self.assertRaisesRegex(RuntimeError, "changed after BookReader creation"):
            reader.snapshot()

    def test_return_point_restore_fails_closed_after_in_place_identity_edit(self):
        document = self.make_book()
        reader = BookReader(document)
        reader.go_to(2)
        reader.save_return_point("resume")

        document.blocks[2].source_anchor = "source-rewritten"

        with self.assertRaisesRegex(RuntimeError, "changed after BookReader creation"):
            reader.restore_return_point("resume")

    def test_new_return_point_cannot_be_published_through_stale_index(self):
        document = self.make_book()
        reader = BookReader(document)
        reader.go_to(1)

        document.blocks.insert(1, Paragraph(text="Inserted", block_id="inserted"))

        with self.assertRaisesRegex(RuntimeError, "changed after BookReader creation"):
            reader.save_return_point("stale")

    def test_progress_saved_before_edit_restores_in_fresh_reader_after_semantic_reorder(self):
        document = self.make_book()
        reader = BookReader(document)
        reader.go_to(1)
        reader.save_return_point("resume")
        snapshot = reader.snapshot()

        revised = BookDocument(
            "Mutable source",
            blocks=[
                document.blocks[0],
                document.blocks[2],
                document.blocks[1],
            ],
        )
        restored = BookReader.restore_snapshot(revised, snapshot)

        self.assertEqual(restored.location().block_id, "alpha")
        self.assertEqual(restored.restore_return_point("resume").block_id, "alpha")


if __name__ == "__main__":
    unittest.main()
