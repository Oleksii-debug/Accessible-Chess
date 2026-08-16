import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import acs.chessbase_file_evidence as file_evidence
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


class ClassicChessBaseFileEvidenceTests(unittest.TestCase):
    def _family(self, root: Path, *, payload=b"opaque") -> Path:
        cbh = root / "sample.cbh"
        cbh.write_bytes(bytes(46) + _record())
        cbh.with_suffix(".cbg").write_bytes(_cbg_game(payload))
        cbh.with_suffix(".cbp").write_bytes(_cbp())
        cbh.with_suffix(".cbt").write_bytes(_cbt())
        return cbh

    def test_file_projection_keeps_exact_neutral_record_evidence(self):
        with tempfile.TemporaryDirectory() as tmp:
            cbh = self._family(Path(tmp), payload=b"opaque-moves")
            result = file_evidence.project_classic_chessbase_file_evidence(cbh)

            self.assertEqual(result.before, result.after)
            self.assertEqual(result.records.complete_count, 1)
            item = result.records.items[0]
            self.assertEqual(item.payload.link.payload.payload_bytes, b"opaque-moves")
            self.assertEqual(item.metadata.metadata.white.pgn_name, "Carlsen, Magnus")
            self.assertEqual(item.metadata.metadata.black.pgn_name, "Anand, Viswanathan")
            self.assertEqual(item.metadata.metadata.tournament.site, "Sochi")

    def test_all_four_required_sources_are_byte_for_byte_unchanged(self):
        with tempfile.TemporaryDirectory() as tmp:
            cbh = self._family(Path(tmp))
            paths = [cbh, cbh.with_suffix(".cbg"), cbh.with_suffix(".cbp"), cbh.with_suffix(".cbt")]
            before = {path: path.read_bytes() for path in paths}

            file_evidence.project_classic_chessbase_file_evidence(cbh)

            self.assertEqual({path: path.read_bytes() for path in paths}, before)

    def test_missing_required_companion_is_explicit(self):
        with tempfile.TemporaryDirectory() as tmp:
            cbh = self._family(Path(tmp))
            missing = cbh.with_suffix(".cbt")
            missing.unlink()

            with self.assertRaises(FileNotFoundError) as caught:
                file_evidence.project_classic_chessbase_file_evidence(cbh)
            self.assertEqual(caught.exception.args[0], missing)

    def test_non_cbh_entry_point_is_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            source = Path(tmp) / "sample.cbg"
            source.write_bytes(b"x")
            with self.assertRaisesRegex(ValueError, "requires a \\.cbh source"):
                file_evidence.project_classic_chessbase_file_evidence(source)

    def test_source_mutation_during_projection_rejects_decoder_output(self):
        with tempfile.TemporaryDirectory() as tmp:
            cbh = self._family(Path(tmp), payload=b"stable")
            cbg = cbh.with_suffix(".cbg")

            def mutate_then_project(records, cbg_data, cbp_data, cbt_data):
                projection = project_cbh_record_evidence(records, cbg_data, cbp_data, cbt_data)
                cbg.write_bytes(cbg.read_bytes() + b"changed")
                return projection

            with patch.object(
                file_evidence,
                "project_cbh_record_evidence",
                side_effect=mutate_then_project,
            ):
                with self.assertRaises(ChessBaseSourceChangedError):
                    file_evidence.project_classic_chessbase_file_evidence(cbh)


if __name__ == "__main__":
    unittest.main()
