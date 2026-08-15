import hashlib
import tempfile
import unittest
from pathlib import Path

from acs.chessbase_cbg import CbgDecodeError
from acs.chessbase_cbg_payload_evidence import (
    extract_cbg_move_payload_evidence,
    read_cbg_move_payload_evidence,
)


def _game(payload: bytes, *, custom=False, suffix=b"") -> bytes:
    prefix_size = 32 if custom else 4
    game_length = prefix_size + len(payload)
    flags = 0x40000000 if custom else 0
    data = bytearray(prefix_size)
    data[:4] = (flags | game_length).to_bytes(4, "big")
    return bytes(data) + payload + suffix


class ClassicCbgMovePayloadEvidenceTests(unittest.TestCase):
    def test_standard_payload_preserves_exact_opaque_bytes(self):
        payload = b"\x00\x7f\x80\xffmoves?"
        evidence = extract_cbg_move_payload_evidence(_game(payload), offset=0)

        self.assertEqual(evidence.payload_bytes, payload)
        self.assertEqual(evidence.payload_length, len(payload))
        self.assertEqual(evidence.payload_start_offset, 4)
        self.assertEqual(evidence.game_end_offset, 4 + len(payload))
        self.assertFalse(evidence.custom_setup_prefix_consumed)
        self.assertEqual(evidence.payload_sha256, hashlib.sha256(payload).hexdigest())

    def test_custom_payload_excludes_fixed_setup_prefix(self):
        payload = b"\xaa\xbb\xcc"
        evidence = extract_cbg_move_payload_evidence(_game(payload, custom=True), offset=0)

        self.assertEqual(evidence.payload_bytes, payload)
        self.assertEqual(evidence.payload_start_offset, 32)
        self.assertTrue(evidence.custom_setup_prefix_consumed)

    def test_trailing_file_bytes_are_not_claimed_as_payload(self):
        payload = b"\x01\x02"
        evidence = extract_cbg_move_payload_evidence(
            _game(payload, suffix=b"not-this-game"), offset=0
        )
        self.assertEqual(evidence.payload_bytes, payload)

    def test_empty_payload_has_stable_sha256(self):
        evidence = extract_cbg_move_payload_evidence(_game(b""), offset=0)
        self.assertEqual(evidence.payload_bytes, b"")
        self.assertEqual(evidence.payload_sha256, hashlib.sha256(b"").hexdigest())

    def test_unsupported_encoding_is_rejected_before_evidence_is_returned(self):
        data = bytearray(_game(b"x"))
        raw = int.from_bytes(data[:4], "big") | 0x80000000
        data[:4] = raw.to_bytes(4, "big")
        with self.assertRaisesRegex(CbgDecodeError, "encoding-flag"):
            extract_cbg_move_payload_evidence(bytes(data), offset=0)

    def test_file_reader_does_not_modify_source_bytes(self):
        source_bytes = _game(b"\x10\x20\x30")
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "sample.cbg"
            path.write_bytes(source_bytes)
            before = hashlib.sha256(path.read_bytes()).hexdigest()

            evidence = read_cbg_move_payload_evidence(path, offset=0)

            after = hashlib.sha256(path.read_bytes()).hexdigest()
            self.assertEqual(before, after)
            self.assertEqual(path.read_bytes(), source_bytes)
            self.assertEqual(evidence.payload_bytes, b"\x10\x20\x30")


if __name__ == "__main__":
    unittest.main()
