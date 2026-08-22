import unittest

from acs.book_index import AmbiguousBookTargetError
from acs.bookdocument import BookDocument, Paragraph
from acs.bookreader import BookReader


class BookReaderAmbiguousPersistenceTests(unittest.TestCase):
    def test_snapshot_rejects_ambiguous_current_block_id_before_publishing_state(self):
        document = BookDocument(
            "Ambiguous IDs",
            blocks=[
                Paragraph(text="First", block_id="same"),
                Paragraph(text="Second", block_id="same"),
            ],
        )
        reader = BookReader(document)

        with self.assertRaisesRegex(AmbiguousBookTargetError, "ambiguous"):
            reader.snapshot()

    def test_snapshot_rejects_ambiguous_current_source_anchor_before_publishing_state(self):
        document = BookDocument(
            "Ambiguous anchors",
            blocks=[
                Paragraph(text="First", source_anchor="same"),
                Paragraph(text="Second", source_anchor="same"),
            ],
        )
        reader = BookReader(document)
        reader.go_to(1)

        with self.assertRaisesRegex(AmbiguousBookTargetError, "ambiguous"):
            reader.snapshot()

    def test_failed_return_point_save_is_atomic_and_does_not_poison_later_snapshot(self):
        document = BookDocument(
            "Mixed identities",
            blocks=[
                Paragraph(text="First", block_id="same"),
                Paragraph(text="Second", block_id="same"),
                Paragraph(text="Unique", block_id="unique"),
            ],
        )
        reader = BookReader(document)

        with self.assertRaisesRegex(AmbiguousBookTargetError, "ambiguous"):
            reader.save_return_point("bad")

        reader.go_to(2)
        snapshot = reader.snapshot()
        self.assertEqual(snapshot["current_target"], "block:unique")
        self.assertEqual(snapshot["return_points"], {})

    def test_unique_semantic_target_still_roundtrips(self):
        document = BookDocument(
            "Unique",
            blocks=[
                Paragraph(text="First", source_anchor="first"),
                Paragraph(text="Second", block_id="second"),
            ],
        )
        reader = BookReader(document)
        reader.go_to(1)
        reader.save_return_point("place")

        snapshot = reader.snapshot()
        restored = BookReader.restore_snapshot(document, snapshot)

        self.assertEqual(restored.index, 1)
        self.assertEqual(restored.restore_return_point("place").block_id, "second")


if __name__ == "__main__":
    unittest.main()
