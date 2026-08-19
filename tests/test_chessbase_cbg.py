import io
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from acs.chessbase_cbg import (
    CbgDecodeError,
    decode_cbg_setup_pieces,
    parse_cbg_custom_setup,
    parse_cbg_game_header,
    read_cbg_custom_setup,
    read_cbg_game_header,
)


class _BoundedBytesIO(io.BytesIO):
    def __init__(self, data):
        super().__init__(data)
        self.read_sizes = []

    def read(self, size=-1):
        if size < 0:
            raise AssertionError("reader attempted an unbounded CBG read")
        self.read_sizes.append(size)
        return super().read(size)


def _cbg_image(*, offset=0, game_length=12, flags=0, suffix=0):
    raw = flags | game_length
    data = bytearray(offset + game_length + suffix)
    data[offset:offset + 4] = raw.to_bytes(4, "big")
    return bytes(data)


def _setup_bytes(*pieces):
    """Encode test-only square/code pairs using the pinned setup token framing."""

    by_square = dict(pieces)
    bits = []
    for file_index in range(8):
        for rank in range(1, 9):
            square = f"{chr(ord('a') + file_index)}{rank}"
            code = by_square.get(square)
            bits.append("0" if code is None else f"{code:05b}")
    payload = "".join(bits)
    if len(payload) > 192:
        raise ValueError("test setup exceeds fixed 24-byte bitstream")
    payload += "0" * (192 - len(payload))
    return bytes(int(payload[index:index + 8], 2) for index in range(0, 192, 8))


def _cbg_custom_setup_image(
    *,
    offset=0,
    metadata=0,
    castling=0,
    next_move_number=1,
    setup_bytes=None,
    flags=0,
    game_length=32,
):
    if setup_bytes is None:
        setup_bytes = bytes(24)
    data = bytearray(
        _cbg_image(
            offset=offset,
            game_length=game_length,
            flags=0x40000000 | flags,
        )
    )
    if game_length >= 8:
        data[offset + 5] = metadata
        data[offset + 6] = castling
        data[offset + 7] = next_move_number
    if game_length >= 32:
        data[offset + 8:offset + 32] = setup_bytes
    return bytes(data)


class ClassicCbgHeaderTests(unittest.TestCase):
    def test_decodes_big_endian_length_and_custom_start(self):
        data = _cbg_image(offset=7, game_length=0x123, flags=0x40000000)

        header = parse_cbg_game_header(data, offset=7)

        self.assertEqual(header.offset, 7)
        self.assertEqual(header.game_length, 0x123)
        self.assertTrue(header.starts_from_custom_position)
        self.assertFalse(header.encoding_flag_set)
        self.assertFalse(header.is_chess960)
        self.assertFalse(header.has_special_encoding)
        self.assertTrue(header.supported_by_pinned_decoder)
        self.assertEqual(header.unsupported_reasons, ())

    def test_encoding_flag_is_explicitly_unsupported(self):
        header = parse_cbg_game_header(
            _cbg_image(game_length=12, flags=0x80000000), offset=0
        )
        self.assertTrue(header.encoding_flag_set)
        self.assertEqual(header.unsupported_reasons, ("encoding-flag",))
        self.assertFalse(header.supported_by_pinned_decoder)

    def test_chess960_mask_is_explicitly_unsupported(self):
        for flag in (0x02000000, 0x08000000, 0x0A000000):
            with self.subTest(flag=hex(flag)):
                header = parse_cbg_game_header(
                    _cbg_image(game_length=12, flags=flag), offset=0
                )
                self.assertTrue(header.is_chess960)
                self.assertIn("chess960", header.unsupported_reasons)
                self.assertFalse(header.supported_by_pinned_decoder)

    def test_special_encoding_is_explicitly_unsupported(self):
        header = parse_cbg_game_header(
            _cbg_image(game_length=12, flags=0x04000000), offset=0
        )
        self.assertTrue(header.has_special_encoding)
        self.assertEqual(header.unsupported_reasons, ("special-encoding",))
        self.assertFalse(header.supported_by_pinned_decoder)

    def test_combined_unsupported_reasons_are_stable(self):
        header = parse_cbg_game_header(
            _cbg_image(
                game_length=12,
                flags=0x80000000 | 0x02000000 | 0x04000000,
            ),
            offset=0,
        )
        self.assertEqual(
            header.unsupported_reasons,
            ("encoding-flag", "chess960", "special-encoding"),
        )

    def test_declared_game_must_fit_inside_file(self):
        data = bytearray(10)
        data[0:4] = (20).to_bytes(4, "big")
        with self.assertRaisesRegex(CbgDecodeError, "declared end 20"):
            parse_cbg_game_header(bytes(data), offset=0)

    def test_declared_game_length_must_include_header(self):
        for game_length in (0, 1, 2, 3):
            with self.subTest(game_length=game_length):
                data = bytearray(4)
                data[0:4] = game_length.to_bytes(4, "big")
                with self.assertRaisesRegex(CbgDecodeError, "invalid length"):
                    parse_cbg_game_header(bytes(data), offset=0)

    def test_truncated_header_is_rejected(self):
        with self.assertRaisesRegex(CbgDecodeError, "header at offset 2 is truncated"):
            parse_cbg_game_header(b"12345", offset=2)

    def test_invalid_offset_is_rejected(self):
        data = _cbg_image(game_length=12)
        for value in (-1, True, 1.5):
            with self.subTest(value=value):
                with self.assertRaisesRegex(CbgDecodeError, "non-negative integer"):
                    parse_cbg_game_header(data, offset=value)

    def test_read_path_is_read_only(self):
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "games.cbg"
            original = _cbg_image(offset=5, game_length=16, flags=0x40000000)
            path.write_bytes(original)

            header = read_cbg_game_header(path, offset=5)

            self.assertEqual(header.game_length, 16)
            self.assertTrue(header.starts_from_custom_position)
            self.assertEqual(path.read_bytes(), original)

    def test_file_header_reader_reads_only_the_fixed_header(self):
        stream = _BoundedBytesIO(_cbg_image(offset=5, game_length=16))
        with mock.patch("acs.chessbase_cbg.Path.open", return_value=stream):
            header = read_cbg_game_header("ignored.cbg", offset=5)

        self.assertEqual(header.game_length, 16)
        self.assertEqual(stream.read_sizes, [4])


class ClassicCbgSetupPieceTests(unittest.TestCase):
    def test_decodes_pinned_piece_codes_and_square_order(self):
        setup_bytes = _setup_bytes(
            ("a1", 0b10001),
            ("a8", 0b10110),
            ("b1", 0b11001),
            ("h8", 0b11110),
        )

        pieces = decode_cbg_setup_pieces(setup_bytes)

        self.assertEqual(
            [(item.square, item.color, item.role, item.raw_code) for item in pieces],
            [
                ("a1", "white", "king", 0b10001),
                ("a8", "white", "pawn", 0b10110),
                ("b1", "black", "king", 0b11001),
                ("h8", "black", "pawn", 0b11110),
            ],
        )

    def test_rejects_unknown_piece_code_instead_of_guessing(self):
        bits = "10111" + "0" * 187
        setup_bytes = bytes(
            int(bits[index:index + 8], 2) for index in range(0, 192, 8)
        )

        with self.assertRaisesRegex(CbgDecodeError, "unsupported.*piece code"):
            decode_cbg_setup_pieces(setup_bytes)

    def test_rejects_bitstream_that_ends_inside_piece_code(self):
        bits = ("10001" * 38) + "10"
        setup_bytes = bytes(
            int(bits[index:index + 8], 2) for index in range(0, 192, 8)
        )

        with self.assertRaisesRegex(CbgDecodeError, "ends inside a five-bit piece code"):
            decode_cbg_setup_pieces(setup_bytes)

    def test_requires_exact_fixed_bitstream_size(self):
        for payload in (b"", bytes(23), bytes(25)):
            with self.subTest(length=len(payload)):
                with self.assertRaisesRegex(CbgDecodeError, "exactly 24 bytes"):
                    decode_cbg_setup_pieces(payload)


class ClassicCbgSetupTests(unittest.TestCase):
    def test_extracts_only_evidence_backed_setup_prefix(self):
        setup_bytes = _setup_bytes(
            ("c3", 0b10011),
            ("f6", 0b11100),
        )
        data = _cbg_custom_setup_image(
            offset=9,
            metadata=0x10 | 0x05,
            castling=0x01 | 0x02 | 0x08,
            next_move_number=37,
            setup_bytes=setup_bytes,
        )

        setup = parse_cbg_custom_setup(data, offset=9)

        self.assertEqual(setup.offset, 9)
        self.assertEqual(setup.en_passant_file_code, 5)
        self.assertTrue(setup.black_to_move)
        self.assertTrue(setup.white_castle_long)
        self.assertTrue(setup.white_castle_short)
        self.assertFalse(setup.black_castle_long)
        self.assertTrue(setup.black_castle_short)
        self.assertEqual(setup.next_move_number, 37)
        self.assertEqual(setup.setup_bytes, setup_bytes)
        self.assertEqual(
            [(item.square, item.color, item.role) for item in setup.pieces],
            [("c3", "white", "knight"), ("f6", "black", "bishop")],
        )

    def test_metadata_ignores_unverified_bits(self):
        data = _cbg_custom_setup_image(metadata=0xE8, castling=0xF0)

        setup = parse_cbg_custom_setup(data, offset=0)

        self.assertEqual(setup.en_passant_file_code, 0)
        self.assertFalse(setup.black_to_move)
        self.assertFalse(setup.white_castle_long)
        self.assertFalse(setup.white_castle_short)
        self.assertFalse(setup.black_castle_long)
        self.assertFalse(setup.black_castle_short)
        self.assertEqual(setup.pieces, ())

    def test_non_custom_start_is_rejected(self):
        data = _cbg_image(game_length=32)
        with self.assertRaisesRegex(CbgDecodeError, "does not declare a custom start"):
            parse_cbg_custom_setup(data, offset=0)

    def test_unsupported_header_states_are_rejected_before_setup(self):
        for flag, reason in (
            (0x80000000, "encoding-flag"),
            (0x02000000, "chess960"),
            (0x04000000, "special-encoding"),
        ):
            with self.subTest(flag=hex(flag)):
                data = _cbg_custom_setup_image(flags=flag)
                with self.assertRaisesRegex(CbgDecodeError, reason):
                    parse_cbg_custom_setup(data, offset=0)

    def test_declared_game_must_contain_complete_fixed_setup_prefix(self):
        for game_length in (8, 31):
            with self.subTest(game_length=game_length):
                data = _cbg_custom_setup_image(game_length=game_length)
                with self.assertRaisesRegex(CbgDecodeError, "need at least 32 bytes"):
                    parse_cbg_custom_setup(data, offset=0)

    def test_setup_reader_is_read_only(self):
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "games.cbg"
            original = _cbg_custom_setup_image(
                offset=4,
                metadata=0x12,
                castling=0x0F,
                next_move_number=12,
                setup_bytes=_setup_bytes(("e1", 0b10001), ("e8", 0b11001)),
            )
            path.write_bytes(original)

            setup = read_cbg_custom_setup(path, offset=4)

            self.assertTrue(setup.black_to_move)
            self.assertEqual(setup.en_passant_file_code, 2)
            self.assertEqual(setup.next_move_number, 12)
            self.assertEqual([item.square for item in setup.pieces], ["e1", "e8"])
            self.assertEqual(path.read_bytes(), original)

    def test_setup_reader_reads_only_header_and_fixed_prefix(self):
        stream = _BoundedBytesIO(
            _cbg_custom_setup_image(
                offset=4,
                setup_bytes=_setup_bytes(("e1", 0b10001), ("e8", 0b11001)),
            )
        )
        with mock.patch("acs.chessbase_cbg.Path.open", return_value=stream):
            setup = read_cbg_custom_setup("ignored.cbg", offset=4)

        self.assertEqual([item.square for item in setup.pieces], ["e1", "e8"])
        self.assertEqual(stream.read_sizes, [4, 32])


if __name__ == "__main__":
    unittest.main()
