from __future__ import annotations

import hashlib
import json
import unittest
from unittest.mock import patch

from acs.bookdocument import BookDocument, Heading, Paragraph
from acs.bookreader import BookReader


class BookReaderRevisionBarrierCurrentTests(unittest.TestCase):
    @staticmethod
    def make_book() -> BookDocument:
        return BookDocument(
            "Book",
            blocks=[
                Heading(text="One", level=1),
                Paragraph(text="alpha"),
                Heading(text="Two", level=1),
                Paragraph(text="beta"),
            ],
        )

    def test_revision_digest_streams_exact_legacy_canonical_bytes(self) -> None:
        book = self.make_book()
        legacy_payload = json.dumps(
            [block.as_dict() for block in book.blocks],
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
        expected = hashlib.sha256(legacy_payload).hexdigest()

        original_dumps = json.dumps
        dumped_values: list[object] = []

        def guarded_dumps(value, *args, **kwargs):
            self.assertNotIsInstance(value, list)
            dumped_values.append(value)
            return original_dumps(value, *args, **kwargs)

        with patch("acs.bookreader.json.dumps", side_effect=guarded_dumps):
            actual = BookReader._revision_digest(book.blocks)

        self.assertEqual(actual, expected)
        self.assertEqual(len(dumped_values), len(book.blocks))
        self.assertTrue(all(type(value) is dict for value in dumped_values))

    def test_location_keeps_one_live_revision_preflight(self) -> None:
        reader = BookReader(self.make_book())
        with patch.object(
            reader,
            "_document_revision_digest",
            wraps=reader._document_revision_digest,
        ) as digest:
            location = reader.location()

        self.assertEqual(location.index, 0)
        self.assertEqual(digest.call_count, 1)

    def test_next_block_uses_preflight_and_final_barrier_only(self) -> None:
        reader = BookReader(self.make_book())
        with patch.object(
            reader,
            "_document_revision_digest",
            wraps=reader._document_revision_digest,
        ) as digest:
            location = reader.next_block()

        self.assertEqual(location.index, 1)
        self.assertEqual(digest.call_count, 2)

    def test_semantic_navigation_uses_preflight_and_final_barrier_only(self) -> None:
        reader = BookReader(self.make_book())
        with patch.object(
            reader,
            "_document_revision_digest",
            wraps=reader._document_revision_digest,
        ) as digest:
            location = reader.next_heading()

        self.assertEqual(location.index, 2)
        self.assertEqual(digest.call_count, 2)

    def test_save_return_point_uses_two_revision_reads(self) -> None:
        reader = BookReader(self.make_book())
        reader.go_to(1)

        with patch.object(
            reader,
            "_document_revision_digest",
            wraps=reader._document_revision_digest,
        ) as digest:
            location = reader.save_return_point("analysis")

        self.assertEqual(location.index, 1)
        self.assertEqual(digest.call_count, 2)

    def test_snapshot_revision_reads_do_not_scale_with_return_points(self) -> None:
        reader = BookReader(self.make_book())
        for index in range(4):
            reader.go_to(index)
            reader.save_return_point(f"p{index}")

        with patch.object(
            reader,
            "_document_revision_digest",
            wraps=reader._document_revision_digest,
        ) as digest:
            snapshot = reader.snapshot()

        self.assertEqual(len(snapshot["return_points"]), 4)
        self.assertEqual(digest.call_count, 2)

    def test_restore_revision_reads_do_not_scale_with_fallback_targets(self) -> None:
        book = self.make_book()
        reader = BookReader(book)
        for index in range(4):
            reader.go_to(index)
            reader.save_return_point(f"p{index}")
        snapshot = reader.snapshot()

        original = BookReader._document_revision_digest
        calls = 0

        def counted(instance: BookReader) -> str:
            nonlocal calls
            calls += 1
            return original(instance)

        with patch.object(BookReader, "_document_revision_digest", counted):
            restored = BookReader.restore_snapshot(book, snapshot)

        # One constructor check, one restore preflight, the target-navigation
        # publication barrier and one final restore barrier: constant work,
        # independent of the number of referenced fallback targets.
        self.assertEqual(calls, 4)
        self.assertEqual(restored.index, reader.index)
        self.assertEqual(restored.snapshot(), snapshot)

    def test_final_navigation_barrier_still_detects_live_authoring_drift(self) -> None:
        book = self.make_book()
        reader = BookReader(book)
        before = reader.index

        original_location = reader._location_after_verified

        def mutate_then_snapshot():
            location = original_location()
            book.blocks[1].text = "changed concurrently"
            return location

        with patch.object(reader, "_location_after_verified", mutate_then_snapshot):
            with self.assertRaisesRegex(
                RuntimeError,
                "changed after BookReader creation",
            ):
                reader.next_block()

        self.assertEqual(reader.index, before)


    def test_navigation_abort_at_final_revision_barrier_rolls_back_cursor(self) -> None:
        class AbortSignal(BaseException):
            pass

        reader = BookReader(self.make_book())
        before = reader.index
        original_digest = reader._document_revision_digest
        calls = 0

        def abort_second_revision_read() -> str:
            nonlocal calls
            calls += 1
            if calls == 2:
                raise AbortSignal("simulated final navigation abort")
            return original_digest()

        with patch.object(
            reader,
            "_document_revision_digest",
            side_effect=abort_second_revision_read,
        ):
            with self.assertRaises(AbortSignal):
                reader.next_block()

        self.assertEqual(before, reader.index)
        self.assertEqual(calls, 2)

    def test_semantic_navigation_abort_at_final_barrier_rolls_back_cursor(self) -> None:
        class AbortSignal(BaseException):
            pass

        reader = BookReader(self.make_book())
        before = reader.index
        original_digest = reader._document_revision_digest
        calls = 0

        def abort_second_revision_read() -> str:
            nonlocal calls
            calls += 1
            if calls == 2:
                raise AbortSignal("simulated semantic-navigation abort")
            return original_digest()

        with patch.object(
            reader,
            "_document_revision_digest",
            side_effect=abort_second_revision_read,
        ):
            with self.assertRaises(AbortSignal):
                reader.next_heading()

        self.assertEqual(before, reader.index)
        self.assertEqual(calls, 2)

    def test_save_return_point_abort_at_final_revision_barrier_rolls_back_binding(self) -> None:
        class AbortSignal(BaseException):
            pass

        reader = BookReader(self.make_book())
        reader.go_to(1)
        original_digest = reader._document_revision_digest
        calls = 0

        def abort_second_revision_read() -> str:
            nonlocal calls
            calls += 1
            if calls == 2:
                raise AbortSignal("simulated final revision abort")
            return original_digest()

        with patch.object(
            reader,
            "_document_revision_digest",
            side_effect=abort_second_revision_read,
        ):
            with self.assertRaises(AbortSignal):
                reader.save_return_point("analysis")

        with self.assertRaises(LookupError):
            reader.restore_return_point("analysis")
        self.assertEqual(1, reader.index)


    def test_provisional_return_point_rejects_successful_handoff_after_live_drift(self) -> None:
        book = self.make_book()
        reader = BookReader(book)
        reader.go_to(1)
        before_return_points = dict(reader._return_points)

        with self.assertRaisesRegex(
            RuntimeError,
            "changed after BookReader creation",
        ):
            with reader.provisional_return_point("handoff") as location:
                self.assertEqual(location.index, 1)
                book.blocks[1].text = "changed during synchronous handoff"

        self.assertEqual(reader._return_points, before_return_points)
        with self.assertRaises(LookupError):
            reader.restore_return_point("handoff")

    def test_provisional_return_point_rejects_reentrant_named_overwrite(self) -> None:
        reader = BookReader(self.make_book())
        reader.go_to(1)
        reader.save_return_point("handoff")
        previous = reader.restore_return_point("handoff")
        self.assertEqual(previous.index, 1)

        reader.go_to(0)
        with self.assertRaisesRegex(
            RuntimeError,
            "provisional return point changed during handoff",
        ):
            with reader.provisional_return_point("handoff") as location:
                self.assertEqual(location.index, 0)
                reader.go_to(2)
                reader.save_return_point("handoff")

        # The failed provisional transaction restores the exact binding that
        # existed before the handoff rather than retaining either competing key.
        self.assertEqual(reader.restore_return_point("handoff").index, 1)

    def test_new_provisional_return_point_rejects_reentrant_named_overwrite(self) -> None:
        reader = BookReader(self.make_book())
        reader.go_to(0)

        with self.assertRaisesRegex(
            RuntimeError,
            "provisional return point changed during handoff",
        ):
            with reader.provisional_return_point("handoff") as location:
                self.assertEqual(location.index, 0)
                reader.go_to(2)
                reader.save_return_point("handoff")

        with self.assertRaises(LookupError):
            reader.restore_return_point("handoff")

    def test_provisional_return_point_success_has_final_revision_barrier(self) -> None:
        reader = BookReader(self.make_book())
        reader.go_to(1)

        with patch.object(
            reader,
            "_document_revision_digest",
            wraps=reader._document_revision_digest,
        ) as digest:
            with reader.provisional_return_point("handoff") as location:
                self.assertEqual(location.index, 1)

        # save_return_point performs preflight + publication validation; the
        # context manager adds one final post-handoff revision barrier.
        self.assertEqual(digest.call_count, 3)
        self.assertEqual(reader.restore_return_point("handoff").index, 1)


if __name__ == "__main__":
    unittest.main()
