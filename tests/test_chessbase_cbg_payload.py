import unittest

from acs.chessbase_cbg import CbgDecodeError
from acs.chessbase_cbg_payload import locate_cbg_move_payload


def _cbg_image(*, offset=0, game_length=12, flags=0, suffix=0):
    raw = flags | game_length
    data = bytearray(offset + game_length + suffix)
    data[offset:offset + 4] = raw.to_bytes(4, "big")
    return bytes(data)


class ClassicCbgMovePayloadSpanTests(unittest.TestCase):
    def test_standard_game_payload_starts_after_four_byte_header(self):
        data = _cbg_image(offset=7, game_length=19, suffix=5)

        span = locate_cbg_move_payload(data, offset=7)

        self.assertEqual(span.game_offset, 7)
        self.assertEqual(span.payload_start_offset, 11)
        self.assertEqual(span.game_end_offset, 26)
        self.assertEqual(span.payload_length, 15)
        self.assertFalse(span.custom_setup_prefix_consumed)

    def test_custom_game_payload_starts_after_fixed_32_byte_prefix(self):
        data = _cbg_image(offset=3, game_length=41, flags=0x40000000)

        span = locate_cbg_move_payload(data, offset=3)

        self.assertEqual(span.game_offset, 3)
        self.assertEqual(span.payload_start_offset, 35)
        self.assertEqual(span.game_end_offset, 44)
        self.assertEqual(span.payload_length, 9)
        self.assertTrue(span.custom_setup_prefix_consumed)

    def test_zero_length_payload_is_reported_without_guessing_moves(self):
        standard = locate_cbg_move_payload(_cbg_image(game_length=4), offset=0)
        custom = locate_cbg_move_payload(
            _cbg_image(game_length=32, flags=0x40000000), offset=0
        )

        self.assertEqual(standard.payload_length, 0)
        self.assertEqual(custom.payload_length, 0)

    def test_custom_game_requires_complete_fixed_setup_prefix(self):
        data = _cbg_image(game_length=31, flags=0x40000000)

        with self.assertRaisesRegex(CbgDecodeError, "need at least 32 bytes"):
            locate_cbg_move_payload(data, offset=0)

    def test_unsupported_header_states_are_rejected_explicitly(self):
        for flag, reason in (
            (0x80000000, "encoding-flag"),
            (0x02000000, "chess960"),
            (0x04000000, "special-encoding"),
        ):
            with self.subTest(flag=hex(flag)):
                data = _cbg_image(game_length=32, flags=flag)
                with self.assertRaisesRegex(CbgDecodeError, reason):
                    locate_cbg_move_payload(data, offset=0)

    def test_declared_game_end_not_trailing_file_bytes_controls_span(self):
        data = _cbg_image(offset=5, game_length=10, suffix=17)

        span = locate_cbg_move_payload(data, offset=5)

        self.assertEqual(span.game_end_offset, 15)
        self.assertEqual(span.payload_start_offset, 9)
        self.assertEqual(span.payload_length, 6)


if __name__ == "__main__":
    unittest.main()
