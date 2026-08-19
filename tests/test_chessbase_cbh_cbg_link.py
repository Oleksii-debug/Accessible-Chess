import hashlib
import tempfile
import unittest
from pathlib import Path

from acs.chessbase_cbg import CbgDecodeError
from acs.chessbase_cbh import parse_cbh_record
from acs.chessbase_cbh_cbg_link import (
    CbhCbgLinkError,
    link_cbh_record_to_cbg_payload,
    read_cbh_record_cbg_payload_link,
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


class ClassicCbhCbgPayloadLinkTests(unittest.TestCase):
    def test_eligible_record_links_exact_nonzero_cbg_offset(self):
        prefix = b"prefix-bytes"
        payload = b"\x10\x20\x30\xff"
        cbg = prefix + _cbg_game(payload) + b"trailing-file-bytes"
        record = _cbh_record(game_offset=len(prefix), record_index=7)

        link = link_cbh_record_to_cbg_payload(record, cbg)

        self.assertEqual(link.record_index, 7)
        self.assertEqual(link.game_offset, len(prefix))
        self.assertEqual(link.payload.payload_bytes, payload)
        self.assertEqual(
            link.payload.payload_sha256,
            hashlib.sha256(payload).hexdigest(),
        )
        self.assertEqual(link.payload.payload_start_offset, len(prefix) + 4)

    def test_non_game_record_is_rejected_explicitly(self):
        record = _cbh_record(game_offset=0, flags=0x00)
        with self.assertRaisesRegex(CbhCbgLinkError, "not a game record"):
            link_cbh_record_to_cbg_payload(record, b"")

    def test_deleted_game_record_is_rejected_explicitly(self):
        record = _cbh_record(game_offset=0, flags=0x81)
        with self.assertRaisesRegex(CbhCbgLinkError, "marked for deletion"):
            link_cbh_record_to_cbg_payload(record, b"")

    def test_cbg_unsupported_state_is_preserved(self):
        cbg = _cbg_game(b"x", unsupported_encoding=True)
        record = _cbh_record(game_offset=0)
        with self.assertRaisesRegex(CbgDecodeError, "encoding-flag"):
            link_cbh_record_to_cbg_payload(record, cbg)

    def test_out_of_range_cross_file_pointer_is_rejected(self):
        record = _cbh_record(game_offset=99)
        with self.assertRaises(CbgDecodeError):
            link_cbh_record_to_cbg_payload(record, _cbg_game(b"x"))

    def test_file_reader_preserves_source_bytes(self):
        prefix = b"abcd"
        payload = b"opaque"
        source_bytes = prefix + _cbg_game(payload)
        record = _cbh_record(game_offset=len(prefix))

        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "sample.cbg"
            path.write_bytes(source_bytes)
            before = hashlib.sha256(path.read_bytes()).hexdigest()

            link = read_cbh_record_cbg_payload_link(record, path)

            after = hashlib.sha256(path.read_bytes()).hexdigest()
            self.assertEqual(before, after)
            self.assertEqual(path.read_bytes(), source_bytes)
            self.assertEqual(link.payload.payload_bytes, payload)


if __name__ == "__main__":
    unittest.main()
