import unittest

from acs.book_index import AmbiguousBookTargetError
from acs.bookdocument import BookDocument, Diagram, Heading, Paragraph
from acs.bookreader import BOOK_READER_SNAPSHOT_SCHEMA_VERSION, BookReader


WHITE_FEN = "8/8/8/8/8/8/4K3/7k w - - 0 1"


class BookReaderProgressContractTests(unittest.TestCase):
    def make_original(self):
        return BookDocument(
            "Reader",
            blocks=[
                Heading(text="Part", level=1, block_id="part"),
                Paragraph(text="Intro", block_id="intro"),
                Diagram(fen=WHITE_FEN, alt_text="Kings", block_id="diagram", source_anchor="p3"),
                Paragraph(text="After", block_id="after"),
            ],
        )

    def make_reordered(self):
        return BookDocument(
            "Reader revised",
            blocks=[
                Heading(text="Part", level=1, block_id="part"),
                Paragraph(text="Inserted", block_id="inserted"),
                Paragraph(text="After", block_id="after"),
                Diagram(fen=WHITE_FEN, alt_text="Kings", block_id="diagram", source_anchor="p3"),
                Paragraph(text="Intro", block_id="intro"),
            ],
        )

    def test_snapshot_uses_strict_versioned_semantic_targets(self):
        reader = BookReader(self.make_original())
        reader.go_to(2)
        reader.save_return_point("analysis")
        snapshot = reader.snapshot()

        self.assertEqual(
            snapshot,
            {
                "schema_version": BOOK_READER_SNAPSHOT_SCHEMA_VERSION,
                "current_target": "block:diagram",
                "return_points": {"analysis": "block:diagram"},
                "fallback_digests": {},
            },
        )

    def test_current_location_and_return_point_survive_source_preserving_reorder(self):
        reader = BookReader(self.make_original())
        reader.go_to(2)
        reader.save_return_point("analysis")
        reader.go_to(3)
        snapshot = reader.snapshot()

        restored = BookReader.restore_snapshot(self.make_reordered(), snapshot)
        self.assertEqual(restored.location().block_id, "after")
        self.assertEqual(restored.location().index, 2)

        analysis = restored.restore_return_point("analysis")
        self.assertEqual(analysis.block_id, "diagram")
        self.assertEqual(analysis.index, 3)
        self.assertEqual(analysis.position_fen, WHITE_FEN)

    def test_missing_target_fails_instead_of_drifting_to_same_numeric_index(self):
        reader = BookReader(self.make_original())
        reader.go_to(2)
        snapshot = reader.snapshot()
        revised = BookDocument(
            "Missing target",
            blocks=[
                Heading(text="Part", level=1, block_id="part"),
                Paragraph(text="Replacement A", block_id="replacement-a"),
                Paragraph(text="Replacement B", block_id="replacement-b"),
            ],
        )
        with self.assertRaisesRegex(LookupError, "Unknown book target"):
            BookReader.restore_snapshot(revised, snapshot)

    def test_ambiguous_source_identity_fails_closed(self):
        snapshot = {
            "schema_version": BOOK_READER_SNAPSHOT_SCHEMA_VERSION,
            "current_target": "source:p3",
            "return_points": {},
            "fallback_digests": {},
        }
        ambiguous = BookDocument(
            "Ambiguous",
            blocks=[
                Diagram(fen=WHITE_FEN, alt_text="One", source_anchor="p3"),
                Diagram(fen=WHITE_FEN, alt_text="Two", source_anchor="p3"),
            ],
        )
        with self.assertRaises(AmbiguousBookTargetError):
            BookReader.restore_snapshot(ambiguous, snapshot)

    def test_snapshot_schema_fields_and_scalar_types_fail_closed(self):
        document = self.make_original()
        valid = {
            "schema_version": BOOK_READER_SNAPSHOT_SCHEMA_VERSION,
            "current_target": "block:part",
            "return_points": {},
            "fallback_digests": {},
        }
        cases = [
            (
                {
                    "schema_version": BOOK_READER_SNAPSHOT_SCHEMA_VERSION,
                    "current_target": "block:part",
                    "return_points": {},
                },
                ValueError,
            ),
            ({**valid, "extra": "future"}, ValueError),
            ({**valid, "schema_version": True}, TypeError),
            ({**valid, "schema_version": 1}, ValueError),
            ({**valid, "schema_version": 99}, ValueError),
            ({**valid, "current_target": 1}, TypeError),
            ({**valid, "return_points": []}, TypeError),
            ({**valid, "return_points": {"analysis": 3}}, TypeError),
            ({**valid, "fallback_digests": []}, TypeError),
            ({**valid, "fallback_digests": {1: "0" * 64}}, TypeError),
            ({**valid, "fallback_digests": {"index:0": 1}}, TypeError),
            ({**valid, "fallback_digests": {"block:part": "0" * 64}}, ValueError),
            ({**valid, "fallback_digests": {"index:0": "A" * 64}}, ValueError),
            ({**valid, "fallback_digests": {"index:0": "0" * 63}}, ValueError),
        ]
        for payload, error in cases:
            with self.subTest(payload=payload):
                with self.assertRaises(error):
                    BookReader.restore_snapshot(document, payload)

    def test_nonempty_snapshot_requires_current_target(self):
        with self.assertRaisesRegex(ValueError, "current_target"):
            BookReader.restore_snapshot(
                self.make_original(),
                {
                    "schema_version": BOOK_READER_SNAPSHOT_SCHEMA_VERSION,
                    "current_target": None,
                    "return_points": {},
                    "fallback_digests": {},
                },
            )

    def test_empty_book_roundtrip_is_explicit_and_stable(self):
        empty = BookDocument("Empty")
        snapshot = BookReader(empty).snapshot()
        self.assertEqual(snapshot["current_target"], None)
        self.assertEqual(snapshot["fallback_digests"], {})
        restored = BookReader.restore_snapshot(empty, snapshot)
        self.assertEqual(restored.index, -1)
        with self.assertRaisesRegex(LookupError, "no readable blocks"):
            restored.location()

    def test_index_and_return_point_names_reject_scalar_coercion(self):
        reader = BookReader(self.make_original())
        with self.assertRaises(TypeError):
            reader.go_to(True)
        with self.assertRaises(TypeError):
            reader.save_return_point(1)
        with self.assertRaises(ValueError):
            reader.save_return_point("   ")

    def test_index_only_targets_roundtrip_with_strict_semantic_digest(self):
        document = BookDocument(
            "Fallback",
            blocks=[
                Paragraph(text="Alpha"),
                Paragraph(text="Beta"),
            ],
        )
        reader = BookReader(document)
        reader.go_to(1)
        reader.save_return_point("beta")
        snapshot = reader.snapshot()

        self.assertEqual(snapshot["current_target"], "index:1")
        self.assertEqual(snapshot["return_points"], {"beta": "index:1"})
        self.assertEqual(set(snapshot["fallback_digests"]), {"index:1"})
        self.assertEqual(len(snapshot["fallback_digests"]["index:1"]), 64)

        restored = BookReader.restore_snapshot(document, snapshot)
        self.assertEqual(restored.index, 1)
        self.assertEqual(restored.restore_return_point("beta").index, 1)

    def test_index_only_target_rejects_inserted_block_at_same_numeric_fallback(self):
        original = BookDocument(
            "Fallback",
            blocks=[
                Paragraph(text="Alpha"),
                Paragraph(text="Beta"),
            ],
        )
        reader = BookReader(original)
        reader.go_to(1)
        snapshot = reader.snapshot()

        revised = BookDocument(
            "Fallback revised",
            blocks=[
                Paragraph(text="Inserted"),
                Paragraph(text="Alpha"),
                Paragraph(text="Beta"),
            ],
        )
        with self.assertRaisesRegex(LookupError, "no longer identifies the same block"):
            BookReader.restore_snapshot(revised, snapshot)

    def test_index_only_target_rejects_semantic_edit_at_same_index(self):
        original = BookDocument("Fallback", blocks=[Paragraph(text="Alpha")])
        snapshot = BookReader(original).snapshot()
        revised = BookDocument("Fallback revised", blocks=[Paragraph(text="Changed")])

        with self.assertRaisesRegex(LookupError, "no longer identifies the same block"):
            BookReader.restore_snapshot(revised, snapshot)

    def test_index_only_target_requires_exact_digest_key_set(self):
        document = BookDocument("Fallback", blocks=[Paragraph(text="Alpha")])
        snapshot = BookReader(document).snapshot()

        missing = dict(snapshot)
        missing["fallback_digests"] = {}
        with self.assertRaisesRegex(ValueError, "do not match referenced index targets"):
            BookReader.restore_snapshot(document, missing)

        extra = dict(snapshot)
        extra["fallback_digests"] = {
            **snapshot["fallback_digests"],
            "index:9": "0" * 64,
        }
        with self.assertRaisesRegex(ValueError, "do not match referenced index targets"):
            BookReader.restore_snapshot(document, extra)


if __name__ == "__main__":
    unittest.main()
