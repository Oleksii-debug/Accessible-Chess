import tempfile
import unittest
from pathlib import Path

from acs.chessbase_cbh import (
    CBH_FILE_HEADER_SIZE,
    CBH_RECORD_SIZE,
    CbhDecodeError,
    iter_cbh_record_window,
    iter_cbh_records,
    parse_cbh_record,
)


def _record(
    *,
    flags=0x01,
    game_offset=0x01020304,
    white_offset=0x010203,
    black_offset=0x040506,
    tournament_offset=0x070809,
    year=2024,
    month=6,
    day=17,
    result_code=2,
    round_no=9,
    subround=2,
    white_elo=2510,
    black_elo=2444,
):
    raw = bytearray(CBH_RECORD_SIZE)
    raw[0] = flags
    raw[1:5] = game_offset.to_bytes(4, "big")
    raw[9:12] = white_offset.to_bytes(3, "big")
    raw[12:15] = black_offset.to_bytes(3, "big")
    raw[15:18] = tournament_offset.to_bytes(3, "big")
    packed_date = (year << 9) | (month << 5) | day
    raw[24:27] = packed_date.to_bytes(3, "big")
    raw[27] = result_code
    raw[29] = round_no
    raw[30] = subround
    raw[31:33] = white_elo.to_bytes(2, "big")
    raw[33:35] = black_elo.to_bytes(2, "big")
    return bytes(raw)


class ClassicCbhRecordTests(unittest.TestCase):
    def test_decodes_evidence_backed_header_fields(self):
        item = parse_cbh_record(_record(), record_index=7)

        self.assertEqual(item.record_index, 7)
        self.assertTrue(item.is_game)
        self.assertFalse(item.marked_for_deletion)
        self.assertTrue(item.eligible_game_record)
        self.assertEqual(item.game_offset, 0x01020304)
        self.assertEqual(item.white_player_offset, 0x010203)
        self.assertEqual(item.black_player_offset, 0x040506)
        self.assertEqual(item.tournament_offset, 0x070809)
        self.assertEqual((item.date.year, item.date.month, item.date.day), (2024, 6, 17))
        self.assertEqual(item.date.as_pgn_date(), "2024.06.17")
        self.assertEqual(item.result, "1-0")
        self.assertEqual((item.round, item.subround), (9, 2))
        self.assertEqual((item.white_elo, item.black_elo), (2510, 2444))

    def test_result_codes_match_pinned_mit_decoder_and_unknown_is_unfinished(self):
        expected = {0: "0-1", 1: "1/2-1/2", 2: "1-0", 9: "*"}
        for code, result in expected.items():
            with self.subTest(code=code):
                self.assertEqual(
                    parse_cbh_record(_record(result_code=code), record_index=1).result,
                    result,
                )

    def test_deleted_or_non_game_records_are_not_header_eligible(self):
        deleted = parse_cbh_record(_record(flags=0x81), record_index=1)
        non_game = parse_cbh_record(_record(flags=0x00), record_index=2)

        self.assertTrue(deleted.is_game)
        self.assertTrue(deleted.marked_for_deletion)
        self.assertFalse(deleted.eligible_game_record)
        self.assertFalse(non_game.is_game)
        self.assertFalse(non_game.eligible_game_record)

    def test_unknown_date_components_remain_unknown_in_pgn_projection(self):
        item = parse_cbh_record(
            _record(year=2024, month=0, day=0),
            record_index=1,
        )
        self.assertEqual(item.date.as_pgn_date(), "2024.??.??")

    def test_invalid_calendar_components_are_not_guessed(self):
        item = parse_cbh_record(_record(month=15, day=31), record_index=1)
        self.assertFalse(item.date.structurally_valid)
        with self.assertRaises(CbhDecodeError):
            item.date.as_pgn_date()

    def test_short_record_is_rejected(self):
        with self.assertRaisesRegex(CbhDecodeError, "exactly 46 bytes"):
            parse_cbh_record(b"short", record_index=1)

    def test_record_index_requires_exact_positive_integer(self):
        for value in (0, True, 1.5):
            with self.subTest(value=value):
                with self.assertRaisesRegex(CbhDecodeError, "record_index"):
                    parse_cbh_record(_record(), record_index=value)

    def test_file_iterator_skips_opaque_file_header_and_streams_records_read_only(self):
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "sample.cbh"
            header = bytes(range(CBH_FILE_HEADER_SIZE))
            original = header + _record(game_offset=10) + _record(game_offset=20)
            path.write_bytes(original)

            records = list(iter_cbh_records(path))

            self.assertEqual([item.record_index for item in records], [1, 2])
            self.assertEqual([item.game_offset for item in records], [10, 20])
            self.assertEqual(path.read_bytes(), original)

    def test_record_window_preserves_exact_indices_and_bounds_read_count(self):
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "window.cbh"
            original = bytes(CBH_FILE_HEADER_SIZE) + b"".join(
                _record(game_offset=value) for value in (10, 20, 30, 40, 50)
            )
            path.write_bytes(original)

            records = list(
                iter_cbh_record_window(
                    path,
                    start_record_index=3,
                    max_records=2,
                )
            )

            self.assertEqual([item.record_index for item in records], [3, 4])
            self.assertEqual([item.game_offset for item in records], [30, 40])
            self.assertEqual(path.read_bytes(), original)

    def test_record_window_zero_count_validates_header_but_returns_no_records(self):
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "zero.cbh"
            path.write_bytes(bytes(CBH_FILE_HEADER_SIZE) + _record())

            self.assertEqual(
                list(
                    iter_cbh_record_window(
                        path,
                        start_record_index=1,
                        max_records=0,
                    )
                ),
                [],
            )

    def test_record_window_past_end_is_empty_without_guessing_indices(self):
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "past-end.cbh"
            path.write_bytes(bytes(CBH_FILE_HEADER_SIZE) + _record())

            self.assertEqual(
                list(
                    iter_cbh_record_window(
                        path,
                        start_record_index=5,
                        max_records=3,
                    )
                ),
                [],
            )

    def test_record_window_rejects_invalid_bounds(self):
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "bounds.cbh"
            path.write_bytes(bytes(CBH_FILE_HEADER_SIZE))

            with self.assertRaisesRegex(ValueError, "start_record_index"):
                list(
                    iter_cbh_record_window(
                        path,
                        start_record_index=0,
                        max_records=1,
                    )
                )
            with self.assertRaisesRegex(ValueError, "max_records"):
                list(
                    iter_cbh_record_window(
                        path,
                        start_record_index=1,
                        max_records=-1,
                    )
                )
            for value in (True, 1.5):
                with self.subTest(start_record_index=value):
                    with self.assertRaisesRegex(ValueError, "start_record_index"):
                        list(
                            iter_cbh_record_window(
                                path,
                                start_record_index=value,
                                max_records=1,
                            )
                        )
            for value in (True, 1.5):
                with self.subTest(max_records=value):
                    with self.assertRaisesRegex(ValueError, "max_records"):
                        list(
                            iter_cbh_record_window(
                                path,
                                start_record_index=1,
                                max_records=value,
                            )
                        )

    def test_record_window_rejects_partial_record_inside_requested_range(self):
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "partial-window.cbh"
            path.write_bytes(
                bytes(CBH_FILE_HEADER_SIZE) + _record(game_offset=10) + b"partial"
            )

            with self.assertRaisesRegex(
                CbhDecodeError,
                "partial CBH record inside requested window at index 2",
            ):
                list(
                    iter_cbh_record_window(
                        path,
                        start_record_index=2,
                        max_records=1,
                    )
                )

    def test_trailing_partial_record_is_explicitly_rejected(self):
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "damaged.cbh"
            path.write_bytes(bytes(CBH_FILE_HEADER_SIZE) + _record() + b"partial")

            with self.assertRaisesRegex(CbhDecodeError, "trailing partial CBH record"):
                list(iter_cbh_records(path))

    def test_short_file_header_is_rejected(self):
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "short.cbh"
            path.write_bytes(b"x" * (CBH_FILE_HEADER_SIZE - 1))

            with self.assertRaisesRegex(CbhDecodeError, "file header must be 46 bytes"):
                list(iter_cbh_records(path))


if __name__ == "__main__":
    unittest.main()
