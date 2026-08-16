import hashlib
import tempfile
import unittest
from pathlib import Path

from acs.chessbase_cbh import parse_cbh_record
from acs.chessbase_cbh_cbg_batch import (
    project_cbh_records_to_cbg_payload_evidence,
    read_cbh_cbg_batch_projection,
)


def _cbh_record(*, game_offset: int, flags: int = 0x01, record_index: int = 1):
    raw = bytearray(46)
    raw[0] = flags
    raw[1:5] = game_offset.to_bytes(4, "big")
    return parse_cbh_record(bytes(raw), record_index=record_index)


def _cbg_game(payload: bytes, *, unsupported_encoding: bool = False) -> bytes:
    game_length = 4 + len(payload)
    raw_header = game_length | (0x80000000 if unsupported_encoding else 0)
    return raw_header.to_bytes(4, "big") + payload


def _cbh_file(records: list[bytes]) -> bytes:
    return b"\x00" * 46 + b"".join(records)


def _raw_cbh_record(*, game_offset: int, flags: int = 0x01) -> bytes:
    raw = bytearray(46)
    raw[0] = flags
    raw[1:5] = game_offset.to_bytes(4, "big")
    return bytes(raw)


class ClassicCbhCbgBatchProjectionTests(unittest.TestCase):
    def test_mixed_batch_preserves_order_and_isolates_failure(self):
        first_payload = b"first"
        first_game = _cbg_game(first_payload)
        bad_offset = len(first_game)
        bad_game = _cbg_game(b"bad", unsupported_encoding=True)
        third_offset = len(first_game) + len(bad_game)
        third_payload = b"third"
        cbg = first_game + bad_game + _cbg_game(third_payload)
        records = [
            _cbh_record(game_offset=0, record_index=1),
            _cbh_record(game_offset=bad_offset, record_index=2),
            _cbh_record(game_offset=third_offset, record_index=3),
        ]

        projection = project_cbh_records_to_cbg_payload_evidence(records, cbg)

        self.assertEqual([item.status for item in projection.items], ["linked", "failed", "linked"])
        self.assertEqual(projection.linked_count, 2)
        self.assertEqual(projection.failed_count, 1)
        self.assertEqual(projection.items[0].link.payload.payload_bytes, first_payload)
        self.assertEqual(projection.items[1].error_type, "CbgDecodeError")
        self.assertIn("encoding-flag", projection.items[1].reason)
        self.assertEqual(projection.items[2].link.payload.payload_bytes, third_payload)

    def test_non_game_and_deleted_records_are_explicitly_skipped(self):
        projection = project_cbh_records_to_cbg_payload_evidence(
            [
                _cbh_record(game_offset=0, flags=0x00, record_index=4),
                _cbh_record(game_offset=0, flags=0x81, record_index=5),
            ],
            b"",
        )

        self.assertEqual(projection.skipped_count, 2)
        self.assertEqual(projection.items[0].reason, "not-game-record")
        self.assertEqual(projection.items[1].reason, "marked-for-deletion")
        self.assertIsNone(projection.items[0].link)
        self.assertIsNone(projection.items[1].link)

    def test_out_of_range_pointer_does_not_hide_later_valid_record(self):
        payload = b"ok"
        cbg = _cbg_game(payload)
        records = [
            _cbh_record(game_offset=99, record_index=1),
            _cbh_record(game_offset=0, record_index=2),
        ]

        projection = project_cbh_records_to_cbg_payload_evidence(records, cbg)

        self.assertEqual(projection.items[0].status, "failed")
        self.assertEqual(projection.items[0].error_type, "CbgDecodeError")
        self.assertEqual(projection.items[1].status, "linked")
        self.assertEqual(projection.items[1].link.payload.payload_bytes, payload)

    def test_success_keeps_exact_payload_hash_evidence(self):
        payload = b"\x00\x10opaque\xff"
        projection = project_cbh_records_to_cbg_payload_evidence(
            [_cbh_record(game_offset=0)],
            _cbg_game(payload),
        )

        evidence = projection.items[0].link.payload
        self.assertEqual(evidence.payload_bytes, payload)
        self.assertEqual(evidence.payload_sha256, hashlib.sha256(payload).hexdigest())

    def test_empty_record_batch_is_a_valid_empty_projection(self):
        projection = project_cbh_records_to_cbg_payload_evidence([], b"arbitrary")
        self.assertEqual(projection.items, ())
        self.assertEqual(projection.linked_count, 0)
        self.assertEqual(projection.skipped_count, 0)
        self.assertEqual(projection.failed_count, 0)

    def test_file_projection_preserves_both_source_files(self):
        payload = b"opaque-source-evidence"
        cbg_bytes = _cbg_game(payload)
        cbh_bytes = _cbh_file([_raw_cbh_record(game_offset=0)])

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            cbh_path = root / "sample.cbh"
            cbg_path = root / "sample.cbg"
            cbh_path.write_bytes(cbh_bytes)
            cbg_path.write_bytes(cbg_bytes)
            before_cbh = hashlib.sha256(cbh_path.read_bytes()).hexdigest()
            before_cbg = hashlib.sha256(cbg_path.read_bytes()).hexdigest()

            projection = read_cbh_cbg_batch_projection(cbh_path, cbg_path)

            self.assertEqual(projection.linked_count, 1)
            self.assertEqual(projection.items[0].link.payload.payload_bytes, payload)
            self.assertEqual(hashlib.sha256(cbh_path.read_bytes()).hexdigest(), before_cbh)
            self.assertEqual(hashlib.sha256(cbg_path.read_bytes()).hexdigest(), before_cbg)
            self.assertEqual(cbh_path.read_bytes(), cbh_bytes)
            self.assertEqual(cbg_path.read_bytes(), cbg_bytes)


if __name__ == "__main__":
    unittest.main()
