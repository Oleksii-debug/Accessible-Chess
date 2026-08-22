import unittest

from acs.bookdocument import BookDocument, Heading
from acs.bookreader import BookReader


class BookReaderSnapshotBoundsTests(unittest.TestCase):
    def make_book(self):
        return BookDocument(
            "Bounded reader",
            blocks=[Heading(text="Chapter", level=1, block_id="chapter")],
        )

    def valid_snapshot(self):
        return BookReader(self.make_book()).snapshot()

    def test_return_point_name_is_bounded_before_state_mutation(self):
        reader = BookReader(self.make_book())
        with self.assertRaisesRegex(ValueError, "Return point name exceeds 256"):
            reader.save_return_point("x" * 257)
        self.assertEqual(reader.snapshot()["return_points"], {})

    def test_exact_return_point_name_limit_is_accepted(self):
        reader = BookReader(self.make_book())
        name = "x" * 256
        reader.save_return_point(name)
        self.assertIn(name, reader.snapshot()["return_points"])

    def test_restore_rejects_too_many_return_points_before_iterating_entries(self):
        snapshot = self.valid_snapshot()
        snapshot["return_points"] = {
            f"bookmark-{index}": snapshot["current_target"]
            for index in range(1001)
        }
        with self.assertRaisesRegex(ValueError, "exceeds 1000 return points"):
            BookReader.restore_snapshot(self.make_book(), snapshot)

    def test_restore_accepts_exact_return_point_limit(self):
        snapshot = self.valid_snapshot()
        snapshot["return_points"] = {
            f"b{index}": snapshot["current_target"]
            for index in range(1000)
        }
        restored = BookReader.restore_snapshot(self.make_book(), snapshot)
        self.assertEqual(len(restored.snapshot()["return_points"]), 1000)

    def test_current_target_key_is_bounded_before_resolution(self):
        snapshot = self.valid_snapshot()
        snapshot["current_target"] = "x" * 4097
        with self.assertRaisesRegex(ValueError, "current_target exceeds 4096"):
            BookReader.restore_snapshot(self.make_book(), snapshot)

    def test_return_point_target_key_is_bounded_before_resolution(self):
        snapshot = self.valid_snapshot()
        snapshot["return_points"] = {"a": "x" * 4097}
        with self.assertRaisesRegex(ValueError, "target key exceeds 4096"):
            BookReader.restore_snapshot(self.make_book(), snapshot)

    def test_fallback_digest_mapping_count_is_bounded_before_iteration(self):
        snapshot = self.valid_snapshot()
        snapshot["fallback_digests"] = {
            f"index:{index}": "0" * 64
            for index in range(1002)
        }
        with self.assertRaisesRegex(ValueError, "too many fallback digests"):
            BookReader.restore_snapshot(self.make_book(), snapshot)

    def test_fallback_digest_key_is_bounded_before_resolution(self):
        snapshot = self.valid_snapshot()
        snapshot["fallback_digests"] = {"index:" + "x" * 4091: "0" * 64}
        with self.assertRaisesRegex(ValueError, "fallback digest key exceeds 4096"):
            BookReader.restore_snapshot(self.make_book(), snapshot)

    def test_snapshot_rejects_out_of_contract_in_memory_return_point_count(self):
        reader = BookReader(self.make_book())
        target = reader.snapshot()["current_target"]
        reader._return_points = {f"b{index}": target for index in range(1001)}
        with self.assertRaisesRegex(ValueError, "at most 1000 return points"):
            reader.snapshot()


if __name__ == "__main__":
    unittest.main()
