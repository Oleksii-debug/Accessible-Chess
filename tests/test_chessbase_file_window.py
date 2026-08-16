import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import acs.chessbase_file_window as file_window
from acs.chessbase_cbh_evidence import project_cbh_record_evidence
from acs.chessbase_integrity import ChessBaseSourceChangedError


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


class ClassicChessBaseWindowEvidenceTests(unittest.TestCase):
    def _family(self, root: Path) -> Path:
        first = _cbg_game(b"first")
        second = _cbg_game(b"second")
        third = _cbg_game(b"third")
        cbg = first + second + third

        cbh = root / "sample.cbh"
        cbh.write_bytes(
            bytes(46)
            + _record(game_offset=0)
            + _record(game_offset=len(first))
            + _record(game_offset=len(first) + len(second))
        )
        cbh.with_suffix(".cbg").write_bytes(cbg)
        cbh.with_suffix(".cbp").write_bytes(_cbp())
        cbh.with_suffix(".cbt").write_bytes(_cbt())
        return cbh

    def test_window_projects_only_requested_records_with_exact_indices(self):
        with tempfile.TemporaryDirectory() as tmp:
            cbh = self._family(Path(tmp))
            result = file_window.project_classic_chessbase_window_evidence(
                cbh, start_record_index=2, max_records=2
            )

            self.assertEqual(result.before, result.after)
            self.assertEqual(result.start_record_index, 2)
            self.assertEqual(result.max_records, 2)
            self.assertEqual([item.record_index for item in result.records.items], [2, 3])
            self.assertEqual(result.records.complete_count, 2)
            self.assertEqual(
                [item.payload.link.payload.payload_bytes for item in result.records.items],
                [b"second", b"third"],
            )

    def test_zero_length_window_validates_family_and_returns_no_records(self):
        with tempfile.TemporaryDirectory() as tmp:
            cbh = self._family(Path(tmp))
            result = file_window.project_classic_chessbase_window_evidence(
                cbh, start_record_index=2, max_records=0
            )
            self.assertEqual(result.before, result.after)
            self.assertEqual(result.records.items, ())

    def test_window_beyond_eof_is_empty_without_guessing_records(self):
        with tempfile.TemporaryDirectory() as tmp:
            cbh = self._family(Path(tmp))
            result = file_window.project_classic_chessbase_window_evidence(
                cbh, start_record_index=20, max_records=4
            )
            self.assertEqual(result.records.items, ())
            self.assertEqual(result.before, result.after)

    def test_all_four_sources_remain_byte_for_byte_unchanged(self):
        with tempfile.TemporaryDirectory() as tmp:
            cbh = self._family(Path(tmp))
            paths = [
                cbh,
                cbh.with_suffix(".cbg"),
                cbh.with_suffix(".cbp"),
                cbh.with_suffix(".cbt"),
            ]
            before = {path: path.read_bytes() for path in paths}
            file_window.project_classic_chessbase_window_evidence(
                cbh, start_record_index=2, max_records=1
            )
            self.assertEqual({path: path.read_bytes() for path in paths}, before)

    def test_source_mutation_rejects_window_projection(self):
        with tempfile.TemporaryDirectory() as tmp:
            cbh = self._family(Path(tmp))
            cbg = cbh.with_suffix(".cbg")

            def mutate_then_project(records, cbg_data, cbp_data, cbt_data):
                projection = project_cbh_record_evidence(records, cbg_data, cbp_data, cbt_data)
                cbg.write_bytes(cbg.read_bytes() + b"changed")
                return projection

            with patch.object(
                file_window,
                "project_cbh_record_evidence",
                side_effect=mutate_then_project,
            ):
                with self.assertRaises(ChessBaseSourceChangedError):
                    file_window.project_classic_chessbase_window_evidence(
                        cbh, start_record_index=1, max_records=1
                    )

    def test_invalid_bounds_and_missing_companion_are_explicit(self):
        with tempfile.TemporaryDirectory() as tmp:
            cbh = self._family(Path(tmp))
            with self.assertRaisesRegex(ValueError, "start_record_index"):
                file_window.project_classic_chessbase_window_evidence(
                    cbh, start_record_index=0, max_records=1
                )
            with self.assertRaisesRegex(ValueError, "max_records"):
                file_window.project_classic_chessbase_window_evidence(
                    cbh, start_record_index=1, max_records=-1
                )

            missing = cbh.with_suffix(".cbt")
            missing.unlink()
            with self.assertRaises(FileNotFoundError) as caught:
                file_window.project_classic_chessbase_window_evidence(
                    cbh, start_record_index=1, max_records=1
                )
            self.assertEqual(caught.exception.args[0], missing)


if __name__ == "__main__":
    unittest.main()
