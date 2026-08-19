import io
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from acs.chessbase_cbp import (
    CBP_RECORD_SIZE,
    CbpDecodeError,
    parse_cbp_player,
    read_cbp_player,
)


class _BoundedBytesIO(io.BytesIO):
    def __init__(self, data):
        super().__init__(data)
        self.read_sizes = []

    def read(self, size=-1):
        if size < 0:
            raise AssertionError("reader attempted an unbounded CBP read")
        self.read_sizes.append(size)
        return super().read(size)


def _cbp_image(*, version=4, players=()):
    first_record = 32 if version == 4 else 28
    data = bytearray(first_record + max(1, len(players)) * CBP_RECORD_SIZE)
    data[0x18] = version
    for player_no, (last_name, first_name) in enumerate(players):
        base = first_record + player_no * CBP_RECORD_SIZE
        last = last_name.encode("utf-8")[:30]
        first = first_name.encode("utf-8")[:20]
        data[base + 9:base + 9 + len(last)] = last
        data[base + 39:base + 39 + len(first)] = first
    return bytes(data)


class ClassicCbpPlayerTests(unittest.TestCase):
    def test_decodes_version_4_player_name(self):
        data = _cbp_image(version=4, players=(("Carlsen", "Magnus"),))

        player = parse_cbp_player(data, player_no=0)

        self.assertEqual(player.player_no, 0)
        self.assertEqual(player.last_name, "Carlsen")
        self.assertEqual(player.first_name, "Magnus")
        self.assertEqual(player.pgn_name, "Carlsen, Magnus")

    def test_decodes_version_0_record_base(self):
        data = _cbp_image(version=0, players=(("Polgar", "Judit"),))
        self.assertEqual(parse_cbp_player(data, player_no=0).pgn_name, "Polgar, Judit")

    def test_player_number_selects_fixed_67_byte_record(self):
        data = _cbp_image(
            version=4,
            players=(("First", "Player"), ("Second", "Player")),
        )
        self.assertEqual(parse_cbp_player(data, player_no=1).pgn_name, "Second, Player")

    def test_utf8_and_nul_termination_match_pinned_decoder_contract(self):
        data = _cbp_image(version=4, players=(("Іванчук", "Василь"),))
        player = parse_cbp_player(data, player_no=0)
        self.assertEqual(player.pgn_name, "Іванчук, Василь")

    def test_invalid_utf8_is_replaced_not_crashed(self):
        data = bytearray(_cbp_image(version=4, players=(("A", "B"),)))
        data[32 + 9:32 + 12] = b"A\xff\x00"
        player = parse_cbp_player(bytes(data), player_no=0)
        self.assertEqual(player.last_name, "A�")

    def test_unknown_version_is_explicitly_unsupported(self):
        data = bytearray(128)
        data[0x18] = 7
        with self.assertRaisesRegex(CbpDecodeError, "unsupported classic CBP file version: 7"):
            parse_cbp_player(bytes(data), player_no=0)

    def test_short_file_is_rejected_before_version_guessing(self):
        with self.assertRaisesRegex(CbpDecodeError, "too short"):
            parse_cbp_player(b"short", player_no=0)

    def test_out_of_range_record_is_rejected(self):
        data = _cbp_image(version=4, players=(("Only", "Player"),))
        with self.assertRaisesRegex(CbpDecodeError, "outside the file"):
            parse_cbp_player(data, player_no=1)

    def test_invalid_player_number_is_rejected(self):
        data = _cbp_image(version=4, players=(("Only", "Player"),))
        for value in (-1, True, 1.5):
            with self.subTest(value=value):
                with self.assertRaisesRegex(CbpDecodeError, "non-negative integer"):
                    parse_cbp_player(data, player_no=value)

    def test_read_path_is_read_only(self):
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "players.cbp"
            original = _cbp_image(version=4, players=(("Kasparov", "Garry"),))
            path.write_bytes(original)

            player = read_cbp_player(path, player_no=0)

            self.assertEqual(player.pgn_name, "Kasparov, Garry")
            self.assertEqual(path.read_bytes(), original)

    def test_file_reader_reads_only_version_header_and_requested_record(self):
        stream = _BoundedBytesIO(
            _cbp_image(
                version=4,
                players=(("First", "Player"), ("Second", "Player")),
            )
        )
        with mock.patch("acs.chessbase_cbp.Path.open", return_value=stream):
            player = read_cbp_player("ignored.cbp", player_no=1)

        self.assertEqual(player.pgn_name, "Second, Player")
        self.assertEqual(stream.read_sizes, [0x19, CBP_RECORD_SIZE])


if __name__ == "__main__":
    unittest.main()
