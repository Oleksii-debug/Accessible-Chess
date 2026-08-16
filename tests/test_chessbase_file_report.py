import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import acs.chessbase_file_evidence as file_evidence
from acs.chessbase_file_report import project_classic_chessbase_file_report


def _record(*, flags=0x01, game_offset=0, white=0, black=1, tournament=0):
    raw = bytearray(46)
    raw[0] = flags
    raw[1:5] = game_offset.to_bytes(4, "big")
    raw[9:12] = white.to_bytes(3, "big")
    raw[12:15] = black.to_bytes(3, "big")
    raw[15:18] = tournament.to_bytes(3, "big")
    return bytes(raw)


def _cbg_game(payload: bytes) -> bytes:
    return (4 + len(payload)).to_bytes(4, "big") + payload


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


class ClassicChessBaseFileReportTests(unittest.TestCase):
    def _family(self, root: Path, *, payload=b"opaque") -> Path:
        cbh = root / "sample.cbh"
        cbh.write_bytes(bytes(46) + _record())
        cbh.with_suffix(".cbg").write_bytes(_cbg_game(payload))
        cbh.with_suffix(".cbp").write_bytes(_cbp())
        cbh.with_suffix(".cbt").write_bytes(_cbt())
        return cbh

    def test_success_report_exposes_only_fingerprints_and_record_counts(self):
        with tempfile.TemporaryDirectory() as tmp:
            cbh = self._family(Path(tmp), payload=b"secret-opaque-moves")
            outcome = file_evidence.inspect_classic_chessbase_file_evidence(cbh)
            report = project_classic_chessbase_file_report(outcome)
            data = report.as_dict()

            self.assertEqual(report.status, "succeeded")
            self.assertEqual(report.record_count, 1)
            self.assertEqual(report.complete_count, 1)
            self.assertEqual(report.partial_count, 0)
            self.assertEqual(report.skipped_count, 0)
            self.assertEqual(report.failed_count, 0)
            self.assertEqual(len(report.sources), 4)
            self.assertTrue(all(len(source.sha256) == 64 for source in report.sources))
            self.assertNotIn("secret-opaque-moves", repr(data))
            self.assertNotIn("Carlsen", repr(data))

    def test_failed_report_preserves_exact_error_and_leaves_counts_unavailable(self):
        with tempfile.TemporaryDirectory() as tmp:
            cbh = self._family(Path(tmp))
            with patch.object(
                file_evidence,
                "_read_classic_projection",
                side_effect=ValueError("exact synthetic failure"),
            ):
                outcome = file_evidence.inspect_classic_chessbase_file_evidence(cbh)

            report = project_classic_chessbase_file_report(outcome)
            self.assertEqual(report.status, "failed")
            self.assertIsNone(report.record_count)
            self.assertIsNone(report.complete_count)
            self.assertIsNone(report.partial_count)
            self.assertIsNone(report.skipped_count)
            self.assertIsNone(report.failed_count)
            self.assertEqual(report.error_type, "ValueError")
            self.assertEqual(report.error_message, "exact synthetic failure")

    def test_report_dict_is_deterministic_for_same_verified_outcome(self):
        with tempfile.TemporaryDirectory() as tmp:
            cbh = self._family(Path(tmp))
            outcome = file_evidence.inspect_classic_chessbase_file_evidence(cbh)
            first = project_classic_chessbase_file_report(outcome).as_dict()
            second = project_classic_chessbase_file_report(outcome).as_dict()
            self.assertEqual(first, second)

    def test_mismatched_integrity_snapshots_are_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            cbh = self._family(Path(tmp))
            outcome = file_evidence.inspect_classic_chessbase_file_evidence(cbh)
            cbg = cbh.with_suffix(".cbg")
            cbg.write_bytes(cbg.read_bytes() + b"changed")
            changed = file_evidence.capture_integrity_snapshot(cbh)
            forged = file_evidence.ClassicChessBaseFileOutcome(
                cbh_path=outcome.cbh_path,
                cbg_path=outcome.cbg_path,
                cbp_path=outcome.cbp_path,
                cbt_path=outcome.cbt_path,
                before=outcome.before,
                after=changed,
                records=outcome.records,
                error_type=None,
                error_message=None,
            )
            with self.assertRaisesRegex(ValueError, "matching verified integrity snapshots"):
                project_classic_chessbase_file_report(forged)


if __name__ == "__main__":
    unittest.main()
