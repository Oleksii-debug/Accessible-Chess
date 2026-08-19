import unittest

from acs.chessbase_cbh import parse_cbh_record
from acs.chessbase_cbh_evidence import project_cbh_record_evidence


def _record(
    *,
    index=1,
    flags=0x01,
    game_offset=0,
    white=0,
    black=1,
    tournament=0,
):
    raw = bytearray(46)
    raw[0] = flags
    raw[1:5] = game_offset.to_bytes(4, "big")
    raw[9:12] = white.to_bytes(3, "big")
    raw[12:15] = black.to_bytes(3, "big")
    raw[15:18] = tournament.to_bytes(3, "big")
    return parse_cbh_record(bytes(raw), record_index=index)


def _cbg_game(payload: bytes, *, unsupported=False) -> bytes:
    raw_header = 4 + len(payload)
    if unsupported:
        raw_header |= 0x80000000
    return raw_header.to_bytes(4, "big") + payload


def _cbp():
    data = bytearray(28 + 2 * 67)
    data[0x18] = 0
    for no, (last, first) in enumerate(
        [("Carlsen", "Magnus"), ("Anand", "Viswanathan")]
    ):
        base = 28 + no * 67
        data[base + 9:base + 9 + len(last)] = last.encode()
        data[base + 39:base + 39 + len(first)] = first.encode()
    return bytes(data)


def _cbt():
    data = bytearray(28 + 99)
    data[0x18] = 0
    data[37:55] = b"World Championship"
    data[77:82] = b"Sochi"
    return bytes(data)


class ClassicCbhRecordEvidenceTests(unittest.TestCase):
    def setUp(self):
        self.cbp = _cbp()
        self.cbt = _cbt()

    def test_complete_record_keeps_metadata_and_exact_opaque_payload(self):
        payload = b"opaque-moves"
        projection = project_cbh_record_evidence(
            [_record()], _cbg_game(payload), self.cbp, self.cbt
        )

        item = projection.items[0]
        self.assertEqual(item.status, "complete")
        self.assertEqual(item.payload.link.payload.payload_bytes, payload)
        self.assertEqual(item.metadata.metadata.white.pgn_name, "Carlsen, Magnus")
        self.assertEqual(item.metadata.metadata.black.pgn_name, "Anand, Viswanathan")
        self.assertEqual(item.metadata.metadata.tournament.site, "Sochi")
        self.assertEqual(projection.complete_count, 1)

    def test_metadata_failure_does_not_discard_valid_cbg_evidence(self):
        payload = b"still-valid"
        projection = project_cbh_record_evidence(
            [_record(white=99)], _cbg_game(payload), self.cbp, self.cbt
        )

        item = projection.items[0]
        self.assertEqual(item.status, "partial")
        self.assertEqual(item.payload.status, "linked")
        self.assertEqual(item.payload.link.payload.payload_bytes, payload)
        self.assertEqual(item.metadata.status, "failed")
        self.assertEqual(item.metadata.error_type, "CbpDecodeError")

    def test_cbg_failure_does_not_discard_valid_metadata(self):
        projection = project_cbh_record_evidence(
            [_record()], _cbg_game(b"bad", unsupported=True), self.cbp, self.cbt
        )

        item = projection.items[0]
        self.assertEqual(item.status, "partial")
        self.assertEqual(item.payload.status, "failed")
        self.assertEqual(item.payload.error_type, "CbgDecodeError")
        self.assertEqual(item.metadata.status, "projected")
        self.assertEqual(item.metadata.metadata.white.pgn_name, "Carlsen, Magnus")

    def test_independent_failures_produce_failed_record_without_guessing(self):
        projection = project_cbh_record_evidence(
            [_record(white=99)],
            _cbg_game(b"bad", unsupported=True),
            self.cbp,
            self.cbt,
        )

        item = projection.items[0]
        self.assertEqual(item.status, "failed")
        self.assertEqual(item.payload.error_type, "CbgDecodeError")
        self.assertEqual(item.metadata.error_type, "CbpDecodeError")
        self.assertEqual(projection.failed_count, 1)

    def test_non_game_and_deleted_records_remain_explicit_skips(self):
        projection = project_cbh_record_evidence(
            [_record(index=4, flags=0), _record(index=5, flags=0x81)],
            b"",
            self.cbp,
            self.cbt,
        )

        self.assertEqual([item.status for item in projection.items], ["skipped", "skipped"])
        self.assertEqual(projection.skipped_count, 2)
        self.assertEqual(projection.items[0].payload.reason, "not-game-record")
        self.assertEqual(projection.items[0].metadata.reason, "not-game-record")
        self.assertEqual(projection.items[1].payload.reason, "marked-for-deletion")
        self.assertEqual(projection.items[1].metadata.reason, "marked-for-deletion")

    def test_generator_is_consumed_once_and_order_is_stable(self):
        first = _cbg_game(b"one")
        second_offset = len(first)
        records = (
            record
            for record in [
                _record(index=7, game_offset=0),
                _record(index=8, game_offset=second_offset),
            ]
        )
        projection = project_cbh_record_evidence(
            records,
            first + _cbg_game(b"two"),
            self.cbp,
            self.cbt,
        )

        self.assertEqual([item.record_index for item in projection.items], [7, 8])
        self.assertEqual([item.status for item in projection.items], ["complete", "complete"])
        self.assertEqual(projection.items[0].payload.link.payload.payload_bytes, b"one")
        self.assertEqual(projection.items[1].payload.link.payload.payload_bytes, b"two")
        self.assertEqual(projection.partial_count, 0)


if __name__ == "__main__":
    unittest.main()
