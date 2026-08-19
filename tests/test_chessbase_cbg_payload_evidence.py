import hashlib
import io
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from acs.chessbase_cbg import CbgDecodeError
from acs.chessbase_cbg_payload_evidence import (
    MAX_CLASSIC_CBG_PAYLOAD_BYTES,
    extract_cbg_move_payload_evidence,
    read_cbg_move_payload_evidence,
)


class _BoundedBytesIO(io.BytesIO):
    def __init__(self, data):
        super().__init__(data)
        self.read_sizes = []

    def read(self, size=-1):
        if size < 0:
            raise AssertionError("reader attempted an unbounded CBG payload read")
        self.read_sizes.append(size)
        return super().read(size)


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

    def test_file_reader_reads_only_header_and_declared_payload(self):
        source_bytes = _game(b"bounded")
        stream = _BoundedBytesIO(source_bytes)
        with mock.patch(
            "pathlib.Path.open",
            return_value=stream,
        ):
            evidence = read_cbg_move_payload_evidence("ignored.cbg", offset=0)

        self.assertEqual(evidence.payload_bytes, b"bounded")
        self.assertEqual(stream.read_sizes, [4, len(b"bounded")])

    def test_configured_payload_bound_fails_before_payload_read(self):
        source_bytes = _game(b"four")
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "bounded.cbg"
            path.write_bytes(source_bytes)
            with self.assertRaisesRegex(CbgDecodeError, "exceeds configured bound"):
                read_cbg_move_payload_evidence(
                    path,
                    offset=0,
                    max_payload_bytes=3,
                )

        self.assertGreaterEqual(MAX_CLASSIC_CBG_PAYLOAD_BYTES, len(b"four"))

    def test_payload_bound_requires_exact_non_negative_integer(self):
        for value in (-1, True, 1.5):
            with self.subTest(value=value):
                with self.assertRaisesRegex(CbgDecodeError, "max_payload_bytes"):
                    read_cbg_move_payload_evidence(
                        "not-opened.cbg",
                        offset=0,
                        max_payload_bytes=value,
                    )


if __name__ == "__main__":
    unittest.main()
