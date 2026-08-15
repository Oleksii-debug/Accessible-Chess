import tempfile
import unittest
from pathlib import Path

from acs.chessbase_cbt import (
    CBT_RECORD_SIZE,
    CbtDecodeError,
    parse_cbt_tournament,
    read_cbt_tournament,
)


def _cbt_image(*, version=4, tournaments=()):
    first_record = 32 if version == 4 else 28
    data = bytearray(first_record + max(1, len(tournaments)) * CBT_RECORD_SIZE)
    data[0x18] = version
    for tournament_no, (event, site) in enumerate(tournaments):
        base = first_record + tournament_no * CBT_RECORD_SIZE
        event_bytes = event.encode("utf-8")[:40]
        site_bytes = site.encode("utf-8")[:30]
        data[base + 9:base + 9 + len(event_bytes)] = event_bytes
        data[base + 49:base + 49 + len(site_bytes)] = site_bytes
    return bytes(data)


class ClassicCbtTournamentTests(unittest.TestCase):
    def test_decodes_version_4_event_and_site(self):
        data = _cbt_image(version=4, tournaments=(("Candidates 2026", "Toronto CAN"),))

        tournament = parse_cbt_tournament(data, tournament_no=0)

        self.assertEqual(tournament.tournament_no, 0)
        self.assertEqual(tournament.event, "Candidates 2026")
        self.assertEqual(tournament.site, "Toronto CAN")

    def test_decodes_version_0_record_base(self):
        data = _cbt_image(version=0, tournaments=(("Wijk aan Zee", "NED"),))
        tournament = parse_cbt_tournament(data, tournament_no=0)
        self.assertEqual((tournament.event, tournament.site), ("Wijk aan Zee", "NED"))

    def test_tournament_number_selects_fixed_99_byte_record(self):
        data = _cbt_image(
            version=4,
            tournaments=(("First Event", "First Site"), ("Second Event", "Second Site")),
        )
        tournament = parse_cbt_tournament(data, tournament_no=1)
        self.assertEqual((tournament.event, tournament.site), ("Second Event", "Second Site"))

    def test_utf8_and_nul_termination_match_pinned_decoder_contract(self):
        data = _cbt_image(version=4, tournaments=(("Київ Open", "Київ UKR"),))
        tournament = parse_cbt_tournament(data, tournament_no=0)
        self.assertEqual(tournament.event, "Київ Open")
        self.assertEqual(tournament.site, "Київ UKR")

    def test_invalid_utf8_is_replaced_not_crashed(self):
        data = bytearray(_cbt_image(version=4, tournaments=(("A", "B"),)))
        data[32 + 9:32 + 12] = b"A\xff\x00"
        tournament = parse_cbt_tournament(bytes(data), tournament_no=0)
        self.assertEqual(tournament.event, "A�")

    def test_unknown_version_is_explicitly_unsupported(self):
        data = bytearray(160)
        data[0x18] = 7
        with self.assertRaisesRegex(CbtDecodeError, "unsupported classic CBT file version: 7"):
            parse_cbt_tournament(bytes(data), tournament_no=0)

    def test_short_file_is_rejected_before_version_guessing(self):
        with self.assertRaisesRegex(CbtDecodeError, "too short"):
            parse_cbt_tournament(b"short", tournament_no=0)

    def test_out_of_range_record_is_rejected(self):
        data = _cbt_image(version=4, tournaments=(("Only", "Here"),))
        with self.assertRaisesRegex(CbtDecodeError, "outside the file"):
            parse_cbt_tournament(data, tournament_no=1)

    def test_invalid_tournament_number_is_rejected(self):
        data = _cbt_image(version=4, tournaments=(("Only", "Here"),))
        for value in (-1, True, 1.5):
            with self.subTest(value=value):
                with self.assertRaisesRegex(CbtDecodeError, "non-negative integer"):
                    parse_cbt_tournament(data, tournament_no=value)

    def test_read_path_is_read_only(self):
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "events.cbt"
            original = _cbt_image(version=4, tournaments=(("Tata Steel", "Wijk aan Zee"),))
            path.write_bytes(original)

            tournament = read_cbt_tournament(path, tournament_no=0)

            self.assertEqual(tournament.event, "Tata Steel")
            self.assertEqual(tournament.site, "Wijk aan Zee")
            self.assertEqual(path.read_bytes(), original)


if __name__ == "__main__":
    unittest.main()
