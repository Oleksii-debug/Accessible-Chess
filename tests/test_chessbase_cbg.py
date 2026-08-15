import tempfile
import unittest
from pathlib import Path

from acs.chessbase_cbg import (
    CbgDecodeError,
    parse_cbg_custom_setup,
    parse_cbg_game_header,
    read_cbg_custom_setup,
    read_cbg_game_header,
)


def _cbg_image(*, offset=0, game_length=12, flags=0, suffix=0):
    raw = flags | game_length
    data = bytearray(offset + game_length + suffix)
    data[offset:offset + 4] = raw.to_bytes(4, "big")
    return bytes(data)


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
        setup_bytes = bytes(range(24))
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


class ClassicCbgSetupTests(unittest.TestCase):
    def test_extracts_only_evidence_backed_setup_prefix(self):
        setup_bytes = bytes(reversed(range(24)))
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

    def test_metadata_ignores_unverified_bits(self):
        data = _cbg_custom_setup_image(metadata=0xE8, castling=0xF0)

        setup = parse_cbg_custom_setup(data, offset=0)

        self.assertEqual(setup.en_passant_file_code, 0)
        self.assertFalse(setup.black_to_move)
        self.assertFalse(setup.white_castle_long)
        self.assertFalse(setup.white_castle_short)
        self.assertFalse(setup.black_castle_long)
        self.assertFalse(setup.black_castle_short)

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
            )
            path.write_bytes(original)

            setup = read_cbg_custom_setup(path, offset=4)

            self.assertTrue(setup.black_to_move)
            self.assertEqual(setup.en_passant_file_code, 2)
            self.assertEqual(setup.next_move_number, 12)
            self.assertEqual(path.read_bytes(), original)


if __name__ == "__main__":
    unittest.main()
