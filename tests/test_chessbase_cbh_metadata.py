import unittest

from acs.chessbase_cbh import parse_cbh_record
from acs.chessbase_cbh_metadata import project_cbh_records_to_metadata


def _record(*, index=1, flags=0x01, white=0, black=1, tournament=0):
    raw = bytearray(46)
    raw[0] = flags
    raw[9:12] = white.to_bytes(3, "big")
    raw[12:15] = black.to_bytes(3, "big")
    raw[15:18] = tournament.to_bytes(3, "big")
    return parse_cbh_record(bytes(raw), record_index=index)


def _cbp(players):
    data = bytearray(28 + 67 * len(players))
    data[0x18] = 0
    for no, (last, first) in enumerate(players):
        base = 28 + no * 67
        data[base + 9:base + 9 + len(last)] = last.encode("utf-8")
        data[base + 39:base + 39 + len(first)] = first.encode("utf-8")
    return bytes(data)


def _cbt(tournaments):
    data = bytearray(28 + 99 * len(tournaments))
    data[0x18] = 0
    for no, (event, site) in enumerate(tournaments):
        base = 28 + no * 99
        data[base + 9:base + 9 + len(event)] = event.encode("utf-8")
        data[base + 49:base + 49 + len(site)] = site.encode("utf-8")
    return bytes(data)


class ClassicCbhMetadataProjectionTests(unittest.TestCase):
    def setUp(self):
        self.cbp = _cbp([("Carlsen", "Magnus"), ("Anand", "Viswanathan")])
        self.cbt = _cbt([("World Championship", "Sochi")])

    def test_projects_only_established_references(self):
        projection = project_cbh_records_to_metadata(
            [_record()], self.cbp, self.cbt
        )
        item = projection.items[0]
        self.assertEqual(item.status, "projected")
        self.assertEqual(item.metadata.white.pgn_name, "Carlsen, Magnus")
        self.assertEqual(item.metadata.black.pgn_name, "Anand, Viswanathan")
        self.assertEqual(item.metadata.tournament.event, "World Championship")
        self.assertEqual(item.metadata.tournament.site, "Sochi")

    def test_non_game_and_deleted_are_explicit_skips(self):
        projection = project_cbh_records_to_metadata(
            [_record(index=1, flags=0), _record(index=2, flags=0x81)],
            self.cbp,
            self.cbt,
        )
        self.assertEqual([i.status for i in projection.items], ["skipped", "skipped"])
        self.assertEqual(projection.items[0].reason, "not-game-record")
        self.assertEqual(projection.items[1].reason, "marked-for-deletion")

    def test_bad_player_reference_is_isolated(self):
        projection = project_cbh_records_to_metadata(
            [_record(index=1, white=99), _record(index=2)], self.cbp, self.cbt
        )
        self.assertEqual([i.status for i in projection.items], ["failed", "projected"])
        self.assertEqual(projection.items[0].error_type, "CbpDecodeError")

    def test_bad_tournament_reference_is_isolated(self):
        projection = project_cbh_records_to_metadata(
            [_record(index=1, tournament=99), _record(index=2)], self.cbp, self.cbt
        )
        self.assertEqual([i.status for i in projection.items], ["failed", "projected"])
        self.assertEqual(projection.items[0].error_type, "CbtDecodeError")

    def test_unsupported_cbp_version_is_explicit_failure(self):
        bad_cbp = bytearray(self.cbp)
        bad_cbp[0x18] = 9
        projection = project_cbh_records_to_metadata(
            [_record()], bytes(bad_cbp), self.cbt
        )
        self.assertEqual(projection.failed_count, 1)
        self.assertIn("unsupported classic CBP file version", projection.items[0].reason)

    def test_empty_batch_is_valid(self):
        projection = project_cbh_records_to_metadata([], self.cbp, self.cbt)
        self.assertEqual(projection.items, ())
        self.assertEqual(projection.projected_count, 0)
        self.assertEqual(projection.skipped_count, 0)
        self.assertEqual(projection.failed_count, 0)


if __name__ == "__main__":
    unittest.main()
